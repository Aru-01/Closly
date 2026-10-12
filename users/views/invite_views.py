import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from users.serializers import (
    InviteSerializer,
    InviteRedeemInputSerializer,
)
from users.services import (
    get_or_create_user_invites,
    redeem_invite_code,
)
from users.utils.error_codes import INVITE_INVALID

logger = logging.getLogger(__name__)


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
    Skinny View: Returns 5 single-use invite codes for the authenticated user.
    Delegates code provisioning to the service layer (V1-API-02 / U-08).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        invites = get_or_create_user_invites(request.user, quota=5)
        serializer = InviteSerializer(invites, many=True)
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
    Skinny View: Validates and consumes a single-use invite code.
    Delegates all verification and atomic row locking to the service layer.
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

        raw_code = serializer.validated_data['code']
        success, data, error_message, error_code = redeem_invite_code(request.user, raw_code)

        if not success:
            return Response({
                'success': False,
                'message': error_message,
                'code': error_code,
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'success': True,
            'message': 'Invite code redeemed successfully.',
            'data': data,
        }, status=status.HTTP_200_OK)
