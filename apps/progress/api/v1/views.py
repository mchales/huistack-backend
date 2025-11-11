from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.progress.models import LemmaProgress
from .serializers import (
    LemmaProgressCreateSerializer,
    LemmaProgressSerializer,
    LemmaSeenByCharactersQuerySerializer,
)


class LemmaProgressViewSet(
    mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]
    serializer_class = LemmaProgressSerializer

    def get_queryset(self):
        return (
            LemmaProgress.objects.select_related("lemma")
            .filter(user=self.request.user)
            .order_by("-updated_at")
        )

    @action(detail=False, methods=["post"], url_path="rank")
    def rank(self, request):
        """
        Upsert a familiarity ranking for a lemma for the current user.
        Body: { "lemma": <lemma_id>, "familiarity": 1..5 }
        """
        serializer = LemmaProgressCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lemma = serializer.validated_data["lemma"]
        familiarity = serializer.validated_data["familiarity"]

        obj, _created = LemmaProgress.objects.update_or_create(
            user=request.user,
            lemma=lemma,
            defaults={"familiarity": familiarity},
        )
        return Response(LemmaProgressSerializer(obj).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="seen-by-characters")
    def seen_by_characters(self, request):
        """
        Return lemma progress records whose lemma contains any character from the given word.
        """
        query_serializer = LemmaSeenByCharactersQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        word = query_serializer.validated_data.get("word", "")
        lemma = query_serializer.validated_data.get("lemma")

        def add_chars(source: str, bucket: set[str]):
            for char in source or "":
                if not char.isspace():
                    bucket.add(char)

        characters: set[str] = set()
        if word:
            add_chars(word, characters)
        if lemma:
            add_chars(lemma.simplified, characters)
            add_chars(lemma.traditional, characters)

        if not characters:
            return Response([], status=status.HTTP_200_OK)

        filters = Q()
        for char in characters:
            filters |= Q(lemma__simplified__contains=char) | Q(lemma__traditional__contains=char)

        queryset = self.get_queryset().filter(filters)
        if lemma:
            queryset = queryset.exclude(lemma=lemma)
        elif word:
            queryset = queryset.exclude(
                Q(lemma__simplified=word) | Q(lemma__traditional=word)
            )
        serialized = LemmaProgressSerializer(queryset, many=True)
        return Response(serialized.data, status=status.HTTP_200_OK)
