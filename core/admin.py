"""
Admin configuration for Resilience System
Enterprise-level admin interface
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (
    Organization, Liaison, OperationalUpdate, 
    Decision, SystemSettings, ShiftPacket
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'license_type', 'is_active', 'created_at']
    list_filter = ['license_type', 'is_active', 'created_at']
    search_fields = ['name']
    readonly_fields = ['created_at']


@admin.register(Liaison)
class LiaisonAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'preferred_channels', 'created_at']
    list_filter = ['organization', 'preferred_channels', 'created_at']
    search_fields = ['user__username', 'user__email', 'organization__name']
    readonly_fields = ['created_at']


@admin.register(OperationalUpdate)
class OperationalUpdateAdmin(admin.ModelAdmin):
    list_display = ['title', 'organization', 'severity', 'owner', 'timestamp', 'is_synthesized']
    list_filter = ['severity', 'is_synthesized', 'timestamp', 'organization']
    search_fields = ['title', 'description']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ['decision', 'organization', 'status', 'owner', 'timestamp']
    list_filter = ['status', 'timestamp', 'organization']
    search_fields = ['decision', 'rationale']
    readonly_fields = ['timestamp']


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ['organization', 'cadence_hours', 'current_status', 'current_phase', 'last_sync']
    list_filter = ['current_status', 'current_phase']
    readonly_fields = ['last_sync']


@admin.register(ShiftPacket)
class ShiftPacketAdmin(admin.ModelAdmin):
    list_display = ['packet_number', 'organization', 'generated_at', 'status', 'sent_at']
    list_filter = ['status', 'generated_at', 'organization']
    search_fields = ['packet_number', 'organization__name']
    readonly_fields = ['generated_at', 'packet_number']
    date_hierarchy = 'generated_at'


