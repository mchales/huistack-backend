from django.conf import settings
from django.db import models
from django.db.models import JSONField

class Radical(models.Model):
    """
    Represents a Kangxi Radical (e.g., 214 standard radicals).
    """
    kangxi_number = models.PositiveSmallIntegerField(
        unique=True, 
        primary_key=True,
        help_text="The standard Kangxi dictionary number (1-214)"
    )
    
    # The 'primary' field used for display/querying. 
    # Automatically set to Simplified if available, otherwise Traditional.
    character = models.CharField(
        max_length=1, 
        db_index=True,
        help_text="Primary display character (Simplified if available, else Traditional)"
    )

    # The historical Kangxi form (e.g., 言)
    traditional_character = models.CharField(
        max_length=1, 
        null=True, 
        blank=True,
        db_index=True,
        help_text="The traditional/Kangxi base form"
    )
    
    # The simplified form (e.g., 讠). Null if no specific simplified form exists.
    simplified_character = models.CharField(
        max_length=1, 
        null=True, 
        blank=True, 
        db_index=True,
        help_text="The simplified Chinese form"
    )
    
    pinyin = models.CharField(max_length=32)
    english = models.CharField(max_length=128)
    stroke_count = models.PositiveSmallIntegerField()
    
    frequency = models.PositiveIntegerField(
        default=0,
        help_text="Number of Chinese characters listed under this radical"
    )
    
    variants = models.JSONField(
        default=list,
        blank=True,
        help_text="List of variant forms (e.g., ['亻', '𠆢'])"
    )

    class Meta:
        ordering = ['kangxi_number']
        verbose_name = "Kangxi Radical"

    def save(self, *args, **kwargs):
        """
        Overriding save to automatically set the 'character' field.
        Priority: Simplified > Traditional.
        """
        if self.simplified_character:
            self.character = self.simplified_character
        else:
            self.character = self.traditional_character
        super().save(*args, **kwargs)

    def __str__(self):
        # Example output: "Radical #149: 讠 (Traditional: 言)"
        if self.character != self.traditional_character:
            return f"Radical #{self.kangxi_number}: {self.character} (Traditional: {self.traditional_character})"
        return f"Radical #{self.kangxi_number}: {self.character}"


class Character(models.Model):
    """
    Represents a unique Chinese character (Hanzi).
    """
    hanzi = models.CharField(max_length=1, unique=True, db_index=True)
    definition = models.TextField(blank=True, null=True)
    pinyin = models.CharField(max_length=100, blank=True, null=True)
    decomposition = models.CharField(max_length=32, blank=True, null=True)
    etymology = models.JSONField(blank=True, null=True)

    stroke_count = models.PositiveIntegerField(null=True, blank=True)
    
    radicals = models.ManyToManyField(
        'Radical', 
        related_name='characters', 
        blank=True
    )

    def __str__(self):
        return self.hanzi

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
    
    # The Magic Link: Allows `lemma.characters.all()`
    characters = models.ManyToManyField(
        Character,
        through='LemmaCharacter',
        related_name='lemmas'
    )

    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["traditional", "simplified", "pinyin_numbers"],
                name="uniq_lemma_t_s_pinyin",
            )
        ]

    def __str__(self):
        return f"{self.simplified} ({self.pinyin_numbers})"


class LemmaCharacter(models.Model):
    """
    The Junction Table (Through Model).
    """
    lemma = models.ForeignKey(Lemma, on_delete=models.CASCADE, related_name="lemma_components")
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name="lemma_occurrences")
    
    order_index = models.PositiveIntegerField()
    specific_pinyin = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        ordering = ['order_index']
        constraints = [
            models.UniqueConstraint(
                fields=['lemma', 'order_index'],
                name='uniq_char_position_in_lemma'
            )
        ]
    
    def __str__(self):
        return f"{self.character.hanzi} in {self.lemma.simplified} ({self.specific_pinyin})"


class Sense(models.Model):
    """
    Each English definition becomes one Sense row.
    """
    lemma = models.ForeignKey(Lemma, on_delete=models.CASCADE, related_name="senses")
    sense_index = models.PositiveIntegerField(default=1)
    gloss = models.CharField(max_length=512)

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
    Stores generated example sentences for a specific user and lemma.
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
        return f"{self.user} -> {self.lemma}"
