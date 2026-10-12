"""
affiliate/views/event_views.py
Re-exports EventBatchView from telemetry_views.py for backward compatibility.
"""

from .telemetry_views import EventBatchView

__all__ = [
    'EventBatchView',
]
