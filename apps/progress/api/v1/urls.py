from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import LemmaProgressViewSet


router = DefaultRouter()
router.register(r'progress', LemmaProgressViewSet, basename='lemma-progress')


urlpatterns = [
    path('', include(router.urls)),
]

