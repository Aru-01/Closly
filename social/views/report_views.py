from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse
from django.utils import timezone
from django.conf import settings

from social.models import ContentReport
from social.serializers.report_serializers import ContentReportSerializer


@extend_schema(
    tags=["Social Feed & Network"],
    summary="Submit Content Report (DSA & UGC)",
    description="Allows authenticated users to report outfits, stories, users, or messages for policy or legal violations (DSA Art. 16/17).",
    request=ContentReportSerializer,
    responses={
        201: ContentReportSerializer,
        400: OpenApiResponse(description="Validation error"),
        429: OpenApiResponse(description="Daily reporting limit reached"),
    }
)
class ContentReportCreateView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        max_daily = getattr(settings, 'MYC_MAX_REPORTS_PER_DAY', 20)
        today_count = ContentReport.objects.filter(
            reporter=request.user,
            created_at__date=timezone.now().date()
        ).count()

        if today_count >= max_daily:
            return Response({
                'success': False,
                'message': f"You have reached the daily reporting limit of {max_daily} reports per day.",
                'code': 'daily_report_limit_exceeded'
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = ContentReportSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response({
                'success': False,
                'message': 'Report submission failed due to invalid data.',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        report = serializer.save(reporter=request.user)

        return Response({
            'success': True,
            'message': 'Report submitted successfully. Our safety and moderation team will review it promptly in compliance with the DSA.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)
