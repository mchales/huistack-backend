import cv2
import numpy as np
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.lessons.models import Lesson, Sentence, SourceText
from apps.lessons.video_jobs import create_lesson_video_job, process_lesson_video_job


def _write_test_video(file_path):
    width, height = 64, 64
    fps = 1
    writer = cv2.VideoWriter(
        str(file_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    for value in (32, 224):
        frame = np.full((height, width, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.mark.django_db
def test_video_job_extracts_frames(tmp_path, settings):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    settings.MEDIA_ROOT = tmp_path
    settings.LESSON_VIDEO_JOB_EXECUTOR = "sync"
    lesson = Lesson.objects.create(
        title="Video Job",
        source_language="zh",
        target_language="en",
        meta={},
    )
    source = SourceText.objects.create(lesson=lesson, name="srt", text="line1\nline2", order=1)
    Sentence.objects.create(
        lesson=lesson,
        source=source,
        index=1,
        text="First line",
        start_char=0,
        end_char=10,
        start_ms=0,
        end_ms=1000,
    )
    Sentence.objects.create(
        lesson=lesson,
        source=source,
        index=2,
        text="Second line",
        start_char=0,
        end_char=11,
        start_ms=1000,
        end_ms=2000,
    )

    video_path = tmp_path / "sample.mp4"
    _write_test_video(video_path)
    uploaded = SimpleUploadedFile(
        "sample.mp4", video_path.read_bytes(), content_type="video/mp4"
    )

    job = create_lesson_video_job(lesson=lesson, uploaded_file=uploaded, user=None)
    assert job.status == job.Status.QUEUED
    process_lesson_video_job(job.id)
    job.refresh_from_db()

    assert job.status == job.Status.COMPLETED
    assert job.processed_frames == 2
    lesson.refresh_from_db()
    assert lesson.has_video_frames is True

    for sentence in Sentence.objects.filter(lesson=lesson):
        sentence.refresh_from_db()
        assert sentence.frame_image.name.startswith("image/")
        # Clean up stored files to keep the test filesystem tidy
        sentence.frame_image.delete(save=False)
