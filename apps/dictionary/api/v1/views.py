import json
import re
from typing import List

from django.shortcuts import get_object_or_404
from rest_framework import filters, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.common.llm import ChatMessage, LLMClient, LLMError
from apps.dictionary.models import Lemma, Sense
from .serializers import LemmaSerializer, SenseSerializer


_SENTENCE_TARGET = 3
_LINE_PREFIX = re.compile(r"^[\s\-\*\d\.\)\(]+")
llm_client = LLMClient()


class LemmaViewSet(viewsets.ModelViewSet):
    queryset = Lemma.objects.all()
    serializer_class = LemmaSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["simplified", "traditional", "pinyin_numbers", "senses__gloss"]
    ordering_fields = ["simplified", "traditional"]
    ordering = ["simplified"]


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
        ChatMessage(role="system", content="Concise Chinese tutor. Output CN only."),
        ChatMessage(role="user", content=prompt),
    ]

    try:
        llm_response = llm_client.chat(messages, max_tokens=192)
    except LLMError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    sentences = _extract_sentences(llm_response.content)
    if len(sentences) < _SENTENCE_TARGET:
        return Response(
            {"detail": "LLM did not return enough sentences."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(
        {
            "lemma_id": lemma.id,
            "simplified": lemma.simplified,
            "traditional": lemma.traditional,
            "pinyin_numbers": lemma.pinyin_numbers,
            "sentences": sentences[:_SENTENCE_TARGET],
        }
    )


def _build_prompt(lemma: Lemma) -> str:
    return (
        f"{lemma.simplified}"
        "→ give 3 short simple Chinese sentences using it. Reply JSON array only."
    )


def _extract_sentences(raw_text: str) -> List[str]:
    text = raw_text.strip()
    if not text:
        return []

    sentences: List[str] = []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        sentences = [str(item).strip() for item in parsed if str(item).strip()]
    else:
        for line in text.splitlines():
            cleaned = _LINE_PREFIX.sub("", line).strip()
            if cleaned:
                sentences.append(cleaned)

    deduped: List[str] = []
    seen = set()
    for sentence in sentences:
        if sentence and sentence not in seen:
            deduped.append(sentence)
            seen.add(sentence)
        if len(deduped) == _SENTENCE_TARGET:
            break
    return deduped
