from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.progress.models import LemmaProgress
from .serializers import (
    LemmaProgressCreateSerializer,
    LemmaProgressSerializer,
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

