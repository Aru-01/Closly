import logging
from django.db import transaction
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import extend_schema, OpenApiResponse

from affiliate.models import AffiliateProduct, ProductClick
from affiliate.throttles import ProductClickRateThrottle
from affiliate.services.catalog_services import (
    build_affiliate_url,
    get_ip_prefix,
    get_ua_hash,
)

# Re-export catalog views for backward compatibility
from .catalog_views import (
    AffiliateProductDetailView,
    AffiliateBrandsListView,
    AffiliateCategoriesListView,
)

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Record Product Click & Generate Attributed Redirect URL",
    description=(
        "Records outbound affiliate link click with unique click reference UUID (AWIN clickref / Rakuten u1 / UTM), "
        "enforces 30 clicks/hour rate limit, supports Idempotency-Key, and returns attribution details."
    ),
    responses={
        200: OpenApiResponse(description="Click recorded; returns click reference token and outbound tracking redirect URL"),
        404: OpenApiResponse(description="Product not found or inactive"),
        429: OpenApiResponse(description="Click rate limit exceeded"),
    }
)
class ProductClickView(APIView):
    """
    Skinny View: Records outbound affiliate click attribution and delegates URL generation.
    POST /api/affiliate/products/<id>/click/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [ProductClickRateThrottle]

    def post(self, request, pk):
        try:
            # Optimized Query with select_related to eliminate N+1 queries
            product = AffiliateProduct.objects.select_related('brand_ref').get(pk=pk, is_active=True)
        except AffiliateProduct.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Product not found or inactive'},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user if request.user and request.user.is_authenticated else None

        surface = (
            request.data.get('surface')
            or request.query_params.get('surface')
            or 'feed'
        )
        session_id = (
            request.headers.get('X-Session-ID')
            or request.data.get('session_id')
            or request.query_params.get('session_id')
            or ''
        )
        idempotency_key = (
            request.headers.get('Idempotency-Key')
            or request.headers.get('X-Idempotency-Key')
            or request.data.get('idempotency_key')
            or ''
        )

        # Idempotency check: if key provided, return previously minted click
        if idempotency_key:
            existing = ProductClick.objects.filter(
                idempotency_key=idempotency_key,
                user=user,
                product=product,
            ).first()
            if existing:
                outbound_url = build_affiliate_url(product, click=existing)
                return Response({
                    'success': True,
                    'message': 'Click retrieved (idempotent). Redirect user to affiliate_url.',
                    'data': {
                        'click_id': str(existing.click_ref),
                        'click_ref': str(existing.click_ref),
                        'url': outbound_url,
                        'affiliate_url': outbound_url,
                        'product_name': product.name,
                        'brand': product.brand,
                    }
                }, status=status.HTTP_200_OK)

        ip_prefix = get_ip_prefix(request)
        ua_hash = get_ua_hash(request)

        with transaction.atomic():
            click = ProductClick.objects.create(
                product=product,
                user=user,
                surface=surface[:50],
                session_id=session_id[:100],
                user_agent_hash=ua_hash[:64],
                ip_prefix=ip_prefix[:45],
                idempotency_key=idempotency_key[:100],
            )

        outbound_url = build_affiliate_url(product, click=click)

        return Response({
            'success': True,
            'message': 'Click recorded. Redirect user to affiliate_url.',
            'data': {
                'click_id': str(click.click_ref),
                'click_ref': str(click.click_ref),
                'url': outbound_url,
                'affiliate_url': outbound_url,
                'product_name': product.name,
                'brand': product.brand,
            }
        }, status=status.HTTP_200_OK)


__all__ = [
    'AffiliateProductDetailView',
    'ProductClickView',
    'AffiliateBrandsListView',
    'AffiliateCategoriesListView',
    'build_affiliate_url',
]
