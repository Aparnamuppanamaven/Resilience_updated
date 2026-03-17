"""
URL configuration for core app
"""
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import extra_views

urlpatterns = [
    path('', views.index, name='index'),
    path('checkout/', views.checkout, name='checkout'),
    path('payment/', views.payment, name='payment'),
    path('payment-success/<str:is_renewal>/', views.payment_success, name='payment_success'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('admin-module/', views.admin_module, name='admin_module'),
    path('admin-module/agency/<str:agency_id>/view/', views.agency_view, name='agency_view'),
    path('admin-module/agency/<str:agency_id>/edit/', views.agency_edit, name='agency_edit'),
    path('admin-module/agency/<str:agency_id>/delete/', views.agency_delete, name='agency_delete'),
    path('capture/', views.capture, name='capture'),
    path('normalize/', views.normalize, name='normalize'),
    path('distribute/', views.distribute, name='distribute'),
    path('decision-log/', views.decision_log, name='decision_log'),
    path('coverage/', views.coverage, name='coverage'),
    path('incident-copy/', views.incident_copy_view, name='incident_copy'),
    path('incidents/', views.incidents_list, name='incidents_list'),
    path('incidents/<int:incident_id>/', views.incident_detail, name='incident_detail'),
    path('incidents/<int:incident_id>/generate-shift-packet/', views.generate_incident_shift_packet_pdf, name='generate_shift_packet_pdf'),
    path('incidents/<int:incident_id>/logs.pdf', views.incident_log_history_pdf, name='incident_log_history_pdf'),
    path('incidents/<int:incident_id>/case-history.csv', views.incident_case_history_csv, name='incident_case_history_csv'),
    path('api/search-users/', views.search_users_for_assignment, name='search_users_for_assignment'),
    path('api/incidents/<int:incident_id>/assign-users/', views.assign_users_to_incident, name='assign_users_to_incident'),
    path('api/incidents/<int:incident_id>/add-event-log/', views.add_incident_event_log, name='add_incident_event_log'),
    path('api/department-services/', views.department_services_api, name='department_services_api'),
    path('api/toggle-alert/', views.toggle_alert, name='toggle_alert'),
    path('api/toggle-alert/', views.toggle_alert, name='toggle_alert'),
    # UI-only pages for prototype workflows (no backend persistence yet)
    path('situation-updates/', extra_views.situation_updates_page, name='situation_updates'),
    path('shift-packets/', extra_views.shift_packets_page, name='shift_packets'),
    path(
        'shift-packets/history/<int:history_id>/edit/',
        extra_views.edit_shift_packet_history,
        name='edit_shift_packet_history',
    ),
    path('reports/', extra_views.reports_page, name='reports'),
    path('reports/pdf/', extra_views.reports_pdf, name='reports_pdf'),
    path('api/situation-logs/', extra_views.api_situation_logs, name='api_situation_logs'),
    path('system-logs/', extra_views.system_logs_page, name='system_logs'),
    # User Management reuses the Admin Module UI and features
    path('user-management/', views.admin_module, name='user_management'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('user-dashboard/', views.user_dashboard, name='user_dashboard'),
    path('registration-success/', views.registration_success, name='registration_success'),
    path('complete-registration/', views.complete_registration, name='complete_registration'),
    path('payment-failed/', views.payment_failed, name='payment_failed'),
    path('setup-password/<str:token>/', views.setup_password, name='setup_password'),
    # Stripe endpoints
    path('create-payment-intent/', views.create_payment_intent, name='create_payment_intent'),
    path('webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('stripe-payments/', views.stripe_payments_page, name='stripe_payments_page'),
    path('stripe-invoice-pdf/', views.stripe_invoice_pdf, name='stripe_invoice_pdf'),
]


