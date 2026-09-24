import logging
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.mail import send_mail
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.models import AccountDeletionRequest, ProfileDataDeletionRequest
from users.serializers import AccountDeleteSerializer
from users.utils import send_account_deletion_email
from drf_spectacular.utils import extend_schema, OpenApiResponse
from .base import standard_response

logger = logging.getLogger(__name__)
User = get_user_model()

@csrf_exempt
def delete_profile_data_request_view(request):
    return render(request, 'users/delete_profile_data_request.html')

@extend_schema(
    tags=["Account Privacy & GDPR"],
    summary="Request Profile Data Erasure (Web Form)",
    description="Submit a request to anonymize and clear user profile information. Sends a verification link to email.",
    responses={
        200: OpenApiResponse(description="Profile erasure request received"),
    }
)
@method_decorator(csrf_exempt, name='dispatch')
class ProfileDataDeletionAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return render(request, 'users/delete_profile_data_request.html', {'error': 'Email is required.'})

        user = User.objects.filter(email=email).first()
        if user:
            deletion_request, created = ProfileDataDeletionRequest.objects.get_or_create(user=user, defaults={'email': email})
            
            verification_link = request.build_absolute_uri(
                reverse('users:verify_profile_data_deletion', kwargs={'token': str(deletion_request.verification_token)})
            )
            
            try:
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@closly.com')
                send_mail(
                    'Verify Profile Data Deletion Request',
                    f'Click the following link to delete your profile data: {verification_link}',
                    from_email,
                    [email],
                    fail_silently=False,
                )
            except Exception as e:
                logger.error(f"Error sending profile data deletion email to {email}: {str(e)}")
        return render(request, 'users/delete_profile_data_submitted.html')

@extend_schema(
    tags=["Account Privacy & GDPR"],
    summary="Verify Profile Data Erasure Token",
    description="Validates email token and scrubs profile attributes (name, bio, DOB, picture) while retaining account authentication.",
    responses={
        200: OpenApiResponse(description="Profile data scrubbed successfully"),
        400: OpenApiResponse(description="Invalid or expired verification token"),
    }
)
class VerifyProfileDataDeletionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        try:
            deletion_request = ProfileDataDeletionRequest.objects.get(verification_token=token, status='pending')
            if deletion_request.user:
                user = deletion_request.user
                user.name = "User"
                user.date_of_birth = None
                user.gender = None
                user.occupation = None
                user.country = None
                user.bio = None
                if user.profile_picture:
                    user.profile_picture.delete(save=False)
                user.save()
                
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/delete_profile_data_confirmed.html')
            else:
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/delete_profile_data_confirmed.html')
        except ProfileDataDeletionRequest.DoesNotExist:
            return standard_response(success=False, message="Invalid or expired verification link.", status_code=status.HTTP_400_BAD_REQUEST)


User = get_user_model()

@csrf_exempt
def account_deletion_request_view(request):
    return render(request, 'users/delete_account.html')

@extend_schema(
    tags=["Account Privacy & GDPR"],
    summary="Request Account Deletion (Web Form)",
    description="Submit a GDPR / Google Play compliant account deletion request via web. Sends confirmation link to user's email.",
    responses={
        200: OpenApiResponse(description="Account deletion request received"),
    }
)
@method_decorator(csrf_exempt, name='dispatch')
class AccountDeletionAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        name = request.data.get('name')
        email = request.data.get('email')

        if not name or not email:
            return render(request, 'users/delete_account.html', {'error': 'Name and email are required.'})

        user = User.objects.filter(email=email).first()
        if user:
            deletion_request, created = AccountDeletionRequest.objects.get_or_create(user=user, defaults={'name': name, 'email': email})

            # Create a verification link
            verification_link = request.build_absolute_uri(
                reverse('users:verify_account_deletion', kwargs={'token': str(deletion_request.verification_token)})
            )

            # Send email to the user
            try:
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@closly.com')
                send_mail(
                    'Verify Account Deletion Request',
                    f'Click the following link to delete your account: {verification_link}',
                    from_email,
                    [email],
                    fail_silently=False,
                )
            except Exception as e:
                logger.error(f"Error sending account deletion email to {email}: {str(e)}")
        return render(request, 'users/deletion_request_submitted.html')


@extend_schema(
    tags=["Account Privacy & GDPR"],
    summary="Verify Account Deletion Token",
    description="Validates email token and permanently destroys user account and associated private data.",
    responses={
        200: OpenApiResponse(description="Account deleted successfully"),
        400: OpenApiResponse(description="Invalid or expired verification token"),
    }
)
class VerifyAccountDeletionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        try:
            deletion_request = AccountDeletionRequest.objects.get(verification_token=token, status='pending')
            if deletion_request.user:
                deletion_request.user.delete()
                deletion_request.user = None
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/deletion_confirmed.html')
            else:
                # Handle case where user is not found, but request exists
                deletion_request.status = 'completed'
                deletion_request.save()
                return render(request, 'users/deletion_confirmed.html')
        except AccountDeletionRequest.DoesNotExist:
            return standard_response(success=False, message="Invalid or expired verification link.", status_code=status.HTTP_400_BAD_REQUEST)




@extend_schema(
    tags=["Account Privacy & GDPR"],
    summary="Delete Account (In-App Authenticated)",
    description="Allows authenticated user to permanently delete their account with password confirmation directly from the mobile app.",
    request=AccountDeleteSerializer,
    responses={
        200: OpenApiResponse(description="Account permanently deleted"),
        400: OpenApiResponse(description="Incorrect password or validation error"),
    }
)
class AccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    """
    API endpoint to delete user account
    
    DELETE /api/users/account-delete/
    
    Request body:
    {
        "password": "user_password",
        "confirm_deletion": true
    }
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = AccountDeleteSerializer
    
    def delete(self, request):
        """Delete user account"""
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            user = request.user
            password = serializer.validated_data['password']
            
            # Verify password (for email/password users)
            if user.auth_provider == 'email':
                if not user.check_password(password):
                    return standard_response(
                        success=False,
                        message="Incorrect password",
                        errors={'password': ['Incorrect password']},
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
            
            # Store email for confirmation email
            user_email = user.email
            user_name = user.name
            
            # Send account deletion confirmation email before deleting
            try:
                send_account_deletion_email(user)
            except Exception:
                pass  # Continue with deletion even if email fails
            
            # Delete user account
            user.delete()
            
            return standard_response(
                success=True,
                message="Account deleted successfully",
                status_code=status.HTTP_200_OK
            )
        
        return standard_response(
            success=False,
            message="Account deletion failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


