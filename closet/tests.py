from django.test import TestCase
from unittest.mock import patch
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from .models import ClosetItem

User = get_user_model()

class ClosetApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='closetuser@example.com',
            password='Password123!',
            name='Closet User'
        )
        self.client.force_authenticate(user=self.user)
        from users.utils.common_utils import record_user_consent
        record_user_consent(self.user, 'photo_ai_processing', granted=True)

    def test_create_and_list_closet_item(self):
        url = '/api/closet/items/'
        data = {
            'name': 'Test Jacket',
            'category': 'top',
            'color': 'Black',
            'brand': 'Zara',
            'size': 'L',
            'price': '100.00'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['name'], 'Test Jacket')
        self.assertEqual(response.data['data']['per_wear_cost'], 100.00)

        # Test Wear Today
        item_id = response.data['data']['id']
        wear_url = f'/api/closet/items/{item_id}/wear-today/'
        wear_response = self.client.post(wear_url)
        self.assertEqual(wear_response.status_code, status.HTTP_200_OK)
        self.assertEqual(wear_response.data['data']['times_worn'], 1)
        self.assertEqual(wear_response.data['data']['per_wear_cost'], 100.00)

    def test_closet_audit(self):
        from django.utils import timezone
        ClosetItem.objects.create(user=self.user, name='Item 1', category='top', price=50.00, times_worn=5, last_worn_at=timezone.now())
        ClosetItem.objects.create(user=self.user, name='Item 2', category='bottom', price=30.00, times_worn=0)

        url = '/api/closet/audit/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertEqual(data['total_pieces'], 2)
        self.assertEqual(data['active_pieces'], 1)
        self.assertEqual(data['ghost_pieces'], 1)
        self.assertEqual(len(data['list_of_most_worn']), 1)
        self.assertEqual(len(data['list_of_ghost_pieces']), 1)
        self.assertIn('environmental_and_space_impact', data)
        self.assertIn('wasted_carbon_kg', data['environmental_and_space_impact'])
        self.assertIn('wardrobe_status', data)
        self.assertIn('badge', data['wardrobe_status'])

    def test_closet_score_dashboard(self):
        url = '/api/closet/score/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertIn('closet_score', data)
        self.assertIn('category', data)
        self.assertIn('cost_wear', data)
        self.assertIn('closet_points', data)
        self.assertIn('achieve_rank', data)
        self.assertIn('style_dna', data)

    def test_negative_price_rejected(self):
        url = '/api/closet/items/'
        data = {
            'name': 'Negative Price Jacket',
            'category': 'top',
            'price': '-25.00'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('price', response.data['errors'])

    def test_image_size_and_format_validation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from users.validators import validate_image_file

        # Test invalid extension
        bad_format_file = SimpleUploadedFile("test.exe", b"fake binary data", content_type="application/octet-stream")
        with self.assertRaises(ValidationError) as ctx:
            validate_image_file(bad_format_file, max_mb=30)
        self.assertIn("Only JPG, JPEG, PNG, WebP, and HEIC", str(ctx.exception))

        # Test oversized file (> 30MB)
        # Mock size attribute to avoid allocating 31MB in memory
        class MockLargeFile:
            name = "large.jpg"
            size = 31 * 1024 * 1024

        with self.assertRaises(ValidationError) as ctx:
            validate_image_file(MockLargeFile(), max_mb=30)
        self.assertIn("exceeds the 30MB limit", str(ctx.exception))

    def test_long_filename_upload_accepted(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='red')
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)

        long_filename = "A" * 153 + ".jpg"
        dummy_file = SimpleUploadedFile(long_filename, file_obj.read(), content_type="image/jpeg")

        url = '/api/closet/items/'
        data = {
            'name': 'Long Filename Item',
            'category': 'top',
            'price': '45.00',
            'image': dummy_file
        }
        response = self.client.post(url, data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        # Check that image URL starts with https://
        if response.data['data']['image']:
            self.assertTrue(response.data['data']['image'].startswith('https://') or response.data['data']['image'].startswith('http://'))

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_ai_scan_clothing_image_success(self, mock_ai_analyzer):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        mock_ai_analyzer.return_value = {
            'is_garment': True,
            'name': 'Navy Shirt',
            'category': 'top',
            'color': 'Navy Blue',
            'brand': 'Closly Studio',
            'price': 45.0,
            'style_vibe': 'smart casual',
            'visual_match_score': 95,
        }

        # Create synthetic navy blue image (aspect ratio ~1.0 for top)
        file_obj = io.BytesIO()
        img = Image.new('RGB', (120, 120), color=(26, 42, 74))
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)

        uploaded_file = SimpleUploadedFile("navy_shirt.jpg", file_obj.read(), content_type="image/jpeg")

        url = '/api/closet/ai-scan/'
        response = self.client.post(url, {'image': uploaded_file}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        data = response.data['data']
        self.assertIn('name', data)
        self.assertIn('category', data)
        self.assertIn('color', data)
        self.assertIn('brand', data)
        self.assertIn('price', data)
        self.assertIn('style_vibe', data)
        self.assertIn('visual_match_score', data)
        self.assertIn('image_url', data)
        self.assertTrue(data['image_url'].startswith('https://') or data['image_url'].startswith('http://'))

    def test_ai_scan_non_garment_returns_clean_notice(self):
        import io
        from PIL import Image
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile

        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='white')
        img.save(file_obj, format='PNG')
        file_obj.seek(0)

        mock_non_garment = {
            'is_garment': False,
            'message': 'The uploaded image does not appear to be a clothing item. Please capture or upload a clear photo of a garment.',
            'notes': 'The image appears to be a screenshot rather than an actual garment.'
        }

        uploaded_file = SimpleUploadedFile("screenshot.png", file_obj.read(), content_type="image/png")
        with patch('closet.ai_scanner.scanner.scan_clothing_image', return_value=mock_non_garment):
            url = '/api/closet/ai-scan/'
            response = self.client.post(url, {'image': uploaded_file}, format='multipart')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertFalse(response.data['success'])
            self.assertFalse(response.data['is_garment'])
            self.assertIn('not appear to be a clothing item', response.data['message'])

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_ai_scan_with_auto_save(self, mock_ai_analyzer):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        mock_ai_analyzer.return_value = {
            'is_garment': True,
            'name': 'Dark Trousers',
            'category': 'bottom',
            'color': 'Dark Grey',
            'brand': 'Closly Bottoms',
            'price': 60.0,
            'style_vibe': 'Formal',
            'visual_match_score': 90,
        }

        file_obj = io.BytesIO()
        img = Image.new('RGB', (100, 150), color=(20, 20, 20))  # Tall dark -> bottom or outerwear
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)

        uploaded_file = SimpleUploadedFile("trousers.jpg", file_obj.read(), content_type="image/jpeg")

        url = '/api/closet/ai-scan/?auto_save=true'
        response = self.client.post(url, {'image': uploaded_file}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        self.assertIn('item', response.data['data'])
        saved_item = response.data['data']['item']
        self.assertTrue(ClosetItem.objects.filter(id=saved_item['id'], user=self.user).exists())
        self.assertTrue(saved_item['image'].startswith('https://') or saved_item['image'].startswith('http://'))

    def test_ai_scan_no_image_returns_400(self):
        url = '/api/closet/ai-scan/'
        response = self.client.post(url, {}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertIn('image', response.data['errors'])

    def test_build_absolute_media_url_utility(self):
        from users.utils import build_absolute_media_url
        url = build_absolute_media_url('closet_items/test.jpg')
        self.assertTrue(url.startswith('https://') or url.startswith('http://'))
        self.assertIn('/media/closet_items/test.jpg', url)

    def test_ai_scan_queue_timeout_returns_503(self):
        import io
        from PIL import Image
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile

        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='white')
        img.save(file_obj, format='PNG')
        file_obj.seek(0)

        uploaded_file = SimpleUploadedFile("overload.png", file_obj.read(), content_type="image/png")
        with patch('closet.ai_scanner.scanner.scan_clothing_image', side_effect=TimeoutError("AI scanning service is currently experiencing very high demand.")):
            url = '/api/closet/ai-scan/'
            response = self.client.post(url, {'image': uploaded_file}, format='multipart')
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertFalse(response.data['success'])
            self.assertEqual(response.headers.get('Retry-After'), '5')
            self.assertIn('very high demand', response.data['message'])

    def test_ai_scan_sha256_cache_hit(self):
        from unittest.mock import patch
        from django.core.cache import cache
        from closet.openai_analyzer import run_direct_dress_analysis
        import hashlib

        dummy_bytes = b"unique_test_garment_bytes_for_cache"
        img_hash = hashlib.sha256(dummy_bytes).hexdigest()
        cache_key = f"closly_ai_scan_{img_hash}"

        cached_mock = {
            "name": "Cached Red Silk Dress",
            "category": "dresses_outerwear",
            "primary_color": "Red",
            "is_garment": True
        }
        cache.set(cache_key, cached_mock, timeout=60)

        # run_direct_dress_analysis should return cached data immediately without calling LLM
        import closet.openai_analyzer
        if getattr(closet.openai_analyzer, 'ai_service', None) is not None:
            with patch('closet.openai_analyzer.ai_service.call_llm_for_analysis') as mock_llm:
                res = run_direct_dress_analysis(dummy_bytes)
                self.assertEqual(res['name'], 'Cached Red Silk Dress')
                mock_llm.assert_not_called()
        else:
            res = run_direct_dress_analysis(dummy_bytes)
            self.assertEqual(res['name'], 'Cached Red Silk Dress')

    def test_ai_scanner_kill_switch_disabled_returns_503(self):
        import io
        from PIL import Image
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile

        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='blue')
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)
        uploaded_file = SimpleUploadedFile("kill_switch_test.jpg", file_obj.read(), content_type="image/jpeg")

        with override_settings(AI_SCANNER_ENABLED=False):
            url = '/api/closet/ai-scan/'
            response = self.client.post(url, {'image': uploaded_file}, format='multipart')
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertFalse(response.data['success'])
            self.assertIn('disabled', response.data['message'])

    def test_ai_scanner_daily_limit_exceeded_returns_429(self):
        import io
        from PIL import Image
        from django.test import override_settings
        from django.core.cache import cache
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch

        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='green')
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)

        # Pre-set user's daily cache limit to threshold
        from django.utils import timezone
        today_str = timezone.now().strftime('%Y-%m-%d')
        daily_cache_key = f"ai_scan_daily_{self.user.id}_{today_str}"
        cache.set(daily_cache_key, 25, timeout=86400)

        with override_settings(MYC_AI_SCAN_DAILY_LIMIT=25):
            url = '/api/closet/ai-scan/'
            uploaded_file = SimpleUploadedFile("limit_test.jpg", file_obj.read(), content_type="image/jpeg")
            response = self.client.post(url, {'image': uploaded_file}, format='multipart')
            self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertFalse(response.data['success'])
            self.assertIn('Daily AI scan limit', response.data['message'])

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_duplicate_photo_sha256_increments_wear_and_avoids_duplicate_item(self, mock_ai_analyzer):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        mock_ai_analyzer.return_value = {
            'is_garment': True,
            'name': 'White Oxford Shirt',
            'category': 'top',
            'color': 'White',
            'brand': 'Closly Classic',
            'price': 45.0,
            'style_vibe': 'smart casual',
            'visual_match_score': 95,
        }

        file_obj = io.BytesIO()
        img = Image.new('RGB', (50, 50), color=(255, 255, 255))
        img.save(file_obj, format='JPEG')
        image_content = file_obj.getvalue()

        # First scan with auto_save creates item
        uploaded_file_1 = SimpleUploadedFile("shirt.jpg", image_content, content_type="image/jpeg")
        url = '/api/closet/ai-scan/?auto_save=true'
        resp1 = self.client.post(url, {'image': uploaded_file_1}, format='multipart')
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)
        item_id = resp1.data['data']['item']['id']
        first_item = ClosetItem.objects.get(id=item_id)
        self.assertEqual(first_item.times_worn, 0)
        initial_items_count = ClosetItem.objects.filter(user=self.user).count()

        # Second scan with exact same photo
        file_obj.seek(0)
        uploaded_file_2 = SimpleUploadedFile("shirt.jpg", image_content, content_type="image/jpeg")
        resp2 = self.client.post(url, {'image': uploaded_file_2}, format='multipart')
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertTrue(resp2.data['data'].get('is_duplicate'))

        # Item count must NOT increase
        final_items_count = ClosetItem.objects.filter(user=self.user).count()
        self.assertEqual(initial_items_count, final_items_count)

        # Times worn must be incremented to 1 (re-wear idempotency)
        first_item.refresh_from_db()
        self.assertEqual(first_item.times_worn, 1)

    def test_corrupted_image_magic_bytes_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Random non-image binary data with .jpg extension
        corrupted_file = SimpleUploadedFile("fake_image.jpg", b"NOT_AN_IMAGE_PAYLOAD_12345", content_type="image/jpeg")
        url = '/api/closet/ai-scan/'
        response = self.client.post(url, {'image': corrupted_file}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])

    def test_item_delete_purges_image_from_storage(self):
        import io
        from PIL import Image
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        # Create image on storage
        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='purple')
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)

        saved_path = default_storage.save("closet_items/test_delete_purge.jpg", ContentFile(file_obj.read()))
        self.assertTrue(default_storage.exists(saved_path))

        item = ClosetItem.objects.create(
            user=self.user,
            name="Deletable Purple Top",
            category="top",
            image=saved_path
        )

        # Delete item via API endpoint
        del_url = f'/api/closet/items/{item.id}/'
        response = self.client.delete(del_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ClosetItem.objects.filter(id=item.id).exists())

        # Storage file must be deleted (GDPR Art. 17 C-02)
        self.assertFalse(default_storage.exists(saved_path))


class FitCheckAsyncPipelineTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='asyncuser@example.com',
            password='Password123!',
            name='Async User'
        )
        self.client.force_authenticate(user=self.user)
        from users.utils.common_utils import record_user_consent
        record_user_consent(self.user, 'photo_ai_processing', granted=True)

    def _create_dummy_image_file(self, filename="async_test.jpg", color="blue"):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        file_obj = io.BytesIO()
        img = Image.new('RGB', (100, 100), color=color)
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)
        return SimpleUploadedFile(filename, file_obj.read(), content_type="image/jpeg")

    @patch('closet.tasks.process_fit_check_task.delay')
    def test_fit_check_create_returns_202_queued(self, mock_celery_task):
        url = '/api/closet/fit-checks/'
        img_file = self._create_dummy_image_file()
        response = self.client.post(url, {'image': img_file}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['status'], 'queued')
        self.assertEqual(response.data['poll_after_s'], 3)
        self.assertIn('id', response.data)

        # Check DB row created
        from closet.models import FitCheck
        fc = FitCheck.objects.get(id=response.data['id'])
        self.assertEqual(fc.status, 'queued')
        self.assertEqual(fc.user, self.user)
        mock_celery_task.assert_called_once_with(str(fc.id))

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_fit_check_celery_task_success(self, mock_ai):
        from closet.models import FitCheck
        from closet.tasks import process_fit_check_task

        mock_ai.return_value = {
            'is_garment': True,
            'name': 'Casual Denim Shirt',
            'category': 'top',
            'color': 'Blue',
            'brand': 'Closly Denim',
            'price': 49.0,
            'confidence': 0.94,
            'tokens_in': 1200,
            'tokens_out': 200,
        }

        # Create queued fitcheck
        url = '/api/closet/fit-checks/'
        img_file = self._create_dummy_image_file("task_test.jpg", color="navy")
        response = self.client.post(url, {'image': img_file}, format='multipart')
        fc_id = response.data['id']

        # Run Celery task directly
        result_status = process_fit_check_task(fc_id)
        self.assertEqual(result_status, 'tagged')

        fc = FitCheck.objects.get(id=fc_id)
        self.assertEqual(fc.status, 'tagged')
        self.assertIsNotNone(fc.tagged_at)
        self.assertTrue(fc.closet_items.exists())
        item = fc.closet_items.first()
        self.assertEqual(item.name, 'Casual Denim Shirt')
        self.assertEqual(item.category, 'top')
        self.assertEqual(item.price, 49.0)

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_fit_check_polling_detail_endpoint(self, mock_ai):
        from closet.models import FitCheck
        from closet.tasks import process_fit_check_task

        mock_ai.return_value = {
            'is_garment': True,
            'name': 'Black Trench Coat',
            'category': 'dresses_outerwear',
            'color': 'Black',
            'brand': 'Closly Outerwear',
            'price': 129.0,
            'confidence': 0.98,
        }

        # Create and process
        img_file = self._create_dummy_image_file("coat.jpg", color="black")
        res_create = self.client.post('/api/closet/fit-checks/', {'image': img_file}, format='multipart')
        fc_id = res_create.data['id']
        process_fit_check_task(fc_id)

        # Poll status
        poll_url = f'/api/closet/fit-checks/{fc_id}/'
        res_poll = self.client.get(poll_url)
        self.assertEqual(res_poll.status_code, status.HTTP_200_OK)
        self.assertTrue(res_poll.data['success'])
        poll_data = res_poll.data['data']
        self.assertEqual(poll_data['status'], 'tagged')
        self.assertEqual(len(poll_data['items']), 1)
        self.assertEqual(poll_data['items'][0]['name'], 'Black Trench Coat')

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_fit_check_dedupe_hit_short_circuit(self, mock_ai):
        from closet.tasks import process_fit_check_task
        mock_ai.return_value = {
            'is_garment': True,
            'name': 'Dedupe Polo',
            'category': 'top',
            'color': 'Teal',
            'brand': 'N/A',
            'price': 35.0,
        }

        # 1. First upload
        img1 = self._create_dummy_image_file("polo.jpg", color="teal")
        res1 = self.client.post('/api/closet/fit-checks/', {'image': img1}, format='multipart')
        self.assertEqual(res1.status_code, status.HTTP_202_ACCEPTED)
        fc_id1 = res1.data['id']
        process_fit_check_task(fc_id1)

        # 2. Second upload with exact same bytes
        img2 = self._create_dummy_image_file("polo.jpg", color="teal")
        res2 = self.client.post('/api/closet/fit-checks/', {'image': img2}, format='multipart')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['status'], 'dedupe_hit')
        self.assertIn('Exact image already analyzed', res2.data['message'])
        self.assertTrue(len(res2.data['items']) >= 1)

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_fit_check_non_clothing_fails_safely(self, mock_ai):
        from closet.models import FitCheck
        from closet.tasks import process_fit_check_task

        mock_ai.return_value = {
            'is_garment': False,
            'message': 'Image does not appear to be a garment.',
            'notes': 'Screenshot detected.',
        }

        img_file = self._create_dummy_image_file("screenshot.jpg", color="white")
        res_create = self.client.post('/api/closet/fit-checks/', {'image': img_file}, format='multipart')
        fc_id = res_create.data['id']
        task_status = process_fit_check_task(fc_id)

        self.assertEqual(task_status, 'failed')
        fc = FitCheck.objects.get(id=fc_id)
        self.assertEqual(fc.status, 'failed')
        self.assertEqual(fc.error_code, 'not_clothing')

        # Poll should return safe message without internal stack traces
        poll_res = self.client.get(f'/api/closet/fit-checks/{fc_id}/')
        self.assertEqual(poll_res.status_code, status.HTTP_200_OK)
        self.assertEqual(poll_res.data['data']['status'], 'failed')
        self.assertIn('does not appear to be a clothing item', poll_res.data['data']['message'])


class NSFWContentSafetyGateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='nsfwuser@example.com',
            password='Password123!',
            name='Safety User'
        )
        self.client.force_authenticate(user=self.user)
        from users.utils.common_utils import record_user_consent
        record_user_consent(self.user, 'photo_ai_processing', granted=True)

    def test_safe_image_passes_safety_gate(self):
        from closet.ai.safety import check_image_safety
        safe_bytes = b"CLEAN_STANDARD_JPEG_IMAGE_BYTES"
        is_safe, reason, score = check_image_safety(safe_bytes)
        self.assertTrue(is_safe)
        self.assertLess(score, 0.75)

    def test_unsafe_image_blocked_by_safety_gate(self):
        from closet.ai.safety import check_image_safety
        unsafe_bytes = b"UNSAFE_TEST_IMAGE_BYTES"
        is_safe, reason, score = check_image_safety(unsafe_bytes)
        self.assertFalse(is_safe)
        self.assertEqual(reason, 'sexual')
        self.assertGreaterEqual(score, 0.75)

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_unsafe_photo_blocked_in_fit_check_pipeline(self, mock_ai):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.files.storage import default_storage
        from closet.models import FitCheck
        from closet.tasks import process_fit_check_task

        # Create dummy image containing NSFW test marker
        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='red')
        img.save(file_obj, format='JPEG')
        img_file = SimpleUploadedFile("nsfw_image.jpg", file_obj.getvalue(), content_type="image/jpeg")

        # Run with unsafe classification in eager Celery mode
        with patch('closet.ai.safety.check_image_safety', return_value=(False, 'sexual', 0.99)):
            res = self.client.post('/api/closet/fit-checks/', {'image': img_file}, format='multipart')
            self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
            fc_id = res.data['id']

        # Downstream LLM MUST NOT be called!
        mock_ai.assert_not_called()

        fc = FitCheck.objects.get(id=fc_id)
        self.assertEqual(fc.status, 'nsfw_blocked')
        self.assertEqual(fc.error_code, 'nsfw_content_detected')
        self.assertIsNotNone(fc.nsfw_score)

        # Blocked file must be cleaned from storage
        if fc.photo and fc.photo.name:
            self.assertFalse(default_storage.exists(fc.photo.name))

    def test_safety_service_timeout_fails_closed(self):
        from closet.ai.safety import check_image_safety, AISafetyError
        with patch('requests.post', side_effect=AISafetyError("Content moderation service timed out.")):
            from django.test import override_settings
            with override_settings(SIGHTENGINE_API_USER="mock_user", SIGHTENGINE_API_SECRET="mock_secret"):
                with self.assertRaises(AISafetyError):
                    check_image_safety(b"TEST_IMAGE_BYTES")


class UserConsentVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='consentuser@example.com',
            password='Password123!',
            name='Consent User'
        )
        self.client.force_authenticate(user=self.user)

    def _create_image(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        file_obj = io.BytesIO()
        img = Image.new('RGB', (20, 20), color='green')
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)
        return SimpleUploadedFile("consent_test.jpg", file_obj.read(), content_type="image/jpeg")

    def test_scan_without_consent_returns_403_consent_required(self):
        # 1. Async endpoint
        res_async = self.client.post('/api/closet/fit-checks/', {'image': self._create_image()}, format='multipart')
        self.assertEqual(res_async.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(res_async.data['success'])
        self.assertEqual(res_async.data['error_code'], 'consent_required')

        # 2. Sync endpoint
        res_sync = self.client.post('/api/closet/ai-scan/', {'image': self._create_image()}, format='multipart')
        self.assertEqual(res_sync.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(res_sync.data['success'])
        self.assertEqual(res_sync.data['error_code'], 'consent_required')

    def test_grant_consent_via_api_and_retry_scan(self):
        # Grant consent via API
        consent_res = self.client.post('/api/closet/consent/', {
            'kind': 'photo_ai_processing',
            'granted': True,
            'version': '1.0'
        })
        self.assertEqual(consent_res.status_code, status.HTTP_200_OK)
        self.assertTrue(consent_res.data['data']['granted'])

        # Now scan should proceed past the consent gate
        with patch('closet.tasks.process_fit_check_task.delay'):
            scan_res = self.client.post('/api/closet/fit-checks/', {'image': self._create_image()}, format='multipart')
            self.assertEqual(scan_res.status_code, status.HTTP_202_ACCEPTED)

    def test_revoke_consent_blocks_subsequent_scans(self):
        # Grant first
        self.client.post('/api/closet/consent/', {'kind': 'photo_ai_processing', 'granted': True})
        # Revoke
        self.client.post('/api/closet/consent/', {'kind': 'photo_ai_processing', 'granted': False})

        # Scan must now be blocked with 403
        scan_res = self.client.post('/api/closet/fit-checks/', {'image': self._create_image()}, format='multipart')
        self.assertEqual(scan_res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(scan_res.data['error_code'], 'consent_required')


class PrivateStorageAndCrossUserOwnershipTests(TestCase):
    def setUp(self):
        self.client_a = APIClient()
        self.user_a = User.objects.create_user(email='usera@example.com', password='Password123!', name='User A')
        self.client_a.force_authenticate(user=self.user_a)

        self.client_b = APIClient()
        self.user_b = User.objects.create_user(email='userb@example.com', password='Password123!', name='User B')
        self.client_b.force_authenticate(user=self.user_b)

        from users.utils.common_utils import record_user_consent
        record_user_consent(self.user_a, 'photo_ai_processing', granted=True)
        record_user_consent(self.user_b, 'photo_ai_processing', granted=True)

    def test_cross_user_fit_check_access_forbidden(self):
        from closet.models import FitCheck
        fc_a = FitCheck.objects.create(
            user=self.user_a,
            photo_sha256='mock_sha256_for_user_a',
            status='tagged'
        )

        # User B attempts to access User A's FitCheck
        res = self.client_b.get(f'/api/closet/fit-checks/{fc_a.id}/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data['error_code'], 'forbidden')

    def test_cross_user_closet_item_access_forbidden(self):
        item_a = ClosetItem.objects.create(
            user=self.user_a,
            name="User A Private Dress",
            category="dresses_outerwear",
            price=150.00
        )

        # User B attempts to read User A's ClosetItem
        res = self.client_b.get(f'/api/closet/items/{item_a.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_fit_check_deletion_purges_storage_file(self):
        import io
        from PIL import Image
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        from closet.models import FitCheck

        file_obj = io.BytesIO()
        img = Image.new('RGB', (10, 10), color='green')
        img.save(file_obj, format='JPEG')
        file_obj.seek(0)

        saved_path = default_storage.save("fit_checks/purge_test.jpg", ContentFile(file_obj.read()))
        self.assertTrue(default_storage.exists(saved_path))

        fc = FitCheck.objects.create(
            user=self.user_a,
            photo=saved_path,
            photo_sha256="test_sha_purge",
            status='tagged'
        )

        fc.delete()
        self.assertFalse(FitCheck.objects.filter(id=fc.id).exists())
        self.assertFalse(default_storage.exists(saved_path))


class AICostAndUsageTrackingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='costuser@example.com',
            password='Password123!',
            name='Cost User'
        )
        self.client.force_authenticate(user=self.user)
        from users.utils.common_utils import record_user_consent
        record_user_consent(self.user, 'photo_ai_processing', granted=True)

    @patch('closet.openai_analyzer.analyze_dress_with_openai')
    def test_scan_records_llm_cost_log(self, mock_ai):
        from closet.models import LLMCostLog
        from closet.ai.gateway import AIGateway

        mock_ai.return_value = {
            'is_garment': True,
            'name': 'Silk Shirt',
            'category': 'top',
            'tokens_in': 1240,
            'tokens_out': 220,
        }

        # Run analysis through gateway
        result = AIGateway.execute_photo_analysis(b"FAKE_IMAGE_BYTES", user=self.user)
        self.assertTrue(result['is_garment'])

        # Check LLMCostLog created
        log = LLMCostLog.objects.filter(user=self.user).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.task, 'photo_analysis')
        self.assertEqual(log.input_tokens, 1240)
        self.assertEqual(log.output_tokens, 220)
        self.assertGreater(log.cost_cents, 0)
        self.assertTrue(log.success)

    def test_cost_endpoint_returns_user_summary(self):
        from closet.models import LLMCostLog
        import decimal
        LLMCostLog.objects.create(
            user=self.user,
            task='photo_analysis',
            model='gpt-4o',
            input_tokens=1000,
            output_tokens=200,
            cost_cents=decimal.Decimal('0.4500'),
            success=True
        )

        res = self.client.get('/api/closet/costs/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])
        self.assertEqual(res.data['data']['count'], 1)
        self.assertAlmostEqual(res.data['data']['total_cost_cents'], 0.45, places=2)


class EUDataResidencyConfigurationTests(TestCase):
    def test_eu_provider_allowlist_enforcement(self):
        from closet.ai.gateway import AIGateway
        from closet.exceptions import AIServiceUnavailableError
        from django.test import override_settings

        with override_settings(AI_PHOTO_PROVIDER="unauthorized_third_party_ai"):
            with self.assertRaises(AIServiceUnavailableError) as ctx:
                AIGateway.verify_provider_and_region()
            self.assertIn("data residency", str(ctx.exception).lower())

    def test_authorized_eu_provider_passes(self):
        from closet.ai.gateway import AIGateway
        from django.test import override_settings

        with override_settings(AI_PHOTO_PROVIDER="openai", AI_DATA_REGION="EU"):
            provider, region = AIGateway.verify_provider_and_region()
            self.assertEqual(provider, "openai")
            self.assertEqual(region, "EU")






