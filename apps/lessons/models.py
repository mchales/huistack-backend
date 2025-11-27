import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

from apps.dictionary.models import Lemma


def lesson_video_upload_path(instance, filename):
    extension = Path(filename).suffix or ".mp4"
    return f"video/{instance.lesson_id}/{uuid.uuid4().hex}{extension.lower()}"


def sentence_frame_upload_path(instance, _filename):
    return f"image/{instance.lesson_id}/{uuid.uuid4().hex}.jpg"


class Lesson(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    source_language = models.CharField(max_length=16, default="zh")
    target_language = models.CharField(max_length=16, default="en")
    audio_url = models.URLField(blank=True, default="")
    has_video_frames = models.BooleanField(
        default=False, help_text="True when at least one frame image has been generated"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Lesson {self.id}: {self.title}"


class LessonSettings(models.Model):
    """Stores per-user preferences for how a lesson should be displayed."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_settings"
    )
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="user_settings")
    show_pinyin = models.BooleanField(default=True)
    show_pinyin_only_for_unfamiliar = models.BooleanField(default=False)
    character_size = models.PositiveSmallIntegerField(default=28)
    pinyin_size = models.PositiveSmallIntegerField(default=14)
    show_frame_images = models.BooleanField(default=False)
    autoplay_audio_on_next = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "lesson"], name="uniq_user_lesson_settings")
        ]
        indexes = [models.Index(fields=["user", "lesson"])]

    def __str__(self) -> str:
        return f"Settings for {self.user_id} / {self.lesson_id}"


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
    frame_image = models.ImageField(
        upload_to=sentence_frame_upload_path, null=True, blank=True, help_text="Preview extracted from video"
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


class LessonVideoJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="video_jobs")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="lesson_video_jobs"
    )
    video_file = models.FileField(upload_to=lesson_video_upload_path)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True, default="")
    total_frames = models.PositiveIntegerField(default=0)
    processed_frames = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"VideoJob {self.id} for Lesson {self.lesson_id} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.FAILED}
