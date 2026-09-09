from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def privacy_policy_view(request):
    return render(request, 'legal/privacy_policy.html')

@csrf_exempt
def terms_and_conditions_view(request):
    return render(request, 'legal/terms_and_conditions.html')