from decouple import config

USE_JSON_LOGGING = config("USE_JSON_LOGGING", default=True, cast=bool)

# Logging Configuration (P-10)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'sensitive_data_filter': {
            '()': 'Config.logging_utils.SensitiveDataFilter',
        },
    },
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'json': {
            '()': 'Config.logging_utils.JSONFormatter',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'json' if USE_JSON_LOGGING else 'verbose',
            'filters': ['sensitive_data_filter'],
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'users': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'closet': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'affiliate': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'social': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'notifications': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
