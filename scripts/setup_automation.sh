#!/bin/bash

# Setup Monthly Automation for ComplyNex Watchlist Screening
# This script adds a cron job to run scrape_all_sources.py on the 1st of every month

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

PYTHON_EXEC="python3" # Adjust if using venv, e.g., "$BASE_DIR/venv/bin/python"
SCRIPT_PATH="$BASE_DIR/scripts/scrape_all_sources.py"

# verification
if [[ ! -f "$SCRIPT_PATH" ]]; then
    echo "Error: Could not find script at $SCRIPT_PATH"
    exit 1
fi

# Cron expression: Run at 02:00 on day-of-month 1 (Monthly)
CRON_CMD="0 2 1 * * cd \"$BASE_DIR\" && $PYTHON_EXEC \"$SCRIPT_PATH\" >> \"$LOG_DIR/automation.log\" 2>&1"

# Check if job already exists
(crontab -l 2>/dev/null | grep -F "$SCRIPT_PATH") >/dev/null

if [ $? -eq 0 ]; then
    echo "Automation already configured."
    echo "Current crontab entry:"
    crontab -l | grep -F "$SCRIPT_PATH"
else
    # Append to crontab
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "Automation scheduled successfully!"
    echo "New job: $CRON_CMD"
fi

# Make script executable
chmod +x "$SCRIPT_PATH"
echo "Ensured $SCRIPT_PATH is executable."
