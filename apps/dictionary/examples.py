from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from apps.dictionary.models import Lemma
from apps.lessons.utils import tokenize
from apps.progress.models import LemmaProgress


def prepare_sentence_payloads(sentences: List[dict], user=None) -> List[dict]:
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
