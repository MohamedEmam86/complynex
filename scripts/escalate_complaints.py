# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================


import os
import sys
import logging
from datetime import datetime, date, timedelta

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import get_db
from models.consumer_protection import ConsumerComplaint, ComplaintEscalation, ComplaintActivityLog
from models.user import User # Needed for context or logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def escalate_overdue_complaints():
    """
    Check for complaints that have exceeded the statutory deadline (15 days)
    and escalate them to 'ESCALATED' status if they are not already resolved.
    """
    app = create_app()
    with app.app_context():
        db = get_db()
        today = date.today().isoformat()
        
        # Find overdue complaints
        query = """
            SELECT * FROM consumer_complaints 
            WHERE statutory_deadline_date < ? 
            AND status NOT IN ('RESOLVED', 'CLOSED', 'ESCALATED', 'DISMISSED')
        """
        overdue_complaints = db.execute(query, (today,)).fetchall()
        
        count = 0
        for row in overdue_complaints:
            complaint = dict(row)
            complaint_id = complaint['id']
            
            logger.info(f"Escalating complaint #{complaint['complaint_pin']} (ID: {complaint_id})")
            
            # Update status
            ConsumerComplaint.update_status(complaint_id, 'ESCALATED')
            
            # Create Escalation Record (if you have an Escalation model/table)
            # For now, just log activity
            
            # Log Activity
            log_data = {
                'complaint_id': complaint_id,
                'activity_type': 'SYSTEM_ESCALATION',
                'activity_description': 'Complaint escalated due to exceeding statutory deadline (15 days).',
                'new_status': 'ESCALATED',
                'performed_by': None # System
            }
            ComplaintActivityLog.create(log_data)
            
            count += 1
            
        logger.info(f"Escalation complete. {count} complaints escalated.")

if __name__ == "__main__":
    escalate_overdue_complaints()
