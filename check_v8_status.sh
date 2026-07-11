#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=15 \
  -i "$HOME/Downloads/ssh-key-2026-07-10.key" \
  ubuntu@140.245.87.238 \
  'cd /opt/v8_project && systemctl status nfe-v2-strategy.timer nfe-v4-strategy.timer --no-pager && jq "{account_id, strategy, evaluated_at, snapshot}" runtime/accounts/*/state.json'
