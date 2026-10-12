"""
affiliate/management/commands/reconcile_rakuten_transactions.py
==============================================================
Automated Rakuten Advertising Transactions Reconciliation Command.
Calls the Rakuten Publisher Transactions API to query recent conversions,
reconciles user attribution via the `u1` SubID token (matching ProductClick.click_ref),
and updates the double-entry rewards ledger (transitioning PENDING awards to AVAILABLE).
"""
import base64, logging, uuid, requests
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from affiliate.models import Conversion, ProductClick, Brand
from rewards.models import PointAward
from rewards.services import transition_award, award_points

logger = logging.getLogger(__name__)

RAKUTEN_API_BASE = "https://api.linksynergy.com"


class Command(BaseCommand):
    help = 'Reconciles conversions from Rakuten Publisher Transactions API and updates rewards ledger'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days in the past to query transactions for (default: 30)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Log intended reconciliations without persisting DB changes',
        )

    def _get_access_token(self):
        """Retrieves or refreshes Rakuten OAuth bearer token."""
        token = getattr(settings, 'RAKUTEN_TOKEN', None)
        if token:
            return token

        client_id = getattr(settings, 'RAKUTEN_CLIENT_ID', None)
        client_secret = getattr(settings, 'RAKUTEN_CLIENT_SECRET', None)
        sid = getattr(settings, 'RAKUTEN_PUBLISHER_SID', '4674442')

        if not client_id or not client_secret:
            return None

        try:
            token_key = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            resp = requests.post(
                f"{RAKUTEN_API_BASE}/token",
                headers={
                    'Authorization': f'Bearer {token_key}',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                data=f'scope={sid}',
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get('access_token')
        except Exception as e:
            logger.warning(f"Failed to refresh Rakuten OAuth token: {e}")
            return None

        return None

    def handle(self, *args, **options):
        days = options.get('days', 30)
        dry_run = options.get('dry_run', False)

        token = self._get_access_token()
        if not token:
            msg = "RAKUTEN_TOKEN / OAuth credentials not configured. Skipping Rakuten transaction reconciliation."
            self.stdout.write(self.style.WARNING(msg))
            return

        # Rakuten limits the real-time Events API to strictly within 30 days of the request time
        clamped_days = min(days, 29)
        end_date = timezone.now()
        start_date = end_date - timedelta(days=clamped_days)
        start_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_date.strftime("%Y-%m-%d %H:%M:%S")

        url = f"{RAKUTEN_API_BASE}/events/1.0/transactions"
        params = {
            'process_date_start': start_str,
            'process_date_end': end_str,
        }
        headers = {
            'Authorization': f"Bearer {token}",
            'Accept': 'application/json',
            'User-Agent': getattr(settings, 'MYC_BOT_USER_AGENT', 'mycloslybot/1.0'),
        }

        self.stdout.write(self.style.WARNING(
            f"Querying Rakuten Transactions API ({start_str} to {end_str})..."
        ))

        transactions = []
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=45)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, list):
                    transactions = body
                elif isinstance(body, dict):
                    transactions = body.get('transactions') or body.get('events') or []
            else:
                self.stdout.write(self.style.ERROR(
                    f"Rakuten API returned HTTP {resp.status_code}: {resp.text[:300]}"
                ))
                return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch Rakuten transactions: {e}"))
            logger.error(f"Rakuten transactions fetch failed: {e}", exc_info=True)
            return

        self.stdout.write(f"Received {len(transactions)} transaction(s) from Rakuten API.")

        created_count = 0
        updated_count = 0
        reconciled_rewards = 0

        for tx in transactions:
            tx_id = str(tx.get('order_id') or tx.get('id') or tx.get('transaction_id') or '').strip()
            if not tx_id:
                continue

            # In Rakuten attribution, u1 carries the click_ref token
            u1_val = str(tx.get('u1') or tx.get('member_id') or tx.get('click_ref') or '').strip()
            raw_status = str(tx.get('status') or tx.get('process_status') or 'pending').strip().lower()
            is_canceled = tx.get('is_canceled', False) or tx.get('is_event_canceled', False)

            if is_canceled or raw_status in ('canceled', 'cancelled', 'deleted', 'declined', 'void'):
                status_val = Conversion.STATUS_DECLINED
            elif raw_status in ('approved', 'completed', 'paid', 'active'):
                status_val = Conversion.STATUS_APPROVED
            else:
                status_val = Conversion.STATUS_PENDING

            adv_id = str(tx.get('advertiser_id') or tx.get('mid') or '').strip()
            sale_amount = float(tx.get('sales') or tx.get('sale_amount') or 0.0)
            commission_amount = float(tx.get('commissions') or tx.get('commission_amount') or 0.0)
            currency = str(tx.get('currency') or 'EUR').strip().upper()
            order_ref = str(tx.get('order_id') or tx_id)
            tx_date_str = tx.get('transaction_date') or tx.get('process_date')
            tx_date = parse_datetime(tx_date_str) if tx_date_str else timezone.now()

            # Attempt attribution join via u1 (ProductClick.click_ref)
            linked_user = None
            linked_product = None
            linked_brand = None
            click_uuid = None

            if u1_val:
                try:
                    if '-' in u1_val:
                        click_uuid = uuid.UUID(u1_val)
                    else:
                        click_uuid = uuid.UUID(hex=u1_val)

                    pclick = ProductClick.objects.filter(click_ref=click_uuid).select_related(
                        'user', 'product', 'product__brand_ref'
                    ).first()
                    if pclick:
                        linked_user = pclick.user
                        linked_product = pclick.product
                        if linked_product and linked_product.brand_ref:
                            linked_brand = linked_product.brand_ref
                except (ValueError, TypeError):
                    pass

            if not linked_brand and adv_id:
                linked_brand = Brand.objects.filter(kind=Brand.KIND_RAKUTEN, external_id=adv_id).first()

            if dry_run:
                self.stdout.write(f"  [DRY RUN] Rakuten Tx #{tx_id}: status={status_val}, amount={sale_amount} {currency}, user={linked_user}")
                continue

            conv, created = Conversion.objects.update_or_create(
                source=Conversion.SOURCE_RAKUTEN,
                conversion_id=tx_id,
                defaults={
                    'click_ref': click_uuid,
                    'user': linked_user,
                    'product': linked_product,
                    'brand': linked_brand,
                    'advertiser_id': adv_id,
                    'order_reference': order_ref,
                    'status': status_val,
                    'sale_amount': sale_amount,
                    'commission_amount': commission_amount,
                    'currency': currency,
                    'transaction_date': tx_date,
                    'raw_payload': tx,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            # Reconcile Point Awards in the double-entry ledger
            if conv.user and not conv.reward_claimed:
                if status_val == Conversion.STATUS_APPROVED:
                    # Check for pending award
                    pending_award = PointAward.objects.filter(
                        user=conv.user,
                        award_type='purchase_rakuten',
                        conversion_reference=order_ref,
                    ).first()

                    if pending_award and pending_award.state in ('PENDING', 'RESERVED'):
                        transition_award(
                            award=pending_award,
                            to_state='AVAILABLE',
                            reason=f"Rakuten verified approved sale #{tx_id}",
                            idempotency_key=f"rakuten_reconcile_avail:{tx_id}"
                        )
                        conv.reward_claimed = True
                        conv.save(update_fields=['reward_claimed'])
                        reconciled_rewards += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"  [RECONCILED] Award #{pending_award.id} -> AVAILABLE for {conv.user.email}"
                        ))
                    elif getattr(settings, 'MYC_AUTO_AWARD_PURCHASE_POINTS', True):
                        points = getattr(settings, 'MYC_PURCHASE_AWARD_POINTS', 200)
                        brand_name = linked_brand.name if linked_brand else "Rakuten Partner"
                        new_tx = award_points(
                            user=conv.user,
                            action_type='make_purchase',
                            description=f"Verified Purchase at {brand_name} (Order: {order_ref})",
                            reference_id=str(order_ref),
                            points_override=points,
                        )
                        conv.reward_transaction = new_tx
                        conv.reward_claimed = True
                        conv.save(update_fields=['reward_transaction', 'reward_claimed'])
                        reconciled_rewards += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"  [AWARDED] +{points} pts to {conv.user.email} for approved Rakuten order #{order_ref}"
                        ))

                elif status_val == Conversion.STATUS_DECLINED:
                    pending_award = PointAward.objects.filter(
                        user=conv.user,
                        award_type='purchase_rakuten',
                        conversion_reference=order_ref,
                    ).first()
                    if pending_award and pending_award.state not in ('VOID', 'CLAWED_BACK'):
                        transition_award(
                            award=pending_award,
                            to_state='VOID',
                            reason=f"Rakuten order #{tx_id} returned or cancelled",
                            idempotency_key=f"rakuten_reconcile_void:{tx_id}"
                        )
                        self.stdout.write(self.style.WARNING(
                            f"  [VOIDED] Award #{pending_award.id} cancelled due to Rakuten decline for {conv.user.email}"
                        ))

        self.stdout.write(self.style.SUCCESS(
            f"\nRakuten Reconciliation Complete:\n"
            f"  Total API Transactions : {len(transactions)}\n"
            f"  Conversions Created    : {created_count}\n"
            f"  Conversions Updated    : {updated_count}\n"
            f"  Rewards Reconciled     : {reconciled_rewards}"
        ))
