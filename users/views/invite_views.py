import secrets
import logging
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from users.models import Invite
from users.utils.error_codes import (
    INVITE_INVALID,
    INVITE_ALREADY_USED,
    INVITE_EXPIRED,
)

logger = logging.getLogger(__name__)


class InviteSerializer(serializers.ModelSerializer):
    is_used = serializers.SerializerMethodField()

    class Meta:
        model = Invite
        fields = [
            'code',
            'kind',
            'is_used',
            'used_at',
            'expires_at',
            'created_at',
        ]
        read_only_fields = fields

    def get_is_used(self, obj):
        return bool(obj.used_by_id or obj.used_at)


class InviteRedeemInputSerializer(serializers.Serializer):
    code = serializers.CharField(
        required=True,
        max_length=64,
        trim_whitespace=True,
        help_text="Single-use invite access code"
    )


@extend_schema(
    tags=["Invite Gate & Access"],
    summary="List User Invite Codes",
    description="Returns 5 single-use invite codes allocated to the authenticated user. Automatically generates new codes up to the quota of 5 if not yet issued.",
    responses={
        200: InviteSerializer(many=True),
        401: OpenApiResponse(description="Unauthorized"),
    }
)
class InviteListView(APIView):
    """
    Returns 5 single-use invite codes for the authenticated user.
    Auto-generates codes up to 5 if needed (V1-API-02 / U-08).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        existing_invites = list(Invite.objects.filter(owner_user=user).order_by('created_at')[:5])
        current_count = len(existing_invites)

        if current_count < 5:
            new_invites = []
            for _ in range(5 - current_count):
                for _attempt in range(10):
                    candidate_code = f"CLO-{secrets.token_hex(4).upper()}"
                    if not Invite.objects.filter(code=candidate_code).exists():
                        inv = Invite.objects.create(
                            code=candidate_code,
                            kind='standard',
                            owner_user=user,
                        )
                        new_invites.append(inv)
                        break
            existing_invites.extend(new_invites)

        serializer = InviteSerializer(existing_invites[:5], many=True)
        return Response({
            'success': True,
            'count': len(serializer.data),
            'data': serializer.data,
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Invite Gate & Access"],
    summary="Redeem Single-Use Invite Code",
    description="Validates and claims a single-use invite code for the authenticated user (V1-API-01 / U-08).",
    request=InviteRedeemInputSerializer,
    responses={
        200: OpenApiResponse(description="Invite code redeemed successfully"),
        400: OpenApiResponse(description="Invalid, expired, or previously claimed code"),
        401: OpenApiResponse(description="Unauthorized"),
    }
)
class InviteRedeemView(APIView):
    """
    Validates and consumes a single-use invite code.
    Fails closed on nonexistent, expired, self-owned, or previously used codes.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        serializer = InviteRedeemInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'message': 'Invalid invite code submission.',
                'errors': serializer.errors,
                'code': INVITE_INVALID,
            }, status=status.HTTP_400_BAD_REQUEST)

        code_str = serializer.validated_data['code'].strip().upper()
        user = request.user

        # Check if user already claimed an invite
        if Invite.objects.filter(used_by=user).exists():
            return Response({
                'success': False,
                'message': 'You have already redeemed an invite code.',
                'code': 'INVITE_ALREADY_CLAIMED',
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check bypass codes (e.g. TestFlight or App Store review)
        bypass_codes = getattr(settings, 'MYC_INVITE_BYPASS_CODES', ['APPLE_REVIEW', 'TESTFLIGHT_BETA'])
        if code_str in bypass_codes:
            return Response({
                'success': True,
                'message': 'Bypass invite code accepted.',
                'data': {
                    'code': code_str,
                    'kind': 'review',
                    'used_at': timezone.now(),
                }
            }, status=status.HTTP_200_OK)

        invite = Invite.objects.filter(code=code_str).first()
        if not invite:
            return Response({
                'success': False,
                'message': 'Invalid invite code.',
                'code': INVITE_INVALID,
            }, status=status.HTTP_400_BAD_REQUEST)

        if invite.owner_user_id == user.id:
            return Response({
                'success': False,
                'message': 'You cannot redeem an invite code that you own.',
                'code': 'INVITE_SELF_REDEEM_NOT_ALLOWED',
            }, status=status.HTTP_400_BAD_REQUEST)

        if not invite.is_valid():
            if invite.used_by_id or invite.used_at:
                return Response({
                    'success': False,
                    'message': 'This invite code has already been claimed.',
                    'code': INVITE_ALREADY_USED,
                }, status=status.HTTP_400_BAD_REQUEST)
            if invite.expires_at and timezone.now() > invite.expires_at:
                return Response({
                    'success': False,
                    'message': 'This invite code has expired.',
                    'code': INVITE_EXPIRED,
                }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            locked_invite = Invite.objects.select_for_update().get(id=invite.id)
            if locked_invite.used_by_id is not None or locked_invite.used_at is not None:
                return Response({
                    'success': False,
                    'message': 'This invite code has already been claimed.',
                    'code': INVITE_ALREADY_USED,
                }, status=status.HTTP_400_BAD_REQUEST)

            locked_invite.used_by = user
            locked_invite.used_at = timezone.now()
            locked_invite.save(update_fields=['used_by', 'used_at'])

        logger.info(f"User {user.id} ({user.email}) successfully redeemed invite code {locked_invite.code}")

        return Response({
            'success': True,
            'message': 'Invite code redeemed successfully.',
            'data': {
                'code': locked_invite.code,
                'kind': locked_invite.kind,
                'used_at': locked_invite.used_at,
            }
        }, status=status.HTTP_200_OK)
