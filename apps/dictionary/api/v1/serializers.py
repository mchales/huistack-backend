from rest_framework import serializers
from apps.dictionary.examples import prepare_sentence_payloads
from apps.dictionary.models import Lemma, Sense, UserLemmaExample
from apps.progress.models import LemmaProgress


class SenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sense
        fields = ["id", "lemma", "sense_index", "gloss"]
        read_only_fields = ["id"]


class LemmaSerializer(serializers.ModelSerializer):
    senses = SenseSerializer(many=True, read_only=True)
    tokens = serializers.SerializerMethodField()
    familiarity = serializers.SerializerMethodField()
    ignore = serializers.SerializerMethodField()
    examples = serializers.SerializerMethodField()
    characters = serializers.SerializerMethodField()

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
            "familiarity",
            "ignore",
            "examples",
            "characters",
        ]
        read_only_fields = ["id", "senses", "tokens", "familiarity", "ignore", "examples", "characters"]

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

    def _get_user_progress(self, obj):
        cache = self.context.setdefault("_progress_cache", {})
        if obj.id in cache:
            return cache[obj.id]

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not user or not user.is_authenticated:
            cache[obj.id] = None
            return None

        cache[obj.id] = (
            LemmaProgress.objects.filter(user=user, lemma=obj).only("familiarity", "ignore").first()
        )
        return cache[obj.id]

    def get_familiarity(self, obj):
        progress = self._get_user_progress(obj)
        return progress.familiarity if progress else None

    def get_ignore(self, obj):
        progress = self._get_user_progress(obj)
        return bool(progress.ignore) if progress else False

    def get_examples(self, obj):
        if not self.context.get("include_tokens"):
            return []

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not user or not user.is_authenticated:
            return []

        example = (
            UserLemmaExample.objects.filter(user=user, lemma=obj)
            .only("sentences")
            .first()
        )
        if not example or not example.sentences:
            return []

        return prepare_sentence_payloads(example.sentences, user)

    def get_characters(self, obj):
        # Build an ordered list of characters (via LemmaCharacter)
        # including their radicals.
        components = (
            obj.lemma_components.select_related("character")
        )
        results = []
        # Access all radicals in a single pass if prefetched
        for comp in components:
            ch = comp.character
            radicals_payload = []
            for r in ch.radicals.all():
                radicals_payload.append(
                    {
                        "kangxi_number": r.kangxi_number,
                        "character": r.character,
                        "traditional_character": r.traditional_character,
                        "simplified_character": r.simplified_character,
                        "pinyin": r.pinyin,
                        "english": r.english,
                        "stroke_count": r.stroke_count,
                        "variants": r.variants,
                    }
                )
            results.append(
                {
                    "order_index": comp.order_index,
                    "specific_pinyin": comp.specific_pinyin or None,
                    "hanzi": ch.hanzi,
                    "pinyin": ch.pinyin,
                    "stroke_count": ch.stroke_count,
                    "radicals": radicals_payload,
                }
            )
        return results
