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

"""
Policy versioning. Every version is its own `policies` row:

    v1 (published) --New version--> v2 (draft, previous_version_id = v1)
    v2 goes through the normal approval stages; publishing v2 archives v1
    (read-only, superseded_by_id = v2) and employees must acknowledge v2 —
    acknowledgements of v1 stay attached to v1 as its history.

All versions share version_group_id (the id of the first version).
"""

import re
from datetime import datetime

from database.db import get_db

# Statuses in which a version can no longer change.
LOCKED_STATUSES = ('published', 'archived')
CLOSED_STATUSES = ('published', 'archived')

COPY_COLUMNS = ('policy_number', 'policy_name', 'category_id', 'effective_date', 'review_date',
                'next_review_date', 'owner_id', 'owner_function', 'description', 'content', 'attachment_path',
                'regulatory_reference', 'cbe_requirement', 'is_public', 'issuing_date', 'approval_cycle',
                'is_mandatory', 'department_id', 'is_internal', 'document_type_id', 'org_unit_id',
                'requires_board_approval')


def next_version(version):
    """'1.0' -> '2.0', '3' -> '4', 'v2.1' -> 'v3.0', '' -> '2.0'."""
    v = str(version or '').strip()
    m = re.match(r'^([^\d]*)(\d+)(?:\.(\d+))?', v)
    if not m:
        return '2.0'
    prefix, major, minor = m.group(1), int(m.group(2)), m.group(3)
    return f'{prefix}{major + 1}.0' if (minor is not None or not prefix and '.' in v) else f'{prefix}{major + 1}'


def is_locked(status):
    """Published and archived versions are read-only."""
    return (status or '').lower() in LOCKED_STATUSES


def new_version_error(status, open_draft_id=None, change_summary=''):
    """Why a new version cannot be started from a version in `status`, or None."""
    if (status or '').lower() != 'published':
        return 'a new version can only be started from the published version'
    if open_draft_id:
        return 'a new version of this policy is already in progress'
    if not (change_summary or '').strip():
        return 'describe what changes in the new version'
    return None


def group_id(row):
    return row.get('version_group_id') or row['id']


def versions(policy_id, db=None):
    """All versions of the policy's family, oldest first, with acknowledgement counts."""
    db = db or get_db()
    row = db.execute("SELECT id, version_group_id FROM policies WHERE id = %s", (policy_id,)).fetchone()
    if not row:
        return []
    gid = group_id(dict(row))
    return [dict(r) for r in db.execute("""
        SELECT p.id, p.version, p.status, p.change_summary, p.created_at, p.created_by, p.published_at,
               p.published_by, p.superseded_at, p.superseded_by_id, p.previous_version_id, p.approval_date,
               NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS creator_name,
               NULLIF(TRIM(COALESCE(pb.first_name, '') || ' ' || COALESCE(pb.last_name, '')), '') AS publisher_name,
               (SELECT count(*) FROM policy_acknowledgments a WHERE a.policy_id = p.id) AS ack_count
        FROM policies p
        LEFT JOIN users u ON u.id = p.created_by
        LEFT JOIN users pb ON pb.id = p.published_by
        WHERE p.id = %s OR p.version_group_id = %s
        ORDER BY p.id
    """, (gid, gid)).fetchall()]


def open_draft(policy_id, db=None):
    """The version of this family still being prepared (not published/archived), if any."""
    for v in versions(policy_id, db):
        if (v['status'] or '').lower() not in CLOSED_STATUSES and v['id'] != policy_id:
            return v
    return None


def current_published(policy_id, db=None):
    pub = [v for v in versions(policy_id, db) if (v['status'] or '').lower() == 'published']
    return pub[-1] if pub else None


def create_new_version(policy_id, change_summary, user_id, db=None):
    """Copy the published version into a new draft. Returns the new policy id."""
    db = db or get_db()
    src = dict(db.execute("SELECT * FROM policies WHERE id = %s", (policy_id,)).fetchone())
    gid = group_id(src)
    cols = [c for c in COPY_COLUMNS if c in src]
    values = [src[c] for c in cols]
    cols += ['version', 'status', 'previous_version_id', 'version_group_id', 'change_summary',
             'created_by', 'updated_by', 'created_at', 'updated_at']
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    values += [next_version(src.get('version')), 'draft', policy_id, gid, change_summary.strip(),
               user_id, user_id, now, now]
    new_id = db.execute(
        f"INSERT INTO policies ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
        values).fetchone()['id']
    if not src.get('version_group_id'):
        db.execute("UPDATE policies SET version_group_id = %s WHERE id = %s", (gid, policy_id))
    # Same audience and same supporting documents as the version it revises.
    db.execute("""INSERT INTO policy_applicability (policy_id, org_unit_id, include_descendants, is_exclusion,
                      match_code, match_type_id, root_unit_id, created_by)
                  SELECT %s, org_unit_id, include_descendants, is_exclusion, match_code, match_type_id,
                         root_unit_id, %s FROM policy_applicability WHERE policy_id = %s""",
               (new_id, user_id, policy_id))
    db.execute("""INSERT INTO policy_attachments (policy_id, filename, file_path, file_size, uploaded_by, uploaded_at)
                  SELECT %s, filename, file_path, file_size, uploaded_by, uploaded_at
                  FROM policy_attachments WHERE policy_id = %s""", (new_id, policy_id))
    db.commit()
    if src.get('document_type_id'):
        try:
            from services import document_service as D
            D.instantiate_workflow(new_id, int(src['document_type_id']),
                                   int(src['org_unit_id']) if src.get('org_unit_id') else None)
        except Exception:
            db.rollback()
    return new_id


def on_published(policy_id, user_id, db=None):
    """Record who published, and archive the version(s) this one supersedes.
    Returns the ids archived."""
    db = db or get_db()
    now = datetime.now()
    db.execute("UPDATE policies SET published_at = %s, published_by = %s WHERE id = %s", (now, user_id, policy_id))
    row = dict(db.execute("SELECT id, version_group_id FROM policies WHERE id = %s", (policy_id,)).fetchone())
    archived = []
    if row.get('version_group_id'):
        gid = row['version_group_id']
        for r in db.execute("""SELECT id FROM policies WHERE (id = %s OR version_group_id = %s) AND id <> %s
                               AND LOWER(status) = 'published'""", (gid, gid, policy_id)).fetchall():
            db.execute("""UPDATE policies SET status = 'archived', superseded_by_id = %s, superseded_at = %s,
                          updated_by = %s, updated_at = %s WHERE id = %s""",
                       (policy_id, now, user_id, now.strftime('%Y-%m-%d %H:%M:%S'), r['id']))
            archived.append(r['id'])
    db.commit()
    return archived


def file_still_used(file_path, exclude_attachment_id=None, db=None):
    """A file shared by several versions must not be deleted from disk."""
    db = db or get_db()
    if db.execute("SELECT 1 FROM policy_attachments WHERE file_path = %s AND id <> %s LIMIT 1",
                  (file_path, exclude_attachment_id or 0)).fetchone():
        return True
    return bool(db.execute("SELECT 1 FROM policies WHERE attachment_path = %s LIMIT 1", (file_path,)).fetchone())
