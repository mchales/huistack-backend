from django.conf import settings
from rest_framework import serializers

from apps.lessons.models import (
    Lesson,
    LessonSettings,
    LessonVideoJob,
    SourceText,
    Sentence,
    SentenceTranslation,
    SentenceToken,
)
from apps.lessons.services import LessonAudioError, generate_presigned_storage_url
from apps.lessons.video_jobs import create_lesson_video_job


class SentenceTokenSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Optionally include user's lemma familiarity if provided in context
        mapping = self.context.get("lemma_familiarity_map")
        if mapping and instance.lemma_id in mapping:
            data["familiarity"] = mapping[instance.lemma_id]
        # Include pinyin (tone numbers) when lemma is available
        if instance.lemma_id and getattr(instance.lemma, "pinyin_numbers", None):
            data["pinyin"] = instance.lemma.pinyin_numbers
        else:
            data["pinyin"] = None
        return data

    class Meta:
        model = SentenceToken
        fields = ["id", "index", "text", "kind", "lemma"]
        read_only_fields = ["id"]


class SentenceTranslationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SentenceTranslation
        fields = ["id", "language", "text", "source"]
        read_only_fields = ["id"]


class SentenceSerializer(serializers.ModelSerializer):
    tokens = SentenceTokenSerializer(many=True, read_only=True)
    translations = SentenceTranslationSerializer(many=True, read_only=True)
    frame_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Sentence
        fields = [
            "id",
            "index",
            "text",
            "start_char",
            "end_char",
            "start_ms",
            "end_ms",
            "frame_image_url",
            "tokens",
            "translations",
        ]
        read_only_fields = ["id", "tokens", "translations", "frame_image_url"]

    def get_frame_image_url(self, obj: Sentence):
        if not obj.frame_image:
            return None
        try:
            url = obj.frame_image.url
        except ValueError:
            return None
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
        if not bucket:
            return url
        try:
            return generate_presigned_storage_url(url, expires_in=86400)
        except LessonAudioError:
            return url


class SourceTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceText
        fields = ["id", "name", "text", "order"]
        read_only_fields = ["id"]


class LessonSerializer(serializers.ModelSerializer):
    sentences = SentenceSerializer(many=True, read_only=True)
    sources = SourceTextSerializer(many=True, read_only=True)

    class Meta:
        model = Lesson
        fields = [
            "id",
            "title",
            "audio_url",
            "source_language",
            "target_language",
            "has_video_frames",
            "meta",
            "created_at",
            "sentences",
            "sources",
        ]
        read_only_fields = ["id", "created_at", "sentences", "sources", "has_video_frames"]


class LessonSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ["id", "title", "created_at"]
        read_only_fields = ["id", "title", "created_at"]


class LessonViewerSettingsSerializer(serializers.Serializer):
    showPinyin = serializers.BooleanField(source="show_pinyin", required=False)
    showPinyinOnlyForUnfamiliar = serializers.BooleanField(
        source="show_pinyin_only_for_unfamiliar", required=False
    )
    characterSize = serializers.IntegerField(
        source="character_size", required=False, min_value=8, max_value=96
    )
    pinyinSize = serializers.IntegerField(
        source="pinyin_size", required=False, min_value=6, max_value=48
    )
    showFrameImages = serializers.BooleanField(source="show_frame_images", required=False)


class LessonSettingsSerializer(serializers.ModelSerializer):
    viewerSettings = LessonViewerSettingsSerializer(source="*", required=False)
    autoplayAudioOnNext = serializers.BooleanField(
        source="autoplay_audio_on_next", required=False
    )

    class Meta:
        model = LessonSettings
        fields = ["viewerSettings", "autoplayAudioOnNext"]

    def update(self, instance, validated_data):
        lesson = self.context.get("lesson") or getattr(instance, "lesson", None)
        updated_fields: list[str] = []
        for attr, value in validated_data.items():
            if attr == "show_frame_images" and lesson and not lesson.has_video_frames:
                value = False
            if attr == "autoplay_audio_on_next" and lesson and not lesson.audio_url:
                value = False
            if getattr(instance, attr) == value:
                continue
            setattr(instance, attr, value)
            updated_fields.append(attr)
        if updated_fields:
            updated_fields.append("updated_at")
            instance.save(update_fields=updated_fields)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        lesson = self.context.get("lesson") or getattr(instance, "lesson", None)
        viewer = data.get("viewerSettings") or {}
        if lesson:
            if not lesson.has_video_frames:
                viewer["showFrameImages"] = False
            if not lesson.audio_url:
                data["autoplayAudioOnNext"] = False
        data["viewerSettings"] = viewer
        return data


class IngestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    text = serializers.CharField()
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    source_language = serializers.CharField(max_length=16, required=False, default="zh")
    target_language = serializers.CharField(max_length=16, required=False, default="en")
    translate = serializers.BooleanField(required=False, default=False)


class IngestSrtSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    file = serializers.FileField()
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    source_language = serializers.CharField(max_length=16, required=False, default="zh")
    target_language = serializers.CharField(max_length=16, required=False, default="en")
    audio_url = serializers.URLField(required=False, allow_blank=True, default="")
    translate = serializers.BooleanField(required=False, default=False)
    video = serializers.FileField(required=False, allow_null=True)

    def validate_video(self, value):
        if value is None:
            return None
        filename = value.name.lower()
        allowed = (".mp4", ".mov", ".mkv", ".avi")
        if not filename.endswith(allowed):
            raise serializers.ValidationError("Unsupported video type. Use MP4/MOV/MKV/AVI files.")
        value.seek(0)
        return value


class LessonVideoJobSerializer(serializers.ModelSerializer):
    video_url = serializers.SerializerMethodField()

    class Meta:
        model = LessonVideoJob
        fields = [
            "id",
            "lesson",
            "status",
            "error_message",
            "total_frames",
            "processed_frames",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
            "video_url",
        ]
        read_only_fields = fields

    def get_video_url(self, obj: LessonVideoJob):
        if obj.video_file:
            try:
                return obj.video_file.url
            except ValueError:
                return None
        return None


class LessonVideoJobCreateSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField()
    video = serializers.FileField()

    def validate_lesson_id(self, value):
        try:
            return Lesson.objects.get(id=value)
        except Lesson.DoesNotExist:
            raise serializers.ValidationError("Lesson not found.")

    def validate_video(self, value):
        filename = value.name.lower()
        allowed = (".mp4", ".mov", ".mkv", ".avi")
        if not filename.endswith(allowed):
            raise serializers.ValidationError("Unsupported video type. Use MP4/MOV/MKV/AVI files.")
        value.seek(0)
        return value

    def create(self, validated_data):
        lesson = validated_data["lesson_id"]
        video = validated_data["video"]
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return create_lesson_video_job(lesson=lesson, uploaded_file=video, user=user)
