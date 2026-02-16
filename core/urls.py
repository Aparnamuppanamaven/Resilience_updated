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
    path('onboarding/', views.onboarding, name='onboarding'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('admin-module/', views.admin_module, name='admin_module'),
    path('capture/', views.capture, name='capture'),
    path('normalize/', views.normalize, name='normalize'),
    path('distribute/', views.distribute, name='distribute'),
    path('decision-log/', views.decision_log, name='decision_log'),
    path('coverage/', views.coverage, name='coverage'),
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
]


