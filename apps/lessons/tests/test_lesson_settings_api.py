import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from apps.lessons.models import Lesson, LessonSettings


@pytest.mark.django_db
def test_get_settings_creates_defaults():
    user = get_user_model().objects.create_user(username="alice", password="pass")
    lesson = Lesson.objects.create(title="Sample lesson", created_by=user)

    client = APIClient()
    client.force_authenticate(user)

    url = reverse("lessons:v1:lesson-settings", kwargs={"pk": lesson.id})
    response = client.get(url)

    assert response.status_code == 200
    payload = response.data
    assert payload["viewerSettings"]["showPinyin"] is True
    assert payload["viewerSettings"]["characterSize"] == 28
    assert payload["autoplayAudioOnNext"] is False
    assert LessonSettings.objects.filter(user=user, lesson=lesson).count() == 1


@pytest.mark.django_db
def test_settings_patch_respects_missing_media():
    user = get_user_model().objects.create_user(username="bob", password="pass")
    lesson = Lesson.objects.create(title="Lesson without extras", created_by=user)
    client = APIClient()
    client.force_authenticate(user)

    url = reverse("lessons:v1:lesson-settings", kwargs={"pk": lesson.id})
    response = client.patch(
        url,
        {
            "viewerSettings": {"showFrameImages": True, "showPinyinOnlyForUnfamiliar": True},
            "autoplayAudioOnNext": True,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.data
    assert payload["viewerSettings"]["showFrameImages"] is False
    assert payload["autoplayAudioOnNext"] is False

    settings = LessonSettings.objects.get(user=user, lesson=lesson)
    assert settings.show_frame_images is False
    assert settings.autoplay_audio_on_next is False
    assert settings.show_pinyin_only_for_unfamiliar is True


@pytest.mark.django_db
def test_settings_patch_allows_features_when_available():
    user = get_user_model().objects.create_user(username="cara", password="pass")
    lesson = Lesson.objects.create(
        title="Media rich lesson",
        created_by=user,
        has_video_frames=True,
        audio_url="https://cdn.example.com/audio.mp3",
    )
    client = APIClient()
    client.force_authenticate(user)

    url = reverse("lessons:v1:lesson-settings", kwargs={"pk": lesson.id})
    response = client.patch(
        url,
        {
            "viewerSettings": {"showFrameImages": True, "characterSize": 32},
            "autoplayAudioOnNext": True,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.data
    assert payload["viewerSettings"]["showFrameImages"] is True
    assert payload["viewerSettings"]["characterSize"] == 32
    assert payload["autoplayAudioOnNext"] is True

    settings = LessonSettings.objects.get(user=user, lesson=lesson)
    assert settings.show_frame_images is True
    assert settings.autoplay_audio_on_next is True
    assert settings.character_size == 32
