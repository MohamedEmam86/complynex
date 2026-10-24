-- ESG reference texts: regulator-neutral wording (the company's regulator may be CBE, FRA or another).
BEGIN;
UPDATE esg_frameworks SET description =
 'ComplyNex''s in-house ESG scoring framework for Egyptian financial-sector companies. Combines the three classic ESG pillars with a fourth Regulatory pillar reflecting the supervisory expectations of the company''s regulator.'
 WHERE code = 'iesg_egypt' AND description LIKE '%PSPs/fintechs%';
UPDATE esg_indicators SET description = REPLACE(description, 'Law 80/2002 and CBE AML/CFT regulations', 'Law 80/2002 and the regulator''s AML/CFT rules')
 WHERE description LIKE '%CBE AML/CFT regulations%';
UPDATE esg_indicators SET name = 'Regulatory Reporting Track Record' WHERE name = 'CBE Regulatory Reporting Track Record';
UPDATE esg_indicators SET description = REPLACE(description, 'mandatory CBE/FRA submissions', 'mandatory regulatory submissions')
 WHERE description LIKE '%mandatory CBE/FRA submissions%';
UPDATE esg_indicators SET description = REPLACE(description, 'CBE cybersecurity framework alignment', 'Alignment with the regulator''s cybersecurity framework')
 WHERE description LIKE '%CBE cybersecurity framework alignment%';
UPDATE esg_materiality_topics SET gri_reference = 'N/A — regulator-specific' WHERE gri_reference = 'N/A — CBE-specific';
COMMIT;
