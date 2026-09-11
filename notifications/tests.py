from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta
from .models import Notification
from .services import create_notification
from .tasks import cleanup_old_notifications_task

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

        # Check sender representation fields: only id, name, profile_picture, is_online, last_seen (no email/country/city)
        sender_data = res.data['data'][0]['sender']
        self.assertEqual(sender_data['name'], 'Notif Two')
        self.assertIn('is_online', sender_data)
        self.assertIn('last_seen', sender_data)
        self.assertNotIn('email', sender_data)
        self.assertNotIn('country', sender_data)
        self.assertNotIn('city', sender_data)

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

    def test_delete_single_notification(self):
        n = create_notification(self.user1, 'system', 'To Delete', 'Will be deleted')
        self.assertEqual(Notification.objects.filter(recipient=self.user1).count(), 1)

        # Delete notification
        res = self.client.delete(f'/api/notifications/{n.id}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertEqual(Notification.objects.filter(recipient=self.user1).count(), 0)

        # Delete non-existent returns 404
        res_404 = self.client.delete(f'/api/notifications/{n.id}/')
        self.assertEqual(res_404.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_delete_other_user_notification(self):
        n = create_notification(self.user2, 'system', 'User2 Notif', 'Private')
        res = self.client.delete(f'/api/notifications/{n.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Notification.objects.filter(id=n.id).count(), 1)

    def test_cleanup_old_notifications_task_and_command(self):
        # Create fresh notification
        fresh = create_notification(self.user1, 'system', 'Fresh', 'Recent notification')
        
        # Create old notification (> 60 days)
        old = create_notification(self.user1, 'system', 'Old', 'Old notification')
        Notification.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=61))

        self.assertEqual(Notification.objects.count(), 2)

        # Run celery cleanup task
        result = cleanup_old_notifications_task(days=60)
        self.assertIn("1 notifications", result)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertTrue(Notification.objects.filter(id=fresh.id).exists())
        self.assertFalse(Notification.objects.filter(id=old.id).exists())

        # Test management command
        old2 = create_notification(self.user1, 'system', 'Old 2', 'Old notification 2')
        Notification.objects.filter(id=old2.id).update(created_at=timezone.now() - timedelta(days=65))
        call_command('cleanup_old_notifications', days=60)
        self.assertFalse(Notification.objects.filter(id=old2.id).exists())
