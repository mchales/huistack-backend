from rest_framework import viewsets, filters
from rest_framework.decorators import api_view
from rest_framework.response import Response
from apps.dictionary.models import Lemma, Sense
from .serializers import LemmaSerializer, SenseSerializer


class LemmaViewSet(viewsets.ModelViewSet):
    queryset = Lemma.objects.all()
    serializer_class = LemmaSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["simplified", "traditional", "pinyin_numbers", "senses__gloss"]
    ordering_fields = ["simplified", "traditional"]
    ordering = ["simplified"]


class SenseViewSet(viewsets.ModelViewSet):
    queryset = Sense.objects.select_related("lemma").all()
    serializer_class = SenseSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["gloss", "lemma__simplified", "lemma__traditional", "lemma__pinyin_numbers"]
    ordering_fields = ["sense_index", "lemma__simplified"]
    ordering = ["lemma__simplified", "sense_index"]


@api_view(["GET"])
def get_routes(request):
    routes = {
        "Dictionary Endpoints": {
            "List Lemmas": "/api/v1/dictionary/lemmas/",
            "Retrieve Lemma": "/api/v1/dictionary/lemmas/{id}/",
            "List Senses": "/api/v1/dictionary/senses/",
            "Retrieve Sense": "/api/v1/dictionary/senses/{id}/",
        }
    }
    return Response(routes)
