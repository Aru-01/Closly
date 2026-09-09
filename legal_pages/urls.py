from django.urls import path
from . import views

app_name = 'legal_pages'

urlpatterns = [
    path('privacy-policy/', views.privacy_policy_view, name='privacy_policy'),
    path('terms-and-conditions/', views.terms_and_conditions_view, name='terms_and_conditions'),
]