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

import pandas as pd
import os
import json
import time
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
import warnings

# Suppress sklearn/xgboost warnings that pollute the terminal
warnings.filterwarnings('ignore')

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import core engine - handles SQLite connection and initialization of the ML calibrator automatically
from screening.complynex_engine import ComplyNexScreeningEngine

def process_chunk(df_chunk, engine):
    """
    Process a small chunk of rows sequentially in one thread.
    engine is thread-safe for reading.
    """
    results = []
    reports = []
    
    for _, row in df_chunk.iterrows():
        merchant_name = str(row['Merchant Name']) if pd.notna(row['Merchant Name']) else ''
        nid = str(row['NID']) if pd.notna(row['NID']) else ''
        
        # We only really care about the name for purely sanction screening capability checks
        if not merchant_name.strip():
            continue
            
        # Screen the name
        hit = engine.screen_person(
            name=merchant_name,
            date_of_birth=None,
            nationality=None,
            include_media=False
        )
        
        is_match = hit.get('is_match', False)
        ml_score = hit.get('ml_score', 0.0)
        
        # Gather best matches if it triggered a hit
        matched_identities = []
        if is_match and 'matches' in hit:
            for m in hit['matches']:
                matched_identities.append(m.get('matched_name', 'Unknown'))
        
        # Save outcome for Master Excel
        result_row = row.to_dict()
        result_row['Screening Status'] = 'MATCH' if is_match else 'CLEAR'
        result_row['ML Score'] = round(ml_score, 2)
        result_row['Confidence'] = hit.get('confidence', 'low')
        result_row['Matched Watchlist Entities'] = " | ".join(matched_identities) if matched_identities else ''
        results.append(result_row)
        
        # Extract full report if it's a MATCH
        if is_match:
            reports.append({
                'nid': nid,
                'merchant_name': merchant_name,
                'report': hit
            })
            
    return results, reports

def main():
    print("="*60)
    print("BATCH SANCTION SCREENING - 35,000 MERCHANTS")
    print("="*60)
    
    input_file = r'C:\Users\Dina\Downloads\ComplyNex_CMS\Screening Reports\Data Sheet.xlsx'
    output_dir = r'C:\Users\Dina\Downloads\ComplyNex_CMS\Screening Reports\Batch_Results'
    master_path = os.path.join(output_dir, 'Screening_Results_Master.xlsx')
    
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'MATCH_Reports'), exist_ok=True)
    
    print(f"Loading data from: {input_file}...")
    df = pd.read_excel(input_file)
    original_len = len(df)
    print(f"Loaded {original_len} merchants.")
    
    # --- CHECKPOINT RESUME LOGIC ---
    processed_nids = set()
    all_results = []
    
    if os.path.exists(master_path):
        print(f"--> Found existing Master Report. Resuming from checkpoint...")
        existing_df = pd.read_excel(master_path)
        all_results = existing_df.to_dict('records')
        # Collect previously processed NIDs or Merchant Names (some NIDs might be NA)
        for _, row in existing_df.iterrows():
            nid = str(row.get('NID', ''))
            name = str(row.get('Merchant Name', ''))
            processed_nids.add((nid, name))
            
        print(f"--> Already processed {len(all_results)} merchants.")
        
        # Filter out existing (using row indices mapped against NID+Name pairs to handle duplicates)
        # Using index is safest if NID is missing
        # Alternatively: Filter by (NID, Name) pair
        df['nid_name_pair'] = list(zip(df['NID'].fillna('').astype(str), df['Merchant Name'].fillna('').astype(str)))
        df = df[~df['nid_name_pair'].isin(processed_nids)].copy()
        df.drop(columns=['nid_name_pair'], inplace=True)
        
    remaining = len(df)
    print(f"--> Remaining merchants to screen: {remaining}")
    
    if remaining == 0:
        print("Screening is already 100% complete!")
        return

    # Initialize engine
    print("Initializing ComplyNex Engine (Models and Database connections)...")
    try:
        db_path = r"C:\Users\Dina\Downloads\ComplyNex_CMS\complynex_cms.db"
        engine = ComplyNexScreeningEngine(db_config=db_path)
        engine.screen_person("Warmup Name Test", include_media=False)
        print("Engine initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize engine: {e}")
        return
    
    start_time = time.time()
    
    chunk_size = 500
    chunks = [df[i:i+chunk_size] for i in range(0, df.shape[0], chunk_size)]
    
    all_match_reports = [] # Track new match reports for saving
    
    print(f"Starting threads (Chunks to process: {len(chunks)}, Mappers: {min(16, os.cpu_count() * 4)})...")
    
    with ProcessPoolExecutor(max_workers=min(16, os.cpu_count() * 4)) as pool:
        futures = {pool.submit(process_chunk, chunk, engine): chunk for chunk in chunks}
        
        for idx, future in enumerate(tqdm(as_completed(futures), total=len(futures), desc='Processing Chunks')):
            try:
                res, reps = future.result()
                all_results.extend(res)
                all_match_reports.extend(reps)
                
                # --- INCREMENTAL SAVE (CHECKPOINTING) ---
                # Save progress after every completed chunk to avoid data loss
                result_df = pd.DataFrame(all_results)
                result_df.to_excel(master_path, index=False)
                
                # Output any new MATCH JSON reports immediately
                for report_obj in reps:
                    name = report_obj['merchant_name'].replace(' ', '_').replace('/', '_')
                    nid = report_obj['nid']
                    safe_name = name[:30] if len(name) > 30 else name
                    # Append unique timestamp to filename to avoid overwrites
                    fname = f"HIT_{safe_name}_{nid}_{int(time.time()*100)}.json"
                    fpath = os.path.join(output_dir, 'MATCH_Reports', fname)
                    with open(fpath, 'w', encoding='utf-8') as f:
                        json.dump(report_obj['report'], f, ensure_ascii=False, indent=4)
                        
            except Exception as e:
                print(f"Chunk processing failed: {e}")
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    print("\n" + "="*60)
    print("SCREENING COMPLETE")
    print(f"Total Master Records: {len(all_results)} / {original_len}")
    print(f"Time Taken (This session): {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
    print(f"Throughput (This session): {remaining/elapsed:.2f} records/second")
    print("="*60)
    print(f"--> Checkpoint saved to {master_path}")
    print(f"--> Reports folder: '{output_dir}\\MATCH_Reports\\'")

if __name__ == '__main__':
    main()
