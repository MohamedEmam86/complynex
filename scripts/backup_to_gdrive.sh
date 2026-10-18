#!/bin/bash
BACKUP_NAME="complynex_backup_$(date +%Y%m%d_%H%M%S)"
echo "$(date): Starting backup ${BACKUP_NAME}" >> /opt/complynex/logs/backup.log

tar -czf /opt/backups/${BACKUP_NAME}.tar.gz \
  --exclude='/opt/complynex/venv' \
  --exclude='/opt/complynex/logs/*.log' \
  --exclude='/opt/complynex/**/__pycache__' \
  --exclude='/opt/complynex/**/*.pyc' \
  --exclude='/opt/complynex/uploads/ofac_auto_*' \
  --exclude='/opt/complynex/uploads/hmt_auto_*' \
  --exclude='/opt/complynex/uploads/un_auto_*' \
  -C /opt complynex

rclone copy /opt/backups/${BACKUP_NAME}.tar.gz gdrive:ComplynexBackups/ --progress

ls -t /opt/backups/complynex_backup_*.tar.gz | tail -n +3 | xargs rm -f

echo "$(date): Backup ${BACKUP_NAME} completed" >> /opt/complynex/logs/backup.log
