from rest_framework import serializers
from apps.dictionary.models import Lemma, Sense
from apps.progress.models import LemmaProgress


class SenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sense
        fields = ["id", "lemma", "sense_index", "gloss"]
        read_only_fields = ["id"]


class LemmaSerializer(serializers.ModelSerializer):
    senses = SenseSerializer(many=True, read_only=True)
    tokens = serializers.SerializerMethodField()

    class Meta:
        model = Lemma
        fields = [
            "id",
            "traditional",
            "simplified",
            "pinyin_numbers",
            "meta",
            "senses",
            "tokens",
        ]
        read_only_fields = ["id", "senses", "tokens"]

    def get_tokens(self, obj):
        if not self.context.get("include_tokens"):
            return []

        simplified = obj.simplified or ""
        if not simplified:
            return []

        chars = list(simplified)
        lookup = {
            lemma.simplified: lemma
            for lemma in Lemma.objects.filter(simplified__in=set(chars)).only("id", "simplified", "pinyin_numbers")
        }

        familiarity_map = {}
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated and lookup:
            lemma_ids = {lemma.id for lemma in lookup.values()}
            familiarity_map = {
                lemma_id: familiarity
                for lemma_id, familiarity in LemmaProgress.objects.filter(
                    user=user, lemma_id__in=lemma_ids
                ).values_list("lemma_id", "familiarity")
            }

        tokens = []
        for idx, ch in enumerate(chars, start=1):
            lemma = lookup.get(ch)
            lemma_id = lemma.id if lemma else None
            tokens.append(
                {
                    "id": idx,
                    "index": idx,
                    "text": ch,
                    "kind": "word",
                    "lemma": lemma_id,
                    "familiarity": familiarity_map.get(lemma_id) if lemma_id else None,
                    "pinyin": lemma.pinyin_numbers if lemma and lemma.pinyin_numbers else None,
                }
            )
        return tokens
