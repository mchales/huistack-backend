from django.conf import settings
from django.db import models


class Lemma(models.Model):
    """
    One row per headword (trad/simp pair).
    """

    traditional = models.CharField(max_length=64, db_index=True)
    simplified = models.CharField(max_length=64, db_index=True)
    pinyin_numbers = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Pinyin from CEDICT (tone numbers in brackets), e.g. 'xue2 xi2'",
    )
    # raw CEDICT line id or metadata, optional:
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["traditional", "simplified", "pinyin_numbers"],
                name="uniq_lemma_t_s_pinyin",
            )
        ]

    def __str__(self):
        return f"{self.simplified} / {self.traditional} [{self.pinyin_numbers}]"


class Sense(models.Model):
    """
    Each English definition becomes one Sense row.
    """

    lemma = models.ForeignKey(Lemma, on_delete=models.CASCADE, related_name="senses")
    sense_index = models.PositiveIntegerField(default=1)  # order as they appear
    gloss = models.CharField(max_length=512)  # one English meaning

    class Meta:
        indexes = [models.Index(fields=["lemma", "sense_index"])]
        constraints = [
            models.UniqueConstraint(
                fields=["lemma", "sense_index"],
                name="uniq_sense_per_lemma_index",
            )
        ]

    def __str__(self):
        return f"{self.lemma.simplified} #{self.sense_index}: {self.gloss[:60]}"


class UserLemmaExample(models.Model):
    """
    Stores the latest generated example sentences for a specific user and lemma.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lemma_examples",
    )
    lemma = models.ForeignKey(
        Lemma,
        on_delete=models.CASCADE,
        related_name="user_examples",
    )
    sentences = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "lemma"],
                name="uniq_user_lemma_examples",
            )
        ]

    def __str__(self):
        return f"{self.user} -> {self.lemma} ({len(self.sentences)} sentences)"
