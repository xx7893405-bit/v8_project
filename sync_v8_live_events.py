#!/usr/bin/env python3
"""Pull V2/V4 VPS events and append newly observed entries and fills locally."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
FIELDS = [
    "event_id", "run_id", "account_id", "event_type", "detected_at", "evaluated_at", "as_of", "strategy",
    "decision", "type", "entry_time", "exit_time", "result", "pnl", "pnl_pct",
    "entry_price", "exit_price", "sl", "tp1", "tp2", "size", "entry_balance",
    "fee", "leverage", "entry_mode", "exit_model", "balance",
]
EVENT_FILES = {
    "paper-nfe-v2": "accounts/paper-nfe-v2/events.jsonl",
    "paper-nfe-v4": "accounts/paper-nfe-v4/events.jsonl",
}


def get_events(remote_filename: str) -> list[dict]:
    installed_key = ROOT / "ssh-key-2026-07-10.key"
    key_path = installed_key if installed_key.exists() else Path.home() / "Downloads/ssh-key-2026-07-10.key"
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-i", str(key_path),
        "ubuntu@140.245.87.238",
        f"test -f /opt/v8_project/runtime/{remote_filename} && cat /opt/v8_project/runtime/{remote_filename} || true",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def paths(name: str) -> tuple[Path, Path, Path]:
    return (
        RUNTIME / f"{name}_live_sync_state.json",
        RUNTIME / f"{name}_live_events.jsonl",
        RUNTIME / f"{name}_live_events.csv",
    )


def load_seen(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    return set(json.loads(state_path.read_text(encoding="utf-8")).get("seen_event_ids", []))


def append_events(events: list[dict], jsonl_path: Path, csv_path: Path) -> None:
    if not events:
        return
    RUNTIME.mkdir(exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as handle:
        for item in events:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(events)


def main() -> None:
    try:
        totals = []
        for name, remote_filename in EVENT_FILES.items():
            events = get_events(remote_filename)
            state_path, jsonl_path, csv_path = paths(name)
            seen = load_seen(state_path)
            new_events = [item for item in events if item["event_id"] not in seen]
            append_events(new_events, jsonl_path, csv_path)
            seen.update(item["event_id"] for item in new_events)
            RUNTIME.mkdir(exist_ok=True)
            state_path.write_text(json.dumps({"seen_event_ids": sorted(seen)}, indent=2) + "\n", encoding="utf-8")
            totals.append(f"{name}: {len(new_events)}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(f"VPS sync failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"synced {', '.join(totals)} new event(s)")


if __name__ == "__main__":
    main()
