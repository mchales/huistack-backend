from typing import List

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.dictionary.models import Lemma
from apps.progress.models import LemmaProgress
from apps.lessons.models import (
    Lesson,
    LessonVideoJob,
    SourceText,
    Sentence,
    SentenceToken,
    SentenceTranslation,
)
from apps.lessons.services import LessonAudioError, generate_lesson_audio_presigned_url
from apps.lessons.utils import parse_srt, split_sentences, tokenize, translate_text
from apps.lessons.video_jobs import create_lesson_video_job
from .serializers import (
    IngestSerializer,
    IngestSrtSerializer,
    LessonSerializer,
    LessonSummarySerializer,
    LessonVideoJobSerializer,
    LessonVideoJobCreateSerializer,
)


class LessonViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Lesson.objects.all().order_by("-created_at")
    serializer_class = LessonSerializer

    def retrieve(self, request, *args, **kwargs):
        lesson = self.get_object()

        # Build a mapping of lemma_id -> familiarity for the authenticated user
        lemma_fam_map = {}
        user = request.user if request and hasattr(request, "user") else None
        if user and user.is_authenticated:
            lemma_ids_qs = (
                SentenceToken.objects.filter(sentence__lesson=lesson, lemma__isnull=False)
                .values_list("lemma_id", flat=True)
                .distinct()
            )
            lemma_ids = list(lemma_ids_qs)
            if lemma_ids:
                pairs = (
                    LemmaProgress.objects.filter(user=user, lemma_id__in=lemma_ids)
                    .values_list("lemma_id", "familiarity")
                )
                lemma_fam_map = {lemma_id: fam for lemma_id, fam in pairs}

        context = self.get_serializer_context()
        if lemma_fam_map:
            context = {**context, "lemma_familiarity_map": lemma_fam_map}

        serializer = self.get_serializer(lesson, context=context)
        return Response(serializer.data)

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

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser],
        url_path="upload-video",
    )
    def upload_video(self, request, pk=None):
        lesson = self.get_object()
        if lesson.created_by_id and lesson.created_by_id != request.user.id and not request.user.is_staff:
            return Response(
                {"detail": "You do not have permission to upload a video for this lesson."},
                status=status.HTTP_403_FORBIDDEN,
            )
        video_file = request.data.get("video")
        if not video_file:
            return Response({"detail": "A video file is required."}, status=status.HTTP_400_BAD_REQUEST)
        video_job = create_lesson_video_job(lesson=lesson, uploaded_file=video_file, user=request.user)
        serializer = LessonVideoJobSerializer(video_job, context=self.get_serializer_context())
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticatedOrReadOnly])
def ingest_text(request):
    serializer = IngestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    do_translate = data.get("translate", False)

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

            # Machine translation per sentence (best-effort) when requested
            if do_translate:
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
    do_translate = data.get("translate", False)

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

            if do_translate:
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

    response_payload = {
        "lesson": LessonSerializer(lesson).data,
        "created": True,
        "sentence_count": lesson.sentences.count(),
        "missing_characters": sorted(list(missing_characters)),
    }

    video_file = data.get("video")
    if video_file:
        video_job = create_lesson_video_job(
            lesson=lesson,
            uploaded_file=video_file,
            user=request.user if hasattr(request, "user") else None,
        )
        response_payload["video_job"] = LessonVideoJobSerializer(video_job).data

    return Response(response_payload)


@api_view(["GET"])
@permission_classes([IsAuthenticatedOrReadOnly])
def sentence_translation(request, sentence_id: int):
    try:
        sentence = (
            Sentence.objects.select_related("lesson")
            .only("id", "text", "lesson__target_language", "lesson__source_language")
            .get(id=sentence_id)
        )
    except Sentence.DoesNotExist:
        return Response({"detail": "Sentence not found"}, status=status.HTTP_404_NOT_FOUND)

    lang = request.query_params.get("language") or sentence.lesson.target_language

    translations = {
        t.source: t
        for t in SentenceTranslation.objects.filter(sentence=sentence, language=lang).only(
            "id", "language", "text", "source"
        )
    }

    # Preference: user > machine > ingest
    preferred = translations.get("user") or translations.get("machine") or translations.get("ingest")

    if not preferred:
        # Best-effort: generate a machine translation, persist, and return it
        mt = translate_text(
            sentence.text,
            source_lang=sentence.lesson.source_language,
            target_lang=lang,
        )
        if mt:
            preferred, _created = SentenceTranslation.objects.get_or_create(
                sentence=sentence,
                language=lang,
                source="machine",
                defaults={"text": mt},
            )
        else:
            return Response(
                {"detail": f"No translation found for language '{lang}'"},
                status=status.HTTP_404_NOT_FOUND,
            )

    return Response(
        {
            "sentence_id": sentence.id,
            "language": preferred.language,
            "translation": preferred.text,
            "source": preferred.source,
        }
    )


class LessonVideoJobViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = LessonVideoJob.objects.select_related("lesson").all()
    serializer_class = LessonVideoJobSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    parser_classes = (MultiPartParser, FormParser)

    def get_queryset(self):
        qs = super().get_queryset()
        lesson_id = self.request.query_params.get("lesson_id")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    def create(self, request, *args, **kwargs):
        input_serializer = LessonVideoJobCreateSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        input_serializer.is_valid(raise_exception=True)
        job = input_serializer.save()
        output_serializer = self.get_serializer(job)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
