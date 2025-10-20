from rest_framework import serializers
from apps.dictionary.models import Lemma, Sense


class SenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sense
        fields = ["id", "lemma", "sense_index", "gloss"]
        read_only_fields = ["id"]


class LemmaSerializer(serializers.ModelSerializer):
    senses = SenseSerializer(many=True, read_only=True)

    class Meta:
        model = Lemma
        fields = [
            "id",
            "traditional",
            "simplified",
            "pinyin_numbers",
            "meta",
            "senses",
        ]
        read_only_fields = ["id", "senses"]

