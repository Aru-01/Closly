"""
Standardized machine-readable error codes and localization mappings.
Audit Reference: U-17 (German-First Error Code Contract).
"""

# Authentication & Credentials
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
UNDERAGE_NOT_ALLOWED = "UNDERAGE_NOT_ALLOWED"
EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
EMAIL_UNVERIFIED = "EMAIL_UNVERIFIED"

# Invites & Handshake
INVITE_REQUIRED = "INVITE_REQUIRED"
INVITE_INVALID = "INVITE_INVALID"
INVITE_ALREADY_USED = "INVITE_ALREADY_USED"
INVITE_EXPIRED = "INVITE_EXPIRED"

# Tokens & Sessions
TOKEN_INVALID = "TOKEN_INVALID"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
TOKEN_REVOKED = "TOKEN_REVOKED"
RESET_TOKEN_REQUIRED = "RESET_TOKEN_REQUIRED"
RESET_TOKEN_INVALID = "RESET_TOKEN_INVALID"

# OTP Codes
OTP_INVALID = "OTP_INVALID"
OTP_EXPIRED = "OTP_EXPIRED"
OTP_RATE_LIMITED = "OTP_RATE_LIMITED"

# Access & Rate Limiting
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
RATE_LIMITED = "RATE_LIMITED"
VALIDATION_ERROR = "VALIDATION_ERROR"
RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"

# German Localized Translations Dictionary for Client Applications
GERMAN_ERROR_TRANSLATIONS = {
    INVALID_CREDENTIALS: "Die angegebenen Anmeldedaten sind ungültig.",
    ACCOUNT_DISABLED: "Ihr Benutzerkonto ist deaktiviert.",
    ACCOUNT_LOCKED: "Das Konto wurde vorübergehend gesperrt. Bitte versuchen Sie es in 15 Minuten erneut.",
    UNDERAGE_NOT_ALLOWED: "Sie müssen mindestens 16 Jahre alt sein, um diesen Dienst zu nutzen.",
    EMAIL_ALREADY_EXISTS: "Eine Registrierung mit diesen Angaben konnte nicht abgeschlossen werden.",
    EMAIL_UNVERIFIED: "Bitte bestätigen Sie zuerst Ihre E-Mail-Adresse.",
    INVITE_REQUIRED: "Für die Registrierung ist ein gültiger Einladungscode erforderlich.",
    INVITE_INVALID: "Der angegebene Einladungscode ist ungültig.",
    INVITE_ALREADY_USED: "Dieser Einladungscode wurde bereits eingelöst.",
    INVITE_EXPIRED: "Dieser Einladungscode ist abgelaufen.",
    TOKEN_INVALID: "Das Authentifizierungs-Token ist ungültig oder abgelaufen.",
    TOKEN_EXPIRED: "Ihre Sitzung ist abgelaufen. Bitte melden Sie sich erneut an.",
    RESET_TOKEN_REQUIRED: "Ein gültiger Rücksetz-Token ist erforderlich.",
    RESET_TOKEN_INVALID: "Der Token zum Zurücksetzen des Passworts ist ungültig oder abgelaufen.",
    OTP_INVALID: "Der eingegebene Bestätigungscode ist ungültig.",
    OTP_EXPIRED: "Der Bestätigungscode ist abgelaufen. Bitte fordern Sie einen neuen an.",
    OTP_RATE_LIMITED: "Zu viele Versuche. Bitte warten Sie einen Moment.",
    UNAUTHORIZED: "Authentifizierung erforderlich.",
    FORBIDDEN: "Zugriff verweigert.",
    NOT_FOUND: "Die angeforderte Ressource wurde nicht gefunden.",
    RATE_LIMITED: "Anfragenlimit überschritten. Bitte versuchen Sie es später erneut.",
    VALIDATION_ERROR: "Die übermittelten Daten sind fehlerhaft.",
    RESOURCE_CONFLICT: "Ein Datensatz mit diesen Daten existiert bereits.",
    INTERNAL_SERVER_ERROR: "Ein unerwarteter Serverfehler ist aufgetreten.",
}

def get_localized_message(error_code, lang="de", default_message=""):
    """
    Returns the localized message for a given error code.
    Defaults to German (de), falls back to English default_message.
    """
    if lang == "de":
        return GERMAN_ERROR_TRANSLATIONS.get(error_code, default_message or "Ein Fehler ist aufgetreten.")
    return default_message
