from typing import List

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.dictionary.models import Lemma
from apps.lessons.models import Lesson, SourceText, Sentence, SentenceToken, SentenceTranslation
from apps.lessons.utils import split_sentences, tokenize, translate_text, parse_srt
from apps.lessons.services import generate_lesson_audio_presigned_url, LessonAudioError
from .serializers import (
    IngestSerializer,
    IngestSrtSerializer,
    LessonSerializer,
    LessonSummarySerializer,
)


class LessonViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Lesson.objects.all().order_by("-created_at")
    serializer_class = LessonSerializer

    @action(
        detail=True,
        methods=["get"],
        permission_classes=[IsAuthenticatedOrReadOnly],
        url_path="audio-url",
    )
    def audio_url(self, request, pk=None):
        lesson = self.get_object()
        if not lesson.audio_url:
            return Response({"detail": "Audio not available"}, status=status.HTTP_404_NOT_FOUND)
        try:
            signed_url = generate_lesson_audio_presigned_url(lesson.audio_url)
        except (LessonAudioError, ImproperlyConfigured) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"url": signed_url})

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated], url_path="mine")
    def mine(self, request):
        lessons = self.filter_queryset(
            self.get_queryset().filter(created_by=request.user).only("id", "title", "created_at")
        )
        serializer = LessonSummarySerializer(lessons, many=True)
        return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticatedOrReadOnly])
def ingest_text(request):
    serializer = IngestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    missing_characters = set()

    with transaction.atomic():
        lesson = Lesson.objects.create(
            title=data["title"],
            source_language=data.get("source_language", "zh"),
            target_language=data.get("target_language", "en"),
            created_by=request.user if request.user and request.user.is_authenticated else None,
            meta={"ingest": "jieba"},
        )
        source = SourceText.objects.create(
            lesson=lesson,
            name=data.get("name", ""),
            text=data["text"],
            order=1,
        )

        sents: List[str] = split_sentences(source.text)
        sent_index = 1
        for sent_text in sents:
            sent = Sentence.objects.create(
                lesson=lesson, source=source, index=sent_index,
                text=sent_text, start_char=0, end_char=len(sent_text)
            )
            sent_index += 1

            toks = tokenize(sent_text)
            tok_index = 1
            for tok_text, kind in toks:
                lemma = None
                if kind == "word":
                    lemma = Lemma.objects.filter(simplified=tok_text).only("id").first()
                    if lemma is None:
                        # Fallback to per-character lookup
                        for ch in tok_text:
                            ch_lemma = Lemma.objects.filter(simplified=ch).only("id").first()
                            if ch_lemma is None:
                                missing_characters.add(ch)
                            SentenceToken.objects.create(
                                sentence=sent,
                                index=tok_index,
                                text=ch,
                                kind=kind,
                                lemma=ch_lemma,
                            )
                            tok_index += 1
                        continue  # Skip the full token since expanded into characters

                SentenceToken.objects.create(
                    sentence=sent,
                    index=tok_index,
                    text=tok_text,
                    kind=kind,
                    lemma=lemma,
                )
                tok_index += 1

            # Machine translation per sentence (best-effort)
            mt = translate_text(
                sent_text,
                source_lang=lesson.source_language,
                target_lang=lesson.target_language,
            )
            if mt:
                # Unique per (sentence, language, source); we use source='machine'
                SentenceTranslation.objects.create(
                    sentence=sent,
                    language=lesson.target_language,
                    text=mt,
                    source="machine",
                )

    return Response(
        {
            "lesson": LessonSerializer(lesson).data,
            "created": True,
            "sentence_count": lesson.sentences.count(),
            "missing_characters": sorted(list(missing_characters)),  # Added here
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticatedOrReadOnly])
def ingest_srt(request):
    serializer = IngestSrtSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    uploaded = data["file"]
    raw_bytes = uploaded.read()
    try:
        srt_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Fallback to latin-1 if encoding unknown
        srt_text = raw_bytes.decode("latin-1")

    cues = parse_srt(srt_text)

    missing_characters = set()

    with transaction.atomic():
        lesson = Lesson.objects.create(
            title=data["title"],
            audio_url=data.get("audio_url", ""),
            source_language=data.get("source_language", "zh"),
            target_language=data.get("target_language", "en"),
            created_by=request.user if request.user and request.user.is_authenticated else None,
            meta={"ingest": "srt"},
        )
        # Keep the original SRT text in a source for provenance
        source = SourceText.objects.create(
            lesson=lesson,
            name=data.get("name", getattr(uploaded, "name", "")) or "",
            text=srt_text,
            order=1,
        )

        sent_index = 1
        for start_ms, end_ms, sent_text in cues:
            sent = Sentence.objects.create(
                lesson=lesson,
                source=source,
                index=sent_index,
                text=sent_text,
                start_char=0,
                end_char=len(sent_text),
                start_ms=start_ms,
                end_ms=end_ms,
            )
            sent_index += 1

            toks = tokenize(sent_text)
            tok_index = 1
            for tok_text, kind in toks:
                lemma = None
                if kind == "word":
                    lemma = Lemma.objects.filter(simplified=tok_text).only("id").first()
                    if lemma is None:
                        for ch in tok_text:
                            ch_lemma = Lemma.objects.filter(simplified=ch).only("id").first()
                            if ch_lemma is None:
                                missing_characters.add(ch)
                            SentenceToken.objects.create(
                                sentence=sent,
                                index=tok_index,
                                text=ch,
                                kind=kind,
                                lemma=ch_lemma,
                            )
                            tok_index += 1
                        continue

                SentenceToken.objects.create(
                    sentence=sent,
                    index=tok_index,
                    text=tok_text,
                    kind=kind,
                    lemma=lemma,
                )
                tok_index += 1

            mt = translate_text(
                sent_text,
                source_lang=lesson.source_language,
                target_lang=lesson.target_language,
            )
            if mt:
                SentenceTranslation.objects.create(
                    sentence=sent,
                    language=lesson.target_language,
                    text=mt,
                    source="machine",
                )

    return Response(
        {
            "lesson": LessonSerializer(lesson).data,
            "created": True,
            "sentence_count": lesson.sentences.count(),
            "missing_characters": sorted(list(missing_characters)),
        }
    )
