#!/usr/bin/env python
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

"""
Manual Watchlist Update Script
Usage: python scripts/update_watchlist.py [--source-id ID]
"""

import sys
import os
import argparse
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screening.data_updater_enhanced import EnhancedDataUpdater

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description='Update sanctions watchlist data')
    parser.add_argument('--source-id', type=int, help='Update specific source by ID')
    parser.add_argument('--user-id', type=int, default=1, help='User ID initiating update')
    parser.add_argument('--db', default='complynex_cms.db', help='Database path')
    
    args = parser.parse_args()
    
    try:
        logger.info("=" * 60)
        logger.info("WATCHLIST DATA UPDATE STARTED")
        logger.info("=" * 60)
        logger.info(f"Database: {args.db}")
        logger.info(f"User ID: {args.user_id}")
        if args.source_id:
            logger.info(f"Source ID: {args.source_id}")
        else:
            logger.info("Mode: Update ALL sources")
        logger.info("-" * 60)
        
        # Initialize updater
        updater = EnhancedDataUpdater(args.db)
        
        # Run update
        stats = updater.update_watchlist(
            source_id=args.source_id,
            user_id=args.user_id
        )
        
        # Display results
        logger.info("=" * 60)
        logger.info("UPDATE COMPLETED SUCCESSFULLY")
        logger.info("=" * 60)
        logger.info(f"Records Added:     {stats['added']:,}")
        logger.info(f"Records Updated:   {stats['updated']:,}")
        logger.info(f"Records Unchanged: {stats['unchanged']:,}")
        logger.info(f"Errors:            {stats['errors']:,}")
        logger.info(f"Duration:          {(stats['end_time'] - stats['start_time']).total_seconds():.2f} seconds")
        logger.info("=" * 60)
        
        return 0
        
    except Exception as e:
        logger.error("=" * 60)
        logger.error("UPDATE FAILED")
        logger.error("=" * 60)
        logger.error(f"Error: {str(e)}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
