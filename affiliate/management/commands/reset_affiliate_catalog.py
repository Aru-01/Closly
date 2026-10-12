from django.core.management.base import BaseCommand
from django.db import transaction
from affiliate.models import (
    Brand,
    AffiliateProduct,
    ProductClick,
    ProductFavorite,
    Event,
    FeedImpressionsDaily,
    Conversion,
    CatalogSyncRun,
    ProductEmbedding,
)


class Command(BaseCommand):
    help = 'Safely and cleanly wipes all affiliate catalog products, brands, and tracking data in topological dependency order.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Bypass confirmation prompt and proceed with database reset',
        )
        parser.add_argument(
            '--keep-brands',
            action='store_true',
            help='Only wipe products and tracking data, preserving the Brand registry table',
        )

    def handle(self, *args, **options):
        confirmed = options.get('yes')
        keep_brands = options.get('keep_brands')

        if not confirmed:
            self.stdout.write(self.style.WARNING(
                "WARNING: This will permanently delete all Affiliate Products, Tracking Events, "
                + ("" if keep_brands else "Brands, ")
                + "and Sync History."
            ))
            answer = input("Are you sure you want to proceed? Type 'yes' to confirm: ")
            if answer.strip().lower() != 'yes':
                self.stdout.write(self.style.NOTICE("Operation aborted by user."))
                return

        self.stdout.write(self.style.WARNING("Starting transactional catalog purge..."))

        with transaction.atomic():
            # 1. Purge events, impressions, and embeddings (referencing AffiliateProduct)
            cnt_events, _ = Event.objects.all().delete()
            cnt_imps, _ = FeedImpressionsDaily.objects.all().delete()
            cnt_embeds, _ = ProductEmbedding.objects.all().delete()

            # 2. Purge PROTECTED foreign keys pointing to AffiliateProduct
            cnt_favs, _ = ProductFavorite.objects.all().delete()
            cnt_clicks, _ = ProductClick.objects.all().delete()

            # 3. Purge conversions and sync runs
            cnt_convs, _ = Conversion.objects.all().delete()
            cnt_runs, _ = CatalogSyncRun.objects.all().delete()

            # 4. Purge all AffiliateProduct rows
            cnt_prods, _ = AffiliateProduct.objects.all().delete()

            # 5. Purge Brands if requested
            cnt_brands = 0
            if not keep_brands:
                cnt_brands, _ = Brand.objects.all().delete()

        self.stdout.write(self.style.SUCCESS(
            "\nDatabase reset complete (Clean Slate achieved)!\n"
            f"  Events purged            : {cnt_events}\n"
            f"  Daily Impressions purged : {cnt_imps}\n"
            f"  Product Embeddings purged: {cnt_embeds}\n"
            f"  Favorites purged         : {cnt_favs}\n"
            f"  Clicks purged            : {cnt_clicks}\n"
            f"  Conversions purged       : {cnt_convs}\n"
            f"  Catalog Sync Runs purged : {cnt_runs}\n"
            f"  Affiliate Products purged: {cnt_prods}\n"
            + (f"  Brands purged            : {cnt_brands}" if not keep_brands else "  Brands preserved (keep-brands flag active)")
        ))
