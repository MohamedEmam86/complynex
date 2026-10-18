#!/bin/bash
# Run daily background tasks

# Escalate Overdue Complaints
python scripts/escalate_complaints.py
python scripts/regcontrols_run.py
python scripts/ai_retention.py
