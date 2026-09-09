from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db import models
from django.utils import timezone
from datetime import datetime, timedelta
import calendar

from .models import ClosetItem
from .serializers import ClosetItemSerializer

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
        serializer.save(user=self.request.user)

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

            serializer = ClosetItemSerializer(item)
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


class ClosetAuditView(APIView):
    """
    API endpoint for closet audit & analytics.
    Returns:
    - total_items
    - added_current_month vs added_previous_month
    - ghost_pieces (not worn in > 30 days or never worn)
    - most_worn (top items by times_worn)
    
    GET /api/closet/audit/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        items = ClosetItem.objects.filter(user=user)
        total_items = items.count()

        now = timezone.now()
        # Current month start
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Previous month start & end
        first_day_prev_month = (current_month_start - timedelta(days=1)).replace(day=1)
        last_day_prev_month = current_month_start - timedelta(microseconds=1)

        added_current_month = items.filter(created_at__gte=current_month_start).count()
        added_previous_month = items.filter(created_at__range=(first_day_prev_month, last_day_prev_month)).count()

        # Ghost pieces: never worn (times_worn == 0) OR not worn in the last 30 days
        thirty_days_ago = now - timedelta(days=30)
        ghost_items = items.filter(
            models.Q(times_worn=0) | models.Q(last_worn_at__lt=thirty_days_ago) | models.Q(last_worn_at__isnull=True)
        ).distinct()

        # Most worn items (top 5 by times_worn)
        most_worn_items = items.filter(times_worn__gt=0).order_by('-times_worn')[:10]

        return Response({
            'success': True,
            'message': 'Closet audit analytics generated successfully.',
            'data': {
                'total_items': total_items,
                'monthly_addition_stats': {
                    'current_month': added_current_month,
                    'previous_month': added_previous_month
                },
                'ghost_pieces': ClosetItemSerializer(ghost_items, many=True).data,
                'most_worn_items': ClosetItemSerializer(most_worn_items, many=True).data
            }
        }, status=status.HTTP_200_OK)
