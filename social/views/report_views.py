from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from django.utils import timezone
from django.conf import settings

from social.models import ContentReport
from social.serializers.report_serializers import ContentReportSerializer


@extend_schema(
    tags=["Social Feed & Network"],
    summary="Submit Content Report (EU DSA Notice-and-Action)",
    description=(
        "Notice-and-action intake endpoint under Article 16 of the EU Digital Services Act (DSA).\n\n"
        "Allows authenticated users to report illegal content, harassment, intellectual property infringement, "
        "or platform violations. Submissions are queued for moderation review with strict audit timestamps."
    ),
    request=ContentReportSerializer,
    responses={
        201: OpenApiResponse(
            description="Report accepted into DSA moderation queue",
            examples=[
                OpenApiExample(
                    "Report Created (201)",
                    value={
                        "success": True,
                        "message": "Report submitted successfully. Our safety and moderation team will review it promptly in compliance with the DSA.",
                        "data": {
                            "id": "e2293b70-13f8-410a-8bf8-d567c9c2c62d",
                            "target_type": "outfit",
                            "target_id": "42",
                            "reason": "illegal_content",
                            "explanation": "This post contains copyrighted commercial photography without permission.",
                            "status": "pending",
                            "created_at": "2026-10-12T10:15:00Z"
                        }
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Validation error in payload"),
        429: OpenApiResponse(description="Daily reporting limit reached (max 20/day)"),
    },
    examples=[
        OpenApiExample(
            "Report Outfit Example",
            value={
                "target_type": "outfit",
                "target_id": "42",
                "reason": "illegal_content",
                "explanation": "This outfit image violates EU copyright standards."
            },
            request_only=True
        ),
        OpenApiExample(
            "Report User Example",
            value={
                "target_type": "user",
                "target_id": "a93e3cf7-1422-48df-b593-ff277abdf931",
                "reason": "harassment",
                "explanation": "User sending abusive direct messages."
            },
            request_only=True
        )
    ]
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

        serializer.save(reporter=request.user)

        return Response({
            'success': True,
            'message': 'Report submitted successfully. Our safety and moderation team will review it promptly in compliance with the DSA.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)
