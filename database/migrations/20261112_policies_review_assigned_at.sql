-- Policies: a review assignment records when it was made (the "Assigned on"
-- column of My reviews showed nothing for rows inserted without it).
ALTER TABLE policy_review_workflow
    ALTER COLUMN created_at SET DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS');
