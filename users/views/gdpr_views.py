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
            
            backend_base = getattr(settings, 'BACKEND_URL', '').rstrip('/')
            path = reverse('users:verify_profile_data_deletion', kwargs={'token': str(deletion_request.verification_token)})
            verification_link = f"{backend_base}{path}" if backend_base else request.build_absolute_uri(path)
            
            try:
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@myclosly.com')
                send_mail(
                    'Verify Profile Data Deletion Request',
                    f'Click the following link to confirm profile data erasure: {verification_link}',
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
    description="Renders confirmation UI on GET; executes profile data erasure strictly on verified POST (P-01).",
    responses={
        200: OpenApiResponse(description="Confirmation UI rendered on GET; profile data scrubbed on POST"),
        400: OpenApiResponse(description="Invalid or expired verification token"),
    }
)
class VerifyProfileDataDeletionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        """Safe GET handler: Validates token and renders confirmation UI without mutating state (P-01)"""
        try:
            deletion_request = ProfileDataDeletionRequest.objects.get(verification_token=token, status='pending')
            return render(request, 'users/confirm_profile_data_deletion.html', {'token': token, 'email': deletion_request.email})
        except ProfileDataDeletionRequest.DoesNotExist:
            return standard_response(
                success=False,
                message="Invalid or expired verification link.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="INVALID_TOKEN"
            )

    def post(self, request, token):
        """Mutating POST handler: Executes profile data erasure only on verified POST submission (P-01)"""
        try:
            deletion_request = ProfileDataDeletionRequest.objects.get(verification_token=token, status='pending')
            if deletion_request.user:
                user = deletion_request.user
                user.name = "User"
                user.date_of_birth = None
                user.gender = None
                user.occupation = None
                user.country = None
                user.city = None
                user.bio = None
                if user.profile_picture:
                    try:
                        user.profile_picture.delete(save=False)
                    except Exception as err:
                        logger.warning(f"Could not delete profile picture for user {user.id}: {err}")
                user.save()
            
            deletion_request.status = 'completed'
            deletion_request.save()
            return render(request, 'users/delete_profile_data_confirmed.html')
        except ProfileDataDeletionRequest.DoesNotExist:
            return standard_response(
                success=False,
                message="Invalid or expired verification link.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="INVALID_TOKEN"
            )


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
            # Re-request handling: Always create a fresh deletion request record (U-27)
            deletion_request = AccountDeletionRequest.objects.create(
                user=user,
                name=name,
                email=email,
                status='pending'
            )

            # Audit record for GDPR action
            from users.models import GdprAction
            GdprAction.objects.create(
                user_id=user.id,
                action_type='account_deletion_requested',
                performed_by='web_form',
                details={'email': email}
            )

            # Create a verification link strictly from settings.BACKEND_URL (U-03)
            backend_base = getattr(settings, 'BACKEND_URL', '').rstrip('/')
            path = reverse('users:verify_account_deletion', kwargs={'token': str(deletion_request.verification_token)})
            verification_link = f"{backend_base}{path}" if backend_base else request.build_absolute_uri(path)

            # Send email to the user asynchronously
            try:
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
                send_mail(
                    'Verify Account Deletion Request',
                    f'Click the following link to confirm permanent deletion of your account: {verification_link}\n\nThis link is valid for 24 hours.',
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
    description="Renders deletion confirmation UI on GET; executes permanent account erasure strictly on verified POST (U-03).",
    responses={
        200: OpenApiResponse(description="Confirmation UI rendered on GET; account erased on POST"),
        400: OpenApiResponse(description="Invalid or expired verification token"),
    }
)
class VerifyAccountDeletionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        """Safe GET handler: Renders confirmation UI without executing deletion (U-03)"""
        try:
            deletion_request = AccountDeletionRequest.objects.get(verification_token=token)
            if deletion_request.status != 'pending' or not deletion_request.is_valid(24):
                return standard_response(
                    success=False,
                    message="Invalid or expired verification link (valid for 24 hours).",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="TOKEN_EXPIRED"
                )
            return render(request, 'users/confirm_deletion.html', {'token': token, 'email': deletion_request.email})
        except AccountDeletionRequest.DoesNotExist:
            return standard_response(
                success=False,
                message="Invalid or expired verification link.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="INVALID_TOKEN"
            )

    def post(self, request, token):
        """Mutating POST handler: Enqueues resumable DeletionJob upon confirmation (U-03, U-04, U-27)"""
        try:
            deletion_request = AccountDeletionRequest.objects.get(verification_token=token)
            if deletion_request.status != 'pending' or not deletion_request.is_valid(24):
                return standard_response(
                    success=False,
                    message="Invalid or expired verification link (valid for 24 hours).",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="TOKEN_EXPIRED"
                )
            if deletion_request.user:
                user = deletion_request.user
                user_id = user.id
                user_email = user.email

                # Freeze account immediately
                user.is_active = False
                user.save(update_fields=['is_active'])

                # Create asynchronous resumable DeletionJob (U-04, U-27)
                from users.models import DeletionJob
                job = DeletionJob.objects.create(
                    user_id=user_id,
                    user_email=user_email,
                    status='queued'
                )

                # Enqueue Celery erasure task with inline fallback
                try:
                    from users.tasks import execute_gdpr_deletion_job
                    execute_gdpr_deletion_job.delay(str(job.id))
                except Exception as e:
                    logger.warning(f"Celery dispatch failed, executing deletion synchronously: {e}")
                    from users.tasks import execute_gdpr_deletion_job
                    execute_gdpr_deletion_job(str(job.id))

                deletion_request.user = None
            
            deletion_request.status = 'completed'
            deletion_request.save()
            return render(request, 'users/deletion_confirmed.html')
        except AccountDeletionRequest.DoesNotExist:
            return standard_response(
                success=False,
                message="Invalid or expired verification link.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="INVALID_TOKEN"
            )


@extend_schema(
    tags=["Account Privacy & GDPR"],
    summary="Delete Account (In-App Authenticated)",
    description="Allows authenticated user to permanently delete their account with password confirmation directly from the mobile app.",
    request=AccountDeleteSerializer,
    responses={
        200: OpenApiResponse(description="Account deletion queued successfully"),
        400: OpenApiResponse(description="Incorrect password or validation error"),
    }
)
class AccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = AccountDeleteSerializer
    
    def delete(self, request):
        """Queue account deletion and trigger resumable erasure cascade (U-04, U-27)"""
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
                        status_code=status.HTTP_400_BAD_REQUEST,
                        code="INVALID_CREDENTIALS"
                    )
            
            # Send account deletion confirmation email before deleting
            try:
                send_account_deletion_email(user)
            except Exception:
                pass  # Continue with deletion even if email fails
            
            user_id = user.id
            user_email = user.email

            # Freeze account immediately
            user.is_active = False
            user.save(update_fields=['is_active'])

            # Create DeletionJob and audit record (U-04, U-27)
            from users.models import DeletionJob, GdprAction
            job = DeletionJob.objects.create(
                user_id=user_id,
                user_email=user_email,
                status='queued'
            )
            GdprAction.objects.create(
                user_id=user_id,
                action_type='account_deletion_requested',
                performed_by='in_app',
                details={'job_id': str(job.id)}
            )

            # Enqueue Celery task with synchronous fallback
            try:
                from users.tasks import execute_gdpr_deletion_job
                execute_gdpr_deletion_job.delay(str(job.id))
            except Exception as e:
                logger.warning(f"Celery dispatch failed, executing deletion synchronously: {e}")
                from users.tasks import execute_gdpr_deletion_job
                execute_gdpr_deletion_job(str(job.id))
            
            return standard_response(
                success=True,
                message="Account deletion successfully queued. Your data will be erased per GDPR guidelines.",
                data={'job_id': str(job.id), 'status': 'queued'},
                status_code=status.HTTP_200_OK,
                code="DELETION_QUEUED"
            )
        
        return standard_response(
            success=False,
            message="Account deletion failed",
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR"
        )


@extend_schema(
    tags=["Account Privacy & GDPR"],
    summary="Export User Personal Data (GDPR Art. 20)",
    description="Generates a structured JSON export of the authenticated user's personal profile, preferences, closet items, and rewards ledger data.",
    responses={
        200: OpenApiResponse(description="Data export generated successfully"),
    }
)
class GdprDataExportView(APIView):
    """
    GDPR Art. 20 Right to Data Portability endpoint (U-05).
    GET /v1/me/export
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        from django.utils import timezone
        from users.models import GdprAction, Consent
        from rewards.models import RewardPointTransaction, UserRewardProfile
        from closet.models import ClosetItem

        # Log GDPR export audit event
        GdprAction.objects.create(
            user_id=user.id,
            action_type='data_export',
            performed_by='user',
            details={'exported_at': timezone.now().isoformat()}
        )

        user_data = {
            'id': str(user.id),
            'name': user.name,
            'email': user.email,
            'username': user.username,
            'date_of_birth': str(user.date_of_birth) if user.date_of_birth else None,
            'gender': user.gender,
            'country': user.country,
            'city': user.city,
            'bio': user.bio,
            'preferred_language': user.preferred_language,
        }

        pref_data = {}
        if hasattr(user, 'preferences'):
            prefs = user.preferences
            pref_data = {
                'style_match': prefs.style_match,
                'what_do_you_dress_for': prefs.what_do_you_dress_for,
                'body_size': prefs.body_size,
                'shoe_size': prefs.shoe_size,
                'clothing_sizes': getattr(prefs, 'clothing_sizes', {}),
                'price_band': getattr(prefs, 'price_band', None),
                'gender_prefs': getattr(prefs, 'gender_prefs', []),
                'preferred_brands': prefs.preferred_brands,
                'blocked_brands': getattr(prefs, 'blocked_brands', []),
                'onboarding_completed': prefs.onboarding_completed,
            }

        items = []
        for item in ClosetItem.objects.filter(user=user):
            items.append({
                'id': item.id,
                'name': getattr(item, 'name', ''),
                'category': str(item.category) if getattr(item, 'category', None) else '',
                'brand': getattr(item, 'brand', ''),
                'color': getattr(item, 'color', ''),
                'created_at': item.created_at.isoformat() if hasattr(item, 'created_at') and item.created_at else None,
            })

        reward_profile = UserRewardProfile.objects.filter(user=user).first()
        rewards_data = {
            'available_points': reward_profile.available_points if reward_profile else 0,
            'lifetime_points': reward_profile.lifetime_points if reward_profile else 0,
            'current_tier': reward_profile.current_tier if reward_profile else 'Bronze',
            'transactions': [
                {
                    'action_type': tx.action_type,
                    'points': tx.points,
                    'status': tx.status,
                    'description': tx.description,
                    'created_at': tx.created_at.isoformat(),
                }
                for tx in RewardPointTransaction.objects.filter(user=user).order_by('-created_at')[:100]
            ]
        }

        consents = [
            {
                'kind': c.kind,
                'granted': c.granted,
                'occurred_at': c.occurred_at.isoformat(),
            }
            for c in Consent.objects.filter(user=user)
        ]

        export_payload = {
            'user': user_data,
            'preferences': pref_data,
            'closet_items': items,
            'rewards': rewards_data,
            'consents': consents,
        }

        return standard_response(
            success=True,
            message="GDPR personal data export generated successfully.",
            data=export_payload,
            code="EXPORT_SUCCESS",
            status_code=status.HTTP_200_OK
        )



