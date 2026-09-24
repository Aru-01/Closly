from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from notifications.models import Notification


class Command(BaseCommand):
    help = 'Permanently delete notifications older than 60 days (or specified --days).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=60,
            help='Number of days after which notifications should be deleted (default: 60)'
        )

    def handle(self, *args, **options):
        days = options['days']
        cutoff_date = timezone.now() - timedelta(days=days)
        deleted_count, _ = Notification.objects.filter(created_at__lt=cutoff_date).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully deleted {deleted_count} notification(s) older than {days} days (cutoff: {cutoff_date})."
            )
        )
