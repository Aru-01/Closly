# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'users': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'closet': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'affiliate': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'social': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'notifications': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
