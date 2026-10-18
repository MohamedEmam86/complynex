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

# Add parent dir to path
# Add project root to path (assuming script is run from project root or scripts dir)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
sys.path.append(os.getcwd())
try:
    import complynex_cms
except ImportError:
    # If run from inside complynex_cms package, we might need to go up one more level
    sys.path.append(os.path.dirname(project_root))

from complynex_cms.screening.complynex_engine import ComplyNexScreeningEngine
# Or use MultiSourceScreener to test that too
from complynex_cms.screening.multi_source_screener import MultiSourceScreener

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def validate_ml_loading():
    logger.info("Initializing Screening Engine...")
    
    # Dummy DB config
    db_config = {'database': 'dummy.db'}
    
    try:
        # Initialize MultiSourceScreener (which initializes ComplyNexScreeningEngine)
        screener = MultiSourceScreener(db_config)
        engine = screener.local_engine
        
        logger.info("Checking ML Calibrator...")
        if engine.ml_calibrator:
            logger.info("ML Calibrator initialized.")
            if engine.ml_calibrator.model:
                logger.info("ML Model loaded successfully.")
                logger.info(f"Model ID/Type: {type(engine.ml_calibrator.model)}")
                
                # Test prediction
                logger.info("Testing dummy prediction...")
                try:
                    result = engine.ml_calibrator.calculate_ml_score(
                        input_name="Mohammed Ali",
                        watchlist_name="Mohammed Ali",
                        input_dob=None,
                        watchlist_dob=None,
                        input_nationality="Egypt",
                        watchlist_nationality="Egypt"
                    )
                    logger.info(f"Prediction Result: {result}")
                    if result.get('ml_score') is not None:
                        logger.info("SUCCESS: ML prediction worked.")
                    else:
                        logger.error("FAILURE: ML prediction returned None score.")
                except Exception as e:
                    logger.error(f"FAILURE: Prediction failed: {e}")
            else:
                logger.error("FAILURE: ML Model is None.")
        else:
            logger.warning("ML Calibrator NOT initialized (module import failed or disabled?).")
            
        screener.close()
        
    except Exception as e:
        logger.error(f"Engine initialization failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    validate_ml_loading()
