from django.urls import path
from . import views

app_name = 'legal_pages'

urlpatterns = [
    path('privacy-policy/', views.privacy_policy_view, name='privacy_policy'),
    path('terms-and-conditions/', views.terms_and_conditions_view, name='terms_and_conditions'),
    path('support/', views.support_view, name='support'),
    path('delete-account/', views.delete_account_view, name='delete_account'),
    path('delete-account/logout/', views.delete_account_logout_view, name='delete_account_logout'),
]
