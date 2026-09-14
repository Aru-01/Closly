"""
Backward-compatibility proxy for notifications service.
In-app notifications have been moved to the dedicated `notifications` Django app.
"""
from notifications.services import create_notification

__all__ = ['create_notification']
