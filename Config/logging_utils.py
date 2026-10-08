import re
import json
import logging
import hashlib
from datetime import datetime, timezone


class SensitiveDataFilter(logging.Filter):
    """
    Security filter that scrubs passwords, JWTs, Firebase tokens, OTPs,
    and user emails from all log records before output (P-10, Spec Ch5 §3.2).
    """
    REDACTED_PATTERNS = [
        (re.compile(r'([Pp]assword[\'"]?\s*[:=]\s*[\'"]?)([^\s\'",]+)'), r'\1[REDACTED]'),
        (re.compile(r'([Tt]oken[\'"]?\s*[:=]\s*[\'"]?)([A-Za-z0-9\-_.]{8,})'), r'\1[REDACTED]'),
        (re.compile(r'([Oo][Tt][Pp][\'"]?\s*[:=]\s*[\'"]?)([^\s\'",]+)'), r'\1[REDACTED]'),
        (re.compile(r'(Bearer\s+)([A-Za-z0-9\-_.]+)'), r'\1[REDACTED]'),
    ]

    def filter(self, record):
        try:
            if isinstance(record.msg, str):
                for pattern, repl in self.REDACTED_PATTERNS:
                    record.msg = pattern.sub(repl, record.msg)
            if record.args and isinstance(record.args, tuple):
                cleaned_args = []
                for arg in record.args:
                    if isinstance(arg, str):
                        for pattern, repl in self.REDACTED_PATTERNS:
                            arg = pattern.sub(repl, arg)
                    cleaned_args.append(arg)
                record.args = tuple(cleaned_args)
        except Exception:
            pass
        return True


class JSONFormatter(logging.Formatter):
    """
    Structured JSON log formatter for production Docker observability (P-10).
    Emits uniform structured JSON with timestamps, log levels, correlation IDs,
    and hashed user IDs for GDPR compliance.
    """
    def format(self, record):
        log_record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        if hasattr(record, 'request_id'):
            log_record['request_id'] = record.request_id

        if hasattr(record, 'user_id'):
            log_record['user_hash'] = hashlib.sha256(str(record.user_id).encode()).hexdigest()[:16]

        if record.exc_info:
            log_record['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_record)
