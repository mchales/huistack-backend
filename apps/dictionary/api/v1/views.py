import json
import re
from typing import List

from django.shortcuts import get_object_or_404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.common.llm import ChatMessage, LLMClient, LLMError
from apps.dictionary.examples import prepare_sentence_payloads
from apps.dictionary.models import Lemma, Sense, UserLemmaExample
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
    raw_sentences = sentences[:_SENTENCE_TARGET]
    processed_sentences = prepare_sentence_payloads(
        raw_sentences,
        user if user and getattr(user, "is_authenticated", False) else None,
    )

    if user and getattr(user, "is_authenticated", False):
        UserLemmaExample.objects.update_or_create(
            user=user,
            lemma=lemma,
            defaults={"sentences": raw_sentences},
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

