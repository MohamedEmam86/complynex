#!/usr/bin/env bash
# =============================================================================
# ComplyNex — independent timestamp (RFC 3161)
#
# WHAT THIS PROVES
#   That a specific version of the codebase existed at a specific moment,
#   attested by a third party who has no interest in the outcome.
#
# WHY IT MATTERS
#   Every other piece of evidence you hold lives on a server you control as
#   root. Anyone disputing ownership can argue you produced those timestamps
#   yourself. A Timestamp Authority's signature cannot be back-dated by you,
#   because you do not hold its private key.
#
#   Usage:  sudo /var/www/complynex/scripts/timestamp.sh
# =============================================================================
set -euo pipefail

ROOT=/var/www/complynex
PROV="$ROOT/provenance"
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$PROV/timestamps"

echo "ComplyNex — independent timestamp"
echo "================================="
echo

echo "1. Generating source manifest..."
python3 "$ROOT/scripts/code_manifest.py" generate | sed 's/^/   /'

MANIFEST="$PROV/manifest_latest.json"
[[ -f "$MANIFEST" ]] || { echo "ERROR: no manifest"; exit 1; }

TREE_HASH=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['tree_sha256'])")
GIT_HEAD=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo 'no-git')

# The evidence file: what we are timestamping. Small, human-readable, and it
# pins both the file-tree hash and the git commit.
EVIDENCE="$PROV/timestamps/evidence_${STAMP}.txt"
cat > "$EVIDENCE" <<EOF
ComplyNex source code attestation
=================================
Product      : ComplyNex Compliance Management Platform
Author       : Mohamed Emam
Generated    : $(date -Iseconds)
Host         : $(hostname)

Tree SHA-256 : $TREE_HASH
Git HEAD     : $GIT_HEAD
Git commits  : $(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 0)
Files        : $(python3 -c "import json;print(json.load(open('$MANIFEST'))['file_count'])")
Lines        : $(python3 -c "import json;print(json.load(open('$MANIFEST'))['total_lines'])")

The tree hash above is the SHA-256 of the sorted list of every source file
path and its individual SHA-256. Any change to any file changes it.
EOF

echo
echo "2. Evidence file:"
sed 's/^/   /' "$EVIDENCE"

echo
echo "3. Requesting timestamps..."
REQ="$PROV/timestamps/request_${STAMP}.tsq"
openssl ts -query -data "$EVIDENCE" -sha256 -cert -out "$REQ" 2>/dev/null
echo "   request built ($(stat -c%s "$REQ") bytes)"

GOT=0
for TSA in "https://freetsa.org/tsr" "http://timestamp.digicert.com" "http://timestamp.sectigo.com"; do
    NAME=$(echo "$TSA" | sed -E 's|https?://||; s|/.*||')
    RESP="$PROV/timestamps/token_${STAMP}_${NAME}.tsr"
    printf "   %-26s " "$NAME"
    if curl -s --max-time 20 -H "Content-Type: application/timestamp-query" \
            --data-binary "@$REQ" "$TSA" -o "$RESP" 2>/dev/null \
       && [[ -s "$RESP" ]] \
       && openssl ts -reply -in "$RESP" -text >/dev/null 2>&1; then
        WHEN=$(openssl ts -reply -in "$RESP" -text 2>/dev/null | grep -i 'Time stamp' | head -1 | cut -d: -f2- | xargs)
        echo "OK  — $WHEN"
        GOT=$((GOT+1))
    else
        echo "unavailable"
        rm -f "$RESP"
    fi
done

echo
if [[ $GOT -eq 0 ]]; then
    echo "No timestamp token obtained. The evidence file is still valid — email"
    echo "it to yourself, which gives you a mail provider's timestamp instead."
    exit 1
fi

echo "$GOT independent timestamp token(s) obtained."
echo
echo "Stored in: $PROV/timestamps/"
echo
echo "TO VERIFY LATER:"
echo "  openssl ts -reply -in <token>.tsr -text"
echo
echo "WHAT TO DO NOW — these files are the evidence, so get them off this box:"
echo "  1. Commit provenance/timestamps/ to git and push to a private remote"
echo "  2. Email the evidence file and tokens to yourself"
echo "  3. Keep a copy with your lawyer or in the Drive backup"
echo
echo "  Tree hash for your records:"
echo "  $TREE_HASH"
