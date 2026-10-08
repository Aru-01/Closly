#!/usr/bin/env bash
# ==============================================================================
# MyClosly - Production PostgreSQL Disaster Recovery & Restore Runbook Script (P-02)
# ==============================================================================
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <backup_file_path> [--clean]"
    echo "Example: $0 /var/backups/myclosly/myclosly_20261008_030000.dump.enc"
    exit 1
fi

INPUT_FILE="$1"
CLEAN_FLAG="${2:-}"
DB_NAME="${DB_NAME:-Closly}"
DB_USER="${DB_USER:-postgres}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

if [ ! -f "${INPUT_FILE}" ]; then
    echo "ERROR: Backup file '${INPUT_FILE}' does not exist!" >&2
    exit 1
fi

TEMP_DUMP="/tmp/restore_$(date +%s).dump"
trap 'rm -f "${TEMP_DUMP}"' EXIT

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Preparing restore from: ${INPUT_FILE}..."

# 1. Decrypt if file is encrypted (.enc)
if [[ "${INPUT_FILE}" == *.enc ]]; then
    if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
        echo "ERROR: File is encrypted, but BACKUP_ENCRYPTION_KEY environment variable is not set!" >&2
        exit 1
    fi
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Decrypting with AES-256-CBC..."
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
        -in "${INPUT_FILE}" \
        -out "${TEMP_DUMP}" \
        -pass env:BACKUP_ENCRYPTION_KEY
    chmod 600 "${TEMP_DUMP}"
    TARGET_DUMP="${TEMP_DUMP}"
else
    TARGET_DUMP="${INPUT_FILE}"
fi

# 2. Verify archive header and table of contents
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Verifying dump TOC integrity..."
if ! pg_restore -l "${TARGET_DUMP}" > /dev/null 2>&1; then
    echo "ERROR: Dump verification failed! Archive is corrupted or decryption key was incorrect." >&2
    exit 2
fi

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Dump integrity verified."

# 3. Prompt or proceed with database restore
EXTRA_ARGS=()
if [ "${CLEAN_FLAG}" == "--clean" ]; then
    EXTRA_ARGS+=(--clean --if-exists)
fi

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Restoring into database '${DB_NAME}' on ${DB_HOST}:${DB_PORT}..."
pg_restore -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" --no-owner --no-privileges "${EXTRA_ARGS[@]}" "${TARGET_DUMP}"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Database restore completed successfully."
