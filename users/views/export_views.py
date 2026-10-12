from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiResponse

from users.tasks import export_user_data_task
from users.views.base import standard_response


class UserDataExportView(APIView):
    """
    GDPR Article 20 Right to Data Portability endpoint.
    Initiates asynchronous compilation of the user's complete data portfolio.
    Returns HTTP 202 Accepted immediately and dispatches an email with a secure download link.
    Routes:
        GET /v1/me/export
        GET /api/v1/me/export/
        GET /api/users/export/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    @extend_schema(
        summary="Initiate personal data export (GDPR Article 20)",
        description=(
            "Asynchronously compiles an archive containing the user's complete personal data "
            "(profile, style preferences, closet items, outfits, stories, chat history, and reward history). "
            "Returns HTTP 202 Accepted immediately. An email containing a secure download link will be dispatched."
        ),
        responses={
            202: OpenApiResponse(
                description="Export initiated successfully",
            ),
            429: OpenApiResponse(description="Too many requests"),
        }
    )
    def post(self, request):
        user = request.user

        # Enqueue the background compilation task
        export_user_data_task.delay(str(user.id))

        return standard_response(
            success=True,
            message="Your data export request has been accepted. We are compiling your personal data archive and will email you a secure download link shortly.",
            data={
                "status": "processing",
                "email": user.email,
                "regulation": "GDPR Article 20 (Right to Data Portability)",
            },
            status_code=status.HTTP_202_ACCEPTED,
            code="EXPORT_ACCEPTED"
        )

    def get(self, request):
        return self.post(request)
