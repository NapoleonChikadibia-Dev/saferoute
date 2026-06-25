# incidents/admin.py

from django.contrib import admin
from .models import Incident, Comment, UserProfile, Area


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display  = ['name', 'level', 'parent', 'is_verified', 'needs_review', 'created_by', 'created_at']
    list_filter   = ['needs_review', 'level', 'is_verified']
    search_fields = ['name', 'slug']
    list_editable = ['is_verified', 'needs_review']
    readonly_fields = ['created_at']
    ordering      = ['-created_at', 'level', 'name']
    autocomplete_fields = ['parent']


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display   = ['title', 'type', 'danger_level', 'location',
                      'reported_by', 'timestamp', 'verified',
                      'confirm_count', 'dispute_count_col', 'net']
    list_filter    = ['type', 'danger_level', 'verified', 'verified_override']
    search_fields  = ['title', 'location', 'description', 'reported_by__username']
    list_editable  = ['verified']
    readonly_fields = ['timestamp']
    ordering       = ['-timestamp']
    date_hierarchy = 'timestamp'

    def confirm_count(self, obj):
        return obj.confirmations.count()
    confirm_count.short_description = 'Confirms'

    def dispute_count_col(self, obj):
        return obj.disputes.count()
    dispute_count_col.short_description = 'Disputes'

    def net(self, obj):
        return obj.net_score()
    net.short_description = 'Net'


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display  = ['author', 'incident', 'timestamp']
    search_fields = ['author__username', 'body', 'incident__title']
    readonly_fields = ['timestamp']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ['user', 'location', 'sos_phone', 'created_at']
    search_fields = ['user__username', 'location']
    readonly_fields = ['created_at']
