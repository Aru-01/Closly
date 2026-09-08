from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db.models import Count
from drf_spectacular.utils import extend_schema, OpenApiResponse

from affiliate.models import AffiliateProduct, ProductFavorite
from affiliate.serializers import AffiliateProductListSerializer
from .feed_views import NewsfeedPagination


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="Toggle Product Favorite / Wishlist",
    description="Saves a product to user's personal wishlist or removes it if already favorited.",
    responses={
        200: OpenApiResponse(description="Product favorite status toggled successfully"),
        404: OpenApiResponse(description="Product not found or inactive"),
    }
)
class ProductFavoriteToggleView(APIView):
    """
    POST /api/affiliate/products/<id>/love/
    POST /api/affiliate/products/<id>/favorite/
    POST /api/affiliate/products/<id>/save/

    Toggles favorite / love status on a product for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        try:
            product = AffiliateProduct.objects.only('id').get(pk=pk, is_active=True)
        except AffiliateProduct.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Product not found or inactive',
                'data': None
            }, status=status.HTTP_404_NOT_FOUND)

        deleted_count, _ = ProductFavorite.objects.filter(product_id=pk, user=request.user).delete()
        if deleted_count > 0:
            is_loved = False
            status_str = 'unloved'
            message = 'Product removed from your saved wishlist'
        else:
            ProductFavorite.objects.create(product_id=pk, user=request.user)
            is_loved = True
            status_str = 'loved'
            message = 'Product saved to your wishlist!'

        favorites_count = ProductFavorite.objects.filter(product_id=pk).count()

        return Response({
            'success': True,
            'message': message,
            'data': {
                'status': status_str,
                'is_loved': is_loved,
                'favorites_count': favorites_count,
                'product_id': pk,
            }
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Affiliate Products & Scraping"],
    summary="List Saved / Wishlist Products",
    description="Returns paginated list of all affiliate products loved or saved by the authenticated user.",
    responses={
        200: AffiliateProductListSerializer(many=True),
    }
)
class SavedProductsListView(generics.ListAPIView):
    """
    GET /api/affiliate/products/saved/
    GET /api/affiliate/products/favorites/

    Returns all products loved / saved by the authenticated user with O(1) query complexity.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = AffiliateProductListSerializer
    pagination_class = NewsfeedPagination

    def get_queryset(self):
        return (
            AffiliateProduct.objects.filter(
                favorites__user=self.request.user,
                is_active=True
            )
            .order_by('-favorites__created_at')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            page_ids = [p.id for p in page]
            fav_counts = dict(
                ProductFavorite.objects.filter(product_id__in=page_ids)
                .values('product_id')
                .annotate(c=Count('id'))
                .values_list('product_id', 'c')
            )
            for p in page:
                p._favorites_count = fav_counts.get(p.id, 0)

            user_fav_ids = set(page_ids)

            serializer = self.get_serializer(
                page,
                many=True,
                context={'request': request, 'favorite_product_ids': user_fav_ids}
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
