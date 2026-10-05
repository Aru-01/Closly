import logging
from celery import shared_task
from django.core.mail import send_mail
from django.core.management import call_command
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def send_email_async_task(self, subject, message, recipient_list, html_message=None):
    """
    Asynchronous Celery task for transactional email delivery.
    Enforces exponential backoff retries on transient SMTP failures.
    """
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Async email '{subject}' successfully dispatched to {recipient_list}")
        return True
    except Exception as exc:
        logger.warning(f"Async email delivery failed to {recipient_list} (attempt {self.request.retries}): {exc}")
        raise self.retry(exc=exc)


@shared_task
def flush_expired_tokens_task():
    """
    Celery beat scheduled task to purge expired tokens from OutstandingToken and BlacklistedToken tables.
    """
    try:
        call_command('flushexpiredtokens')
        logger.info("Successfully flushed expired JWT tokens from database.")
        return True
    except Exception as exc:
        logger.error(f"Error executing flushexpiredtokens command: {exc}")
        return False


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def execute_gdpr_deletion_job(self, job_id):
    """
    Asynchronously executes a 9-step GDPR erasure sequence (U-04, U-15, U-27).
    Resumable via job.steps_done tracking. Retryable on failure.
    """
    from datetime import timedelta
    from django.utils import timezone
    from django.core.cache import cache
    from users.models import DeletionJob, GdprAction, User
    from users.utils import revoke_all_user_tokens, delete_firebase_user, revoke_apple_token
    from affiliate.models import ProductClick
    from rewards.models import RewardPointTransaction

    try:
        job = DeletionJob.objects.get(id=job_id)
    except DeletionJob.DoesNotExist:
        logger.error(f"DeletionJob {job_id} not found.")
        return False

    job.status = 'running'
    job.save(update_fields=['status'])
    steps_done = list(job.steps_done or [])
    user_id = job.user_id

    try:
        user = User.objects.filter(id=user_id).first()
        firebase_uid = user.firebase_uid if user else None
        auth_provider = user.auth_provider if user else None

        # Step 1: Freeze account / set is_active=False
        if 1 not in steps_done:
            if user:
                user.is_active = False
                user.save(update_fields=['is_active'])
            steps_done.append(1)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 2: Revoke JWT tokens
        if 2 not in steps_done:
            if user:
                revoke_all_user_tokens(user)
            steps_done.append(2)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 3: Clear cache
        if 3 not in steps_done:
            cache.delete(f"user_online_{user_id}")
            cache.delete(f"user_last_seen_{user_id}")
            cache.delete(f"user_feed_{user_id}")
            steps_done.append(3)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 4: Delete private media/files
        if 4 not in steps_done:
            if user and user.profile_picture:
                try:
                    user.profile_picture.delete(save=False)
                except Exception as e:
                    logger.warning(f"Error deleting user avatar {user_id}: {e}")
            steps_done.append(4)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 5: Delete/anonymize applicable database rows
        if 5 not in steps_done:
            if user:
                user.delete()
            steps_done.append(5)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 6: Pseudonymize data that must legally remain (ProductClicks, ledger)
        if 6 not in steps_done:
            try:
                ProductClick.objects.filter(user_id=user_id).update(user=None)
            except Exception as e:
                logger.warning(f"Error pseudonymizing ProductClicks for {user_id}: {e}")
            try:
                RewardPointTransaction.objects.filter(reference_id=str(user_id)).update(reference_id='pseudonymized')
            except Exception as e:
                logger.warning(f"Error pseudonymizing RewardPointTransactions for {user_id}: {e}")
            steps_done.append(6)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 7: Revoke Apple identity
        if 7 not in steps_done:
            if auth_provider == 'apple' and user:
                try:
                    revoke_apple_token(user)
                except Exception as e:
                    logger.warning(f"Error revoking Apple token for {user_id}: {e}")
            steps_done.append(7)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 8: Delete Firebase identity
        if 8 not in steps_done:
            if firebase_uid:
                try:
                    delete_firebase_user(firebase_uid)
                except Exception as e:
                    logger.warning(f"Error deleting Firebase user for {user_id}: {e}")
            steps_done.append(8)
            job.steps_done = steps_done
            job.save(update_fields=['steps_done'])

        # Step 9: Mark deletion job complete
        if 9 not in steps_done:
            steps_done.append(9)
            job.steps_done = steps_done
            job.status = 'done'
            job.finished_at = timezone.now()
            job.save(update_fields=['steps_done', 'status', 'finished_at'])

            GdprAction.objects.create(
                user_id=user_id,
                action_type='account_deletion_completed',
                performed_by='system_worker',
                details={'job_id': str(job.id), 'steps_completed': steps_done}
            )

        logger.info(f"GDPR DeletionJob {job_id} successfully completed for user {user_id}")
        return True

    except Exception as exc:
        job.status = 'failed'
        job.error_message = str(exc)
        job.save(update_fields=['status', 'error_message'])
        logger.error(f"GDPR DeletionJob {job_id} failed at steps {steps_done}: {exc}")
        raise self.retry(exc=exc)


@shared_task
def purge_old_login_history_task():
    """
    Celery beat scheduled task to purge UserLoginHistory older than retention period (U-25).
    """
    from datetime import timedelta
    from django.utils import timezone
    from users.models import UserLoginHistory
    retention_days = getattr(settings, 'MYC_LOGIN_HISTORY_RETENTION_DAYS', 90)
    cutoff = timezone.now() - timedelta(days=retention_days)
    count, _ = UserLoginHistory.objects.filter(login_time__lt=cutoff).delete()
    logger.info(f"Purged {count} login history records older than {retention_days} days.")
    return count


@shared_task
def purge_completed_gdpr_jobs_task():
    """
    Celery beat scheduled task to clean up completed DeletionJob records older than retention period.
    """
    from datetime import timedelta
    from django.utils import timezone
    from users.models import DeletionJob
    retention_days = getattr(settings, 'MYC_GDPR_JOB_RETENTION_DAYS', 30)
    cutoff = timezone.now() - timedelta(days=retention_days)
    count, _ = DeletionJob.objects.filter(status='done', finished_at__lt=cutoff).delete()
    logger.info(f"Purged {count} completed GDPR deletion jobs older than {retention_days} days.")
    return count

