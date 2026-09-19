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

    def test_notifications_flow(self):
        from notifications.models import Notification

        # 1. User1 likes User2's outfit -> should trigger notification for User2
        dummy_img = SimpleUploadedFile("u2.jpg", b"image data", content_type="image/jpeg")
        outfit2 = TodayOutfit.objects.create(user=self.user2, image=dummy_img, caption="U2 look", visibility="public")
        self.client.post(f'/api/social/outfits/{outfit2.id}/like/')

        u2_notifs = Notification.objects.filter(recipient=self.user2)
        self.assertEqual(u2_notifs.count(), 1)
        self.assertEqual(u2_notifs.first().notification_type, 'outfit_like')

        # 2. User1 likes their own outfit -> should NOT create self-notification
        outfit1 = TodayOutfit.objects.create(user=self.user1, image=dummy_img, caption="U1 look", visibility="public")
        self.client.post(f'/api/social/outfits/{outfit1.id}/like/')
        self.assertEqual(Notification.objects.filter(recipient=self.user1, notification_type='outfit_like').count(), 0)

        # 3. User1 follows User2 -> creates new_follower notification
        self.client.post(f'/api/social/users/{self.user2.id}/follow/')
        self.assertTrue(Notification.objects.filter(recipient=self.user2, notification_type='new_follower').exists())

        # 4. User1 sends DM to User2 -> creates direct_message notification
        self.client.post('/api/social/messages/', {'recipient_id': str(self.user2.id), 'content': 'Test notification message'})
        self.assertTrue(Notification.objects.filter(recipient=self.user2, notification_type='direct_message').exists())

        # 5. User2 checks notification list & unread count
        self.client.force_authenticate(user=self.user2)
        res = self.client.get('/api/notifications/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(res.data['unread_count'], 3)

        # 6. User2 marks single notification as read
        notif_id = u2_notifs.first().id
        read_res = self.client.post(f'/api/notifications/{notif_id}/read/')
        self.assertEqual(read_res.status_code, status.HTTP_200_OK)
        self.assertTrue(Notification.objects.get(id=notif_id).is_read)

        # 7. User2 marks all notifications as read
        mark_all_res = self.client.post('/api/notifications/mark-all-read/')
        self.assertEqual(mark_all_res.status_code, status.HTTP_200_OK)
        self.assertEqual(Notification.objects.filter(recipient=self.user2, is_read=False).count(), 0)

    def test_liked_outfits_excludes_self_outfits(self):
        from .models import OutfitLike

        dummy_img = SimpleUploadedFile("look.jpg", b"look data", content_type="image/jpeg")
        outfit_u1 = TodayOutfit.objects.create(user=self.user1, image=dummy_img, caption="My own look", visibility="public")
        outfit_u2 = TodayOutfit.objects.create(user=self.user2, image=dummy_img, caption="User2 chic look", visibility="public")

        # User1 likes both their own look and User2's look
        OutfitLike.objects.create(outfit=outfit_u1, user=self.user1)
        OutfitLike.objects.create(outfit=outfit_u2, user=self.user1)

        # GET /api/social/outfits/liked/
        res = self.client.get('/api/social/outfits/liked/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data['data']['results']

        # Self outfit MUST be excluded, only User2's outfit should be present!
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], outfit_u2.id)
        self.assertEqual(results[0]['caption'], "User2 chic look")

    def test_outfit_calendar_view(self):
        from django.utils import timezone

        dummy_img = SimpleUploadedFile("cal.jpg", b"cal data", content_type="image/jpeg")
        TodayOutfit.objects.create(user=self.user1, image=dummy_img, caption="Calendar outfit", visibility="public")

        now = timezone.now()
        # Test with explicit year & month
        cal_url = f'/api/social/outfits/calendar/?year={now.year}&month={now.month}'
        res = self.client.get(cal_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertIn('days', res.data['data'])
        self.assertGreaterEqual(res.data['data']['total_outfits'], 1)

        # Test without ANY query parameters (must default to running month)
        default_cal_url = '/api/social/outfits/calendar/'
        def_res = self.client.get(default_cal_url)
        self.assertEqual(def_res.status_code, status.HTTP_200_OK)
        self.assertTrue(def_res.data['data']['is_running_month'])
        self.assertEqual(def_res.data['data']['year'], now.year)
        self.assertEqual(def_res.data['data']['month'], now.month)

    def test_follower_tabs_dna_match_and_self_following(self):
        # Setup location and preferences
        self.user1.city = "New York"
        self.user1.country = "USA"
        self.user1.save()

        self.user2.city = "New York"
        self.user2.country = "USA"
        self.user2.save()

        # Follow user2
        self.client.post(f'/api/social/users/{self.user2.id}/follow/')

        # 1. Test Self following endpoint: GET /api/social/following/?tab=all
        following_res = self.client.get('/api/social/following/?tab=all')
        self.assertEqual(following_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(following_res.data), 1)
        item = following_res.data[0]
        self.assertIn('dna_match', item)
        self.assertIn('score', item['dna_match'])
        self.assertTrue(item['is_new'])
        self.assertTrue(item['same_location'])

        # 2. Test DNA Match tab: GET /api/social/following/?tab=dna_match
        dna_res = self.client.get('/api/social/following/?tab=dna_match')
        self.assertEqual(dna_res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(dna_res.data), 1)

        # 3. Test New Followers tab: GET /api/social/following/?tab=new_followers
        new_res = self.client.get('/api/social/following/?tab=new_followers')
        self.assertEqual(new_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(new_res.data), 1)

        # 4. Test Same Location tab: GET /api/social/following/?tab=same_location
        loc_res = self.client.get('/api/social/following/?tab=same_location')
        self.assertEqual(loc_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(loc_res.data), 1)

        # 5. Test Visit Other User Profile: GET /api/social/users/<user2_id>/profile/
        prof_res = self.client.get(f'/api/social/users/{self.user2.id}/profile/')
        self.assertEqual(prof_res.status_code, status.HTTP_200_OK)
        prof_data = prof_res.data['data']
        self.assertEqual(prof_data['id'], str(self.user2.id))
        self.assertTrue(prof_data['is_following'])
        self.assertIn('dna_match', prof_data)
        self.assertIn('score', prof_data['dna_match'])

    def test_your_day_weather_and_outfit_suggestion(self):
        from closet.models import ClosetItem
        ClosetItem.objects.create(user=self.user1, name="Navy Linen Shirt", category="top", price=45.00)
        ClosetItem.objects.create(user=self.user1, name="Beige Chino Pants", category="bottom", price=55.00)
        ClosetItem.objects.create(user=self.user1, name="Leather Jacket", category="dresses_outerwear", price=120.00)
        ClosetItem.objects.create(user=self.user1, name="White Sneakers", category="shoes", price=80.00)

        url = '/api/social/your-day/?lat=23.8103&lon=90.4125'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        data = response.data['data']
        self.assertIn('weather', data)
        weather = data['weather']
        self.assertIn('day', weather)
        self.assertIn('date', weather)
        self.assertIn('temp', weather)
        self.assertIn('humidity', weather)
        self.assertIn('wind', weather)
        self.assertIn('pressure', weather)
        self.assertIn('condition', weather)

        self.assertIn('suggested_outfit_today', data)
        outfit = data['suggested_outfit_today']
        self.assertIn('pieces', outfit)
        self.assertGreaterEqual(len(outfit['pieces']), 2)
        self.assertIn('styling_description', outfit)
        self.assertIn('quick_action', outfit)
        self.assertEqual(outfit['quick_action']['action'], 'wear_today')

    def test_explore_feed_excludes_followed_users(self):
        user3 = User.objects.create_user(
            email='unfollowed@example.com',
            password='Password123!',
            name='Unfollowed Creator'
        )
        # user1 follows user2
        self.client.post(f'/api/social/users/{self.user2.id}/follow/')

        # user2 (followed) posts an outfit
        dummy_img = SimpleUploadedFile("user2_outfit.jpg", b"img", content_type="image/jpeg")
        TodayOutfit.objects.create(user=self.user2, image=dummy_img, caption="Followed creator look", visibility="public")

        # user3 (unfollowed) posts an outfit
        dummy_img2 = SimpleUploadedFile("user3_outfit.jpg", b"img2", content_type="image/jpeg")
        outfit3 = TodayOutfit.objects.create(user=user3, image=dummy_img2, caption="Unfollowed creator look", visibility="public")

        url = '/api/social/explore/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        results = response.data['data']['results']
        outfit_ids = [o['id'] for o in results]
        self.assertIn(outfit3.id, outfit_ids)
        # Followed user2's outfit must be excluded from Explore
        for o in results:
            self.assertNotEqual(o['user']['id'], str(self.user2.id))

        self.assertIn('available_categories', response.data)

    def test_outfit_visibility_private_vs_public(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        dummy_img = SimpleUploadedFile("priv.gif", tiny_gif, content_type="image/gif")
        res = self.client.post('/api/social/outfits/', {
            'image': dummy_img,
            'caption': 'My private outfit look #secret',
            'visibility': 'private'
        }, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        outfit_id = res.data['data']['id']
        self.assertEqual(res.data['data']['visibility'], 'private')

        # Author can view private outfit details
        res_author = self.client.get(f'/api/social/outfits/{outfit_id}/')
        self.assertEqual(res_author.status_code, status.HTTP_200_OK)

        # Author sees it in my-outfits
        res_my = self.client.get('/api/social/my-outfits/')
        self.assertEqual(res_my.status_code, status.HTTP_200_OK)
        my_ids = [o['id'] for o in res_my.data['data']['results']]
        self.assertIn(outfit_id, my_ids)

        # Other user (user2) cannot view private outfit (404)
        client2 = APIClient()
        client2.force_authenticate(user=self.user2)
        res_other = client2.get(f'/api/social/outfits/{outfit_id}/')
        self.assertEqual(res_other.status_code, status.HTTP_404_NOT_FOUND)

        # Other user cannot see in public feed
        feed_res = client2.get('/api/social/feed/')
        feed_ids = [o['id'] for o in feed_res.data['data']['results']]
        self.assertNotIn(outfit_id, feed_ids)

        # Other user viewing user1's profile outfits does NOT see private outfit
        user1_outfits_res = client2.get(f'/api/social/users/{self.user1.id}/outfits/')
        user1_outfits_ids = [o['id'] for o in user1_outfits_res.data['data']['results']]
        self.assertNotIn(outfit_id, user1_outfits_ids)

    def test_outfit_style_and_weather_inference(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        dummy_img = SimpleUploadedFile("street.gif", tiny_gif, content_type="image/gif")
        # Do not provide style_category or weather_tag explicitly
        res = self.client.post('/api/social/outfits/', {
            'image': dummy_img,
            'caption': 'Chilly morning streetwear look #ootd',
            'visibility': 'public'
        }, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data['data']
        # style_category inferred from caption 'streetwear'
        self.assertEqual(data['style_category'], 'streetwear')
        # weather_tag inferred from caption 'chilly'
        self.assertEqual(data['weather_tag'], 'chilly')

    def test_outfit_patch_author_only(self):
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        dummy_img = SimpleUploadedFile("test_patch.gif", tiny_gif, content_type="image/gif")
        res = self.client.post('/api/social/outfits/', {
            'image': dummy_img,
            'caption': 'Initial look',
            'visibility': 'public'
        }, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        outfit_id = res.data['data']['id']

        # Non-author attempting to PATCH public outfit gets 403 Forbidden
        client2 = APIClient()
        client2.force_authenticate(user=self.user2)
        hacked_res = client2.patch(f'/api/social/outfits/{outfit_id}/', {
            'caption': 'Hacked caption'
        }, format='json')
        self.assertEqual(hacked_res.status_code, status.HTTP_403_FORBIDDEN)

        # Author can PATCH caption and visibility without re-uploading image
        patch_res = self.client.patch(f'/api/social/outfits/{outfit_id}/', {
            'caption': 'Updated caption',
            'visibility': 'private'
        }, format='json')
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res.data['data']['caption'], 'Updated caption')
        self.assertEqual(patch_res.data['data']['visibility'], 'private')

        # Non-author attempting to PATCH private outfit gets 404 (hidden)
        hacked_priv_res = client2.patch(f'/api/social/outfits/{outfit_id}/', {
            'caption': 'Hacked private caption'
        }, format='json')
        self.assertEqual(hacked_priv_res.status_code, status.HTTP_404_NOT_FOUND)
