#!/bin/bash
# deploy.sh — push local changes to GitHub + pull on VPS + restart
set -e
cd /c/polymarket-bot
git add -A
git commit -m "${1:-update}" 2>/dev/null || echo "(nada nuevo para commitear)"
git push origin main
ssh -i /c/Users/Max/.ssh/id_ed25519 root@157.230.59.207 \
  "cd /root/polymarket-bot && git pull && systemctl restart claudio && sleep 3 && systemctl status claudio --no-pager | head -6"
