from django.conf import settings
from rest_framework import serializers

from apps.lessons.models import (
    Lesson,
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
            return generate_presigned_storage_url(url, expires_in=43200)
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
