import random
import hashlib
import logging
from zoneinfo import ZoneInfo
from django.core.paginator import Paginator, Page
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from affiliate.serializers import AffiliateProductListSerializer
from affiliate.services.discovery_services import (
    get_clean_base_queryset,
    get_or_create_cached_feed_ids,
    get_for_you_feed_page,
)

logger = logging.getLogger(__name__)
BERLIN_TZ = ZoneInfo("Europe/Berlin")


class ForYouPagination(PageNumberPagination):
    """
    Pagination class for the 'For You' discovery feed.
    Carries the discovery seed in pagination links (seed=<int>) so infinite scrolling
    remains completely non-repetitive across pages, while fresh requests produce
    a freshly seeded discovery sequence.
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def __init__(self):
        super().__init__()
        self.seed = None

    def get_paginated_response(self, data):
        response_data = {
            'count':    self.page.paginator.count,
            'next':     self.get_next_link(),
            'previous': self.get_previous_link(),
            'results':  data,
        }
        if self.seed is not None:
            response_data['seed'] = self.seed

        return Response({
            'success': True,
            'message': 'Products retrieved successfully',
            'data': response_data,
        }, status=status.HTTP_200_OK)

    def get_next_link(self):
        link = super().get_next_link()
        if link and self.seed is not None:
            from rest_framework.utils.urls import replace_query_param
            link = replace_query_param(link, 'seed', self.seed)
        return link

    def get_previous_link(self):
        link = super().get_previous_link()
        if link and self.seed is not None:
            from rest_framework.utils.urls import replace_query_param
            link = replace_query_param(link, 'seed', self.seed)
        return link


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Personalized 'For You' Products Feed",
    description=(
        "Curated affiliate discovery feed customized by behavioral interaction signals, "
        "taste profile, gender preference, greedy brand diversity, and cached stable pagination."
    ),
    parameters=[
        OpenApiParameter('seed', int, description="Discovery seed for deterministic pagination continuity"),
        OpenApiParameter('refresh', bool, description="Set to true to generate a freshly randomized curation seed"),
    ],
    responses={
        200: AffiliateProductListSerializer(many=True),
    }
)
class AffiliateProductForYouView(generics.ListAPIView):
    """
    Skinny View: Dispatches to discovery_services for vector retrieval,
    behavioral scoring, and greedy brand diversity windows.
    GET /api/affiliate/products/for-you/
    """
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = ForYouPagination

    def get_queryset(self):
        return get_clean_base_queryset(self.request.user)

    def paginate_queryset(self, queryset):
        user = self.request.user
        page_size = self.paginator.get_page_size(self.request) or getattr(self.paginator, 'page_size', 20) or 20
        page_number_str = self.request.query_params.get(self.paginator.page_query_param, 1)

        try:
            page_number = int(page_number_str)
            if page_number < 1:
                page_number = 1
        except (ValueError, TypeError):
            page_number = 1

        seed_param = self.request.query_params.get('seed')
        refresh_param = self.request.query_params.get('refresh', '').lower() in ('true', '1', 'yes')

        if refresh_param or not seed_param or (page_number == 1 and not seed_param):
            seed = random.randint(100000, 999999)
        else:
            try:
                seed = int(seed_param)
            except (ValueError, TypeError):
                seed = int(hashlib.sha256(str(seed_param).encode('utf-8')).hexdigest()[:8], 16) % 1000000

        if hasattr(self.paginator, 'seed'):
            self.paginator.seed = seed

        # Retrieve or compute cached candidate sequence via discovery service
        ordered_ids = get_or_create_cached_feed_ids(user, seed, refresh=refresh_param)

        total_count = len(ordered_ids)
        paginator = Paginator(range(total_count), page_size)
        try:
            self.paginator.page = paginator.page(page_number)
        except Exception:
            self.paginator.page = Page([], page_number, paginator)
        self.paginator.request = self.request

        # Fetch requested page with select_related('brand_ref') and favorites annotated
        ordered_page, user_fav_ids = get_for_you_feed_page(user, ordered_ids, page_number, page_size)
        self._user_fav_ids = user_fav_ids

        return ordered_page

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        user_fav_ids = getattr(self, '_user_fav_ids', set())

        if page is not None:
            serializer = self.get_serializer(
                page,
                many=True,
                context={'request': request, 'favorite_product_ids': user_fav_ids}
            )
            response = self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(queryset, many=True)
            response = Response(serializer.data)

        user = request.user
        is_personalized = bool(user and user.is_authenticated)

        prefs_summary = None
        if is_personalized and hasattr(user, 'preferences'):
            prefs = user.preferences
            prefs_summary = {
                'palette': prefs.color_palette or 'neutral_minimalist',
                'styles': prefs.style_match or ['minimalist'],
                'preferred_brands': prefs.preferred_brands or []
            }

        response.data['user_taste_profile'] = prefs_summary
        response.data['personalized'] = is_personalized
        if getattr(self.paginator, 'seed', None) is not None:
            response.data['seed'] = self.paginator.seed

        if is_personalized:
            response.data['message'] = "Personalized 'For You' discovery feed curated based on your taste profile and behavioral signals."
        else:
            response.data['message'] = "Discover trending fashion items. Sign in to personalize your discovery feed."

        return response
