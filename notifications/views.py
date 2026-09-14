from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404

from .models import Notification
from .serializers import NotificationSerializer


class StandardNotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response({
            'success': True,
            'message': 'Notifications retrieved successfully.',
            'total': self.page.paginator.count,
            'data': data
        })


class NotificationListView(generics.ListAPIView):
    """
    API endpoint to list in-app notifications for the authenticated user.
    
    GET /api/notifications/?unread_only=true
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = NotificationSerializer
    pagination_class = StandardNotificationPagination

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user).select_related('sender')
        unread_only = self.request.query_params.get('unread_only')
        if unread_only and unread_only.lower() in ['true', '1']:
            qs = qs.filter(is_read=False)
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        response.data['unread_count'] = unread_count
        return response


class NotificationMarkReadView(APIView):
    """
    API endpoint to mark a single notification as read.
    
    POST /api/notifications/<id>/read/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response({
            'success': True,
            'message': 'Notification marked as read.',
            'data': {'id': notification.id, 'is_read': True}
        }, status=status.HTTP_200_OK)


class NotificationMarkAllReadView(APIView):
    """
    API endpoint to mark all notifications as read for current user.
    
    POST /api/notifications/mark-all-read/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        updated_count = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({
            'success': True,
            'message': f'Marked {updated_count} notifications as read.',
            'data': {'updated_count': updated_count}
        }, status=status.HTTP_200_OK)
