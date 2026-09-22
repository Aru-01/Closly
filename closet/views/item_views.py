import logging
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from closet.models import ClosetItem
from closet.serializers import ClosetItemSerializer

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Closet & Digital Wardrobe"],
    summary="List or Add Wardrobe Items",
    description="Retrieve all clothes in digital wardrobe with optional category/color/brand filters, or add a new clothing item.",
    parameters=[
        OpenApiParameter('category', str, description="Filter by clothing category (e.g. top, bottom, dress, shoes, outerwear)"),
        OpenApiParameter('color', str, description="Filter by clothing color"),
        OpenApiParameter('brand', str, description="Filter by clothing brand"),
    ],
    responses={
        200: ClosetItemSerializer(many=True),
        201: ClosetItemSerializer,
    }
)
class ClosetItemListCreateView(generics.ListCreateAPIView):
    """
    API endpoint to list and add items in the user's closet.
    
    GET /api/closet/items/ - List all user's clothes
    POST /api/closet/items/ - Add a new item to closet
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = ClosetItemSerializer

    def get_queryset(self):
        queryset = ClosetItem.objects.filter(user=self.request.user)
        category = self.request.query_params.get('category')
        color = self.request.query_params.get('color')
        brand = self.request.query_params.get('brand')

        if category:
            queryset = queryset.filter(category=category)
        if color:
            queryset = queryset.filter(color__icontains=color)
        if brand:
            queryset = queryset.filter(brand__icontains=brand)

        return queryset

    def perform_create(self, serializer):
        item = serializer.save(user=self.request.user)
        try:
            from rewards.services import award_points
            award_points(
                user=self.request.user,
                action_type='add_closet_item',
                description=f"Added '{item.name}' to closet",
                reference_id=str(item.id)
            )
        except Exception as e:
            logger.warning(f"Error awarding points for adding closet item: {e}")

        try:
            from notifications.services import create_notification
            create_notification(
                recipient=self.request.user,
                notification_type='closet_item_added',
                title='Closet Item Added',
                message=f"'{item.name}' has been added to your digital wardrobe!",
                data={'item_id': item.id, 'category': item.category}
            )
        except Exception as e:
            logger.debug(f"Error creating closet item notification: {e}")

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({
            'success': True,
            'message': 'Closet items retrieved successfully.',
            'data': response.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            self.perform_create(serializer)
            return Response({
                'success': True,
                'message': 'Cloth item added to closet successfully.',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'success': False,
            'message': 'Failed to add item to closet.',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["Closet & Digital Wardrobe"],
    summary="Retrieve, Update or Delete a Wardrobe Item",
    description="Fetch single clothing item details, edit its metadata, or remove it from the digital closet.",
    responses={
        200: ClosetItemSerializer,
        204: OpenApiResponse(description="Item deleted successfully"),
    }
)
class ClosetItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    API endpoint to view, update or delete a specific cloth item.
    
    GET /api/closet/items/<id>/
    PUT / PATCH / DELETE
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = ClosetItemSerializer

    def get_queryset(self):
        return ClosetItem.objects.filter(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'message': 'Cloth details retrieved successfully.',
            'data': serializer.data
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Closet & Digital Wardrobe"],
    summary="Record Today's Wear for Garment",
    description="Increments the item's times_worn counter and updates last_worn_at timestamp to calculate cost-per-wear.",
    responses={
        200: ClosetItemSerializer,
        404: OpenApiResponse(description="Cloth item not found in your closet"),
    }
)
class WearTodayView(APIView):
    """
    API endpoint to record today's wear for a specific cloth item.
    Increments times_worn counter and updates last_worn_at.
    
    POST /api/closet/items/<id>/wear-today/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        try:
            item = ClosetItem.objects.get(pk=pk, user=request.user)
            item.times_worn += 1
            item.last_worn_at = timezone.now()
            item.save()

            serializer = ClosetItemSerializer(item, context={'request': request})
            return Response({
                'success': True,
                'message': f"Calculated today's wear for '{item.name}'. Times worn is now {item.times_worn}.",
                'data': serializer.data
            }, status=status.HTTP_200_OK)
        except ClosetItem.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Cloth item not found in your closet.'
            }, status=status.HTTP_404_NOT_FOUND)
