# Access security and audit integrity (Phase 6: P6-5, P6-6)

## Sign-in rules

| Rule | Default | Setting (.env) |
|---|---|---|
| Lock after failed sign-ins (password or MFA code) | 5 in a row | `LOGIN_LOCK_AFTER` |
| First lock | 15 minutes, doubled on every further lock (back-off) | `LOGIN_LOCK_MINUTES` |
| Longest lock | 24 hours | `LOGIN_LOCK_MAX_MINUTES` |
| Idle session ends after | 60 minutes | `SESSION_IDLE_MINUTES` |
| Any session ends after | 12 hours | `SESSION_ABSOLUTE_HOURS` |
| "Remember me" lasts | 14 days | `REMEMBER_DAYS` |
| Password: no re-use of the last | 5 passwords | `PASSWORD_HISTORY` |
| MFA enrolment grace — admin / compliance roles | 0 days (enrol at first login) | `MFA_ENROLL_GRACE_DAYS_PRIVILEGED` |
| MFA enrolment grace — other back-office users | 7 days | `MFA_ENROLL_GRACE_DAYS` |

A successful sign-in, or an administrator's **Unlock** (Administration → User access review),
clears the failures and the back-off. Every lock, unlock, MFA change and session end is in the audit trail.

MFA backup codes are stored as salted hashes. Codes issued before this change keep working
(they are hashed when first used, or all at once with `scripts/hash_mfa_backup_codes.py --apply`).

The demo instance never requires MFA.

## Audit trail integrity

`audit_logs` is append-only (the database refuses UPDATE / DELETE, the app user has no
UPDATE / DELETE / TRUNCATE right) and each record carries the SHA-256 fingerprint of the one
before it. Every day at 05:47 `scripts/audit_anchor.py` recomputes the whole chain and saves a
checkpoint (`audit_anchors`, itself chained and append-only, plus a copy in
`logs/audit_anchors.log`). A trail changed or cut by a database superuser no longer matches the
earlier checkpoints. Status and "check now": Administration → Audit trail integrity.

## Break-glass (nobody can sign in to fix an account)

On the server, as the app user:

    sudo -u complynex bash -c 'set -a; . /var/www/complynex/.env; set +a; cd /var/www/complynex && \
      venv/bin/python scripts/break_glass_reset_mfa.py --email USER@DOMAIN --reason "why, ticket ..."'

That is a dry run. Repeat with `--apply`: the user's second factor is cleared, the account is
unlocked, all their sessions end, and they enrol again at the next sign-in. The action is written to
`mfa_audit` and to the audit trail with the reason and the server user who ran it. The password is not
changed (use the normal reset).

## الدخول الطارئ (بالعربي باختصار)

لو مفيش حد يقدر يدخل يصلح الحساب (موبايل ضاع ومفيش أكواد احتياطية، أو المدير الوحيد اتقفل):
شغّل الأمر اللي فوق على السيرفر بالإيميل وسبب واضح (تجربة)، وبعدين نفس الأمر مع `--apply`.
بيمسح التحقق الثنائي، ويفك القفل، ويقفل كل الجلسات، والمستخدم يسجل التحقق من جديد أول دخول.
كل ده بيتسجل في سجل التدقيق.
