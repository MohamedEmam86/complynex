-- Policy Review Workflow Schema

CREATE TABLE IF NOT EXISTS policy_review_workflow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    reviewer_id INTEGER NOT NULL,
    stage_name TEXT NOT NULL, -- e.g., 'Initial Review', 'Compliance Approval', 'Management Approval'
    status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    comments TEXT,
    review_date DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (policy_id) REFERENCES policies (id),
    FOREIGN KEY (reviewer_id) REFERENCES users (id)
);

-- Add review-related columns to policies table if they don't exist
-- SQLite doesn't support ADD COLUMN IF NOT EXISTS easily, so we usually rely on models or separate scripts.
-- For this workflow, the external table handles most of the logic.
