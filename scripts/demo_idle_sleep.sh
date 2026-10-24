#!/bin/bash
# Stop the demo web app (and its eKYC worker) after DEMO_IDLE_MINUTES without a
# real request. complynex-demo.socket keeps listening, so the next visitor
# starts it again (first page takes a few seconds). Run by complynex-demo-sleep.timer.
set -u
IDLE_MIN=${DEMO_IDLE_MINUTES:-30}
MARK=/var/www/complynex-demo/logs/.last_request
systemctl is-active --quiet complynex-demo || exit 0
now=$(date +%s)
since=$(date -d "$(systemctl show -p ActiveEnterTimestamp --value complynex-demo)" +%s 2>/dev/null || echo "$now")
last=$since
[ -f "$MARK" ] && m=$(stat -c %Y "$MARK") && [ "$m" -gt "$last" ] && last=$m
if [ $(( now - last )) -ge $(( IDLE_MIN * 60 )) ]; then
  echo "demo idle for $(( (now - last) / 60 )) min: stopping until the next request"
  systemctl stop complynex-demo
fi
