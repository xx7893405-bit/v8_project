#!/usr/bin/env python3
"""Pull V8's VPS snapshot and append newly observed entries and fills locally."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
STATE_PATH = RUNTIME / "v8_live_sync_state.json"
JSONL_PATH = RUNTIME / "v8_live_events.jsonl"
CSV_PATH = RUNTIME / "v8_live_events.csv"
FIELDS = [
    "event_id", "event_type", "detected_at", "evaluated_at", "as_of", "strategy",
    "decision", "type", "entry_time", "exit_time", "result", "pnl", "pnl_pct",
    "entry_price", "exit_price", "sl", "tp1", "tp2", "size", "entry_balance",
    "fee", "leverage", "entry_mode", "exit_model", "balance",
]


def get_events() -> list[dict]:
    installed_key = ROOT / "ssh-key-2026-07-10.key"
    key_path = installed_key if installed_key.exists() else Path.home() / "Downloads/ssh-key-2026-07-10.key"
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-i", str(key_path),
        "ubuntu@140.245.87.238",
        "test -f /opt/v8_project/runtime/oracle_strategy_events.jsonl && cat /opt/v8_project/runtime/oracle_strategy_events.jsonl || true",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def load_seen() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    return set(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("seen_event_ids", []))


def append_events(events: list[dict]) -> None:
    if not events:
        return
    RUNTIME.mkdir(exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as handle:
        for item in events:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    write_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    with CSV_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(events)


def main() -> None:
    try:
        events = get_events()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(f"VPS sync failed: {error}", file=sys.stderr)
        raise SystemExit(1)

    seen = load_seen()
    new_events = [item for item in events if item["event_id"] not in seen]
    append_events(new_events)
    seen.update(item["event_id"] for item in new_events)
    RUNTIME.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps({"seen_event_ids": sorted(seen)}, indent=2) + "\n", encoding="utf-8")
    print(f"synced {len(new_events)} new event(s)")


if __name__ == "__main__":
    main()
