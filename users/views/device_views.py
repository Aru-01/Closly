from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import status
from drf_spectacular.utils import extend_schema

from users.serializers.device_serializers import DeviceSerializer
from users.services.device_services import register_or_update_device
from users.views.base import standard_response


class DeviceRegistrationView(APIView):
    """
    Push device registration endpoint (U-29 / Table A #8).
    Accepts APNs or FCM tokens securely, linking them to the authenticated user.
    Routes:
        POST /v1/devices
        POST /api/v1/devices/
        POST /api/users/devices/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    @extend_schema(
        summary="Register push device token (APNs/FCM)",
        description="Registers an Apple APNs or Google FCM device token for push notifications.",
        request=DeviceSerializer,
        responses={200: DeviceSerializer, 201: DeviceSerializer}
    )
    def post(self, request):
        serializer = DeviceSerializer(data=request.data)
        if not serializer.is_valid():
            return standard_response(
                success=False,
                message="Device registration validation failed.",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="VALIDATION_ERROR"
            )

        apns_token = serializer.validated_data['apns_token']
        platform = serializer.validated_data.get('platform', 'ios')
        prefs = serializer.validated_data.get('prefs', {})

        device, created = register_or_update_device(
            user=request.user,
            apns_token=apns_token,
            platform=platform,
            prefs=prefs,
            request=request
        )

        return standard_response(
            success=True,
            message="Device registered successfully.",
            data=DeviceSerializer(device).data,
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            code="DEVICE_REGISTERED"
        )
