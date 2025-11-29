from django.contrib import admin
from .models import (
    Character,
    Lemma,
    LemmaCharacter,
    Radical,
    Sense,
    UserLemmaExample,
)


class SenseInline(admin.TabularInline):
    model = Sense
    extra = 0


@admin.register(Lemma)
class LemmaAdmin(admin.ModelAdmin):
    list_display = ("simplified", "traditional", "pinyin_numbers")
    search_fields = ("simplified", "traditional", "pinyin_numbers", "senses__gloss")
    inlines = [SenseInline]


@admin.register(Sense)
class SenseAdmin(admin.ModelAdmin):
    list_display = ("lemma", "sense_index", "gloss")
    list_select_related = ("lemma",)
    search_fields = ("gloss", "lemma__simplified", "lemma__traditional", "lemma__pinyin_numbers")
    ordering = ("lemma", "sense_index")
    # Avoid loading all lemmas on the change form
    autocomplete_fields = ["lemma"]
    # Speed up large changelists by skipping COUNT(*).
    show_full_result_count = False


@admin.register(UserLemmaExample)
class UserLemmaExampleAdmin(admin.ModelAdmin):
    list_display = ("user", "lemma", "updated_at")
    list_select_related = ("user", "lemma")
    search_fields = ("user__email", "user__username", "lemma__simplified", "lemma__traditional")
    autocomplete_fields = ["lemma", "user"]
    ordering = ("-updated_at",)


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("hanzi", "main_radical", "stroke_count", "definition")
    search_fields = (
        "hanzi",
        "main_radical__character",
        "other_radicals__character",
        "definition",
    )
    ordering = ("hanzi",)
    # Use autocomplete for radical relations
    autocomplete_fields = ["main_radical", "other_radicals"]


@admin.register(LemmaCharacter)
class LemmaCharacterAdmin(admin.ModelAdmin):
    list_display = ("lemma", "character", "order_index", "specific_pinyin")
    list_select_related = ("lemma", "character")
    search_fields = (
        "lemma__simplified",
        "lemma__traditional",
        "character__hanzi",
        "specific_pinyin",
    )
    ordering = ("lemma", "order_index")
    autocomplete_fields = ["lemma", "character"]


@admin.register(Radical)
class RadicalAdmin(admin.ModelAdmin):
    list_display = ("kangxi_number", "character", "english", "stroke_count")
    search_fields = (
        "character",
        "traditional_character",
        "simplified_character",
        "name_simplified",
        "name_pinyin",
        "english",
        "pinyin",
        "kangxi_number",
    )
    ordering = ("kangxi_number",)
