import cv2
import numpy as np
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from apps.lessons.models import Lesson, LessonVideoJob, Sentence, SourceText
from apps.lessons.video_jobs import process_lesson_video_job


def _write_test_video(path):
    width, height = 32, 32
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 1, (width, height))
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = 128
    writer.write(frame)
    writer.release()


@pytest.mark.django_db
def test_upload_video_action_creates_job(tmp_path, settings):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = tmp_path
    settings.LESSON_VIDEO_JOB_EXECUTOR = "sync"

    User = get_user_model()
    owner = User.objects.create_user(username="owner", password="pass")
    lesson = Lesson.objects.create(
        title="Existing lesson",
        source_language="zh",
        target_language="en",
        created_by=owner,
    )
    source = SourceText.objects.create(lesson=lesson, name="src", text="Hello", order=1)
    Sentence.objects.create(
        lesson=lesson,
        source=source,
        index=1,
        text="Hello",
        start_char=0,
        end_char=5,
        start_ms=0,
        end_ms=1000,
    )

    client = APIClient()
    client.force_authenticate(owner)

    video_path = tmp_path / "upload.mp4"
    _write_test_video(video_path)
    uploaded = SimpleUploadedFile("upload.mp4", video_path.read_bytes(), content_type="video/mp4")

    url = reverse("lessons:v1:lesson-upload-video", kwargs={"pk": lesson.id})
    response = client.post(url, {"video": uploaded}, format="multipart")
    assert response.status_code == 201

    job = LessonVideoJob.objects.get(lesson=lesson)
    assert job.status in [LessonVideoJob.Status.QUEUED, LessonVideoJob.Status.PROCESSING]
    process_lesson_video_job(job.id)
    job.refresh_from_db()
    assert job.status == LessonVideoJob.Status.COMPLETED
    assert response.data["id"] == str(job.id)
    lesson.refresh_from_db()
    assert lesson.has_video_frames is True

    for sentence in lesson.sentences.all():
        sentence.refresh_from_db()
        assert sentence.frame_image
        sentence.frame_image.delete(save=False)
