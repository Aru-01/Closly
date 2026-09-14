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

    def test_conversations_inbox(self):
        user3 = User.objects.create_user(
            email='user3@example.com',
            password='Password123!',
            name='User Three'
        )

        # user2 sends 2 messages to user1 (unread)
        DirectMessage.objects.create(sender=self.user2, recipient=self.user1, content='Hey user1, first message')
        DirectMessage.objects.create(sender=self.user2, recipient=self.user1, content='Hey user1, second message')

        # user1 sends 1 message to user3
        DirectMessage.objects.create(sender=self.user1, recipient=user3, content='Hello user3')

        # Get inbox for user1
        inbox_url = '/api/social/conversations/'
        res = self.client.get(inbox_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        conversations = res.data['data']
        self.assertEqual(len(conversations), 2)

        # Most recent conversation should be with user3 (created last)
        self.assertEqual(conversations[0]['other_user']['id'], str(user3.id))
        self.assertEqual(conversations[0]['last_message']['content'], 'Hello user3')
        self.assertEqual(conversations[0]['unread_count'], 0)

        # Second conversation should be with user2 with unread_count=2
        self.assertEqual(conversations[1]['other_user']['id'], str(self.user2.id))
        self.assertEqual(conversations[1]['last_message']['content'], 'Hey user1, second message')
        self.assertEqual(conversations[1]['unread_count'], 2)

    def test_feed_optimization_and_likes(self):
        from closet.models import ClosetItem
        from .models import OutfitLike

        item = ClosetItem.objects.create(user=self.user2, name='Test Jeans', category='bottom', price=40.00)
        dummy_image = SimpleUploadedFile("feed.jpg", b"dummy_content", content_type="image/jpeg")
        outfit = TodayOutfit.objects.create(user=self.user2, image=dummy_image, caption="Feed outfit", visibility="public")
        outfit.tagged_items.add(item)
        OutfitLike.objects.create(outfit=outfit, user=self.user1)

        feed_url = '/api/social/feed/'
        res = self.client.get(feed_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        first_item = res.data['data']['results'][0]
        self.assertEqual(first_item['likes_count'], 1)
        self.assertTrue(first_item['is_liked'])
        self.assertEqual(len(first_item['tagged_items_details']), 1)

