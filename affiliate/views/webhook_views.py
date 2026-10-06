"""
affiliate/views/webhook_views.py
AWIN Server-to-Server Transaction Notification & Conversion Webhook API (Audit CF-30).
Receives, validates, and records affiliate purchase conversions with:
- Token-based webhook authentication
- Click reference linkage (clickref -> ProductClick -> User)
- Idempotent update_or_create to handle retries and status changes (pending -> approved)
- Product and Brand linkage
- Reward points reconciliation with rewards service
"""
import decimal
import hmac
import logging
import uuid
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiResponse

from affiliate.models import (
    AffiliateProduct,
    Brand,
    ProductClick,
    Conversion,
)

logger = logging.getLogger(__name__)


def _normalize_conversion_status(raw_status: str) -> str:
    s = (raw_status or '').strip().lower()
    if s in ('approved', 'confirmed', 'accepted', 'paid'):
        return Conversion.STATUS_APPROVED
    elif s in ('declined', 'rejected'):
        return Conversion.STATUS_DECLINED
    elif s in ('deleted', 'cancelled', 'canceled'):
        return Conversion.STATUS_DELETED
    return Conversion.STATUS_PENDING


def _validate_webhook_auth(request) -> bool:
    """Validate webhook secret token from Authorization header or X-Awin-Token."""
    secret = getattr(settings, 'MYC_AWIN_WEBHOOK_SECRET', None)
    if not secret:
        # If no secret configured in environment, allow in dev/test
        return True

    # 1. Check Authorization: Bearer <secret>
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
        if hmac.compare_digest(token, secret):
            return True

    # 2. Check X-Awin-Token or X-Awin-Signature
    custom_token = request.META.get('HTTP_X_AWIN_TOKEN') or request.META.get('HTTP_X_AWIN_SIGNATURE', '')
    if custom_token and hmac.compare_digest(custom_token.strip(), secret):
        return True

    # 3. Check query param ?token=
    query_token = request.query_params.get('token', '')
    if query_token and hmac.compare_digest(query_token.strip(), secret):
        return True

    return False


@extend_schema(
    tags=["Affiliate Webhooks"],
    summary="AWIN Server-to-Server Transaction Webhook",
    description="Idempotently ingest purchase conversions from AWIN with click attribution and ledger linkage.",
    responses={
        200: OpenApiResponse(description="Transaction processed successfully"),
        400: OpenApiResponse(description="Invalid transaction payload"),
        401: OpenApiResponse(description="Unauthorized webhook signature/token"),
    }
)
class AwinWebhookView(APIView):
    """
    Endpoint for AWIN transaction notifications and conversions postback.
    POST /api/affiliate/webhooks/awin/
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if not _validate_webhook_auth(request):
            logger.warning("AWIN Webhook: Unauthorized request received.")
            return Response({
                'success': False,
                'message': 'Unauthorized webhook request.'
            }, status=status.HTTP_401_UNAUTHORIZED)

        payload = request.data
        if not payload:
            return Response({
                'success': False,
                'message': 'Empty payload.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Support single transaction dict or list of transactions
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get('transactions') or payload.get('events') or [payload]
        else:
            return Response({
                'success': False,
                'message': 'Payload must be a JSON object or array.'
            }, status=status.HTTP_400_BAD_REQUEST)

        created_count = 0
        updated_count = 0
        processed_count = 0

        for item in items:
            if not isinstance(item, dict):
                continue

            tx_id = (
                item.get('id') or
                item.get('transaction_id') or
                item.get('order_id')
            )
            if not tx_id:
                logger.warning(f"AWIN Webhook: Transaction item missing id/transaction_id: {item}")
                continue

            tx_id_str = str(tx_id).strip()
            raw_click_ref = item.get('clickref') or item.get('click_ref') or item.get('sub_id') or item.get('u1')
            raw_surface = item.get('clickref2') or item.get('surface', '')
            adv_id = str(item.get('advertiser_id') or item.get('merchant_id') or item.get('mid') or '').strip()
            order_ref = str(item.get('order_reference') or item.get('order_id') or item.get('ref') or '').strip()

            raw_amount = item.get('amount') or item.get('sale_amount') or item.get('price') or '0.00'
            raw_commission = item.get('commission') or item.get('publisher_commission') or item.get('payout') or '0.00'

            try:
                sale_amount = decimal.Decimal(str(raw_amount).replace(',', '.'))
            except (decimal.InvalidOperation, ValueError):
                sale_amount = decimal.Decimal('0.00')

            try:
                commission_amount = decimal.Decimal(str(raw_commission).replace(',', '.'))
            except (decimal.InvalidOperation, ValueError):
                commission_amount = decimal.Decimal('0.00')

            currency = (item.get('currency') or 'EUR').strip().upper()
            status_val = _normalize_conversion_status(item.get('status', ''))

            # Parse transaction timestamp
            tx_date_raw = item.get('transaction_date') or item.get('date')
            tx_date = parse_datetime(str(tx_date_raw)) if tx_date_raw else timezone.now()

            # Attempt click attribution linkage
            click_obj = None
            click_uuid = None
            linked_user = None
            linked_product = None
            linked_brand = None

            if raw_click_ref:
                try:
                    click_uuid = uuid.UUID(str(raw_click_ref).strip())
                    click_obj = ProductClick.objects.filter(
                        click_ref=click_uuid
                    ).select_related('user', 'product', 'product__brand_ref').first()

                    if click_obj:
                        linked_user = click_obj.user
                        linked_product = click_obj.product
                        if linked_product and linked_product.brand_ref:
                            linked_brand = linked_product.brand_ref
                except (ValueError, TypeError):
                    logger.warning(f"AWIN Webhook: Non-UUID clickref '{raw_click_ref}' for tx {tx_id_str}")

            # Product linkage fallback
            if not linked_product:
                raw_prod_id = item.get('product_id') or item.get('merchant_product_id') or item.get('aw_product_id')
                if raw_prod_id:
                    linked_product = AffiliateProduct.objects.filter(
                        aw_product_id=str(raw_prod_id).strip()
                    ).select_related('brand_ref').first()
                    if linked_product and linked_product.brand_ref:
                        linked_brand = linked_product.brand_ref

            # Brand linkage fallback
            if not linked_brand and adv_id:
                linked_brand = Brand.objects.filter(external_id=adv_id).first()

            # Determine validation date
            validation_date = None
            if status_val in (Conversion.STATUS_APPROVED, Conversion.STATUS_DECLINED):
                val_date_raw = item.get('validation_date')
                validation_date = parse_datetime(str(val_date_raw)) if val_date_raw else timezone.now()

            # Idempotent upsert
            defaults = {
                'click': click_obj,
                'click_ref': click_uuid,
                'user': linked_user,
                'product': linked_product,
                'brand': linked_brand,
                'advertiser_id': adv_id,
                'order_reference': order_ref or tx_id_str,
                'status': status_val,
                'sale_amount': sale_amount,
                'commission_amount': commission_amount,
                'currency': currency,
                'transaction_date': tx_date,
                'raw_payload': item,
            }
            if validation_date:
                defaults['validation_date'] = validation_date

            conversion, created = Conversion.objects.update_or_create(
                source=Conversion.SOURCE_AWIN,
                conversion_id=tx_id_str,
                defaults=defaults,
            )

            # Auto-award purchase points if approved and user linked
            if conversion.status == Conversion.STATUS_APPROVED and conversion.user and not conversion.reward_claimed:
                self._reconcile_reward_points(conversion)

            if created:
                created_count += 1
            else:
                updated_count += 1
            processed_count += 1

        logger.info(
            f"AWIN Webhook: Processed {processed_count} conversions "
            f"({created_count} created, {updated_count} updated)."
        )

        return Response({
            'success': True,
            'message': 'AWIN transaction(s) processed successfully',
            'data': {
                'processed': processed_count,
                'created': created_count,
                'updated': updated_count,
            }
        }, status=status.HTTP_200_OK)

    def _reconcile_reward_points(self, conversion: Conversion):
        """Link or award purchase reward points for verified conversions."""
        try:
            from rewards.models import RewardPointTransaction
            from rewards.services import award_points

            order_ref = conversion.order_reference or conversion.conversion_id

            # Check if points already exist for this order reference
            existing_tx = RewardPointTransaction.objects.filter(
                user=conversion.user,
                action_type='make_purchase',
                reference_id=str(order_ref)
            ).first()

            if existing_tx:
                conversion.reward_transaction = existing_tx
                conversion.reward_claimed = True
                conversion.save(update_fields=['reward_transaction', 'reward_claimed'])
            elif getattr(settings, 'MYC_AUTO_AWARD_PURCHASE_POINTS', True):
                points = getattr(settings, 'MYC_PURCHASE_AWARD_POINTS', 200)
                brand_name = conversion.brand.name if conversion.brand else "Affiliate Partner"
                desc = f"Verified Purchase at {brand_name} (Order: {order_ref})"

                new_tx = award_points(
                    user=conversion.user,
                    action_type='make_purchase',
                    description=desc,
                    reference_id=str(order_ref),
                    points_override=points,
                )
                conversion.reward_transaction = new_tx
                conversion.reward_claimed = True
                conversion.save(update_fields=['reward_transaction', 'reward_claimed'])
                logger.info(f"Awarded {points} reward points to user {conversion.user.id} for conversion {conversion.id}")

        except Exception as e:
            logger.error(f"Error reconciling rewards for conversion {conversion.id}: {e}", exc_info=True)
