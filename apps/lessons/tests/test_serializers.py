import pytest
from django.core.files.base import ContentFile

from apps.lessons.api.v1.serializers import SentenceSerializer
from apps.lessons.models import Lesson, Sentence, SourceText


@pytest.mark.django_db
def test_sentence_serializer_returns_presigned_frame_url(monkeypatch, settings, tmp_path):
    settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = tmp_path

    captured = {}

    def fake_presign(url, expires_in):
        captured["url"] = url
        captured["expires_in"] = expires_in
        return "https://signed.example.com/frame.jpg"

    monkeypatch.setattr(
        "apps.lessons.api.v1.serializers.generate_presigned_storage_url",
        fake_presign,
    )

    lesson = Lesson.objects.create(title="Test", source_language="zh", target_language="en")
    source = SourceText.objects.create(lesson=lesson, name="src", text="hello", order=1)
    sentence = Sentence.objects.create(
        lesson=lesson, source=source, index=1, text="hello", start_char=0, end_char=5
    )
    sentence.frame_image.save("frame.jpg", ContentFile(b"frame-data"), save=True)

    serializer = SentenceSerializer(sentence)
    data = serializer.data

    assert data["frame_image_url"] == "https://signed.example.com/frame.jpg"
    assert captured["expires_in"] == 43200
    assert captured["url"]
