#!/usr/bin/env bash
# ==============================================================================
# MyClosly - Production PostgreSQL Automated Encrypted Backup Script (P-02)
# Retention: 35 Days (Spec Ch5 §1.3)
# ==============================================================================
set -euo pipefail

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="${BACKUP_DIR:-/var/backups/myclosly}"
DB_NAME="${DB_NAME:-Closly}"
DB_USER="${DB_USER:-postgres}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
RETENTION_DAYS=35

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

RAW_DUMP="${BACKUP_DIR}/myclosly_${TIMESTAMP}.dump"
ENCRYPTED_DUMP="${BACKUP_DIR}/myclosly_${TIMESTAMP}.dump.enc"
SHA_FILE="${BACKUP_DIR}/myclosly_${TIMESTAMP}.sha256"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting logical PostgreSQL backup for ${DB_NAME}..."

# 1. Produce custom-format compressed dump
if ! pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -Fc -Z 9 -f "${RAW_DUMP}"; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: pg_dump failed! Check database connectivity." >&2
    rm -f "${RAW_DUMP}"
    exit 1
fi

# 2. Verify dump integrity via pg_restore listing
if ! pg_restore -l "${RAW_DUMP}" > /dev/null 2>&1; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: Backup integrity check failed! Corrupt dump produced." >&2
    rm -f "${RAW_DUMP}"
    exit 2
fi

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Dump integrity verified successfully."

# 3. Generate SHA-256 checksum of raw dump
sha256sum "${RAW_DUMP}" > "${SHA_FILE}"

# 4. Encrypt with AES-256-CBC using PBKDF2
if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] WARNING: BACKUP_ENCRYPTION_KEY unset; storing unencrypted with strict permissions."
    chmod 600 "${RAW_DUMP}"
else
    openssl enc -aes-256-cbc -salt -pbkdf2 -iter 100000 \
        -in "${RAW_DUMP}" \
        -out "${ENCRYPTED_DUMP}" \
        -pass env:BACKUP_ENCRYPTION_KEY
    chmod 600 "${ENCRYPTED_DUMP}"
    rm -f "${RAW_DUMP}"
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Encrypted backup generated: ${ENCRYPTED_DUMP}"
fi

# 5. Off-site sync if storage remote configured (Hetzner Storage Box / S3 / Bunny)
if command -v rclone >/dev/null 2>&1 && [ -n "${RCLONE_REMOTE:-}" ]; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Shipping backup to off-machine remote: ${RCLONE_REMOTE}..."
    rclone copy "${BACKUP_DIR}" "${RCLONE_REMOTE}:myclosly-backups" --include "myclosly_${TIMESTAMP}.*"
fi

# 6. Enforce 35-day retention policy (GDPR & Business Continuity)
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Enforcing ${RETENTION_DAYS}-day retention policy..."
find "${BACKUP_DIR}" -type f \( -name "myclosly_*.dump*" -o -name "myclosly_*.sha256" \) -mtime +${RETENTION_DAYS} -delete

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Backup cycle complete. Retention verified."
