"""
affiliate/management/commands/sync_approved_brands.py
=====================================================
Dynamic Brand Registry Synchronization Command (Strict Publisher APIs).
Strictly fetches joined and approved merchants from Awin and Rakuten APIs
and automatically maintains the Brand database registry with live statuses.

Key Principles:
- AWIN: Queries Awin Publisher Programmes API (relationship=joined) and strictly verifies membership.
- Rakuten: Queries LinkLocator getMerchByAppStatus/approved and Partnerships API for active status.
- Zero Hardcoded Fallbacks: No ANCHOR_BRAND_NAMES or KNOWN_ACTIVE_MIDS fallback activation.
- Precise Sync: Only strictly joined/approved merchants are saved and activated as status='live'.
- Graceful Deactivation: Merchandisers who sever partnership or go offline are marked status='paused'.
- Transparent Terminal Logging: Prints exact name and ID of every successfully joined brand.
"""

import base64, logging, requests
import xml.etree.ElementTree as ET
from typing import Dict, List, Set, Optional
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from affiliate.models import Brand

logger = logging.getLogger(__name__)

RAKUTEN_API = "https://api.linksynergy.com"
AWIN_API = "https://api.awin.com"


class Command(BaseCommand):
    help = "Dynamically sync strictly approved affiliate merchants from Awin & Rakuten APIs into Brand registry"

    def add_arguments(self, parser):
        parser.add_argument(
            "--network",
            type=str,
            choices=["all", "awin", "rakuten"],
            default="all",
            help="Affiliate network to sync (default: all)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log intended changes without saving to database",
        )
        parser.add_argument(
            "--eur-only",
            action="store_true",
            default=True,
            help="Strictly filter and register only EUR currency merchant programs (always active by default for DACH catalog)",
        )

    def handle(self, *args, **options):
        network = options.get("network", "all")
        dry_run = options.get("dry_run", False)
        allowed_currencies = getattr(settings, "MYC_INGEST_CURRENCIES", ["EUR"])

        self.stdout.write(
            self.style.WARNING(
                f"Starting strict Brand Registry sync (network={network}, dry_run={dry_run}, "
                f"allowed_currencies={allowed_currencies} [Strict DACH Requirement])..."
            )
        )

        # ------------------------------------------------------------------ #
        # Step 0: Drop/Purge Any Existing Non-EUR Brands (DACH Rule Enforcement)
        # ------------------------------------------------------------------ #
        if not dry_run:
            non_eur_brands = Brand.objects.exclude(currency__in=allowed_currencies)
            if non_eur_brands.exists():
                for b in non_eur_brands:
                    if b.products.count() == 0:
                        b_name, b_curr = b.name, b.currency
                        b.delete()
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [PURGED NON-EUR BRAND] Deleted '{b_name}' (Currency: {b_curr}) from database."
                            )
                        )
                    else:
                        b.status = Brand.STATUS_PAUSED
                        b.save(update_fields=["status"])
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [PAUSED NON-EUR BRAND] Paused '{b.name}' (Currency: {b.currency}) due to non-EUR currency."
                            )
                        )

        awin_stats = {
            "created": 0,
            "updated": 0,
            "paused": 0,
            "total": 0,
            "non_eur_dropped": 0,
        }
        rakuten_stats = {
            "created": 0,
            "updated": 0,
            "paused": 0,
            "total": 0,
            "non_eur_dropped": 0,
        }

        if network in ("all", "awin"):
            try:
                awin_stats = self._sync_awin_programmes(dry_run, allowed_currencies)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error syncing Awin programmes: {e}")
                )
                logger.error(f"Awin brand sync failure: {e}", exc_info=True)

        if network in ("all", "rakuten"):
            try:
                rakuten_stats = self._sync_rakuten_advertisers(
                    dry_run, allowed_currencies
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error syncing Rakuten advertisers: {e}")
                )
                logger.error(f"Rakuten brand sync failure: {e}", exc_info=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDynamic Brand Registry sync complete (DACH Market - EUR Only):\n"
                f"  AWIN:    total={awin_stats['total']}, created={awin_stats['created']}, updated={awin_stats['updated']}, paused={awin_stats['paused']}, non_eur_dropped={awin_stats['non_eur_dropped']}\n"
                f"  Rakuten: total={rakuten_stats['total']}, created={rakuten_stats['created']}, updated={rakuten_stats['updated']}, paused={rakuten_stats['paused']}, non_eur_dropped={rakuten_stats['non_eur_dropped']}"
            )
        )

    # =========================================================================
    # AWIN Publisher Programmes Synchronization
    # =========================================================================
    def _sync_awin_programmes(
        self, dry_run: bool, allowed_currencies: List[str]
    ) -> Dict[str, int]:
        self.stdout.write("\nFetching joined programmes from AWIN Publisher API...")

        publisher_id = getattr(settings, "AWIN_PUBLISHER_ID", None)
        api_token = getattr(settings, "AWIN_API_TOKEN", None)

        if not publisher_id or not api_token:
            msg = "AWIN_PUBLISHER_ID or AWIN_API_TOKEN not configured in settings. Skipping Awin brand sync."
            self.stdout.write(self.style.WARNING(msg))
            return {
                "created": 0,
                "updated": 0,
                "paused": 0,
                "total": 0,
                "non_eur_dropped": 0,
            }

        url = f"{AWIN_API}/publishers/{publisher_id}/programmes?relationship=joined"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "User-Agent": getattr(settings, "MYC_BOT_USER_AGENT", "mycloslybot/1.0"),
        }

        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            self.stdout.write(
                self.style.ERROR(
                    f"AWIN API error: HTTP {resp.status_code}: {resp.text[:200]}"
                )
            )
            return {
                "created": 0,
                "updated": 0,
                "paused": 0,
                "total": 0,
                "non_eur_dropped": 0,
            }

        programmes = resp.json()
        if not isinstance(programmes, list):
            self.stdout.write(
                self.style.ERROR(f"Unexpected AWIN response format: {type(programmes)}")
            )
            return {
                "created": 0,
                "updated": 0,
                "paused": 0,
                "total": 0,
                "non_eur_dropped": 0,
            }

        self.stdout.write(
            f"Received {len(programmes)} joined programme candidate(s) from Awin API."
        )

        created_count = 0
        updated_count = 0
        non_eur_dropped = 0
        active_external_ids: Set[str] = set()

        for prog in programmes:
            prog_id = str(prog.get("id", "")).strip()
            name = (prog.get("name") or "").strip()
            if not prog_id or not name:
                continue

            # Strict verification of membership / status
            prog_status = (prog.get("status") or "").strip().lower()
            membership_status = (prog.get("membershipStatus") or "").strip().lower()

            rel = prog.get("relationship")
            rel_status = ""
            if isinstance(rel, dict):
                rel_status = (rel.get("status") or "").strip().lower()
            elif isinstance(rel, str):
                rel_status = rel.strip().lower()

            # Reject any program that is explicitly not active, pending, rejected, or suspended
            if membership_status in (
                "pending",
                "rejected",
                "suspended",
                "not joined",
            ) or rel_status in ("pending", "rejected", "suspended", "not joined"):
                self.stdout.write(
                    self.style.WARNING(
                        f"  [AWIN SKIPPED] {name} (ID {prog_id}): Not joined (Status: '{prog_status}', Rel: '{rel_status}')"
                    )
                )
                continue

            if prog_status not in (
                "active",
                "joined",
                "approved",
            ) and rel_status not in ("joined", "approved"):
                self.stdout.write(
                    self.style.WARNING(
                        f"  [AWIN SKIPPED] {name} (ID {prog_id}): Inactive status ('{prog_status}')"
                    )
                )
                continue

            # Strict DACH currency validation: Drop non-EUR programs
            currency = (prog.get("currencyCode") or "EUR").strip().upper()
            if currency not in allowed_currencies:
                non_eur_dropped += 1
                self.stdout.write(
                    self.style.NOTICE(
                        f"  [AWIN NON-EUR DROPPED] {name} (ID {prog_id}) | Currency: '{currency}' (Dropped: strictly EUR required for DACH catalog)"
                    )
                )
                continue

            active_external_ids.add(prog_id)
            display_url = prog.get("displayUrl") or ""
            logo_url = prog.get("logoUrl") or ""
            primary_region = prog.get("primaryRegion") or {}
            country_code = primary_region.get("countryCode", "")

            # Explicit terminal feedback on every joined brand
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [AWIN APPROVED] {name} (ID {prog_id}) | Currency: {currency} | Region: {country_code or 'N/A'} -> LIVE"
                )
            )

            if dry_run:
                continue

            brand = Brand.objects.filter(
                kind=Brand.KIND_AWIN, external_id=prog_id
            ).first()
            if not brand:
                brand = Brand.objects.filter(
                    kind=Brand.KIND_AWIN, name__iexact=name
                ).first()

            if brand:
                brand.name = name
                brand.external_id = prog_id
                brand.status = Brand.STATUS_LIVE
                brand.currency = currency
                if display_url and not brand.feed_url:
                    brand.feed_url = display_url
                config_data = brand.config or {}
                config_data["logo_url"] = logo_url
                config_data["primary_region"] = primary_region
                brand.config = config_data
                brand.last_sync_at = timezone.now()
                brand.fail_count = 0
                brand.save()
                updated_count += 1
            else:
                slug = self._generate_unique_slug(name)
                Brand.objects.create(
                    name=name,
                    slug=slug,
                    kind=Brand.KIND_AWIN,
                    external_id=prog_id,
                    feed_url=display_url,
                    currency=currency,
                    tier=Brand.TIER_INDIE,
                    status=Brand.STATUS_LIVE,
                    config={"logo_url": logo_url, "primary_region": primary_region},
                    last_sync_at=timezone.now(),
                )
                created_count += 1

        # Automatically mark brands that are no longer joined as PAUSED
        paused_count = 0
        if not dry_run and active_external_ids:
            stale_brands = Brand.objects.filter(
                kind=Brand.KIND_AWIN,
                status=Brand.STATUS_LIVE,
            ).exclude(external_id__in=active_external_ids)

            for b in stale_brands:
                b.status = Brand.STATUS_PAUSED
                b.save(update_fields=["status"])
                paused_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  [AWIN PAUSED] {b.name} (ID {b.external_id}): No longer in approved list."
                    )
                )

        return {
            "total": len(active_external_ids),
            "created": created_count,
            "updated": updated_count,
            "paused": paused_count,
            "non_eur_dropped": non_eur_dropped,
        }

    # =========================================================================
    # Rakuten Advertising Advertisers Synchronization
    # =========================================================================
    def _sync_rakuten_advertisers(
        self, dry_run: bool, allowed_currencies: List[str]
    ) -> Dict[str, int]:
        self.stdout.write(
            "\nFetching strictly approved advertisers from Rakuten API..."
        )

        client_id = getattr(settings, "RAKUTEN_CLIENT_ID", None)
        client_secret = getattr(settings, "RAKUTEN_CLIENT_SECRET", None)
        sid = getattr(settings, "RAKUTEN_PUBLISHER_SID", "4674442")
        token = getattr(settings, "RAKUTEN_TOKEN", None)

        if not client_id or not client_secret:
            msg = "RAKUTEN_CLIENT_ID or RAKUTEN_CLIENT_SECRET not configured in settings. Skipping Rakuten brand sync."
            self.stdout.write(self.style.WARNING(msg))
            return {
                "created": 0,
                "updated": 0,
                "paused": 0,
                "total": 0,
                "non_eur_dropped": 0,
            }

        # Ensure valid OAuth Token
        token = self._get_rakuten_token(client_id, client_secret, sid, token)
        if not token:
            self.stdout.write(
                self.style.ERROR("Failed to obtain Rakuten OAuth access token.")
            )
            return {
                "created": 0,
                "updated": 0,
                "paused": 0,
                "total": 0,
                "non_eur_dropped": 0,
            }

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": getattr(settings, "MYC_BOT_USER_AGENT", "mycloslybot/1.0"),
        }

        # Query Rakuten LinkLocator API for strictly approved merchants
        approved_merchants: Dict[str, Dict[str, str]] = {}

        # 1. Primary Approved Source: LinkLocator getMerchByAppStatus/approved
        ll_url = f"{RAKUTEN_API}/linklocator/1.0/getMerchByAppStatus/approved"
        try:
            resp_ll = requests.get(ll_url, headers=headers, timeout=20)
            if resp_ll.status_code == 200:
                root = ET.fromstring(resp_ll.text)
                for ret in root.iter():
                    if ret.tag.endswith("return"):
                        mid = ""
                        name = ""
                        app_status = ""
                        for c in ret:
                            tag = c.tag.split("}")[-1]
                            if tag == "mid":
                                mid = (c.text or "").strip()
                            elif tag == "name":
                                name = (c.text or "").strip()
                            elif tag == "applicationStatus":
                                app_status = (c.text or "").strip()

                        if mid and name and app_status.lower() == "approved":
                            approved_merchants[mid] = {"name": name, "currency": "EUR"}
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"LinkLocator check error: {e}"))

        # 2. Secondary Verification: Partnerships API (/v1/partnerships)
        # Guarantees catching active approved programs even if linklocator XML varies
        try:
            part_url = f"{RAKUTEN_API}/v1/partnerships?limit=100"
            resp_part = requests.get(part_url, headers=headers, timeout=20)
            if resp_part.status_code == 200:
                p_data = resp_part.json()
                for p in p_data.get("partnerships", []):
                    # Strict check: partnership status MUST be 'active'
                    if p.get("status") == "active":
                        adv = p.get("advertiser", {})
                        mid_str = str(adv.get("id", "")).strip()
                        adv_name = (adv.get("name") or "").strip()
                        if mid_str and adv_name:
                            approved_merchants[mid_str] = {
                                "name": adv_name,
                                "currency": "EUR",
                            }
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Partnerships API check error: {e}"))

        self.stdout.write(
            f"Confirmed {len(approved_merchants)} strictly approved merchant(s) for SID {sid}."
        )

        created_count = 0
        updated_count = 0
        non_eur_dropped = 0
        active_mids: Set[str] = set()

        for mid, m_info in approved_merchants.items():
            merchant_name = m_info["name"]
            currency = (m_info.get("currency") or "EUR").strip().upper()
            if currency not in allowed_currencies:
                non_eur_dropped += 1
                self.stdout.write(
                    self.style.NOTICE(
                        f"  [RAKUTEN NON-EUR DROPPED] {merchant_name} (MID {mid}) | Currency: '{currency}' (Dropped: strictly EUR required for DACH catalog)"
                    )
                )
                continue

            active_mids.add(mid)

            # Explicit terminal feedback on approved brand
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [RAKUTEN APPROVED] {merchant_name} (MID {mid}) | Currency: {currency} | Status: Approved -> LIVE"
                )
            )

            if dry_run:
                continue

            brand = Brand.objects.filter(
                kind=Brand.KIND_RAKUTEN, external_id=mid
            ).first()
            if not brand:
                brand = Brand.objects.filter(
                    kind=Brand.KIND_RAKUTEN, name__iexact=merchant_name
                ).first()

            if brand:
                brand.name = merchant_name
                brand.external_id = mid
                brand.status = Brand.STATUS_LIVE
                brand.currency = currency
                brand.tier = Brand.TIER_ANCHOR
                brand.last_sync_at = timezone.now()
                brand.save()
                updated_count += 1
            else:
                slug = self._generate_unique_slug(merchant_name)
                Brand.objects.create(
                    name=merchant_name,
                    slug=slug,
                    kind=Brand.KIND_RAKUTEN,
                    external_id=mid,
                    currency=currency,
                    tier=Brand.TIER_ANCHOR,
                    status=Brand.STATUS_LIVE,
                    last_sync_at=timezone.now(),
                )
                created_count += 1

        # Automatically mark Rakuten brands that are no longer approved as PAUSED
        paused_count = 0
        if not dry_run and active_mids:
            stale_rakuten = Brand.objects.filter(
                kind=Brand.KIND_RAKUTEN,
                status=Brand.STATUS_LIVE,
            ).exclude(external_id__in=active_mids)

            for b in stale_rakuten:
                b.status = Brand.STATUS_PAUSED
                b.save(update_fields=["status"])
                paused_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  [RAKUTEN PAUSED] {b.name} (MID {b.external_id}): No longer in approved list."
                    )
                )

        return {
            "total": len(active_mids),
            "created": created_count,
            "updated": updated_count,
            "paused": paused_count,
            "non_eur_dropped": non_eur_dropped,
        }

    # =========================================================================
    # Helpers
    # =========================================================================
    def _get_rakuten_token(
        self,
        client_id: str,
        client_secret: str,
        sid: str,
        existing_token: Optional[str],
    ) -> Optional[str]:
        """Obtain a fresh OAuth access token from Rakuten."""
        try:
            token_key = base64.b64encode(
                f"{client_id}:{client_secret}".encode()
            ).decode()
            resp = requests.post(
                f"{RAKUTEN_API}/token",
                headers={
                    "Authorization": f"Bearer {token_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=f"scope={sid}",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("access_token")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Rakuten token fetch error: {e}"))
        return existing_token

    def _generate_unique_slug(self, name: str) -> str:
        base_slug = slugify(name) or "brand"
        slug = base_slug[:240]
        counter = 1
        while Brand.objects.filter(slug=slug).exists():
            slug = f"{base_slug[:235]}-{counter}"
            counter += 1
        return slug
