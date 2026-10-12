"""
affiliate/management/commands/reconcile_awin_transactions.py
===========================================================
Automated AWIN Transactions Reconciliation Command (Spec Ch4 §1.4 & Acceptance #10).
Calls the Awin Publisher Transactions API to query recent conversions,
reconciles user attribution via UUID clickrefs, and updates the double-entry
rewards ledger (transitioning PENDING awards to CONFIRMED / AVAILABLE).
"""

import logging, uuid, requests
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from affiliate.models import Conversion, ProductClick, Brand
from rewards.models import PointAward
from rewards.services import transition_award, award_points

logger = logging.getLogger(__name__)

AWIN_API_URL = "https://api.awin.com"


class Command(BaseCommand):
    help = "Reconciles conversions from Awin Publisher Transactions API and updates rewards ledger"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Number of days in the past to query transactions for (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log intended reconciliations without persisting DB changes",
        )

    def handle(self, *args, **options):
        days = options.get("days", 30)
        dry_run = options.get("dry_run", False)

        publisher_id = getattr(settings, "AWIN_PUBLISHER_ID", None)
        api_token = getattr(settings, "AWIN_API_TOKEN", None)

        if not publisher_id or not api_token:
            msg = "AWIN_PUBLISHER_ID or AWIN_API_TOKEN not configured. Skipping transaction reconciliation."
            self.stdout.write(self.style.WARNING(msg))
            return

        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        start_str = start_date.strftime("%Y-%m-%dT00:00:00")
        end_str = end_date.strftime("%Y-%m-%dT23:59:59")

        url = f"{AWIN_API_URL}/publishers/{publisher_id}/transactions/?startDate={start_str}&endDate={end_str}&timezone=UTC"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "User-Agent": getattr(settings, "MYC_BOT_USER_AGENT", "mycloslybot/1.0"),
        }

        self.stdout.write(
            self.style.WARNING(
                f"Querying AWIN Transactions API ({start_str} to {end_str})..."
            )
        )

        try:
            resp = requests.get(url, headers=headers, timeout=45)
            if resp.status_code != 200:
                self.stdout.write(
                    self.style.ERROR(
                        f"AWIN API returned HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                )
                return
            transactions = resp.json()
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to fetch Awin transactions: {e}")
            )
            logger.error(f"Awin transactions fetch failed: {e}", exc_info=True)
            return

        if not isinstance(transactions, list):
            self.stdout.write(
                self.style.ERROR(
                    f"Unexpected AWIN response format: {type(transactions)}"
                )
            )
            return

        self.stdout.write(f"Received {len(transactions)} transaction(s) from AWIN API.")

        created_count = 0
        updated_count = 0
        reconciled_rewards = 0

        for tx in transactions:
            tx_id = str(tx.get("id", "")).strip()
            if not tx_id:
                continue

            click_refs = tx.get("clickRefs") or {}
            click_ref_val = click_refs.get("clickRef") or tx.get("clickRef") or ""
            raw_status = (tx.get("commissionStatus") or "pending").strip().lower()

            status_map = {
                "approved": Conversion.STATUS_APPROVED,
                "pending": Conversion.STATUS_PENDING,
                "deleted": Conversion.STATUS_DECLINED,
                "declined": Conversion.STATUS_DECLINED,
            }
            status_val = status_map.get(raw_status, Conversion.STATUS_PENDING)

            adv_id = str(tx.get("advertiserId", ""))
            sale_obj = tx.get("saleAmount") or {}
            comm_obj = tx.get("commissionAmount") or {}

            sale_amount = float(sale_obj.get("amount") or 0.0)
            commission_amount = float(comm_obj.get("amount") or 0.0)
            currency = sale_obj.get("currency") or comm_obj.get("currency") or "EUR"
            order_ref = str(tx.get("orderRef") or tx_id)
            tx_date_str = tx.get("transactionDate")
            tx_date = parse_datetime(tx_date_str) if tx_date_str else timezone.now()

            # Attempt attribution join via click_ref UUID
            linked_user = None
            linked_product = None
            linked_brand = None
            click_uuid = None

            if click_ref_val:
                try:
                    click_uuid = uuid.UUID(str(click_ref_val).strip())
                    pclick = (
                        ProductClick.objects.filter(click_ref=click_uuid)
                        .select_related("user", "product", "product__brand_ref")
                        .first()
                    )
                    if pclick:
                        linked_user = pclick.user
                        linked_product = pclick.product
                        if linked_product and linked_product.brand_ref:
                            linked_brand = linked_product.brand_ref
                except (ValueError, TypeError):
                    pass

            if not linked_brand and adv_id:
                linked_brand = Brand.objects.filter(
                    kind=Brand.KIND_AWIN, external_id=adv_id
                ).first()

            if dry_run:
                self.stdout.write(
                    f"  [DRY RUN] Tx #{tx_id}: status={status_val}, amount={sale_amount} {currency}, user={linked_user}"
                )
                continue

            conv, created = Conversion.objects.update_or_create(
                source=Conversion.SOURCE_AWIN,
                conversion_id=tx_id,
                defaults={
                    "click_ref": click_uuid,
                    "user": linked_user,
                    "product": linked_product,
                    "brand": linked_brand,
                    "advertiser_id": adv_id,
                    "order_reference": order_ref,
                    "status": status_val,
                    "sale_amount": sale_amount,
                    "commission_amount": commission_amount,
                    "currency": currency,
                    "transaction_date": tx_date,
                    "raw_payload": tx,
                },
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
                        award_type="purchase_awin",
                        conversion_reference=order_ref,
                    ).first()

                    if pending_award and pending_award.state in ("PENDING", "RESERVED"):
                        transition_award(
                            award=pending_award,
                            to_state="AVAILABLE",
                            reason=f"AWIN verified approved sale #{tx_id}",
                            idempotency_key=f"awin_reconcile_avail:{tx_id}",
                        )
                        conv.reward_claimed = True
                        conv.save(update_fields=["reward_claimed"])
                        reconciled_rewards += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [RECONCILED] Award #{pending_award.id} -> AVAILABLE for {conv.user.email}"
                            )
                        )
                    elif getattr(settings, "MYC_AUTO_AWARD_PURCHASE_POINTS", True):
                        points = getattr(settings, "MYC_PURCHASE_AWARD_POINTS", 200)
                        brand_name = (
                            linked_brand.name if linked_brand else "Affiliate Partner"
                        )
                        new_tx = award_points(
                            user=conv.user,
                            action_type="make_purchase",
                            description=f"Verified Purchase at {brand_name} (Order: {order_ref})",
                            reference_id=str(order_ref),
                            points_override=points,
                        )
                        conv.reward_transaction = new_tx
                        conv.reward_claimed = True
                        conv.save(
                            update_fields=["reward_transaction", "reward_claimed"]
                        )
                        reconciled_rewards += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [AWARDED] +{points} pts to {conv.user.email} for approved AWIN order #{order_ref}"
                            )
                        )

                elif status_val == Conversion.STATUS_DECLINED:
                    pending_award = PointAward.objects.filter(
                        user=conv.user,
                        award_type="purchase_awin",
                        conversion_reference=order_ref,
                    ).first()
                    if pending_award and pending_award.state not in (
                        "VOID",
                        "CLAWED_BACK",
                    ):
                        transition_award(
                            award=pending_award,
                            to_state="VOID",
                            reason=f"AWIN order #{tx_id} returned or cancelled",
                            idempotency_key=f"awin_reconcile_void:{tx_id}",
                        )
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [VOIDED] Award #{pending_award.id} cancelled due to AWIN decline for {conv.user.email}"
                            )
                        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nAWIN Reconciliation Complete:\n"
                f"  Total API Transactions : {len(transactions)}\n"
                f"  Conversions Created    : {created_count}\n"
                f"  Conversions Updated    : {updated_count}\n"
                f"  Rewards Reconciled     : {reconciled_rewards}"
            )
        )
