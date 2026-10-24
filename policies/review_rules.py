"""Policy review / approval-stage rules (no database access; unit-tested).

Maker-checker: the person who drafted a policy version (its created_by)
cannot review it or decide any of its approval stages, and cannot be assigned
as its reviewer. A review decision is one of a fixed set of values."""

REVIEW_DECISIONS = ('approved', 'rejected')


def author_error(user_id, author_id):
    """Untranslated reason when `user_id` drafted the version, else None."""
    if user_id is not None and author_id is not None and int(user_id) == int(author_id):
        return 'Maker-checker: you drafted this version, so another person must review and approve it.'
    return None


def reviewer_assignment_error(reviewer_id, author_id):
    if reviewer_id is None:
        return 'Select a reviewer.'
    if author_id is not None and int(reviewer_id) == int(author_id):
        return 'The author of this version cannot be assigned as its reviewer.'
    return None


def review_error(user_id, author_id, decision, comments, has_pending_assignment):
    """Why a review decision is refused (untranslated), or None."""
    if not has_pending_assignment:
        return 'You have no pending review assigned on this policy.'
    err = author_error(user_id, author_id)
    if err:
        return err
    if decision not in REVIEW_DECISIONS:
        return 'Invalid decision.'
    if decision == 'rejected' and not (comments or '').strip():
        return 'Please give the reason for rejecting.'
    return None
