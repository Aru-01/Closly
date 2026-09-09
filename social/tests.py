from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import TodayOutfit, UserFollow, DirectMessage

User = get_user_model()

class SocialApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1 = User.objects.create_user(
            email='user1@example.com',
            password='Password123!',
            name='User One'
        )
        self.user2 = User.objects.create_user(
            email='user2@example.com',
            password='Password123!',
            name='User Two'
        )
        self.client.force_authenticate(user=self.user1)

    def test_follow_and_following_feed(self):
        # Follow user2
        follow_url = f'/api/social/users/{self.user2.id}/follow/'
        res = self.client.post(follow_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['data']['is_following'])

        # Create public outfit post by user2
        dummy_image = SimpleUploadedFile("outfit.jpg", b"file_content", content_type="image/jpeg")
        TodayOutfit.objects.create(user=self.user2, image=dummy_image, caption="User2 Outfit", visibility="public")

        # Get following feed for user1
        feed_url = '/api/social/feed/following/'
        feed_res = self.client.get(feed_url)
        self.assertEqual(feed_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(feed_res.data['data']['results']), 1)

    def test_direct_messaging(self):
        msg_url = '/api/social/messages/'
        data = {
            'recipient_id': str(self.user2.id),
            'content': 'Hello from User 1!'
        }
        res = self.client.post(msg_url, data)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['data']['content'], 'Hello from User 1!')

        # Conversation view
        conv_url = f'/api/social/messages/{self.user2.id}/'
        conv_res = self.client.get(conv_url)
        self.assertEqual(conv_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(conv_res.data['data']['results']), 1)
