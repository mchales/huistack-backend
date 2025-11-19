from __future__ import annotations

import logging
import os
import tempfile
import threading
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .models import Lesson, LessonVideoJob, Sentence

try:  # pragma: no cover - optional dependency guarded in tests
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - handled in runtime
    cv2 = None  # type: ignore

logger = logging.getLogger(__name__)


def create_lesson_video_job(
    *, lesson: Lesson, uploaded_file, user=None
) -> LessonVideoJob:
    """Persist an uploaded video and enqueue background processing."""
    if uploaded_file is None:
        raise ValueError("uploaded_file is required")

    owner = user if user and getattr(user, "is_authenticated", False) else None
    sentences_qs = lesson.sentences.exclude(start_ms__isnull=True)
    job = LessonVideoJob(
        lesson=lesson,
        uploaded_by=owner,
        total_frames=sentences_qs.count(),
        processed_frames=0,
    )
    job.video_file.save(uploaded_file.name, uploaded_file, save=False)
    job.status = LessonVideoJob.Status.QUEUED
    job.save()

    def _enqueue():
        enqueue_lesson_video_job(job.id)

    connection = transaction.get_connection()
    if connection.in_atomic_block:
        transaction.on_commit(_enqueue)
    else:
        _enqueue()
    return job


def enqueue_lesson_video_job(job_id) -> None:
    """Dispatch a video job using the configured executor."""
    executor = getattr(settings, "LESSON_VIDEO_JOB_EXECUTOR", "thread")
    if executor == "thread":
        thread = threading.Thread(
            target=process_lesson_video_job, args=(job_id,), daemon=True
        )
        thread.start()
    else:
        process_lesson_video_job(job_id)


def process_lesson_video_job(job_id) -> LessonVideoJob | None:
    """Process a queued lesson video job."""
    try:
        job = LessonVideoJob.objects.select_related("lesson").get(id=job_id)
    except LessonVideoJob.DoesNotExist:  # pragma: no cover - defensive
        logger.warning("LessonVideoJob %s not found", job_id)
        return None

    if job.is_terminal:
        return job

    sentences = list(
        Sentence.objects.filter(lesson=job.lesson)
        .exclude(start_ms__isnull=True)
        .order_by("index", "id")
    )
    if not sentences:
        return _fail_job(job, "No timestamped sentences were found for this lesson.")

    if cv2 is None:
        return _fail_job(job, "opencv-python is required to process lesson videos.")

    job.status = LessonVideoJob.Status.PROCESSING
    job.started_at = timezone.now()
    job.error_message = ""
    job.processed_frames = 0
    job.save(
        update_fields=[
            "status",
            "started_at",
            "error_message",
            "processed_frames",
            "updated_at",
        ]
    )

    temp_file_path = None
    capture = None
    try:
        temp_file_path = _materialize_video(job)
        capture = cv2.VideoCapture(temp_file_path)
        if not capture or not capture.isOpened():
            raise RuntimeError("Unable to open uploaded video.")

        for sentence in sentences:
            try:
                frame_saved = _extract_frame_for_sentence(capture, sentence, sentence.start_ms or 0)
            except Exception as exc:
                frame_saved = False
                logger.exception(
                    "Failed to capture frame for sentence %s in job %s",
                    sentence.id,
                    job.id,
                )
            if frame_saved:
                job.processed_frames += 1
                job.save(update_fields=["processed_frames", "updated_at"])

        job.status = LessonVideoJob.Status.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "completed_at", "updated_at"])
        _update_lesson_video_flag(job.lesson_id)
        return job
    except Exception as exc:
        logger.exception("Lesson video job %s failed", job.id)
        job.error_message = str(exc)
        job.status = LessonVideoJob.Status.FAILED
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        _update_lesson_video_flag(job.lesson_id)
        return job
    finally:
        if capture is not None:
            capture.release()
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                logger.warning("Unable to remove temp video file %s", temp_file_path)
        _cleanup_video(job)


def _materialize_video(job: LessonVideoJob) -> str:
    """Copy the uploaded video to a temp file so OpenCV can consume it."""
    extension = Path(job.video_file.name).suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(suffix=extension, delete=False)
    with job.video_file.open("rb") as src, tmp:
        for chunk in src.chunks():
            tmp.write(chunk)
    return tmp.name


def _extract_frame_for_sentence(capture, sentence: Sentence, start_ms: int) -> bool:
    """Seek to the timestamp and store the captured frame on the sentence."""
    capture.set(cv2.CAP_PROP_POS_MSEC, float(start_ms))
    success, frame = capture.read()
    if not success or frame is None:
        raise RuntimeError(f"Unable to capture frame at {start_ms}ms")

    ok, buffer = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("Failed to encode frame to JPEG.")

    filename = f"{uuid.uuid4().hex}.jpg"
    sentence.frame_image.save(filename, ContentFile(buffer.tobytes()), save=True)
    return True


def _fail_job(job: LessonVideoJob, message: str) -> LessonVideoJob:
    job.status = LessonVideoJob.Status.FAILED
    job.error_message = message
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
    _update_lesson_video_flag(job.lesson_id)
    _cleanup_video(job)
    return job


def _cleanup_video(job: LessonVideoJob) -> None:
    """Delete the original uploaded video once we're done processing."""
    if job.video_file:
        try:
            job.video_file.delete(save=False)
        except Exception:  # pragma: no cover - depends on storage backend
            logger.warning("Unable to delete processed video for job %s", job.id)


def _update_lesson_video_flag(lesson_id):
    has_frames = Sentence.objects.filter(
        lesson_id=lesson_id, frame_image__isnull=False
    ).exists()
    Lesson.objects.filter(id=lesson_id).update(has_video_frames=has_frames)
