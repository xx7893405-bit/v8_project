#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=15 \
  -i "$HOME/Downloads/ssh-key-2026-07-10.key" \
  ubuntu@140.245.87.238 \
  'cd /opt/v8_project && systemctl status v8-strategy.timer --no-pager && jq "{evaluated_at, snapshot}" runtime/oracle_strategy_state.json'
