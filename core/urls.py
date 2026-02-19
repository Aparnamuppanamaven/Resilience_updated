"""
URL configuration for core app
"""
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('checkout/', views.checkout, name='checkout'),
    path('payment/', views.payment, name='payment'),
    path('payment-success/<str:is_renewal>/', views.payment_success, name='payment_success'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('admin-module/', views.admin_module, name='admin_module'),
    path('capture/', views.capture, name='capture'),
    path('normalize/', views.normalize, name='normalize'),
    path('distribute/', views.distribute, name='distribute'),
    path('decision-log/', views.decision_log, name='decision_log'),
    path('coverage/', views.coverage, name='coverage'),
    path('incidents/', views.incidents_list, name='incidents_list'),
    path('incidents/<int:incident_id>/', views.incident_detail, name='incident_detail'),
    path('api/toggle-alert/', views.toggle_alert, name='toggle_alert'),
    path('api/toggle-alert/', views.toggle_alert, name='toggle_alert'),
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


