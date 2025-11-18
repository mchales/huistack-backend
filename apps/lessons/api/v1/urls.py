from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    LessonVideoJobViewSet,
    LessonViewSet,
    ingest_text,
    ingest_srt,
    sentence_translation,
)


router = DefaultRouter()
router.register(r"lessons", LessonViewSet, basename="lesson")
router.register(r"lesson-video-jobs", LessonVideoJobViewSet, basename="lesson-video-job")

lesson_audio_url = LessonViewSet.as_view({"get": "audio_url"})


urlpatterns = [
    path("lessons/ingest/", ingest_text, name="ingest-text"),
    path("lessons/ingest-srt/", ingest_srt, name="ingest-srt"),
    path("lessons/<uuid:pk>/audio-url/", lesson_audio_url, name="lesson-audio-url"),
    path("sentences/<int:sentence_id>/translation/", sentence_translation, name="sentence-translation"),
    path("", include(router.urls)),
]
