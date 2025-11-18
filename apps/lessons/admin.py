from django.contrib import admin
from .models import (
    Lesson,
    LessonVideoJob,
    SourceText,
    Sentence,
    SentenceTranslation,
    SentenceToken,
)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "audio_url", "source_language", "target_language", "created_at")
    search_fields = ("title",)
    autocomplete_fields = ["created_by"]
    show_full_result_count = False


@admin.register(SourceText)
class SourceTextAdmin(admin.ModelAdmin):
    list_display = ("id", "lesson", "order", "name")
    search_fields = ("name", "text")
    list_select_related = ("lesson",)
    autocomplete_fields = ["lesson"]
    show_full_result_count = False


class SentenceTokenInline(admin.TabularInline):
    model = SentenceToken
    extra = 0
    autocomplete_fields = ["lemma"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("lemma")


@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):
    list_display = ("id", "lesson", "index", "text", "has_frame")
    search_fields = ("text",)
    list_select_related = ("lesson", "source")
    autocomplete_fields = ["lesson", "source"]
    inlines = [SentenceTokenInline]
    show_full_result_count = False

    @admin.display(boolean=True, description="Frame")
    def has_frame(self, obj):
        return bool(obj.frame_image)


@admin.register(SentenceTranslation)
class SentenceTranslationAdmin(admin.ModelAdmin):
    list_display = ("id", "sentence", "language", "source")
    search_fields = ("text",)
    list_select_related = ("sentence",)
    autocomplete_fields = ["sentence"]
    show_full_result_count = False


@admin.register(SentenceToken)
class SentenceTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "sentence", "index", "text", "kind", "lemma")
    search_fields = ("text",)
    list_select_related = ("sentence", "lemma")
    autocomplete_fields = ["sentence", "lemma"]
    show_full_result_count = False


@admin.register(LessonVideoJob)
class LessonVideoJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "lesson",
        "status",
        "processed_frames",
        "total_frames",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("lesson__title", "id")
    readonly_fields = (
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "processed_frames",
        "total_frames",
        "error_message",
    )
    autocomplete_fields = ["lesson", "uploaded_by"]
