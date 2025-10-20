from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import LemmaViewSet, SenseViewSet, get_routes


router = DefaultRouter()
router.register(r'dictionary/lemmas', LemmaViewSet, basename='lemma')
router.register(r'dictionary/senses', SenseViewSet, basename='sense')


urlpatterns = [
    path('', include(router.urls)),
    path('dictionary/routes/', get_routes, name='routes'),
]

