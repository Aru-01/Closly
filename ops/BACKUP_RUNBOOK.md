# MyClosly - Database Backup & Disaster Recovery Runbook (P-02)

## 1. Overview & SLA
Per MyClosly Specification Ch5 §1.3 and GDPR Article 32:
- **Backup Frequency**: Nightly logical dump via `pg_dump -Fc -Z 9`.
- **Encryption**: AES-256-CBC with PBKDF2 (100,000 iterations) using `BACKUP_ENCRYPTION_KEY`.
- **Retention Period**: **35 Days** (automated purge of older snapshots).
- **Off-Machine Redundancy**: Storage Box / S3 / Bunny replica via `rclone`.
- **RPO (Recovery Point Objective)**: <= 24 hours.
- **RTO (Recovery Time Objective)**: <= 30 minutes.

---

## 2. Backup Execution
The automated script lives at `scripts/backup_postgres.sh`.

### Environment Configuration
```bash
export DB_NAME="Closly"
export DB_USER="postgres"
export DB_HOST="127.0.0.1"
export DB_PORT="5432"
export PGPASSWORD="<DB_PASSWORD_FROM_VAULT>"
export BACKUP_ENCRYPTION_KEY="<STRONG_PASSPHRASE_FROM_VAULT>"
export BACKUP_DIR="/var/backups/myclosly"
export RCLONE_REMOTE="hetzner_box"
```

### Manual Trigger
```bash
chmod +x scripts/backup_postgres.sh
./scripts/backup_postgres.sh
```

### Nightly Host Cron Job (`/etc/cron.d/myclosly-backup`)
```cron
# Every night at 02:30 UTC
30 2 * * * root /bin/bash /opt/myclosly/scripts/backup_postgres.sh >> /var/log/myclosly_backup.log 2>&1
```

---

## 3. Disaster Recovery / Restore Procedure
To restore a backup into a new or recovered PostgreSQL instance:

### Step 1: Locate Target Snapshot
```bash
ls -lh /var/backups/myclosly/
# Example: myclosly_20261008_023000.dump.enc
```

### Step 2: Execute Restore Script
```bash
chmod +x scripts/restore_postgres.sh
export BACKUP_ENCRYPTION_KEY="<ENCRYPTION_PASSPHRASE>"
export PGPASSWORD="<DB_PASSWORD>"

# Clean restore (drops existing tables before recreating)
./scripts/restore_postgres.sh /var/backups/myclosly/myclosly_20261008_023000.dump.enc --clean
```

### Step 3: Run Database Migrations Check
```bash
python manage.py showmigrations
python manage.py check --database default
```

### Step 4: Verify Uptime & Health
```bash
curl -f https://api.myclosly.com/health/
```

---

## 4. Security & Compliance Rules
1. **Zero Secret Leakage**: Database passwords and encryption keys must NEVER be hardcoded, echoed, or committed to Git.
2. **Strict File Permissions**: The backup directory is locked to `chmod 700` and individual encrypted dumps to `chmod 600`.
3. **Restoration Verification Drill**: Restore integrity is verified immediately upon dump creation via `pg_restore -l`.
