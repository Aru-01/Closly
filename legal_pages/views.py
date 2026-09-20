from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt
from users.models import AccountDeletionRequest, User


@csrf_exempt
def privacy_policy_view(request):
    """Render the official privacy policy web page."""
    return render(request, 'legal/privacy_policy.html')


@csrf_exempt
def terms_and_conditions_view(request):
    """Render the official terms and conditions web page."""
    return render(request, 'legal/terms_and_conditions.html')


@csrf_exempt
def support_view(request):
    """Render the official customer support and help center web page."""
    return render(request, 'legal/support.html')


def delete_account_logout_view(request):
    """Log user out from the deletion portal."""
    logout(request)
    return redirect('legal_pages:delete_account')


def delete_account_view(request):
    """
    Google Play & GDPR compliant account deletion portal.
    Requires authentication before displaying deletion terms.
    Submitted requests are queued for administrator review and approval.
    """
    # 1. Authenticated user flow
    if request.user.is_authenticated:
        user = request.user
        pending_req = AccountDeletionRequest.objects.filter(user=user, status='pending').first()

        if request.method == 'POST':
            confirmation = request.POST.get('confirmation')
            reason = request.POST.get('reason', '').strip()
            details = request.POST.get('details', '').strip()
            if not confirmation:
                return render(request, 'legal/delete_account.html', {
                    'state': 'authenticated',
                    'user': user,
                    'error': 'Please check the confirmation box to submit your deletion request.'
                })

            AccountDeletionRequest.objects.update_or_create(
                user=user,
                defaults={
                    'name': user.name or 'User',
                    'email': user.email,
                    'status': 'pending',
                    'reason': reason,
                    'details': details,
                }
            )
            return render(request, 'legal/delete_account.html', {
                'state': 'submitted',
                'user': user
            })

        if pending_req:
            return render(request, 'legal/delete_account.html', {
                'state': 'submitted',
                'user': user
            })

        return render(request, 'legal/delete_account.html', {
            'state': 'authenticated',
            'user': user
        })

    # 2. Unauthenticated login flow
    error = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'login':
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '').strip()

            if not email or not password:
                error = "Email and password are required."
            else:
                user = authenticate(request, email=email, password=password)
                if user is not None:
                    if not user.is_active:
                        error = "This account is inactive or has already been deleted."
                    else:
                        login(request, user)
                        return redirect('legal_pages:delete_account')
                else:
                    error = "Invalid email or password. Please check your credentials."

    return render(request, 'legal/delete_account.html', {
        'state': 'login',
        'error': error
    })