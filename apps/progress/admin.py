from django.contrib import admin
from .models import LemmaProgress


@admin.register(LemmaProgress)
class LemmaProgressAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "lemma", "familiarity", "updated_at")
    list_filter = ("familiarity",)
    search_fields = ("user__username", "lemma__simplified", "lemma__traditional")

