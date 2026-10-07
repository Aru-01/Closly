class AIScannerError(Exception):
    """Base exception for Closet AI Scanner module."""
    pass


class AIServiceUnavailableError(AIScannerError):
    """Raised when the AI scanning service or upstream vision LLM is unavailable."""
    pass


class AIDailyLimitExceededError(AIScannerError):
    """Raised when a user exceeds their allowed daily scan quota."""
    pass


class AIImageValidationError(AIScannerError):
    """Raised when an uploaded garment image fails validation or corruption checks."""
    pass
