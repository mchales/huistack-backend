import uuid
from django.conf import settings
from django.db import models
from apps.dictionary.models import Lemma


class Lesson(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    source_language = models.CharField(max_length=16, default="zh")
    target_language = models.CharField(max_length=16, default="en")
    audio_url = models.URLField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Lesson {self.id}: {self.title}"


class SourceText(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="sources")
    name = models.CharField(max_length=255, blank=True, default="")
    text = models.TextField()
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["lesson_id", "order", "id"]

    def __str__(self) -> str:
        return f"SourceText {self.id} for Lesson {self.lesson_id}"


class Sentence(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="sentences")
    source = models.ForeignKey(
        SourceText, on_delete=models.CASCADE, related_name="sentences", null=True, blank=True
    )
    index = models.PositiveIntegerField(help_text="1-based index within lesson")
    text = models.TextField()
    start_char = models.PositiveIntegerField(default=0)
    end_char = models.PositiveIntegerField(default=0)
    start_ms = models.PositiveIntegerField(
        null=True, blank=True, help_text="Start time in ms (optional)"
    )
    end_ms = models.PositiveIntegerField(
        null=True, blank=True, help_text="End time in ms (optional)"
    )

    class Meta:
        ordering = ["lesson_id", "index", "id"]
        indexes = [models.Index(fields=["lesson", "index"])]

    def __str__(self) -> str:
        return f"Sent {self.index} — {self.text[:24]}"


class SentenceTranslation(models.Model):
    sentence = models.ForeignKey(
        Sentence, on_delete=models.CASCADE, related_name="translations"
    )
    language = models.CharField(max_length=16, default="en")
    text = models.TextField()
    source = models.CharField(
        max_length=32, default="user", help_text="user|machine|ingest"
    )

    class Meta:
        indexes = [models.Index(fields=["sentence", "language"])]
        constraints = [
            models.UniqueConstraint(
                fields=["sentence", "language", "source"],
                name="uniq_translation_per_sentence_lang_src",
            )
        ]

    def __str__(self) -> str:
        return f"{self.language}: {self.text[:32]}"


class SentenceToken(models.Model):
    WORD = "word"
    PUNCT = "punct"
    LATIN = "latin"
    SPACE = "space"
    NUMBER = "number"
    KIND_CHOICES = [
        (WORD, "Word"),
        (PUNCT, "Punctuation"),
        (LATIN, "Latin"),
        (SPACE, "Space"),
        (NUMBER, "Number"),
    ]

    sentence = models.ForeignKey(
        Sentence, on_delete=models.CASCADE, related_name="tokens"
    )
    index = models.PositiveIntegerField(help_text="1-based index within sentence")
    text = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=WORD)
    lemma = models.ForeignKey(
        Lemma, on_delete=models.SET_NULL, null=True, blank=True, related_name="occurrences"
    )

    class Meta:
        ordering = ["sentence_id", "index", "id"]
        indexes = [models.Index(fields=["sentence", "index"])]

    def __str__(self) -> str:
        return f"{self.text} ({self.kind})"
