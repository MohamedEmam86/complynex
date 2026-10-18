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

from screening.db_pool import db_pool
# ========================================
# FROM FILE: screening/ml_calibrator.py
# ========================================

import os
import joblib
import logging
import json
import pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score

import warnings
# Suppress sklearn UserWarning about feature names
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
# Suppress InconsistentVersionWarning for cross-version model loading
warnings.filterwarnings("ignore", message=".*InconsistentVersionWarning.*")

logger = logging.getLogger(__name__)

class MLScoreCalibrator:
    """
    ML-based score calibrator for sanctions screening with Arabic enhancement.
    
    4-Tier Weighted Ensemble Architecture:
        Tier 1 (Primary)  : Master Unified (75K, RF+GB+ET, 20 features, weight=0.40)
        Tier 2 (Secondary): 50K Model       (50K, RF+GB,    18 features, weight=0.30)
        Tier 3 (Tertiary) : 24K Enhanced    (24K, RF,        14 features, weight=0.20)
        Tier 4 (Legacy)   : Legacy V1       (500, RF,         9 features, weight=0.10)
    """
    
    _SCREENING_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # Tier 3: 24K Enhanced (was the primary before)
    MODEL_PATH = os.path.join(_SCREENING_DIR, 'ml_model.pkl')
    METADATA_PATH = os.path.join(_SCREENING_DIR, 'model_metadata.json')
    
    # Tier 4: Legacy V1
    LEGACY_MODEL_PATH = os.path.join(_SCREENING_DIR, 'ml_model_legacy.pkl')
    LEGACY_METADATA_PATH = os.path.join(_SCREENING_DIR, 'model_metadata_legacy.json')
    
    # Tier 2: 50K Model (NEW)
    MODEL_50K_PATH = os.path.join(_SCREENING_DIR, 'ml_model_50k.pkl')
    METADATA_50K_PATH = os.path.join(_SCREENING_DIR, 'model_metadata_50k.json')
    
    # Tier 1: Master Unified (NEW - PRIMARY)
    MODEL_MASTER_PATH = os.path.join(_SCREENING_DIR, 'ml_model_master_unified.pkl')
    METADATA_MASTER_PATH = os.path.join(_SCREENING_DIR, 'model_metadata_master_unified.json')
    
    # Ensemble weights: sum to 1.0
    ENSEMBLE_WEIGHTS = {
        'master': 0.40,
        'model_50k': 0.30,
        'v2': 0.20,
        'v1': 0.10,
    }
    
    def __init__(self, model_path=None, metadata_path=None, threshold=0.60):
        """
        Initialize ML calibrator.
        """
        self.model_path = model_path or self.MODEL_PATH
        self.metadata_path = metadata_path or self.METADATA_PATH
        self.legacy_model_path = self.LEGACY_MODEL_PATH
        self.legacy_metadata_path = self.LEGACY_METADATA_PATH
        self.model_50k_path = self.MODEL_50K_PATH
        self.metadata_50k_path = self.METADATA_50K_PATH
        self.model_master_path = self.MODEL_MASTER_PATH
        self.metadata_master_path = self.METADATA_MASTER_PATH
        
        self.threshold = threshold
        
        # Model slots
        self.model = None           # Tier 3: 24K Enhanced
        self.legacy_model = None    # Tier 4: Legacy V1
        self.model_50k = None       # Tier 2: 50K bundle
        self.model_master = None    # Tier 1: Master Unified bundle
        
        self.metadata = {}
        self.legacy_metadata = {}
        self.metadata_50k = {}
        self.metadata_master = {}
        self.is_fitted = False
        
        # Bundled transliteration maps (loaded from new models)
        self.translit_map = {}
        self.last_name_map = {}
        self.reverse_map = {}
        self.confusion_pairs = []
        
        # Feature name lists for each tier
        self.master_features = []
        self.features_50k = []
        
        # Try to import Arabic name handler (Legacy)
        try:
            from .arabic_name_handler import ArabicNameHandler
            self.arabic_handler = ArabicNameHandler()
            self.has_arabic_handler = True
        except (ImportError, ValueError):
            try:
                from screening.arabic_name_handler import ArabicNameHandler
                self.arabic_handler = ArabicNameHandler()
                self.has_arabic_handler = True
            except (ImportError, ValueError):
                self.arabic_handler = None
                self.has_arabic_handler = False
                logger.warning("Arabic name handler not available. Using fallback logic.")
                
        # Import Enhanced Transliterator (New) - DEPRECATED
        # The cross language transliteration is now explicitly enforced at the 
        # API boundary (routes/ingestion) via prepare_name_for_screening().
        self.transliterator = None
        self.has_transliterator = False
        
        self._load_all_models()
        self._load_all_metadata()
    
    # ------------------------------------------------------------------
    # MODEL LOADING
    # ------------------------------------------------------------------
    
    def _load_all_models(self):
        """Load all model tiers from disk."""
        self._load_model()          # Tier 3: 24K
        self._load_legacy_model()   # Tier 4: Legacy
        self._load_50k_model()      # Tier 2: 50K
        self._load_master_model()   # Tier 1: Master Unified
        
        active = sum(1 for m in [self.model_master, self.model_50k, self.model, self.legacy_model] if m is not None)
        logger.info(f"ML Ensemble: {active}/4 model tiers loaded.")
    
    def _load_model(self):
        """Load Tier 3: 24K Enhanced model."""
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                if hasattr(self.model, 'n_jobs'):
                    self.model.n_jobs = 1
                if hasattr(self.model, 'verbose'):
                    self.model.verbose = 0
                self.is_fitted = True
                logger.info(f"Tier 3 (24K Enhanced) model loaded from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load Tier 3 model: {e}")
                self.is_fitted = False
        else:
            logger.info(f"No Tier 3 model at {self.model_path}")
            self.is_fitted = False
    
    def _load_legacy_model(self):
        """Load Tier 4: Legacy V1 model."""
        if os.path.exists(self.legacy_model_path):
            try:
                self.legacy_model = joblib.load(self.legacy_model_path)
                if hasattr(self.legacy_model, 'n_jobs'):
                    self.legacy_model.n_jobs = 1
                if hasattr(self.legacy_model, 'verbose'):
                    self.legacy_model.verbose = 0
                logger.info(f"Tier 4 (Legacy V1) model loaded from {self.legacy_model_path}")
            except Exception as e:
                logger.error(f"Failed to load Tier 4 model: {e}")
                self.legacy_model = None
        else:
            logger.info(f"No Tier 4 model at {self.legacy_model_path}")
    
    def _load_bundle_model(self, bundle_path, tier_name):
        """
        Load a dict-bundle model (50K or Master Unified).
        Returns (sklearn_model, bundle_dict) or (None, None).
        """
        if not os.path.exists(bundle_path):
            logger.info(f"No {tier_name} model at {bundle_path}")
            return None, None
        try:
            bundle = joblib.load(bundle_path)
            if not isinstance(bundle, dict) or 'model' not in bundle:
                logger.error(f"{tier_name} bundle missing 'model' key")
                return None, None
            
            clf = bundle['model']
            # Force single-threaded inference
            if hasattr(clf, 'n_jobs'):
                clf.n_jobs = 1
            if hasattr(clf, 'verbose'):
                clf.verbose = 0
            # Also set for sub-estimators if VotingClassifier
            if hasattr(clf, 'estimators_'):
                for est in clf.estimators_:
                    sub = est[1] if isinstance(est, tuple) else est
                    if hasattr(sub, 'n_jobs'):
                        sub.n_jobs = 1
                    if hasattr(sub, 'verbose'):
                        sub.verbose = 0
            
            logger.info(f"{tier_name} model loaded from {bundle_path}")
            return clf, bundle
        except Exception as e:
            logger.error(f"Failed to load {tier_name} model: {e}")
            return None, None
    
    def _load_50k_model(self):
        """Load Tier 2: 50K model bundle."""
        clf, bundle = self._load_bundle_model(self.model_50k_path, "Tier 2 (50K)")
        if clf is not None:
            self.model_50k = clf
            self.features_50k = bundle.get('feature_names', [])
            # Merge transliteration maps (50K as base, master overrides later)
            if not self.translit_map:
                self.translit_map = bundle.get('translit_map', {})
                self.last_name_map = bundle.get('last_name_map', {})
                self.reverse_map = bundle.get('reverse_map', {})
            self.is_fitted = True
    
    def _load_master_model(self):
        """Load Tier 1: Master Unified model bundle."""
        clf, bundle = self._load_bundle_model(self.model_master_path, "Tier 1 (Master Unified)")
        if clf is not None:
            self.model_master = clf
            self.master_features = bundle.get('feature_names', [])
            # Master maps take priority (largest & most complete)
            self.translit_map = bundle.get('translit_map', self.translit_map)
            self.last_name_map = bundle.get('last_name_map', self.last_name_map)
            self.reverse_map = bundle.get('reverse_map', self.reverse_map)
            self.confusion_pairs = bundle.get('confusion_pairs', [])
            self.is_fitted = True
            logger.info(f"Master model maps: {len(self.translit_map)} translit, "
                        f"{len(self.last_name_map)} last-name, "
                        f"{len(self.confusion_pairs)} confusion pairs")
    
    # ------------------------------------------------------------------
    # METADATA LOADING
    # ------------------------------------------------------------------
    
    def _load_all_metadata(self):
        """Load all metadata files."""
        self.metadata = self._read_json(self.metadata_path, "Tier 3")
        self.legacy_metadata = self._read_json(self.legacy_metadata_path, "Tier 4")
        self.metadata_50k = self._read_json(self.metadata_50k_path, "Tier 2")
        self.metadata_master = self._read_json(self.metadata_master_path, "Tier 1")
    
    @staticmethod
    def _read_json(path, label):
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                logger.info(f"{label} metadata loaded.")
                return data
            except Exception as e:
                logger.warning(f"Could not load {label} metadata: {e}")
        return {}

    # ------------------------------------------------------------------
    # PREDICTION
    # ------------------------------------------------------------------
    
    def calculate_ml_score(self, input_name, watchlist_name, 
                          input_dob=None, watchlist_dob=None,
                          input_nationality=None, watchlist_nationality=None,
                          network_score=0, tx_velocity_score=0, 
                          media_risk_score=0, tenure_days=0):
        """
        Calculate ML-based match score using 4-tier weighted ensemble.
        """
        if not self.is_fitted:
            return {
                'ml_score': 0,
                'is_match': False,
                'confidence': 'model_not_loaded',
                'threshold_used': self.threshold
            }
        
        try:
            # Extract the full feature set (superset of all tiers)
            features = self._extract_features(
                input_name, watchlist_name,
                input_dob, watchlist_dob,
                input_nationality, watchlist_nationality,
                network_score, tx_velocity_score,
                media_risk_score, tenure_days
            )
            
            # Predict with each available tier
            tier_scores = {}
            
            # --- Tier 1: Master Unified (75K, RF+GB+ET) ---
            tier_scores['master'] = self._predict_with_tier(
                self.model_master, features, self.master_features,
                self.metadata_master, "Master Unified", is_bundle=True
            )
            
            # --- Tier 2: 50K (RF+GB) ---
            tier_scores['model_50k'] = self._predict_with_tier(
                self.model_50k, features, self.features_50k,
                self.metadata_50k, "50K", is_bundle=True
            )
            
            # --- Tier 3: 24K Enhanced ---
            tier_features = self._get_tier_features(self.metadata, fallback_14=True)
            tier_scores['v2'] = self._predict_with_tier(
                self.model, features, tier_features,
                self.metadata, "24K Enhanced", is_bundle=False
            )
            
            # --- Tier 4: Legacy V1 ---
            legacy_features = self._get_legacy_features()
            tier_scores['v1'] = self._predict_with_tier(
                self.legacy_model, features, legacy_features,
                self.legacy_metadata, "Legacy V1", is_bundle=False
            )
            
            # --- WEIGHTED ENSEMBLE ---
            probability, source_model = self._weighted_ensemble(tier_scores)
            
            # --- RISK POLICY BOOST ---
            original_prob = probability
            if media_risk_score >= 80 or network_score >= 80:
                if probability < 0.85:
                    probability = 0.85
                    source_model += " + CriticalRiskBoost"
                    logger.info(f"Score boosted from {original_prob:.2f} to 0.85 due to Critical Risk")
            elif media_risk_score >= 50 or network_score >= 50:
                if probability < 0.65:
                    probability = 0.65
                    source_model += " + ModerateRiskBoost"
            
            # APPLY THRESHOLD
            is_match = bool(probability >= self.threshold)
            ml_score = float(probability * 100)
            
            # Confidence level
            if probability >= 0.90:
                confidence = 'very_high'
            elif probability >= 0.75:
                confidence = 'high'
            elif probability >= self.threshold:
                confidence = 'medium'
            elif probability >= 0.40:
                confidence = 'low'
            else:
                confidence = 'very_low'
            
            return {
                'ml_score': ml_score,
                'is_match': is_match,
                'confidence': confidence,
                'threshold_used': self.threshold,
                'raw_probability': probability,
                'model_source': source_model,
                'scores': tier_scores,
                'explanation': self._explain_prediction(features)
            }
        except Exception as e:
            logger.error(f"ML calculation error: {e}")
            return {
                'ml_score': 0,
                'is_match': False,
                'confidence': 'error',
                'threshold_used': self.threshold
            }

    def calculate_ml_score_batch(self, batch_inputs):
        """
        Evaluate multiple candidates in a single vectorized ML prediction.
        batch_inputs is a list of dicts with keys matching calculate_ml_score arguments.
        Returns a list of result dicts in the same order.
        """
        if not self.is_fitted or not batch_inputs:
            return [{
                'ml_score': 0,
                'is_match': False,
                'confidence': 'model_not_loaded',
                'threshold_used': self.threshold
            } for _ in batch_inputs]

        try:
            # 1. Extract features for all candidates
            all_features = []
            for inputs in batch_inputs:
                all_features.append(self._extract_features(
                    inputs.get('input_name'), inputs.get('watchlist_name'),
                    inputs.get('input_dob'), inputs.get('watchlist_dob'),
                    inputs.get('input_nationality'), inputs.get('watchlist_nationality'),
                    inputs.get('network_score', 0), inputs.get('tx_velocity_score', 0),
                    inputs.get('media_risk_score', 0), inputs.get('tenure_days', 0),
                    semantic_score=inputs.get('semantic_score', 0.0)
                ))

            # 2. Batch predict for each tier
            tier_feature_sets = {
                'master': (self.model_master, self.master_features, True),
                'model_50k': (self.model_50k, self.features_50k, True),
                'v2': (self.model, self._get_tier_features(self.metadata, fallback_14=True), False),
                'v1': (self.legacy_model, self._get_legacy_features(), False),
            }
            
            tier_probs = {}
            for tier_name, (model_obj, feat_list, is_bundle) in tier_feature_sets.items():
                if model_obj is None or not feat_list:
                    tier_probs[tier_name] = [0.0] * len(all_features)
                    continue
                try:
                    df = pd.DataFrame(
                        [{f: feat.get(f, 0) for f in feat_list} for feat in all_features],
                        columns=feat_list
                    ).fillna(0)
                    tier_probs[tier_name] = list(model_obj.predict_proba(df)[:, 1])
                except Exception as e:
                    logger.error(f"Batch {tier_name} prediction failed: {e}")
                    tier_probs[tier_name] = [0.0] * len(all_features)

            # 3. Compile results
            results = []
            for i, inputs in enumerate(batch_inputs):
                scores = {t: float(tier_probs[t][i]) for t in tier_probs}
                probability, source_model = self._weighted_ensemble(scores)
                
                # Risk boost
                media_risk = inputs.get('media_risk_score', 0)
                network_risk = inputs.get('network_score', 0)
                if media_risk >= 80 or network_risk >= 80:
                    if probability < 0.85:
                        probability = 0.85
                        source_model += " + CriticalRiskBoost"
                elif media_risk >= 50 or network_risk >= 50:
                    if probability < 0.65:
                        probability = 0.65
                        source_model += " + ModerateRiskBoost"

                confidence = 'very_high' if probability >= 0.90 else \
                             'high' if probability >= 0.75 else \
                             'medium' if probability >= self.threshold else \
                             'low' if probability >= 0.40 else 'very_low'

                results.append({
                    'ml_score': float(probability * 100),
                    'is_match': bool(probability >= self.threshold),
                    'confidence': confidence,
                    'threshold_used': self.threshold,
                    'raw_probability': probability,
                    'model_source': source_model,
                    'scores': scores,
                    'explanation': self._explain_prediction(all_features[i])
                })

            return results
            
        except Exception as e:
            logger.error(f"Batch ML calculation error: {e}")
            return [{
                'ml_score': 0,
                'is_match': False,
                'confidence': 'error',
                'threshold_used': self.threshold
            } for _ in batch_inputs]

    # ------------------------------------------------------------------
    # PREDICTION HELPERS
    # ------------------------------------------------------------------
    
    def _predict_with_tier(self, model_obj, features, feature_list, metadata, label, is_bundle=False):
        """Predict probability from a single model tier. Returns float 0-1."""
        if model_obj is None or not feature_list:
            return 0.0
        try:
            x = pd.DataFrame(
                [{f: features.get(f, 0) for f in feature_list}],
                columns=feature_list
            ).fillna(0)
            prob = float(model_obj.predict_proba(x)[0][1])
            logger.debug(f"{label} Score: {prob:.4f}")
            return prob
        except Exception as e:
            logger.error(f"{label} prediction failed: {e}")
            return 0.0
    
    def _weighted_ensemble(self, tier_scores):
        """
        Compute weighted ensemble probability from tier scores.
        Only active tiers (score > 0 because model was loaded) contribute.
        Falls back to MAX strategy if only one tier is active.
        
        Returns (probability, source_description).
        """
        active_tiers = {k: v for k, v in tier_scores.items() if v > 0}
        
        if not active_tiers:
            return 0.0, "No Active Models"
        
        if len(active_tiers) == 1:
            tier_name = next(iter(active_tiers))
            return active_tiers[tier_name], f"Solo: {tier_name}"
        
        # Renormalize weights for active tiers
        raw_weights = {k: self.ENSEMBLE_WEIGHTS.get(k, 0.1) for k in active_tiers}
        total_weight = sum(raw_weights.values())
        norm_weights = {k: w / total_weight for k, w in raw_weights.items()}
        
        probability = sum(tier_scores[k] * norm_weights[k] for k in active_tiers)
        
        # Determine dominant source
        top_tier = max(active_tiers, key=lambda k: active_tiers[k])
        source = f"Ensemble({len(active_tiers)}T, dominant={top_tier})"
        
        # If all tiers closely agree, note consensus
        values = list(active_tiers.values())
        if max(values) - min(values) < 0.05:
            source = f"Consensus({len(active_tiers)}T)"
        
        return float(probability), source
    
    def _get_tier_features(self, metadata, fallback_14=False):
        """Get feature list from metadata, with fallbacks."""
        feats = metadata.get('features', [])
        if not feats:
            feats = list(metadata.get('feature_importance', {}).keys())
        if not feats and fallback_14:
            feats = [
                'fuzzy_ratio', 'jaro_winkler', 'phonetic_score',
                'has_arabic_input', 'has_arabic_watchlist', 'mixed_script',
                'transliteration_score', 'first_name_match', 'last_name_match',
                'known_translit_pair', 'dob_exact_match', 'dob_days_diff',
                'dob_year_match', 'dob_bonus'
            ]
        return feats
    
    def _get_legacy_features(self):
        """Get feature list for the legacy V1 model."""
        if self.legacy_model and hasattr(self.legacy_model, 'feature_names_in_'):
            return list(self.legacy_model.feature_names_in_)
        feats = list(self.legacy_metadata.get('feature_importance', {}).keys())
        if not feats:
            feats = [
                'fuzzy_ratio', 'jaro_winkler', 'phonetic_score', 'dob_bonus',
                'is_common_name', 'network_score', 'tx_velocity_score',
                'media_risk_score', 'tenure_days'
            ]
        return feats

    # ------------------------------------------------------------------
    # FEATURE EXTRACTION (full 20-feature superset)
    # ------------------------------------------------------------------
    
    def _extract_features(self, input_name, watchlist_name, 
                         input_dob, watchlist_dob,
                         input_nationality, watchlist_nationality,
                         network_score, tx_velocity_score,
                         media_risk_score, tenure_days,
                         semantic_score=0.0):
        """
        Extract the full superset of features (20+ features) covering all model tiers.
        
        Produces features required for:
          - Master Unified (20 features)
          - 50K model (18 features, different naming convention)
          - 24K Enhanced (14 features)
          - Legacy V1 (9 features)
        """
        from rapidfuzz import fuzz
        import jellyfish
        
        input_norm = input_name.lower().strip() if input_name else ""
        watchlist_norm = watchlist_name.lower().strip() if watchlist_name else ""
        
        # ======== 0. PRE-PROCESSING (Normalization -> Transliteration) ========
        features = {}
        
        # Transliterate everything to common English script for fuzzy/phonetic logic
        if self.has_transliterator:
            features['has_arabic_input'] = 1.0 if self.transliterator.is_arabic(input_name) else 0.0
            features['has_arabic_watchlist'] = 1.0 if self.transliterator.is_arabic(watchlist_name) else 0.0
            
            def get_translit_str(name):
                t = self.transliterator.transliterate_arabic_to_english(name)
                return t[0] if isinstance(t, list) and t else str(t)

            input_norm = get_translit_str(input_name).lower().strip() if features['has_arabic_input'] else input_norm
            watchlist_norm = get_translit_str(watchlist_name).lower().strip() if features['has_arabic_watchlist'] else watchlist_norm
        else:
            features['has_arabic_input'] = 1.0 if (self.has_arabic_handler and self.arabic_handler.is_arabic(input_name)) else 0.0
            features['has_arabic_watchlist'] = 1.0 if (self.has_arabic_handler and self.arabic_handler.is_arabic(watchlist_name)) else 0.0

        comp_input = input_norm
        comp_watchlist = watchlist_norm
        
        # ======== 1. BASIC FUZZY MATCHING (on Transliterated Strings) ========
        features['fuzzy_ratio'] = float(fuzz.ratio(comp_input, comp_watchlist))
        features['jaro_winkler'] = float(jellyfish.jaro_winkler_similarity(comp_input, comp_watchlist) * 100)
        
        # NEW: Partial ratio & token set ratio (for 50K / Master models)
        features['partial_ratio'] = float(fuzz.partial_ratio(comp_input, comp_watchlist))
        features['token_set_ratio'] = float(fuzz.token_set_ratio(comp_input, comp_watchlist))
        
        # ======== 2. PHONETIC MATCHING ========
        try:
            input_soundex = jellyfish.soundex(comp_input) if comp_input else ""
            watchlist_soundex = jellyfish.soundex(comp_watchlist) if comp_watchlist else ""
            features['phonetic_score'] = 100.0 if input_soundex == watchlist_soundex else 0.0
            # NEW: Separate soundex score (same value, different key for 50K model)
            features['soundex_score'] = features['phonetic_score']
            features['semantic_score'] = float(semantic_score)
            
            # METAPHONE (for Translator module)
            input_metaphone = jellyfish.metaphone(comp_input) if comp_input else ""
            watchlist_metaphone = jellyfish.metaphone(comp_watchlist) if comp_watchlist else ""
            features['metaphone_score'] = 100.0 if input_metaphone == watchlist_metaphone else 0.0
        except:
            features['phonetic_score'] = 0.0
            features['soundex_score'] = 0.0
            features['metaphone_score'] = 0.0
            features['semantic_score'] = float(semantic_score)
        
        # ======== 3. ARABIC ENHANCEMENTS & TRANSLITERATION ========
        if self.has_transliterator:
            cross_lang_score = float(self.transliterator.calculate_cross_language_similarity(
                input_name, watchlist_name
            ))
            features['transliteration_score'] = cross_lang_score
            features['transliteration_match'] = cross_lang_score
            features['translit_score'] = cross_lang_score  # 50K model alias
            
            features['known_translit_pair'] = 1.0 if cross_lang_score >= 90.0 else 0.0
            features['known_pair'] = features['known_translit_pair']  # 50K model alias
            
            features['has_arabic_input'] = 1.0 if self.transliterator.is_arabic(input_name) else 0.0
            features['has_arabic_watchlist'] = 1.0 if self.transliterator.is_arabic(watchlist_name) else 0.0
            features['has_arabic_cust'] = features['has_arabic_input']      # 50K alias
            features['has_arabic_wtch'] = features['has_arabic_watchlist']   # 50K alias
            features['mixed_script'] = 1.0 if (features['has_arabic_input'] != features['has_arabic_watchlist']) else 0.0
            
            # Enhance with bundled transliteration maps
            if self.translit_map:
                names_to_check = [input_norm, watchlist_norm]
                for n in names_to_check:
                    parts = n.split()
                    for part in parts:
                        if part in self.translit_map:
                            features['known_translit_pair'] = 1.0
                            features['known_pair'] = 1.0
                            break
            
        elif self.has_arabic_handler and self.arabic_handler:
            features['has_arabic_input'] = 1.0 if self.arabic_handler.is_arabic(input_name) else 0.0
            features['has_arabic_watchlist'] = 1.0 if self.arabic_handler.is_arabic(watchlist_name) else 0.0
            features['has_arabic_cust'] = features['has_arabic_input']
            features['has_arabic_wtch'] = features['has_arabic_watchlist']
            features['mixed_script'] = 1.0 if (features['has_arabic_input'] + features['has_arabic_watchlist'] == 1.0) else 0.0

            vars1 = set(self.arabic_handler.get_all_variations(input_name))
            vars2 = set(self.arabic_handler.get_all_variations(watchlist_name))
            has_overlap = bool(vars1 & vars2)
            features['transliteration_match'] = 100.0 if has_overlap else 0.0
            features['transliteration_score'] = 100.0 if has_overlap else 0.0
            features['translit_score'] = 100.0 if has_overlap else 0.0
            features['known_translit_pair'] = 1.0 if has_overlap else 0.0
            features['known_pair'] = 1.0 if has_overlap else 0.0
        else:
            for key in ['transliteration_match', 'transliteration_score', 'translit_score',
                        'known_translit_pair', 'known_pair', 'has_arabic_input', 
                        'has_arabic_watchlist', 'has_arabic_cust', 'has_arabic_wtch', 'mixed_script']:
                features[key] = 0.0

        # ======== 4. NAME COMPONENT MATCHING ========
        input_parts = input_norm.split() if input_norm else []
        watchlist_parts = watchlist_norm.split() if watchlist_norm else []
        
        if self.has_arabic_handler and self.arabic_handler and features.get('mixed_script', 0.0) == 0.0:
            features['arabic_similarity'] = float(self.arabic_handler.calculate_arabic_similarity(
                input_name, watchlist_name
            ))
            comp1 = self.arabic_handler.extract_name_components(input_name)
            comp2 = self.arabic_handler.extract_name_components(watchlist_name)
            
            features['first_name_match'] = float(self.arabic_handler.calculate_arabic_similarity(
                comp1.get('first_name', '') or '', 
                comp2.get('first_name', '') or ''
            ))
            features['last_name_match'] = float(self.arabic_handler.calculate_arabic_similarity(
                comp1.get('last_name', '') or '',
                comp2.get('last_name', '') or ''
            ))
            # NEW: middle name match (for Master model)
            mid1 = comp1.get('middle_name', '') or ''
            mid2 = comp2.get('middle_name', '') or ''
            if mid1 and mid2:
                features['middle_name_match'] = float(self.arabic_handler.calculate_arabic_similarity(mid1, mid2))
            else:
                features['middle_name_match'] = 0.0
        else:
            features['arabic_similarity'] = features.get('transliteration_score', 0.0) if features.get('mixed_script', 0.0) == 1.0 else 0.0
            # Fallback component matching with basic string comparison
            features['first_name_match'] = float(fuzz.ratio(
                input_parts[0] if input_parts else '', 
                watchlist_parts[0] if watchlist_parts else ''
            ))
            features['last_name_match'] = float(fuzz.ratio(
                input_parts[-1] if len(input_parts) > 1 else '', 
                watchlist_parts[-1] if len(watchlist_parts) > 1 else ''
            ))
            # Middle name
            mid1 = ' '.join(input_parts[1:-1]) if len(input_parts) > 2 else ''
            mid2 = ' '.join(watchlist_parts[1:-1]) if len(watchlist_parts) > 2 else ''
            features['middle_name_match'] = float(fuzz.ratio(mid1, mid2)) if mid1 and mid2 else 0.0
        
        # 50K model aliases
        features['first_name_sim'] = features['first_name_match']
        features['last_name_sim'] = features['last_name_match']
        
        # ======== 4.5 N-GRAM SIMILARITY (for Translator Model) ========
        def ngram_sim(s1, s2, n):
            if not s1 or not s2 or len(s1) < n or len(s2) < n:
                return 0.0
            ng1 = set(s1[i:i+n] for i in range(len(s1)-n+1))
            ng2 = set(s2[i:i+n] for i in range(len(s2)-n+1))
            if not ng1 or not ng2: return 0.0
            return float(len(ng1 & ng2)) / float(len(ng1 | ng2)) * 100.0
            
        features['bigram_sim'] = ngram_sim(input_norm, watchlist_norm, 2)
        features['trigram_sim'] = ngram_sim(input_norm, watchlist_norm, 3)
        
        # ======== 5. NAME LENGTH FEATURES (NEW for 50K/Master) ========
        len_input = len(input_norm) if input_norm else 1
        len_watchlist = len(watchlist_norm) if watchlist_norm else 1
        features['name_len_ratio'] = float(min(len_input, len_watchlist) / max(len_input, len_watchlist))
        
        # Token count difference (Master only)
        features['token_count_diff'] = float(abs(len(input_parts) - len(watchlist_parts)))
        
        # ======== 6. DOB FEATURES (expanded) ========
        features['dob_exact_match'] = 0.0
        features['dob_exact'] = 0.0          # 50K alias
        features['dob_days_diff'] = 0.0
        features['dob_year_match'] = 0.0
        features['dob_bonus'] = 0.0
        
        if input_dob and watchlist_dob:
            input_dob_str = str(input_dob)[:10]
            watchlist_dob_str = str(watchlist_dob)[:10]
            
            if input_dob_str == watchlist_dob_str:
                features['dob_exact_match'] = 1.0
                features['dob_exact'] = 1.0
                features['dob_days_diff'] = 0.0
                features['dob_year_match'] = 1.0
                features['dob_bonus'] = 10.0
            else:
                if input_dob_str[:4] == watchlist_dob_str[:4]:
                    features['dob_year_match'] = 1.0
                    features['dob_bonus'] = 5.0
                else:
                    features['dob_year_match'] = 0.0
                    features['dob_bonus'] = -10.0
                
                try:
                    from datetime import datetime as dt
                    d1 = dt.strptime(input_dob_str, '%Y-%m-%d')
                    d2 = dt.strptime(watchlist_dob_str, '%Y-%m-%d')
                    features['dob_days_diff'] = float(abs((d1 - d2).days))
                except (ValueError, TypeError):
                    features['dob_days_diff'] = 9999.0
        
        # ======== 7. LEGACY CONTEXT FEATURES ========
        common_names = ['mohamed', 'muhammad', 'ahmed', 'ali', 'hassan', 
                       'hussein', 'ibrahim', 'omar', 'mahmoud', 'khalid']
        features['is_common_name'] = 1.0 if any(c in input_norm for c in common_names) else 0.0
        
        features['network_score'] = float(network_score)
        features['tx_velocity_score'] = float(tx_velocity_score)
        features['media_risk_score'] = float(media_risk_score)
        features['tenure_days'] = float(tenure_days)
        
        return features

    # ------------------------------------------------------------------
    # EXPLAINABILITY & UTILITIES
    # ------------------------------------------------------------------
    
    def _explain_prediction(self, feature_dict):
        """Simple explainability: return feature values weighted by importance."""
        # Try master metadata first, then fall back
        importance = self.metadata_master.get('feature_importance')
        if not importance:
            importance = self.metadata.get('feature_importance')
        if not importance:
            return None
        
        contributions = []
        for feat, imp in importance.items():
            val = feature_dict.get(feat, 0)
            contributions.append({'feature': feat, 'score': round(val * imp, 2)})
            
        contributions.sort(key=lambda x: abs(x['score']), reverse=True)
        return contributions[:3]  # Top 3

    def adjust_threshold(self, new_threshold):
        """Adjust decision threshold dynamically."""
        if 0.0 <= new_threshold <= 1.0:
            self.threshold = new_threshold
            logger.info(f"Threshold adjusted to {new_threshold}")
        else:
            raise ValueError("Threshold must be between 0.0 and 1.0")

    def train(self, data, version_tag=None):
        """Train logic preserved for backward compatibility (not using in inference)"""
        logger.warning("Training is disabled in this inference-optimized version.")
        return None
    
    def get_model_info(self):
        """Return a summary of loaded model tiers for diagnostics."""
        return {
            'tier_1_master': {
                'loaded': self.model_master is not None,
                'version': self.metadata_master.get('version', 'N/A'),
                'features': len(self.master_features),
            },
            'tier_2_50k': {
                'loaded': self.model_50k is not None,
                'version': self.metadata_50k.get('version', 'N/A'),
                'features': len(self.features_50k),
            },
            'tier_3_24k': {
                'loaded': self.model is not None,
                'version': self.metadata.get('version', 'N/A'),
                'features': len(self._get_tier_features(self.metadata, fallback_14=True)),
            },
            'tier_4_legacy': {
                'loaded': self.legacy_model is not None,
                'version': self.legacy_metadata.get('version', 'N/A'),
                'features': len(self._get_legacy_features()),
            },
            'ensemble_weights': self.ENSEMBLE_WEIGHTS,
            'threshold': self.threshold,
            'translit_map_size': len(self.translit_map),
            'last_name_map_size': len(self.last_name_map),
            'confusion_pairs_count': len(self.confusion_pairs),
        }

# ========================================
# FROM FILE: screening/ml_manager.py
# ========================================

import os
import joblib
import logging
import glob
import re
from datetime import datetime
import pandas as pd


logger = logging.getLogger(__name__)

class ModelVersionManager:
    """
    Manages loading, saving, and versioning of ML models.
    Format: ml_model_v{version}_{date}.pkl
    """
    def __init__(self, model_dir='.'):
        self.model_dir = model_dir
        self.current_model = None
        self.current_version = 0

    def get_latest_model_path(self):
        """Finds the model file with the highest version number."""
        pattern = os.path.join(self.model_dir, "ml_model_v*_*.pkl")
        files = glob.glob(pattern)
        
        if not files:
            # Fallback to legacy name if exists
            legacy = os.path.join(self.model_dir, "ml_model.pkl")
            if os.path.exists(legacy):
                return legacy
            return None

        # Parse versions
        latest_file = None
        max_version = -1
        
        for f in files:
            match = re.search(r"ml_model_v(\d+)_(\d+)\.pkl", f)
            if match:
                version = int(match.group(1))
                if version > max_version:
                    max_version = version
                    latest_file = f
        
        self.current_version = max_version
        return latest_file

    def load_model(self):
        """Loads the latest model or returns None."""
        model_path = self.get_latest_model_path()
        if model_path:
            logger.info(f"Loading ML model from: {model_path}")
            try:
                self.current_model = joblib.load(model_path)
                
                # IMPORTANT: Disable multi-threading thrashing during single-file/predict sequence
                if hasattr(self.current_model, 'n_jobs'):
                    self.current_model.n_jobs = 1
                if hasattr(self.current_model, 'verbose'):
                    self.current_model.verbose = 0
                    
                return self.current_model
            except Exception as e:
                logger.error(f"Failed to load model {model_path}: {e}")
                return None
        else:
            logger.warning("No ML model found.")
            return None

    def save_new_version(self, model):
        """Saves the model with an incremented version number."""
        next_version = self.current_version + 1
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"ml_model_v{next_version}_{date_str}.pkl"
        path = os.path.join(self.model_dir, filename)
        
        logger.info(f"Saving new model version to: {path}")
        joblib.dump(model, path)
        self.current_version = next_version
        self.current_model = model
        return path

class OnlineLearner:
    """
    Handles incremental updates to the model based on feedback.
    """
    def __init__(self, model_manager: ModelVersionManager):
        self.manager = model_manager
        self.calibrator = MLScoreCalibrator() # Uses default logic for feature extraction
        
        # Buffer for batch updates (updates every N feedback items)
        self.feedback_buffer = [] 
        self.BATCH_SIZE = 10 

    def log_feedback(self, candidate_data, actual_label):
        """
        Log user feedback (True Match vs False Positive).
        candidate_data: Dict containing features or raw data to extract features.
        actual_label: 1 for Match, 0 for False Positive.
        """
        # Extract features if not already extracted
        if 'features' not in candidate_data:
            # We need the context (names, scores) to extract features
            # This assumes candidate_data has match_details
            features = self.calibrator._extract_features(candidate_data)
        else:
            features = candidate_data['features']
            
        self.feedback_buffer.append({
            'features': features,
            'label': actual_label
        })
        
        logger.info(f"Feedback logged. Buffer size: {len(self.feedback_buffer)}")
        
        if len(self.feedback_buffer) >= self.BATCH_SIZE:
            self._retrain_and_save()

    def _retrain_and_save(self):
        """
        Retrains the model with buffered data and saves a new version.
        Note: RandomForest doesn't support partial_fit easily, so we usually
        need to retrain on the full dataset + new data, OR use a warm_start approach.
        For simplicity/robustness here, we'll assume we load the current model 
        and if it supports incremental learning we use it, otherwise we might just 
        re-fit if we had the full training set.
        
        BETTER APPROACH for Production with RandomForest:
        - Save feedback to DB.
        - Scheduled job retrains model daily with ALL data (historic + feedback).
        
        FOR THIS PROTOTYPE:
        We will append to a 'training_feedback.csv' and trigger a quick retrain 
        if we have access to the original training set, or just warn that 
        RandomForest needs full retraining.
        """
        logger.info("Batch threshold reached. Saving feedback for future retraining.")
        
        # Save buffer to disk
        df = pd.DataFrame([item['features'] for item in self.feedback_buffer])
        df['target'] = [item['label'] for item in self.feedback_buffer]
        
        feedback_file = os.path.join(self.manager.model_dir, 'feedback_data.csv')
        write_header = not os.path.exists(feedback_file)
        
        df.to_csv(feedback_file, mode='a', header=write_header, index=False)
        
        # Clear buffer
        self.feedback_buffer = []
        
        # TODO: Trigger full retraining workflow (separate script)
        logger.info(f"Feedback saved to {feedback_file}. Model retraining pending scheduled job.")

# ========================================
# FROM FILE: scripts/retrain_model.py
# ========================================

import os
import sys
import json
import sqlite3
import shutil
import logging
from datetime import datetime

# Add parent directory to path to import screening modules



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ModelRetrainer:
    def __init__(self, db_path='complynex.db', min_f1_threshold=0.6):
        self.db_path = db_path
        self.min_f1_threshold = min_f1_threshold
        self.calibrator = MLScoreCalibrator()
        self.model_dir = os.path.dirname(self.calibrator.MODEL_PATH)
        self.backup_dir = os.path.join(self.model_dir, 'backups')
        
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)

    def _get_training_data(self):
        """Pull historical screening results with feedback/status labels."""
        conn = db_pool.checkout_connection()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # We look for screenings that have been resolved
            # matches is stored as a JSON string in the database
            cur.execute("SELECT matches, status FROM screening_results WHERE status IN ('TRUE_HIT', 'FALSE_POSITIVE', 'DISMISSED')")
            rows = cur.fetchall()

            training_data = []
            for row in rows:
                try:
                    matches = json.loads(row['matches'])
                    label = 1 if row['status'] == 'TRUE_HIT' else 0

                    for match in matches:
                        # Extract features from the match info
                        # Note: In a real system, we'd store the features separately during screening
                        # to avoid re-calculating or losing context.
                        features = {
                            'fuzzy_ratio': match.get('fuzzy_ratio', 0),
                            'jaro_winkler': match.get('jaro_winkler', 0),
                            'phonetic_score': match.get('phonetic_score', 0),
                            'dob_bonus': match.get('dob_bonus', 0),
                            'is_common_name': match.get('is_common_name', 0),
                            'network_score': match.get('network_score', 0),
                            'tx_velocity_score': match.get('tx_velocity_score', 0),
                            'media_risk_score': match.get('media_risk_score', 0),
                            'tenure_days': match.get('tenure_days', 0),
                            'label': label
                        }
                        training_data.append(features)
                except Exception as e:
                    logger.warning(f"Failed to parse match data: {e}")

            return training_data
        finally:
            db_pool.return_connection(conn)

    def backup_current_model(self):
        """Create a backup of the current model and metadata."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if os.path.exists(self.calibrator.MODEL_PATH):
            shutil.copy2(
                self.calibrator.MODEL_PATH, 
                os.path.join(self.backup_dir, f'ml_model_{timestamp}.pkl')
            )
        if os.path.exists(self.calibrator.METADATA_PATH):
            shutil.copy2(
                self.calibrator.METADATA_PATH, 
                os.path.join(self.backup_dir, f'model_metadata_{timestamp}.json')
            )
        
        # Also symlink to 'last_stable'
        shutil.copy2(self.calibrator.MODEL_PATH, os.path.join(self.backup_dir, 'ml_model_stable.pkl'))
        shutil.copy2(self.calibrator.METADATA_PATH, os.path.join(self.backup_dir, 'model_metadata_stable.json'))
        
        logger.info(f"Backup created in {self.backup_dir}")
        return timestamp

    def rollback(self):
        """Restore model from 'last_stable' backup."""
        stable_model = os.path.join(self.backup_dir, 'ml_model_stable.pkl')
        stable_meta = os.path.join(self.backup_dir, 'model_metadata_stable.json')
        
        if os.path.exists(stable_model) and os.path.exists(stable_meta):
            shutil.copy2(stable_model, self.calibrator.MODEL_PATH)
            shutil.copy2(stable_meta, self.calibrator.METADATA_PATH)
            logger.info("Rollback successful. Restored stable version.")
        else:
            logger.error("Rollback failed: No stable backup found.")

    def run_retraining(self):
        """Main execution flow for retraining."""
        logger.info("Starting automated retraining process...")
        
        data = self._get_training_data()
        if len(data) < 5:  # Arbitrary threshold for demo
            logger.warning(f"Insufficient training data (found {len(data)} rows). Aborting.")
            return False
            
        # 1. Backup
        self.backup_current_model()
        
        # 2. Train
        try:
            version_tag = datetime.now().strftime('%Y.%m.%d-%v')
            self.calibrator.train(data, version_tag=version_tag)
        except Exception as e:
            logger.error(f"Retraining failed during execution: {e}")
            self.rollback()
            return False
            
        # 3. Validate Governance Metrics
        metadata = self.calibrator.metadata
        f1 = metadata.get('metrics', {}).get('f1_score', 0)
        
        logger.info(f"New model F1 Score: {f1:.4f}")
        
        if f1 < self.min_f1_threshold:
            logger.warning(f"Model performance ({f1:.4f}) below threshold ({self.min_f1_threshold}). Rolling back.")
            self.rollback()
            return False
        
        logger.info("Retraining successful. New model deployed.")
        return True

if __name__ == '__main__':
    retrainer = ModelRetrainer()
    success = retrainer.run_retraining()
    sys.exit(0 if success else 1)

# ========================================
# FROM FILE: scripts/seed_training_data.py
# ========================================

import os
import sys
import logging
import random

# Add parent directory to path



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_synthetic_data(num_samples=200):
    data = []
    
    # Generate Matches (Positive Class)
    for _ in range(num_samples // 2):
        # Matches generally have high scores and varying risk features
        fuzzy = random.randint(85, 100)
        jaro = random.uniform(0.85, 1.0)
        phonetic = random.randint(80, 100)
        dob = random.choice([0, 5, 10]) 
        common = random.choice([0, 0, 1])
        
        # High-risk entities might have higher network/tx scores
        network = random.uniform(40, 100) if random.random() > 0.5 else random.uniform(0, 30)
        tx_vel = random.uniform(50, 100) if random.random() > 0.4 else random.uniform(0, 40)
        media = random.uniform(60, 100) if random.random() > 0.6 else random.uniform(0, 20)
        tenure = random.randint(0, 365)
        
        data.append({
            'fuzzy_ratio': fuzzy,
            'jaro_winkler': jaro,
            'phonetic_score': phonetic,
            'dob_bonus': dob,
            'is_common_name': common,
            'network_score': network,
            'tx_velocity_score': tx_vel,
            'media_risk_score': media,
            'tenure_days': tenure,
            'is_match': 1
        })
        
    # Generate Non-Matches (Negative Class)
    for _ in range(num_samples // 2):
        fuzzy = random.randint(0, 75)
        jaro = random.uniform(0.0, 0.75)
        phonetic = random.randint(0, 60)
        dob = 0
        common = random.choice([0, 1])
        
        # Low risk features usually for non-matches, unless hard negative
        network = random.uniform(0, 30)
        tx_vel = random.uniform(0, 30)
        media = random.uniform(0, 20)
        tenure = random.randint(30, 1000) # Existing customers less likely to be new sanctions hits%s
        
        # Hard Negatives
        if random.random() > 0.8:
            fuzzy = random.randint(75, 90)
            jaro = random.uniform(0.75, 0.9)
            phonetic = random.randint(60, 80)
            dob = 0
            network = random.uniform(0, 50)
            
        data.append({
            'fuzzy_ratio': fuzzy,
            'jaro_winkler': jaro,
            'phonetic_score': phonetic,
            'dob_bonus': max(0, dob),
            'is_common_name': common,
            'network_score': network,
            'tx_velocity_score': tx_vel,
            'media_risk_score': media,
            'tenure_days': tenure,
            'is_match': 0
        })
        
    return data

def seed_model():
    print("Generating synthetic training data...")
    data = generate_synthetic_data(500)
    
    print(f"Training ML Model with {len(data)} samples...")
    calibrator = MLScoreCalibrator()
    calibrator.train(data)
    
    # Test Prediction
    test_case = {
        'fuzzy_ratio': 95,
        'jaro_winkler': 0.98,
        'phonetic_score': 100,
        'dob_bonus': 10,
        'is_common_name': 0,
        'network_score': 10,
        'tx_velocity_score': 5,
        'media_risk_score': 0,
        'tenure_days': 100
    }
    prob, expl = calibrator.predict_probability(test_case)
    print(f"Test Prediction (Strong Match): {prob:.4f}")
    
    test_case_weak = {
        'fuzzy_ratio': 50,
        'jaro_winkler': 0.6,
        'phonetic_score': 40,
        'dob_bonus': 0,
        'is_common_name': 1,
        'network_score': 0,
        'tx_velocity_score': 0,
        'media_risk_score': 0,
        'tenure_days': 500
    }
    prob_weak, expl_weak = calibrator.predict_probability(test_case_weak)
    print(f"Test Prediction (Weak Match): {prob_weak:.4f}")

if __name__ == "__main__":
    seed_model()
