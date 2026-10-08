import io
from PIL import Image
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from .models import TodayOutfit, UserFollow, DirectMessage, UserBlock, ContentReport, OutfitImage, OutfitLike
from closet.models import ClosetItem

User = get_user_model()


def create_test_image(filename="test.jpg", format="JPEG"):
    """Creates a real in-memory image accepted by Pillow and validate_image_file."""
    buf = io.BytesIO()
    img = Image.new('RGB', (40, 40), color=(73, 109, 137))
    img.save(buf, format=format)
    buf.seek(0)
    content_type = "image/png" if format.upper() == "PNG" else "image/jpeg"
    return SimpleUploadedFile(filename, buf.read(), content_type=content_type)


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
        dummy_image = create_test_image("outfit.jpg")
        TodayOutfit.objects.create(user=self.user2, image=dummy_image, caption="User2 Outfit", visibility="public")

        # Get following feed for user1
        feed_url = '/api/social/feed/following/'
        feed_res = self.client.get(feed_url)
        self.assertEqual(feed_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(feed_res.data['data']['results']), 1)

    def test_dm_disabled_by_default(self):
        """SR-01: Direct messaging is disabled by default and returns 404 feature_disabled."""
        msg_res = self.client.post('/api/social/messages/', {
            'recipient_id': str(self.user2.id),
            'content': 'Hello!'
        })
        self.assertEqual(msg_res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(msg_res.data.get('code'), 'feature_disabled')

        conv_res = self.client.get('/api/social/conversations/')
        self.assertEqual(conv_res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(conv_res.data.get('code'), 'feature_disabled')

    @override_settings(MYC_DM_ENABLED=True)
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

    @override_settings(MYC_DM_ENABLED=True)
    def test_direct_messaging_image_compression(self):
        # Create a test PIL image (large 1600x1200)
        img_buffer = io.BytesIO()
        img = Image.new('RGB', (1600, 1200), color='blue')
        img.save(img_buffer, format='JPEG', quality=95)
        img_buffer.seek(0)

        uploaded_img = SimpleUploadedFile("chat_test.jpg", img_buffer.read(), content_type="image/jpeg")

        # Send ONLY image (no text content)
        msg_url = '/api/social/messages/'
        data = {
            'recipient_id': str(self.user2.id),
            'image': uploaded_img,
        }
        res = self.client.post(msg_url, data, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['data']['message_type'], 'image')
        self.assertTrue(res.data['data']['image'])
        self.assertEqual(res.data['data']['content'], '')

        # Check saved message in DB and that dimensions were scaled down
        msg = DirectMessage.objects.get(id=res.data['data']['id'])
        self.assertEqual(msg.message_type, 'image')
        saved_img = Image.open(msg.image)
        self.assertLessEqual(saved_img.width, 1280)
        self.assertLessEqual(saved_img.height, 1280)

    @override_settings(MYC_DM_ENABLED=True)
    def test_direct_messaging_shared_outfit(self):
        dummy_image = create_test_image("outfit.jpg")
        outfit = TodayOutfit.objects.create(user=self.user1, image=dummy_image, caption="My Cool Outfit", visibility="public")

        msg_url = '/api/social/messages/'
        data = {
            'recipient_id': str(self.user2.id),
            'outfit_id': outfit.id,
            'content': 'Check out my outfit!'
        }
        res = self.client.post(msg_url, data)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['data']['message_type'], 'outfit')
        self.assertIsNotNone(res.data['data']['outfit_preview'])
        self.assertEqual(res.data['data']['outfit_preview']['id'], outfit.id)
        self.assertEqual(res.data['data']['outfit_preview']['caption'], 'My Cool Outfit')

    @override_settings(MYC_DM_ENABLED=True)
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
        item = ClosetItem.objects.create(user=self.user2, name='Test Jeans', category='bottom', price=40.00)
        dummy_image = create_test_image("feed.jpg")
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

    @override_settings(MYC_DM_ENABLED=True)
    def test_notifications_flow(self):
        from notifications.models import Notification

        # 1. User1 likes User2's outfit -> should trigger notification for User2
        dummy_img = create_test_image("u2.jpg")
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
        dummy_img = create_test_image("look.jpg")
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
        dummy_img = create_test_image("cal.jpg")
        TodayOutfit.objects.create(user=self.user1, image=dummy_img, caption="Calendar outfit", visibility="public")

        now = timezone.now()
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
        # SR-03 PII: email must never be exposed on other user profiles
        self.assertNotIn('email', prof_data)

    @patch('requests.get')
    def test_your_day_weather_and_outfit_suggestion(self, mock_requests_get):
        # Mock Open-Meteo weather response (SR-19)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "current_weather": {
                "temperature": 21.5,
                "windspeed": 10.0,
                "weathercode": 1
            }
        }
        mock_requests_get.return_value = mock_response

        ClosetItem.objects.create(user=self.user1, name="Navy Linen Shirt", category="top", price=45.00)
        ClosetItem.objects.create(user=self.user1, name="Beige Chino Pants", category="bottom", price=55.00)
        ClosetItem.objects.create(user=self.user1, name="Leather Jacket", category="dresses_outerwear", price=120.00)
        ClosetItem.objects.create(user=self.user1, name="White Sneakers", category="shoes", price=80.00)

        url = '/api/social/your-day/?lat=48.14&lon=11.58'
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
        dummy_img = create_test_image("user2_outfit.jpg")
        TodayOutfit.objects.create(user=self.user2, image=dummy_img, caption="Followed creator look", visibility="public")

        # user3 (unfollowed) posts an outfit
        dummy_img2 = create_test_image("user3_outfit.jpg")
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
        dummy_img = create_test_image("priv.jpg")
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
        dummy_img = create_test_image("street.jpg")
        res = self.client.post('/api/social/outfits/', {
            'image': dummy_img,
            'caption': 'Chilly morning streetwear look #ootd',
            'visibility': 'public'
        }, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data['data']
        self.assertEqual(data['style_category'], 'streetwear')
        self.assertEqual(data['weather_tag'], 'chilly')

    def test_outfit_patch_author_only(self):
        dummy_img = create_test_image("test_patch.jpg")
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

    def test_outfit_multiple_images_upload_up_to_4(self):
        img1 = create_test_image("img1.jpg")
        img2 = create_test_image("img2.jpg")
        img3 = create_test_image("img3.jpg")

        res = self.client.post('/api/social/outfits/', {
            'images': [img1, img2, img3],
            'caption': 'Triple look outfit post',
            'visibility': 'public'
        }, format='multipart')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data['data']
        self.assertIsNotNone(data['image'])
        self.assertEqual(len(data['images']), 3)
        self.assertEqual(len(data['images_details']), 3)
        self.assertEqual(data['images_details'][0]['order'], 0)
        self.assertEqual(data['images_details'][1]['order'], 1)
        self.assertEqual(data['images_details'][2]['order'], 2)

        # Verify OutfitImage DB records
        outfit_id = data['id']
        db_images = OutfitImage.objects.filter(outfit_id=outfit_id).order_by('order')
        self.assertEqual(db_images.count(), 3)

    def test_outfit_exceeds_max_4_images_validation(self):
        images = [create_test_image(f"img{i}.jpg") for i in range(5)]

        res = self.client.post('/api/social/outfits/', {
            'images': images,
            'caption': 'Too many images post',
            'visibility': 'public'
        }, format='multipart')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res.data['success'])
        self.assertIn('images', res.data['errors'])
        error_msg = str(res.data['errors']['images'][0])
        self.assertIn("Maximum 4 images are allowed", error_msg)

    @override_settings(MYC_DM_ENABLED=True)
    def test_conversations_does_not_contain_stories(self):
        DirectMessage.objects.create(sender=self.user2, recipient=self.user1, content='Hey user1')

        res = self.client.get('/api/social/conversations/?page=1')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertNotIn('stories', res.data)
        self.assertIn('data', res.data)

    def test_story_cannot_self_love(self):
        from social.models import Story, StoryLike
        dummy_img = create_test_image("story.jpg")
        story = Story.objects.create(user=self.user1, image=dummy_img, caption="My daily story")

        # user1 attempts to love their own story -> must be rejected with 400
        res = self.client.post(f'/api/social/stories/{story.id}/like/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res.data['success'])
        self.assertEqual(res.data['message'], 'You cannot love or react to your own story.')
        self.assertEqual(story.loves_count, 0)
        self.assertFalse(StoryLike.objects.filter(story=story, user=self.user1).exists())

    def test_story_self_view_does_not_count_and_follower_visibility(self):
        from social.models import Story, StoryView, StoryLike
        dummy_img = create_test_image("story_view.jpg")
        story = Story.objects.create(user=self.user1, image=dummy_img, caption="View test story")

        # user1 views their own story -> acknowledged but view not recorded
        res_self = self.client.post(f'/api/social/stories/{story.id}/view/')
        self.assertEqual(res_self.status_code, status.HTTP_200_OK)
        self.assertEqual(res_self.data['data']['views_count'], 0)
        self.assertFalse(res_self.data['data']['is_first_view'])
        self.assertEqual(story.views_count, 0)
        self.assertFalse(StoryView.objects.filter(story=story, viewer=self.user1).exists())

        # user2 attempts to view story BEFORE following user1 -> 404 hidden (SR-14)
        client2 = APIClient()
        client2.force_authenticate(user=self.user2)
        unfollowed_res = client2.post(f'/api/social/stories/{story.id}/view/')
        self.assertEqual(unfollowed_res.status_code, status.HTTP_404_NOT_FOUND)

        # user2 follows user1 -> now authorized
        UserFollow.objects.create(follower=self.user2, following=self.user1)

        # user2 views story -> recorded as 1 view
        res_other = client2.post(f'/api/social/stories/{story.id}/view/')
        self.assertEqual(res_other.status_code, status.HTTP_200_OK)
        self.assertEqual(res_other.data['data']['views_count'], 1)
        self.assertTrue(res_other.data['data']['is_first_view'])
        self.assertEqual(story.views_count, 1)

        # user2 loves story -> success
        love_res = client2.post(f'/api/social/stories/{story.id}/like/')
        self.assertEqual(love_res.status_code, status.HTTP_200_OK)
        self.assertTrue(love_res.data['data']['has_loved'])
        self.assertEqual(story.loves_count, 1)

        # user1 checks viewers list -> only user2 appears
        viewers_res = self.client.get(f'/api/social/stories/{story.id}/viewers/')
        self.assertEqual(viewers_res.status_code, status.HTTP_200_OK)
        viewers_data = viewers_res.data['data']['results']
        self.assertEqual(len(viewers_data), 1)
        self.assertEqual(viewers_data[0]['viewer']['id'], str(self.user2.id))
        self.assertTrue(viewers_data[0]['has_loved'])

    def test_other_user_profile_returns_is_online_and_last_seen(self):
        profile_url = f'/api/social/users/{self.user2.id}/profile/'
        res = self.client.get(profile_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        data = res.data['data']
        self.assertIn('is_online', data)
        self.assertIn('last_seen', data)

    def test_outfit_likers_returns_is_online_and_last_seen(self):
        dummy_image = create_test_image("outfit.jpg")
        outfit = TodayOutfit.objects.create(user=self.user1, image=dummy_image, caption="Liker test", visibility="public")
        OutfitLike.objects.create(outfit=outfit, user=self.user2)

        likes_url = f'/api/social/outfits/{outfit.id}/likes/'
        res = self.client.get(likes_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        likers = res.data['data']
        self.assertEqual(len(likers), 1)
        self.assertIn('is_online', likers[0])
        self.assertIn('last_seen', likers[0])
        self.assertNotIn('email', likers[0])

    @override_settings(MYC_DM_ENABLED=True)
    def test_simple_user_representation_excludes_email_country_city(self):
        dummy_image = create_test_image("outfit.jpg")
        TodayOutfit.objects.create(user=self.user1, image=dummy_image, caption="Outfit test", visibility="public")

        # Test my-outfits response user payload
        outfit_res = self.client.get('/api/social/my-outfits/')
        self.assertEqual(outfit_res.status_code, status.HTTP_200_OK)
        outfit_user = outfit_res.data['data']['results'][0]['user']
        self.assertEqual(outfit_user['id'], str(self.user1.id))
        self.assertEqual(outfit_user['name'], self.user1.name)
        self.assertIn('is_online', outfit_user)
        self.assertIn('last_seen', outfit_user)
        self.assertNotIn('email', outfit_user)
        self.assertNotIn('country', outfit_user)
        self.assertNotIn('city', outfit_user)

        # Test direct message sender & recipient payload
        msg_res = self.client.post('/api/social/messages/', {
            'recipient_id': str(self.user2.id),
            'content': 'Field test'
        })
        self.assertEqual(msg_res.status_code, status.HTTP_201_CREATED)
        sender_data = msg_res.data['data']['sender']
        recipient_data = msg_res.data['data']['recipient']
        for u_data in [sender_data, recipient_data]:
            self.assertIn('id', u_data)
            self.assertIn('name', u_data)
            self.assertIn('profile_picture', u_data)
            self.assertIn('is_online', u_data)
            self.assertIn('last_seen', u_data)
            self.assertNotIn('email', u_data)
            self.assertNotIn('country', u_data)
            self.assertNotIn('city', u_data)

    def test_user_block_toggle_and_bilateral_invisibility(self):
        """SR-10: Test blocking user removes follows and enforces bilateral feed/story invisibility."""
        # 1. User1 follows User2, and User2 follows User1
        UserFollow.objects.create(follower=self.user1, following=self.user2)
        UserFollow.objects.create(follower=self.user2, following=self.user1)

        # 2. Block User2
        block_url = f'/api/social/users/{self.user2.id}/block/'
        block_res = self.client.post(block_url)
        self.assertEqual(block_res.status_code, status.HTTP_200_OK)
        self.assertTrue(block_res.data['data']['is_blocked'])
        self.assertTrue(UserBlock.objects.filter(blocker=self.user1, blocked=self.user2).exists())

        # Follow relationships should be cleared in both directions
        self.assertFalse(UserFollow.objects.filter(follower=self.user1, following=self.user2).exists())
        self.assertFalse(UserFollow.objects.filter(follower=self.user2, following=self.user1).exists())

        # Outfits by User2 should NOT appear in User1's Explore or Following
        dummy_img = create_test_image("blocked.jpg")
        TodayOutfit.objects.create(user=self.user2, image=dummy_img, caption="Blocked user outfit", visibility="public")
        feed_res = self.client.get('/api/social/explore/')
        self.assertEqual(feed_res.status_code, status.HTTP_200_OK)
        explore_creators = [o['user']['id'] for o in feed_res.data['data']['results']]
        self.assertNotIn(str(self.user2.id), explore_creators)

        # Cannot block oneself
        self_block_res = self.client.post(f'/api/social/users/{self.user1.id}/block/')
        self.assertEqual(self_block_res.status_code, status.HTTP_400_BAD_REQUEST)

        # Toggle unblock
        unblock_res = self.client.post(block_url)
        self.assertEqual(unblock_res.status_code, status.HTTP_200_OK)
        self.assertFalse(unblock_res.data['data']['is_blocked'])
        self.assertFalse(UserBlock.objects.filter(blocker=self.user1, blocked=self.user2).exists())

    def test_content_reporting_dsa(self):
        """SR-10: Test reporting content with rate limiting and validation."""
        dummy_img = create_test_image("reported.jpg")
        outfit = TodayOutfit.objects.create(user=self.user2, image=dummy_img, caption="Offensive outfit", visibility="public")

        report_url = '/api/social/reports/'
        report_data = {
            'target_type': 'outfit',
            'target_id': str(outfit.id),
            'reason': 'harassment',
            'details': 'This outfit caption violates guidelines.'
        }
        res = self.client.post(report_url, report_data)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['success'])
        self.assertEqual(res.data['data']['status'], 'pending')
        self.assertEqual(res.data['data']['reason'], 'harassment')
        self.assertTrue(ContentReport.objects.filter(reporter=self.user1, target_id=str(outfit.id)).exists())

        # Reporting non-existent object returns 400
        bad_res = self.client.post(report_url, {
            'target_type': 'outfit',
            'target_id': '99999999-9999-9999-9999-999999999999',
            'reason': 'spam',
            'details': 'Nonexistent'
        })
        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tagged_items_price_and_notes_privacy(self):
        """SR-27: Public representation of tagged items must conceal price and notes."""
        item = ClosetItem.objects.create(
            user=self.user1,
            name='Designer Coat',
            category='dresses_outerwear',
            brand='Gucci',
            color='Black',
            price=2500.00
        )
        dummy_img = create_test_image("tagged.jpg")
        outfit = TodayOutfit.objects.create(user=self.user1, image=dummy_img, caption="Luxury look", visibility="public")
        outfit.tagged_items.add(item)

        res = self.client.get(f'/api/social/outfits/{outfit.id}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        tagged_details = res.data['data']['tagged_items_details']
        self.assertEqual(len(tagged_details), 1)
        item_rep = tagged_details[0]
        self.assertEqual(item_rep['name'], 'Designer Coat')
        self.assertEqual(item_rep['brand'], 'Gucci')
        # Crucial privacy assertion: price MUST NOT be present
        self.assertNotIn('price', item_rep)
        self.assertNotIn('notes', item_rep)
        self.assertNotIn('cost_cents', item_rep)

    def test_activity_point_awards_flag(self):
        """SR-07: Outfit creation only awards points if enabled and if visibility is public."""
        from rewards.models import UserRewardProfile

        # Default flag is False: no points awarded
        dummy_img = create_test_image("outfit1.jpg")
        self.client.post('/api/social/outfits/', {
            'image': dummy_img,
            'caption': 'No points outfit',
            'visibility': 'public'
        }, format='multipart')

        profile, _ = UserRewardProfile.objects.get_or_create(user=self.user1)
        self.assertEqual(profile.available_points, 0)

        # With flag enabled: public outfit earns 120 points, private earns 0
        with override_settings(MYC_POINTS_ACTIVITY_AWARDS=True):
            dummy_img2 = create_test_image("outfit2.jpg")
            self.client.post('/api/social/outfits/', {
                'image': dummy_img2,
                'caption': 'Points public outfit',
                'visibility': 'public'
            }, format='multipart')

            profile.refresh_from_db()
            self.assertEqual(profile.available_points, 120)

            dummy_img3 = create_test_image("outfit3.jpg")
            self.client.post('/api/social/outfits/', {
                'image': dummy_img3,
                'caption': 'Private outfit no points',
                'visibility': 'private'
            }, format='multipart')

            profile.refresh_from_db()
            # Still 120 because private outfits do not earn points
            self.assertEqual(profile.available_points, 120)

    def test_websocket_ticket_auth_and_single_use(self):
        """SR-09: Single-use short-lived ticket auth for WebSockets without token in query string."""
        from social.middleware import get_user_from_ticket

        # 1. Feature disabled by default -> returns 404
        res_disabled = self.client.post('/api/social/ws-ticket/')
        self.assertEqual(res_disabled.status_code, status.HTTP_404_NOT_FOUND)

        # 2. Feature enabled -> returns 200 with 60-second ticket
        with override_settings(MYC_DM_ENABLED=True):
            from social.middleware import get_user_from_ticket_sync
            res = self.client.post('/api/social/ws-ticket/')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            ticket = res.data['data']['ticket']
            self.assertTrue(ticket.startswith('wst_'))
            self.assertEqual(res.data['data']['expires_in'], 60)

            # 3. First consumption resolves user
            user = get_user_from_ticket_sync(ticket)
            self.assertEqual(user.id, self.user1.id)

            # 4. Second consumption returns AnonymousUser (single-use replay protection)
            replay_user = get_user_from_ticket_sync(ticket)
            self.assertTrue(replay_user.is_anonymous)

    def test_outfit_delete_reverses_points_and_decrements_times_worn(self):
        """SR-07 & SR-26: Deleting an outfit claws back reward points and decrements item times_worn."""
        from rewards.models import UserRewardProfile, PointAward

        item = ClosetItem.objects.create(
            user=self.user1,
            name='Daily Jeans',
            category='bottoms',
            times_worn=0
        )

        with override_settings(MYC_POINTS_ACTIVITY_AWARDS=True):
            dummy_img = create_test_image("outfit_signal.jpg")
            res = self.client.post('/api/social/outfits/', {
                'image': dummy_img,
                'caption': 'Daily look test',
                'visibility': 'public',
                'tagged_items': [item.id]
            }, format='multipart')
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)
            outfit_id = res.data['data']['id']

            # Verify reward awarded and times_worn incremented
            profile = UserRewardProfile.objects.get(user=self.user1)
            self.assertEqual(profile.available_points, 120)
            item.refresh_from_db()
            self.assertEqual(item.times_worn, 1)

            # Delete the outfit via API
            del_res = self.client.delete(f'/api/social/outfits/{outfit_id}/')
            self.assertEqual(del_res.status_code, status.HTTP_200_OK)

            # Assert points clawed back
            profile.refresh_from_db()
            self.assertEqual(profile.available_points, 0)

            # Assert award state is CLAWED_BACK
            award = PointAward.objects.filter(user=self.user1, outfit_id=outfit_id).first()
            self.assertIsNotNone(award)
            self.assertEqual(award.state, 'CLAWED_BACK')
            self.assertEqual(award.points_current, 0)

            # Assert times_worn decremented back to 0
            item.refresh_from_db()
            self.assertEqual(item.times_worn, 0)

    def test_websocket_middleware_security_and_raw_jwt_rejection(self):
        """SR-09: Raw JWTs in query strings or subprotocols are strictly rejected; only single-use tickets are accepted."""
        from social.middleware import JWTAuthMiddleware
        from rest_framework_simplejwt.tokens import AccessToken
        import asyncio

        raw_jwt = str(AccessToken.for_user(self.user1))

        # Helper to execute async middleware call synchronously in test
        def call_middleware(scope):
            inner_called = {'called': False, 'user': None}
            async def dummy_inner(s, r, snd):
                inner_called['called'] = True
                inner_called['user'] = s.get('user')
            middleware = JWTAuthMiddleware(dummy_inner)
            asyncio.run(middleware(scope, None, None))
            return inner_called['user']

        def mock_user_get(**kwargs):
            if str(kwargs.get('id')) == str(self.user1.id):
                return self.user1
            elif str(kwargs.get('id')) == str(self.user2.id):
                return self.user2
            raise User.DoesNotExist()

        with patch('social.middleware.User.objects.get', side_effect=mock_user_get):
            # 1. Raw JWT in query string (?token=...) MUST BE REJECTED
            scope_jwt_query = {
                'query_string': f'token={raw_jwt}'.encode('utf-8'),
                'headers': []
            }
            user = call_middleware(scope_jwt_query)
            self.assertTrue(user.is_anonymous)

            # 2. Raw JWT in Sec-WebSocket-Protocol MUST BE REJECTED
            scope_jwt_proto = {
                'query_string': b'',
                'headers': [(b'sec-websocket-protocol', f'closly-auth.{raw_jwt}'.encode('utf-8'))]
            }
            user = call_middleware(scope_jwt_proto)
            self.assertTrue(user.is_anonymous)

            # 3. Valid ticket in query string SUCCEEDS
            with override_settings(MYC_DM_ENABLED=True):
                ticket_res = self.client.post('/api/social/ws-ticket/')
                valid_ticket = ticket_res.data['data']['ticket']

                scope_valid_ticket = {
                    'query_string': f'ticket={valid_ticket}'.encode('utf-8'),
                    'headers': []
                }
                user = call_middleware(scope_valid_ticket)
                self.assertEqual(user.id, self.user1.id)

                # 4. Reusing consumed ticket FAILS (single-use guarantee)
                replay_user = call_middleware(scope_valid_ticket)
                self.assertTrue(replay_user.is_anonymous)

            # 5. Valid ticket via Sec-WebSocket-Protocol SUCCEEDS
            with override_settings(MYC_DM_ENABLED=True):
                ticket_res2 = self.client.post('/api/social/ws-ticket/')
                valid_ticket2 = ticket_res2.data['data']['ticket']

                scope_proto_ticket = {
                    'query_string': b'',
                    'headers': [(b'sec-websocket-protocol', f'closly-auth.{valid_ticket2}'.encode('utf-8'))]
                }
                user = call_middleware(scope_proto_ticket)
                self.assertEqual(user.id, self.user1.id)

            # 6. Malformed ticket rejected
            scope_malformed = {
                'query_string': b'ticket=invalid_ticket_format_without_prefix',
                'headers': []
            }
            self.assertTrue(call_middleware(scope_malformed).is_anonymous)

            # 7. Raw ?access_token=<JWT> is also strictly rejected
            scope_jwt_access = {
                'query_string': f'access_token={raw_jwt}'.encode('utf-8'),
                'headers': []
            }
            self.assertTrue(call_middleware(scope_jwt_access).is_anonymous)

            # 8. Concurrent ticket consumption race test (SR-09 atomic guarantee)
            with override_settings(MYC_DM_ENABLED=True):
                ticket_res3 = self.client.post('/api/social/ws-ticket/')
                valid_ticket3 = ticket_res3.data['data']['ticket']
                scope_race = {
                    'query_string': f'ticket={valid_ticket3}'.encode('utf-8'),
                    'headers': []
                }
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    f1 = executor.submit(call_middleware, scope_race)
                    f2 = executor.submit(call_middleware, scope_race)
                    res1 = f1.result()
                    res2 = f2.result()

                authenticated_count = sum(1 for u in [res1, res2] if u and u.is_authenticated)
                anonymous_count = sum(1 for u in [res1, res2] if u and u.is_anonymous)
                self.assertEqual(authenticated_count, 1)
                self.assertEqual(anonymous_count, 1)

    def test_storage_cleanup_resilience_on_missing_file(self):
        """SR-11: Deleting records when the underlying file is already missing on disk does not crash."""
        dummy_img = create_test_image("resilience.jpg")
        outfit = TodayOutfit.objects.create(
            user=self.user1,
            image=dummy_img,
            caption="Resilience look",
            visibility="public"
        )
        file_path = outfit.image.name
        storage = outfit.image.storage

        # Delete physical file out-of-band to simulate orphaned or missing file
        if storage.exists(file_path):
            storage.delete(file_path)

        # Model deletion must handle missing storage file gracefully without raising
        try:
            outfit.delete()
            deletion_succeeded = True
        except Exception:
            deletion_succeeded = False

        self.assertTrue(deletion_succeeded)
        self.assertFalse(TodayOutfit.objects.filter(caption="Resilience look").exists())

    def test_storage_cleanup_and_retention_suite(self):
        """SR-11: Physical file cleanup on record deletion and retention purge for expired stories."""
        from datetime import timedelta
        from django.utils import timezone
        from .models import Story
        from .tasks import expire_old_stories_task

        # 1. Normal TodayOutfit deletion cleans physical storage
        img1 = create_test_image("clean_outfit.jpg")
        outfit1 = TodayOutfit.objects.create(
            user=self.user1,
            image=img1,
            caption="Clean Look",
            visibility="public"
        )
        file1 = outfit1.image.name
        storage1 = outfit1.image.storage
        self.assertTrue(storage1.exists(file1))
        outfit1.delete()
        self.assertFalse(storage1.exists(file1))

        # 2. Shared storage path between records is not deleted prematurely
        img2 = create_test_image("shared.jpg")
        outfit_a = TodayOutfit.objects.create(user=self.user1, image=img2, caption="Look A")
        shared_path = outfit_a.image.name
        # Create second record pointing to exact same file path
        outfit_b = TodayOutfit.objects.create(user=self.user2, caption="Look B")
        outfit_b.image.name = shared_path
        outfit_b.save(update_fields=['image'])
        # Deleting outfit_a should NOT delete file since outfit_b still references it
        outfit_a.delete()
        self.assertTrue(storage1.exists(shared_path))
        # Deleting outfit_b cleans up the file now that no references remain
        outfit_b.delete()
        self.assertFalse(storage1.exists(shared_path))

        # 3. Story retention purge: stories past MYC_STORY_RETENTION_DAYS are purged with files
        img3 = create_test_image("retention_story.jpg")
        st = Story.objects.create(
            user=self.user1,
            image=img3,
            caption="Old Story",
            expires_at=timezone.now() - timedelta(days=8)
        )
        story_file = st.image.name
        self.assertTrue(storage1.exists(story_file))

        # Run periodic retention cleanup task
        expire_old_stories_task()

        # Story row and file purged
        self.assertFalse(Story.objects.filter(id=st.id).exists())
        self.assertFalse(storage1.exists(story_file))
