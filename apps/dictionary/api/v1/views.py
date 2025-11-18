import json
import re
from typing import Dict, List, Optional, Tuple

from django.shortcuts import get_object_or_404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.common.llm import ChatMessage, LLMClient, LLMError
from apps.dictionary.models import Lemma, Sense
from apps.lessons.utils import tokenize
from apps.progress.models import LemmaProgress
from .serializers import LemmaSerializer, SenseSerializer
from pydantic import BaseModel, ValidationError

_SENTENCE_TARGET = 3
_LINE_PREFIX = re.compile(r"^[\s\-\*\d\.\)\(]+")
llm_client = LLMClient()

class SentencePair(BaseModel):
    chinese: str
    english: str

class ExampleSentences(BaseModel):
    sentences: List[SentencePair]

class LemmaViewSet(viewsets.ModelViewSet):
    queryset = Lemma.objects.all()
    serializer_class = LemmaSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["simplified", "traditional", "pinyin_numbers", "senses__gloss"]
    ordering_fields = ["simplified", "traditional"]
    ordering = ["simplified"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["include_tokens"] = getattr(self, "action", None) == "retrieve"
        return context


class SenseViewSet(viewsets.ModelViewSet):
    queryset = Sense.objects.select_related("lemma").all()
    serializer_class = SenseSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["gloss", "lemma__simplified", "lemma__traditional", "lemma__pinyin_numbers"]
    ordering_fields = ["sense_index", "lemma__simplified"]
    ordering = ["lemma__simplified", "sense_index"]


@api_view(["GET"])
def get_routes(request):
    routes = {
        "Dictionary Endpoints": {
            "List Lemmas": "/api/v1/dictionary/lemmas/",
            "Retrieve Lemma": "/api/v1/dictionary/lemmas/{id}/",
            "List Senses": "/api/v1/dictionary/senses/",
            "Retrieve Sense": "/api/v1/dictionary/senses/{id}/",
            "Lemma Examples": "/api/v1/dictionary/lemmas/{id}/examples/",
        }
    }
    return Response(routes)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def lemma_examples(request, lemma_id: int):
    lemma = get_object_or_404(Lemma, pk=lemma_id)
    prompt = _build_prompt(lemma)
    messages = [
        ChatMessage(role="system", content="Concise Chinese tutor. Respond in JSON matching the given schema."),
        ChatMessage(role="user", content=prompt),
    ]

    try:
        llm_response = llm_client.chat(messages, text_format=ExampleSentences)
    except LLMError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    # Now this returns a list of {chinese, english} dicts
    sentences = _extract_sentences(llm_response.content)
    if len(sentences) < _SENTENCE_TARGET:
        return Response(
            {"detail": "LLM did not return enough sentences."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    user = getattr(request, "user", None)
    processed_sentences = _prepare_sentence_payloads(
        sentences[:_SENTENCE_TARGET],
        user if user and getattr(user, "is_authenticated", False) else None,
    )

    return Response(
        {
            "lemma_id": lemma.id,
            "simplified": lemma.simplified,
            "traditional": lemma.traditional,
            "pinyin_numbers": lemma.pinyin_numbers,
            "sentences": processed_sentences,
        }
    )


def _build_prompt(lemma: Lemma) -> str:
    return (
        f"{lemma.simplified} → give 3 Chinese sentences of increasing complexity with english translations."
    )


def _extract_sentences(raw_text: str) -> List[dict]:
    """
    Extract up to _SENTENCE_TARGET Chinese/English pairs.

    Expected primary format (from ExampleSentences model):
    {
      "sentences": [
        {"chinese": "...", "english": "..."},
        ...
      ]
    }
    """
    text = raw_text.strip()
    if not text:
        return []

    pairs: List[dict] = []

    # 1) Preferred path: use Pydantic ExampleSentences
    try:
        parsed = ExampleSentences.model_validate_json(text)
        for sp in parsed.sentences:
            chinese = sp.chinese.strip()
            english = sp.english.strip()
            if chinese:
                pairs.append({"chinese": chinese, "english": english})
    except ValidationError:
        # 2) Fallback: manual JSON or line-based parsing
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError:
            parsed_json = None

        if isinstance(parsed_json, dict) and "sentences" in parsed_json:
            # e.g. {"sentences": [{"chinese": "...", "english": "..."}, ...]}
            for item in parsed_json.get("sentences", []):
                if isinstance(item, dict):
                    chinese = str(item.get("chinese", "")).strip()
                    english = str(item.get("english", "")).strip()
                    if chinese:
                        pairs.append({"chinese": chinese, "english": english})
        elif isinstance(parsed_json, list):
            # e.g. [["CN", "EN"], ...] or ["CN only", ...]
            for item in parsed_json:
                if isinstance(item, dict):
                    chinese = str(item.get("chinese", "")).strip()
                    english = str(item.get("english", "")).strip()
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    chinese = str(item[0]).strip()
                    english = str(item[1]).strip()
                else:
                    chinese = str(item).strip()
                    english = ""

                if chinese:
                    pairs.append({"chinese": chinese, "english": english})
        else:
            # Very last resort: line-based parsing (Chinese only, no EN)
            for line in text.splitlines():
                cleaned = _LINE_PREFIX.sub("", line).strip()
                if cleaned:
                    pairs.append({"chinese": cleaned, "english": ""})

    # Deduplicate by Chinese sentence and limit to _SENTENCE_TARGET
    deduped: List[dict] = []
    seen_cn = set()
    for pair in pairs:
        cn = pair.get("chinese")
        if not cn or cn in seen_cn:
            continue
        seen_cn.add(cn)
        deduped.append(pair)
        if len(deduped) == _SENTENCE_TARGET:
            break

    return deduped


def _prepare_sentence_payloads(sentences: List[dict], user=None) -> List[dict]:
    """
    Augment raw LLM sentences with lesson-style tokens and translations.
    """
    if not sentences:
        return []

    tokenized_sentences: List[Tuple[dict, List[Tuple[str, str]], str]] = []
    candidate_texts = set()

    for sentence in sentences:
        raw_chinese = str(sentence.get("chinese") or "")
        token_pairs = tokenize(raw_chinese)
        tokenized_sentences.append((sentence, token_pairs, raw_chinese))
        for tok_text, kind in token_pairs:
            if kind == "word" and tok_text:
                candidate_texts.add(tok_text)
                candidate_texts.update(tok_text)

    lemma_lookup = _build_lemma_lookup(candidate_texts)

    processed: List[dict] = []
    all_lemma_ids = set()
    token_id_counter = 1
    translation_id_counter = 1

    for sentence_data, token_pairs, raw_text in tokenized_sentences:
        tokens, token_id_counter, sentence_lemma_ids = _build_tokens_for_sentence(
            token_pairs, lemma_lookup, token_id_counter
        )
        all_lemma_ids.update(sentence_lemma_ids)

        english_text = str(sentence_data.get("english") or "").strip()
        translations = []
        if english_text:
            translations.append(
                {
                    "id": translation_id_counter,
                    "language": "en",
                    "text": english_text,
                    "source": "machine",
                }
            )
            translation_id_counter += 1

        processed.append(
            {
                "chinese": (raw_text.strip() or raw_text),
                "english": english_text,
                "tokens": tokens,
                "translations": translations,
            }
        )

    familiarity_map = _build_familiarity_map(all_lemma_ids, user)
    if familiarity_map:
        for sentence in processed:
            for token in sentence["tokens"]:
                lemma_id = token.get("lemma")
                if lemma_id and lemma_id in familiarity_map:
                    token["familiarity"] = familiarity_map[lemma_id]

    return processed


def _build_lemma_lookup(candidates: set) -> Dict[str, Lemma]:
    if not candidates:
        return {}
    lookup: Dict[str, Lemma] = {}
    lemmas = Lemma.objects.filter(simplified__in=candidates).only("id", "simplified", "pinyin_numbers")
    for lemma in lemmas:
        lookup.setdefault(lemma.simplified, lemma)
    return lookup


def _build_tokens_for_sentence(
    token_pairs: List[Tuple[str, str]],
    lemma_lookup: Dict[str, Lemma],
    token_id_counter: int,
) -> Tuple[List[dict], int, set]:
    tokens: List[dict] = []
    lemma_ids = set()
    token_index = 1

    for tok_text, kind in token_pairs:
        if kind == "word":
            lemma = lemma_lookup.get(tok_text)
            if lemma:
                tokens.append(_make_token_dict(token_id_counter, token_index, tok_text, kind, lemma))
                lemma_ids.add(lemma.id)
                token_index += 1
                token_id_counter += 1
            else:
                for ch in tok_text:
                    ch_lemma = lemma_lookup.get(ch)
                    tokens.append(_make_token_dict(token_id_counter, token_index, ch, kind, ch_lemma))
                    if ch_lemma:
                        lemma_ids.add(ch_lemma.id)
                    token_index += 1
                    token_id_counter += 1
            continue

        tokens.append(_make_token_dict(token_id_counter, token_index, tok_text, kind, None))
        token_index += 1
        token_id_counter += 1

    return tokens, token_id_counter, lemma_ids


def _make_token_dict(token_id: int, index: int, text: str, kind: str, lemma: Optional[Lemma]) -> dict:
    return {
        "id": token_id,
        "index": index,
        "text": text,
        "kind": kind,
        "lemma": lemma.id if lemma else None,
        "pinyin": lemma.pinyin_numbers if lemma and lemma.pinyin_numbers else None,
        "familiarity": None,
    }


def _build_familiarity_map(lemma_ids: set, user=None) -> Dict[int, int]:
    if not lemma_ids or not user or not getattr(user, "is_authenticated", False):
        return {}
    qs = LemmaProgress.objects.filter(user=user, lemma_id__in=lemma_ids).values_list("lemma_id", "familiarity")
    return {lemma_id: familiarity for lemma_id, familiarity in qs}
