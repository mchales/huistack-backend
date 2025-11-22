from django.contrib import admin
from .models import Lemma, Sense, UserLemmaExample


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
