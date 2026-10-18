#!/usr/bin/env bash
# =============================================================================
# ComplyNex — set the outbound email password.
#
# Everything is automated except typing the password itself. It is read with a
# hidden prompt, so it never appears on screen, never enters your shell history,
# and never passes through a chat transcript.
#
#   sudo /var/www/complynex/scripts/setup_email.sh
# =============================================================================
set -euo pipefail

ENV_FILE=/var/www/complynex/.env
VENV_PY=/var/www/complynex/venv/bin/python

[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE not found"; exit 1; }

echo "ComplyNex — outbound email setup"
echo "================================"
echo

CURRENT_USER=$(grep -E '^EMAIL_USER=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d "'\"" || true)
read -rp "Email address to send from [${CURRENT_USER:-none set}]: " ADDR
ADDR="${ADDR:-$CURRENT_USER}"
[[ -n "$ADDR" ]] || { echo "ERROR: an address is required"; exit 1; }

echo
echo "Now the password."
echo "  - Gmail: use a 16-character App Password, not your account password."
echo "    Create one at myaccount.google.com/apppasswords"
echo "  - Spaces are stripped automatically."
echo
read -rp "SMTP host [smtp.hostinger.com]: " HOST
HOST="${HOST:-smtp.hostinger.com}"
read -rp "SMTP port  [465]: " PORT
PORT="${PORT:-465}"
echo
read -rsp "Password (hidden): " PW1; echo
read -rsp "Confirm         : " PW2; echo
[[ "$PW1" == "$PW2" ]] || { echo "ERROR: the two entries do not match"; exit 1; }
PW1="${PW1// /}"
[[ -n "$PW1" ]] || { echo "ERROR: password is empty"; exit 1; }

cp "$ENV_FILE" "${ENV_FILE}.bak_$(date +%Y%m%d_%H%M%S)"

# Rewrite the three keys in place; append any that are absent.
python3 - "$ENV_FILE" "$ADDR" "$PW1" "$HOST" "$PORT" <<'PYEOF'
import io, sys
path, addr, pw, host, port = sys.argv[1:6]
want = {'EMAIL_USER': addr, 'EMAIL_PASS': pw, 'EMAIL_MOCK_MODE': 'False',
        'MAIL_SERVER': host, 'MAIL_PORT': port, 'MAIL_DEFAULT_SENDER': addr,
        'GMAIL_USER': addr, 'GMAIL_PASS': pw}
lines, seen = [], set()
for line in io.open(path, encoding='utf-8'):
    k = line.split('=', 1)[0].strip()
    if k in want:
        lines.append(f"{k}={want[k]}\n"); seen.add(k)
    else:
        lines.append(line)
for k, v in want.items():
    if k not in seen:
        lines.append(f"{k}={v}\n")
io.open(path, 'w', encoding='utf-8').writelines(lines)
PYEOF

chown complynex:complynex "$ENV_FILE"
chmod 600 "$ENV_FILE"
unset PW1 PW2

echo
echo "Saved. Restarting ComplyNex (about 30 seconds)..."
systemctl restart complynex
sleep 32

echo
echo "Verifying delivery..."
echo "---------------------"
sudo -u complynex env HOME=/tmp "$VENV_PY" /var/www/complynex/scripts/mailcheck.py "$ADDR" 2>/dev/null \
  | grep -vE '^(INFO|WARNING|DEBUG)' || true

echo
echo "If all three checks say OK, declaration and case reminders now go out by"
echo "email as well as in-app. Nothing else needs changing."
