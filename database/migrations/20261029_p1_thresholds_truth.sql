-- Phase 1: the screening_config thresholds were never read by the engine (it uses 75 / 80 / 95).
-- Store the values the engine really applies so every screen and report shows the truth.
UPDATE screening_config SET config_value = '95', updated_at = CURRENT_TIMESTAMP WHERE config_key = 'confirmed_hit_threshold';
UPDATE screening_config SET config_value = '80', updated_at = CURRENT_TIMESTAMP WHERE config_key = 'potential_match_threshold';
UPDATE screening_config SET config_value = '75', updated_at = CURRENT_TIMESTAMP WHERE config_key = 'low_match_threshold';
