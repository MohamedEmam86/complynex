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

"""Merchant KYB approval workflow: allowed transitions, four-eyes and the
status history. Pure rules first (unit-tested), then the history writer."""

FINAL = ('APPROVED', 'REJECTED')
EDITABLE = ('PENDING', 'SENT', 'SUBMITTED', 'UNDER_REVIEW')   # statuses an edit may set
DECIDABLE = ('SUBMITTED', 'UNDER_REVIEW')                     # waiting for a decision
SUBMITTABLE = ('PENDING', 'SENT')
RESUBMITTABLE = ('REJECTED',)                                 # corrected after a rejection
MIN_REASON = 10


def submit_error(status, note=None):
    """Why a submission for approval is refused (untranslated), or None. A
    rejected merchant may be resubmitted once corrected; the resubmission must
    say what was corrected (the rejection stays in the status history)."""
    st = (status or 'PENDING').upper()
    if st in RESUBMITTABLE:
        if len((note or '').strip()) < MIN_REASON:
            return 'Describe what was corrected since the rejection (at least 10 characters).'
        return None
    if st not in SUBMITTABLE:
        return 'Only a pending merchant can be submitted for approval.'
    return None


def four_eyes_error(approver_id, created_by=None, submitted_by=None):
    """The approver must be neither the person who created the merchant nor the
    one who submitted it for approval. Returns an untranslated reason or None."""
    if approver_id is None:
        return None
    if submitted_by is not None and approver_id == submitted_by:
        return 'Four-eyes: you submitted this merchant for approval; another person must decide.'
    if created_by is not None and approver_id == created_by:
        return 'Four-eyes: you created this merchant; another person must decide.'
    return None


def decision_error(merchant, approver_id, action, reason=None):
    """Why an approve / reject decision is refused (untranslated), or None."""
    st = (merchant.get('kyc_status') or 'PENDING').upper()
    if st in FINAL:
        return 'This merchant has already been decided.'
    if action == 'approve' and st not in DECIDABLE:
        return 'Only a merchant submitted for approval can be approved.'
    if action == 'reject' and len((reason or '').strip()) < MIN_REASON:
        return 'Give the rejection reason (at least 10 characters).'
    return four_eyes_error(approver_id, merchant.get('created_by'), merchant.get('submitted_by'))


def edit_status(current, requested):
    """Status an ordinary edit may leave the merchant in: final decisions are
    only made with the approve / reject actions."""
    cur = (current or 'PENDING').upper()
    if cur in FINAL:
        return cur
    req = (requested or '').upper()
    return req if req in EDITABLE else cur


def record(db, merchant_id, from_status, to_status, action, user_id=None, reason=None, actor_label=None):
    db.execute("""INSERT INTO merchant_status_history (merchant_id, from_status, to_status, action, reason, user_id,
                  actor_label) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (merchant_id, from_status, to_status, action, reason, user_id, actor_label))


def history(db, merchant_id):
    return [dict(r) for r in db.execute(
        """SELECT h.*, TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS user_name
             FROM merchant_status_history h LEFT JOIN users u ON u.id = h.user_id
            WHERE h.merchant_id = %s ORDER BY h.id DESC""", (merchant_id,)).fetchall()]
