from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from .models import Notification
from .services import create_notification

User = get_user_model()


class NotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1 = User.objects.create_user(email='notif1@example.com', password='Password123!', name='Notif One')
        self.user2 = User.objects.create_user(email='notif2@example.com', password='Password123!', name='Notif Two')
        self.client.force_authenticate(user=self.user1)

    def test_create_and_list_notifications(self):
        # Create notification from user2 to user1
        n = create_notification(
            recipient=self.user1,
            notification_type='outfit_like',
            title='New Like',
            message='User Two liked your outfit',
            sender=self.user2,
            data={'outfit_id': 10}
        )
        self.assertIsNotNone(n)

        # Listing via API
        res = self.client.get('/api/notifications/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['unread_count'], 1)
        self.assertEqual(len(res.data['data']), 1)

        # Mark as read
        read_res = self.client.post(f'/api/notifications/{n.id}/read/')
        self.assertEqual(read_res.status_code, status.HTTP_200_OK)
        self.assertTrue(Notification.objects.get(id=n.id).is_read)

        # Check unread count is now 0
        res2 = self.client.get('/api/notifications/?unread_only=true')
        self.assertEqual(len(res2.data['data']), 0)

    def test_self_notification_suppressed(self):
        # Sender is recipient -> should be suppressed
        n = create_notification(
            recipient=self.user1,
            notification_type='outfit_like',
            title='Self Like',
            message='You liked yourself',
            sender=self.user1
        )
        self.assertIsNone(n)
        self.assertEqual(Notification.objects.filter(recipient=self.user1).count(), 0)

    def test_mark_all_read(self):
        create_notification(self.user1, 'system', 'Alert 1', 'Message 1')
        create_notification(self.user1, 'system', 'Alert 2', 'Message 2')
        self.assertEqual(Notification.objects.filter(recipient=self.user1, is_read=False).count(), 2)

        res = self.client.post('/api/notifications/mark-all-read/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(Notification.objects.filter(recipient=self.user1, is_read=False).count(), 0)
