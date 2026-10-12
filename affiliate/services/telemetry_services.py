import logging
from typing import List, Dict, Any
from affiliate.tasks import ingest_event_batch_task

logger = logging.getLogger(__name__)


def queue_event_batch(user, events_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sanitizes and asynchronously queues behavioral event batches for background ingestion.
    """
    clean_events = []
    for item in events_data:
        entry = dict(item)
        if entry.get('client_ts') and hasattr(entry['client_ts'], 'isoformat'):
            entry['client_ts'] = entry['client_ts'].isoformat()
        clean_events.append(entry)

    # Offload DB write & taste vector math to background Celery worker
    ingest_event_batch_task.delay(str(user.id), clean_events)

    return {
        'queued_count': len(events_data),
        'ingested_count': len(events_data),
        'status': 'processing',
    }
