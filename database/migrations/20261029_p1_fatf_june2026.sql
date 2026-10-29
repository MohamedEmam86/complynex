-- Phase 1 (G6): FATF lists as published after the Paris plenary of 19 June 2026.
-- Call for action: Iran, DPRK, Myanmar (unchanged).
-- Increased monitoring: Algeria and Namibia removed (June 2026); Kuwait and Papua New Guinea added
-- (February 2026); Bosnia and Herzegovina and Iraq added (June 2026).
UPDATE high_risk_countries SET is_active = 0, updated_at = NOW(),
       notes = 'Removed from FATF increased monitoring on 19 June 2026'
 WHERE country_code IN ('DZ', 'NA') AND risk_category = 'INCREASED_MONITORING';
INSERT INTO high_risk_countries (country_code, country_name, name_ar, aliases, risk_category, source, effective_date, notes, is_active, updated_at)
SELECT v.* FROM (VALUES
  ('BA', 'Bosnia and Herzegovina', 'البوسنة والهرسك', 'Bosnia|Bosnian|BIH', 'INCREASED_MONITORING', 'FATF public statement, 19 June 2026', '2026-06-19', 'Added June 2026', 1, NOW()),
  ('IQ', 'Iraq', 'العراق', 'Iraqi|IRQ', 'INCREASED_MONITORING', 'FATF public statement, 19 June 2026', '2026-06-19', 'Added June 2026', 1, NOW()),
  ('KW', 'Kuwait', 'الكويت', 'Kuwaiti|KWT', 'INCREASED_MONITORING', 'FATF public statement, 13 February 2026', '2026-02-13', 'Added February 2026', 1, NOW()),
  ('PG', 'Papua New Guinea', 'بابوا غينيا الجديدة', 'PNG', 'INCREASED_MONITORING', 'FATF public statement, 13 February 2026', '2026-02-13', 'Added February 2026', 1, NOW())
) AS v(country_code, country_name, name_ar, aliases, risk_category, source, effective_date, notes, is_active, updated_at)
WHERE NOT EXISTS (SELECT 1 FROM high_risk_countries h WHERE h.country_code = v.country_code AND h.is_active = 1);
UPDATE high_risk_countries SET source = 'FATF public statement, 19 June 2026', effective_date = '2026-06-19', updated_at = NOW()
 WHERE is_active = 1 AND source LIKE 'Default seed list%';
