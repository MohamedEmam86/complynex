#!/usr/bin/env python3
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
import joblib
import json
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from screening.ml_module import MLScoreCalibrator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('MLTrainer')

def train_new_model():
    """
    Trains a new RandomForest model incorporating the 'semantic_score' 
    and 'token_set_ratio' features introduced in the V2 engine.
    """
    logger.info("Initializing ML Calibrator for Feature Extraction...")
    calibrator = MLScoreCalibrator()
    
    # Define the new enhanced feature set
    enhanced_features = [
        'fuzzy_ratio', 'jaro_winkler', 'phonetic_score', 'partial_ratio', 'token_set_ratio',
        'has_arabic_input', 'has_arabic_watchlist', 'mixed_script',
        'transliteration_score', 'first_name_match', 'last_name_match', 'middle_name_match',
        'known_translit_pair', 'dob_exact_match', 'dob_days_diff',
        'dob_year_match', 'dob_bonus', 'semantic_score', 'network_score', 'media_risk_score'
    ]
    
    logger.info("Generating synthetic training data for Semantic & RapidFuzz recalibration...")
    # In a real scenario, this would load from a historical hits/alerts database.
    # We generate a representative synthetic dataset to bootstrap the new model weights.
    
    np.random.seed(42)  # reproducible synthetic data across retraining runs

    data = []
    labels = []

    # 1. Exact/High Matches (True Positives)
    for _ in range(500):
        data.append({
            'fuzzy_ratio': np.random.uniform(85, 100),
            'jaro_winkler': np.random.uniform(90, 100),
            'phonetic_score': 100.0,
            'partial_ratio': np.random.uniform(90, 100),
            'token_set_ratio': np.random.uniform(95, 100),
            'has_arabic_input': 1.0, 'has_arabic_watchlist': 1.0, 'mixed_script': 0.0,
            'transliteration_score': 100.0, 'first_name_match': 100.0, 'last_name_match': 100.0, 'middle_name_match': 100.0,
            'known_translit_pair': 1.0, 'dob_exact_match': 1.0, 'dob_days_diff': 0.0,
            'dob_year_match': 1.0, 'dob_bonus': 10.0, 
            'semantic_score': np.random.uniform(85, 100), # HIGH SEMANTIC SCORE
            'network_score': 0.0, 'media_risk_score': 0.0
        })
        labels.append(1)
        
    # 2. Cross-lingual matches (English Input <-> Arabic Watchlist) (True Positives)
    # These should ONLY be true positives if the semantic score is EXTREMELY high (>95)
    for _ in range(300):
        data.append({
            'fuzzy_ratio': np.random.uniform(20, 50),
            'jaro_winkler': np.random.uniform(20, 50),
            'phonetic_score': 0.0,
            'partial_ratio': np.random.uniform(30, 50),
            'token_set_ratio': np.random.uniform(30, 50),
            'has_arabic_input': 0.0, 'has_arabic_watchlist': 1.0, 'mixed_script': 1.0,
            'transliteration_score': np.random.uniform(85, 100), 
            'first_name_match': np.random.choice([0.0, 50.0, 100.0]),
            'last_name_match': np.random.choice([0.0, 50.0, 100.0]),
            'middle_name_match': 50.0,
            'known_translit_pair': 1.0, 'dob_exact_match': 1.0, 'dob_days_diff': 0.0,
            'dob_year_match': 1.0, 'dob_bonus': 10.0, 
            'semantic_score': np.random.uniform(96, 100), # SUPER HIGH SEMANTIC SCORE REQUIRED
            'network_score': 0.0, 'media_risk_score': 0.0
        })
        labels.append(1)
        
    # 2b. Cross-lingual FALSE Positives (High semantic score, but wrong name)
    # This teaches the model that a semantic score of 85-94% is NOT enough on its own
    # if the transliteration and token sets don't align perfectly.
    for _ in range(300):
        data.append({
            'fuzzy_ratio': np.random.uniform(10, 40),
            'jaro_winkler': np.random.uniform(10, 40),
            'phonetic_score': 0.0,
            'partial_ratio': np.random.uniform(10, 40),
            'token_set_ratio': np.random.uniform(10, 40),
            'has_arabic_input': 0.0, 'has_arabic_watchlist': 1.0, 'mixed_script': 1.0,
            'transliteration_score': 0.0, 
            'first_name_match': 0.0, 'last_name_match': 0.0, 'middle_name_match': 0.0,
            'known_translit_pair': 0.0, 'dob_exact_match': 0.0, 'dob_days_diff': 1000.0,
            'dob_year_match': 0.0, 'dob_bonus': -10.0, 
            'semantic_score': np.random.uniform(85, 95), # MID-HIGH SEMANTIC, but it's a false positive!
            'network_score': 0.0, 'media_risk_score': 0.0
        })
        labels.append(0)
        
    # 3. Clear Non-Matches (True Negatives)
    for _ in range(800):
        data.append({
            'fuzzy_ratio': np.random.uniform(0, 40),
            'jaro_winkler': np.random.uniform(0, 40),
            'phonetic_score': 0.0,
            'partial_ratio': np.random.uniform(0, 40),
            'token_set_ratio': np.random.uniform(0, 40),
            'has_arabic_input': 1.0, 'has_arabic_watchlist': 1.0, 'mixed_script': 0.0,
            'transliteration_score': 0.0, 'first_name_match': 0.0, 'last_name_match': 0.0, 'middle_name_match': 0.0,
            'known_translit_pair': 0.0, 'dob_exact_match': 0.0, 'dob_days_diff': 5000.0,
            'dob_year_match': 0.0, 'dob_bonus': -10.0, 
            'semantic_score': np.random.uniform(0, 40), # LOW SEMANTIC SCORE
            'network_score': 0.0, 'media_risk_score': 0.0
        })
        labels.append(0)

    df = pd.DataFrame(data, columns=enhanced_features)
    y = np.array(labels)
    
    logger.info("Training Enhanced RandomForest Classifier...")
    X_train, X_test, y_train, y_test = train_test_split(df, y, test_size=0.2, random_state=42)
    
    clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    clf.fit(X_train, y_train)
    
    logger.info("Evaluating Model...")
    preds = clf.predict(X_test)
    logger.info(f"\\n{classification_report(y_test, preds)}")
    report = classification_report(y_test, preds, output_dict=True, zero_division=0)
    # 'weighted avg' matches how the other tiers' metadata report accuracy/precision/recall/f1
    metrics = {
        'accuracy': report['accuracy'],
        'precision': report['weighted avg']['precision'],
        'recall': report['weighted avg']['recall'],
        'f1_score': report['weighted avg']['f1-score'],
    }

    importances = clf.feature_importances_
    feat_imps = {feat: float(imp) for feat, imp in zip(enhanced_features, importances)}
    sorted_imps = dict(sorted(feat_imps.items(), key=lambda item: item[1], reverse=True))
    
    logger.info(f"Top 5 Feature Importances:")
    for i, (k, v) in enumerate(list(sorted_imps.items())[:5]):
        logger.info(f" {i+1}. {k}: {v:.4f}")
        
    out_dir = os.path.dirname(calibrator.model_path)
    model_file = os.path.join(out_dir, 'ml_model_master_unified.pkl')
    meta_file = os.path.join(out_dir, 'model_metadata_master_unified.json')
    
    logger.info(f"Saving Retrained Model to {model_file}")
    
    bundle = {
        'model': clf,
        'feature_names': enhanced_features,
        'version': 'semantic-v1',
        'translit_map': calibrator.translit_map,
        'last_name_map': calibrator.last_name_map,
        'reverse_map': calibrator.reverse_map,
        'confusion_pairs': getattr(calibrator, 'confusion_pairs', [])
    }
    
    joblib.dump(bundle, model_file)
    
    with open(meta_file, 'w') as f:
        json.dump({
            'version': 'semantic-v1',
            'features': enhanced_features,
            'feature_importance': sorted_imps,
            'threshold': 0.60,
            'trained': datetime.now(timezone.utc).isoformat(),
            'training_data': {
                'source': 'synthetic',  # see module docstring: no real labeled-outcome pipeline exists yet
                'total_samples': len(df),
                'training_samples': len(X_train),
                'test_samples': len(X_test),
            },
            'metrics': metrics,
        }, f, indent=4)

    logger.info("Successfully retrained and saved semantic ML cluster.")

if __name__ == '__main__':
    train_new_model()
