from django.contrib import admin
from .models import Lemma, Sense


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
