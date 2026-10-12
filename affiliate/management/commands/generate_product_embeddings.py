"""
affiliate/management/commands/generate_product_embeddings.py
============================================================
Management command to process catalog products into 768-dimensional
FashionSigLIP vector embeddings using pgvector.
"""
from django.core.management.base import BaseCommand
from affiliate.services.embedding_service import batch_generate_product_embeddings
from affiliate.models import ProductEmbedding, AffiliateProduct


class Command(BaseCommand):
    help = 'Generate 768-dimensional FashionSigLIP vector embeddings for catalog products'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=200,
            help='Maximum number of products to process in this run (default: 200)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Recompute embeddings even if product already has an existing vector',
        )

    def handle(self, *args, **options):
        limit = options.get('limit', 200)
        force = options.get('force', False)

        total_active = AffiliateProduct.objects.filter(is_active=True, price__gt=0).count()
        total_embedded = ProductEmbedding.objects.count()

        self.stdout.write(self.style.WARNING(
            f"Starting FashionSigLIP vector embedding generation (limit={limit}, force={force})...\n"
            f"  Catalog Status: {total_embedded}/{total_active} products currently embedded in pgvector."
        ))

        processed = batch_generate_product_embeddings(limit=limit, force=force)

        new_total_embedded = ProductEmbedding.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Successfully generated {processed} 768-dim vector embeddings!\n"
            f"  Total embedded products in DB: {new_total_embedded}/{total_active}"
        ))
