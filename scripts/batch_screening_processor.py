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
import pandas as pd
import json
import time
import logging
from datetime import datetime
import warnings

# Suppress sklearn/joblib warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# Add root directory to path for imports
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from screening.multi_source_screener import MultiSourceScreener
from config import get_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("batch_screening.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
INPUT_FILE = r'C:\Users\Dina\Downloads\ComplyNex_CMS\Screening Reports\Data Sheet.xlsx'
OUTPUT_DIR = r'C:\Users\Dina\Downloads\ComplyNex_CMS\Screening Reports\Batch_Results'
CHECKPOINT_FILE = r'C:\Users\Dina\Downloads\ComplyNex_CMS\Screening Reports\screening_checkpoint.json'
BATCH_SIZE = 100

def get_db_config():
    cfg = get_config()
    return {'database': cfg.DATABASE}

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {'last_index': -1, 'total_processed': 0, 'start_time': None}

def save_checkpoint(index, total_processed, start_time):
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({
            'last_index': index,
            'total_processed': total_processed,
            'last_updated': datetime.now().isoformat(),
            'start_time': start_time
        }, f, indent=4)

def run_batch_screening():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Load Data
    logger.info(f"Loading data from {INPUT_FILE}...")
    df = pd.read_excel(INPUT_FILE)
    total_rows = len(df)
    logger.info(f"Loaded {total_rows} records.")

    # Load Checkpoint
    checkpoint = load_checkpoint()
    start_index = checkpoint['last_index'] + 1
    total_processed = checkpoint['total_processed']
    start_time = checkpoint['start_time'] or datetime.now().isoformat()
    
    # Handle optional limit for testing
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
            logger.info(f"Test Mode: Limiting to {limit} records.")
        except ValueError:
            pass

    if start_index >= total_rows:
        logger.info("All records already processed according to checkpoint.")
        return

    # Initialize Engine
    logger.info("Initializing Screening Engine...")
    db_config = get_db_config()
    screener = MultiSourceScreener(db_config)
    
    output_file = os.path.join(OUTPUT_DIR, f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    
    end_index = total_rows
    if limit:
        end_index = min(start_index + limit, total_rows)

    logger.info(f"Starting screening from index {start_index} to {end_index} (Batch Size: {BATCH_SIZE})...")
    
    results_buffer = []

    try:
        for i in range(start_index, end_index):
            row = df.iloc[i]
            merchant_name = str(row.get('Merchant Name', '')).strip()
            
            if not merchant_name or merchant_name.lower() == 'nan':
                logger.warning(f"Skipping empty name at row {i}")
                checkpoint_data = {'status': 'skipped', 'reason': 'empty_name'}
            else:
                try:
                    # Execute screening
                    res = screener.screen_person(
                        name=merchant_name,
                        entity_type='ENTITY', # Defaulting to entity as these are merchants
                        include_media=False
                    )
                    
                    checkpoint_data = {
                        'Merchant Name': merchant_name,
                        'NID': row.get('NID', ''),
                        'Screening Result': res.get('screening_result', 'UNKNOWN'),
                        'Match Score': res.get('highest_score', 0),
                        'Matches Found': res.get('total_matches', 0),
                        'Risk Level': res.get('risk_level', 'CLEAR'),
                        'Discovery Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                except Exception as e:
                    logger.error(f"Error screening {merchant_name} at row {i}: {e}")
                    checkpoint_data = {'Merchant Name': merchant_name, 'status': 'error', 'error': str(e)}

            results_buffer.append(checkpoint_data)
            total_processed += 1
            
            # Batch Completion Logic
            if (i + 1) % BATCH_SIZE == 0 or (i + 1) == end_index:
                batch_df = pd.DataFrame(results_buffer)
                
                # Write to CSV (Append mode) with retries for PermissionError
                max_save_retries = 5
                for retry in range(max_save_retries):
                    try:
                        file_exists = os.path.isfile(output_file)
                        batch_df.to_csv(output_file, mode='a', index=False, header=not file_exists)
                        break
                    except PermissionError:
                        if retry < max_save_retries - 1:
                            logger.warning(f"File {output_file} is locked. Retrying in 5 seconds... ({retry+1}/{max_save_retries})")
                            time.sleep(5)
                        else:
                            # If we still can't save, try a new filename
                            new_output_file = output_file.replace('.csv', f'_fallback_{int(time.time())}.csv')
                            logger.error(f"Could not save to {output_file}. Saving to fallback: {new_output_file}")
                            batch_df.to_csv(new_output_file, mode='a', index=False, header=True)
                            output_file = new_output_file # Switch to new file for future batches
                
                # Update Checkpoint
                save_checkpoint(i, total_processed, start_time)
                
                logger.info(f"COMPLETED BATCH: Processed {total_processed}/{total_rows} (Latest row index: {i})")
                results_buffer = [] # Clear buffer

    except KeyboardInterrupt:
        logger.info("Process interrupted by user. Saving checkpoint...")
    except Exception as e:
        logger.error(f"Fatal error during batch processing: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        screener.close()
        logger.info("Screening engine closed.")

if __name__ == "__main__":
    run_batch_screening()
