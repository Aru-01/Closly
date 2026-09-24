"""
Django settings package for Closly project.
Modularized into clean, domain-specific setting files:
- base: Core Django, DB, Auth, Templates, Cache, Third-party configurations
- celery: Redis, Channels, Celery broker, Beat tasks
- drf_swagger: DRF, CORS, SimpleJWT, Spectacular OpenAPI specs
- unfold: Django Unfold luxury admin theme and dashboard
- logging: Centralized structured logging configuration
"""

from .base import *
from .celery import *
from .drf_swagger import *
from .unfold import *
from .logging import *
