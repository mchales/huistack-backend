from django.conf import settings
from django.db import models

from apps.dictionary.models import Lemma


class LemmaProgress(models.Model):
    """
    Tracks a user's familiarity with a given lemma on a 1-5 scale.
    1 = unknown, 5 = familiar
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lemma_progress"
    )
    lemma = models.ForeignKey(
        Lemma, on_delete=models.CASCADE, related_name="user_progress"
    )
    familiarity = models.PositiveSmallIntegerField(default=1)
    ignore = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "lemma"], name="uniq_progress_per_user_lemma"
            )
        ]
        indexes = [models.Index(fields=["user", "lemma"])]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.lemma_id} -> {self.familiarity}"

