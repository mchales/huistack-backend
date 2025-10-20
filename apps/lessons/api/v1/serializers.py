from rest_framework import serializers
from apps.lessons.models import Lesson, SourceText, Sentence, SentenceTranslation, SentenceToken


class SentenceTokenSerializer(serializers.ModelSerializer):
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
            "tokens",
            "translations",
        ]
        read_only_fields = ["id", "tokens", "translations"]


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
            "meta",
            "created_at",
            "sentences",
            "sources",
        ]
        read_only_fields = ["id", "created_at", "sentences", "sources"]


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


class IngestSrtSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    file = serializers.FileField()
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    source_language = serializers.CharField(max_length=16, required=False, default="zh")
    target_language = serializers.CharField(max_length=16, required=False, default="en")
    audio_url = serializers.URLField(required=False, allow_blank=True, default="")
