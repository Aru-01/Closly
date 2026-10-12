import logging
from typing import List, Dict, Any, Tuple
from django.utils import timezone
from zoneinfo import ZoneInfo

from affiliate.models import AffiliateProduct, Event, ProductFavorite
from affiliate.services.vector_engine import update_user_taste_vector

logger = logging.getLogger(__name__)
BERLIN_TZ = ZoneInfo("Europe/Berlin")


def process_swipe_interactions(
    user,
    raw_swipes: List[Dict[str, Any]],
) -> Tuple[int, bool, int]:
    """
    Processes swipe interactions from the Style Sprint deck.

    BULK DATABASE OPTIMIZATION:
    - Resolves all referenced products in a SINGLE query with select_related('brand_ref').
    - Performs Event logging in a SINGLE bulk_create query.
    - Performs ProductFavorite inserts in a SINGLE bulk_create(ignore_conflicts=True) query.
    - Updates user StyleProfile taste vectors incrementally.
    - Awards completion points when the daily 10-card goal is reached.

    Returns:
        (processed_count, is_completed, points_awarded)
    """
    if not user or not user.is_authenticated or not raw_swipes:
        return 0, False, 0

    today_berlin = timezone.now().astimezone(BERLIN_TZ).date()

    # Collect distinct product IDs
    product_ids = []
    for item in raw_swipes:
        pid = item.get('product_id')
        if pid:
            try:
                product_ids.append(int(pid))
            except (ValueError, TypeError):
                continue

    if not product_ids:
        return 0, False, 0

    # Bulk query products with select_related to eliminate N+1 queries
    products_by_id = {
        p.id: p
        for p in AffiliateProduct.objects.filter(id__in=product_ids).select_related('brand_ref')
    }

    events_to_create = []
    favorites_to_create = []
    taste_updates = []

    for item in raw_swipes:
        try:
            p_id = int(item.get('product_id'))
        except (ValueError, TypeError):
            continue

        product = products_by_id.get(p_id)
        if not product:
            continue

        act = str(item.get('action') or item.get('direction') or 'like').strip().lower()

        if act in ('right', 'like', 'love'):
            event_type = Event.TYPE_LIKE
            event_act = 'like'
        elif act in ('left', 'skip', 'dislike'):
            event_type = Event.TYPE_SKIP
            event_act = 'skip'
        elif act in ('up', 'save', 'favorite'):
            event_type = Event.TYPE_SAVE
            event_act = 'save'
            favorites_to_create.append(ProductFavorite(user=user, product=product))
        else:
            event_type = Event.TYPE_LIKE
            event_act = 'like'

        events_to_create.append(
            Event(
                user=user,
                product=product,
                event_class=Event.CLASS_INTERACTION,
                event_type=event_type,
                source='sprint',
                berlin_day=today_berlin,
            )
        )
        taste_updates.append((product.id, event_act))

    # BULK OPERATION 1: Bulk insert all events
    if events_to_create:
        Event.objects.bulk_create(events_to_create)

    # BULK OPERATION 2: Bulk insert all favorites with conflict ignore
    if favorites_to_create:
        ProductFavorite.objects.bulk_create(favorites_to_create, ignore_conflicts=True)

    # Update StyleProfile taste vector with EMA for each interaction
    for pid, event_act in taste_updates:
        try:
            update_user_taste_vector(user, pid, event_act)
        except Exception as e:
            logger.warning(f"Error updating taste vector for product {pid}: {e}")

    processed_count = len(events_to_create)

    # Check total unique cards swiped today in Berlin timezone
    current_swiped = Event.objects.filter(
        user=user,
        source='sprint',
        berlin_day=today_berlin,
    ).values('product_id').distinct().count()

    is_completed = current_swiped >= 10
    points_awarded = 0

    # Award completion points if user reached 10 cards today
    if is_completed:
        try:
            from rewards.models import PointAward
            already_awarded = PointAward.objects.filter(
                user=user,
                award_type='weekly_goal',
                created_at__date=today_berlin,
            ).exists()
            if not already_awarded:
                PointAward.objects.create(
                    user=user,
                    award_type='weekly_goal',
                    points_original=50,
                    points_current=50,
                    state='AVAILABLE',
                )
                points_awarded = 50
        except Exception as e:
            logger.warning(f"Error awarding Style Sprint completion points: {e}")

    return processed_count, current_swiped, is_completed, points_awarded
