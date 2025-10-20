from rest_framework import serializers

from apps.dictionary.api.v1.serializers import LemmaSerializer
from apps.dictionary.models import Lemma
from apps.progress.models import LemmaProgress


class LemmaProgressCreateSerializer(serializers.Serializer):
    lemma = serializers.PrimaryKeyRelatedField(queryset=Lemma.objects.all())
    familiarity = serializers.IntegerField(min_value=1, max_value=5)


class LemmaProgressSerializer(serializers.ModelSerializer):
    lemma = LemmaSerializer(read_only=True)

    class Meta:
        model = LemmaProgress
        fields = [
            "id",
            "lemma",
            "familiarity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

