#!/usr/bin/env python3
"""Read cumulative session counters; partition every selected delta without hiding overhead."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


CORE = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
OPTIONAL = ("reasoning_output_tokens", "cache_write_input_tokens")
FIELDS = CORE + OPTIONAL
PHASES = ("production", "evidence", "maintenance", "unclassified")


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result


def phase_windows(manifest: dict) -> list[tuple]:
    start, end = instant(manifest["start"]), instant(manifest["end"])
    if start >= end:
        raise ValueError("Run start must precede end")
    windows = []
    for p in manifest.get("phases", []):
        left, right = instant(p["start"]), instant(p["end"])
        if p["name"] not in PHASES[:-1] or not start <= left < right <= end:
            raise ValueError("Invalid phase name or phase outside run window")
        windows.append((left, right, p["name"]))
    windows.sort()
    if any(a[1] > b[0] for a, b in zip(windows, windows[1:])):
        raise ValueError("Phase windows must not overlap")
    return windows


def totals(events: list[dict]) -> dict:
    result = {k: (None if any(e["tokens"][k] is None for e in events)
                  else sum(e["tokens"][k] for e in events)) for k in FIELDS}
    result["non_cached_input_tokens"] = result["input_tokens"] - result["cached_input_tokens"]
    result["updates"] = len(events)
    return result


def measure(events, manifest: dict) -> dict:
    windows = phase_windows(manifest)
    start, end = instant(manifest["start"]), instant(manifest["end"])
    history, available = [], {"thread_token_usage": 0, "legacy_total_token_usage": 0}
    for e in events:
        if instant(e["timestamp"]) > end:
            break
        p = e.get("payload", {})
        if e["type"] == "turn_context":
            history.append({"timestamp": e["timestamp"], "type": e["type"],
                            "payload": {k: p.get(k) for k in ("turn_id", "model", "effort", "reasoning_effort")}})
        elif e["type"] == "token_usage_record":
            history.append(e)
            available["thread_token_usage"] += 1
        elif e["type"] == "event_msg" and p.get("type") == "token_count":
            history.append(e)
            available["legacy_total_token_usage"] += 1
    chosen = manifest.get("counter_format", "auto")
    if chosen == "auto":
        chosen = "thread_token_usage" if available["thread_token_usage"] else "legacy_total_token_usage"
    if chosen not in available:
        raise ValueError("Unknown counter_format")
    prior = prior_at = None
    selected, settings = [], []
    turn = setting = None
    prior_format = thread_id = None
    formats, responses = [], {}
    for e in history:
        at = instant(e["timestamp"])
        if at > end:
            break
        p = e.get("payload", {})
        if e["type"] == "turn_context":
            turn = p.get("turn_id")
            setting = {"model": p.get("model"), "reasoning_effort": p.get("effort", p.get("reasoning_effort"))}
        if e["type"] == "token_usage_record":
            if chosen != "thread_token_usage":
                continue
            counter_format = "thread_token_usage"
            usage = p.get("thread_token_usage")
            current_thread, response_id = p.get("thread_id"), p.get("response_id")
            if not isinstance(usage, dict) or not current_thread or not response_id:
                raise ValueError("Incomplete token_usage_record; cannot silently omit usage")
            if thread_id is not None and current_thread != thread_id:
                raise ValueError("Multiple thread counter scopes cannot share one ledger")
            thread_id = current_thread
            key = (current_thread, response_id)
            if key in responses:
                if responses[key] != usage:
                    raise ValueError("Conflicting duplicate response counter")
                continue
            responses[key] = dict(usage)
            turn = p.get("turn_id", turn)
        elif e["type"] == "event_msg" and p.get("type") == "token_count":
            if chosen != "legacy_total_token_usage":
                continue
            counter_format = "legacy_total_token_usage"
            usage = (p.get("info") or {}).get("total_token_usage")
            if usage is None:
                continue
        else:
            continue
        if counter_format not in formats:
            formats.append(counter_format)
        for k in CORE:
            if type(usage.get(k)) is not int or usage[k] < 0:
                raise ValueError(f"Missing/invalid cumulative {k} at {e['timestamp']}")
        for k in OPTIONAL:
            if usage.get(k) is not None and (type(usage[k]) is not int or usage[k] < 0):
                raise ValueError(f"Invalid optional counter {k}")
        if usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
            raise ValueError("Total is not input + output; inspect the counter schema")
        if usage["cached_input_tokens"] > usage["input_tokens"]:
            raise ValueError("Cached input exceeds input")
        if prior is not None and all(prior[k] == usage[k] for k in CORE):
            # Some exports mirror the same counter in both schemas.
            for k in OPTIONAL:
                if prior.get(k) is None and usage.get(k) is not None:
                    prior[k] = usage[k]
            continue
        reset = prior is not None and usage["total_tokens"] < prior["total_tokens"]
        if reset and (counter_format != prior_format or counter_format == "thread_token_usage"):
            raise ValueError("Counter scope decreased across formats or within one thread; inspect before measuring")
        base = {k: 0 for k in FIELDS} if reset else prior
        if at > start:
            if base is None:
                raise ValueError("No counter before run start; cannot claim a complete measured delta")
            delta = {k: None if usage.get(k) is None or base.get(k) is None
                     else usage[k] - base[k] for k in FIELDS}
            if any(v is not None and v < 0 for v in delta.values()):
                raise ValueError("Partial counter decrease; refusing to silently clamp")
            if delta["total_tokens"] > 0:
                if setting is not None and setting not in settings:
                    settings.append(setting)
                phase = "unclassified"
                for left, right, name in windows:
                    if left <= prior_at < at <= right:
                        phase = name
                        break
                selected.append({"at": e["timestamp"], "previous_counter_at": prior_at.isoformat(),
                                 "turn_id": turn, "phase": phase, "counter_reset": reset,
                                 "counter_format": counter_format, "tokens": delta})
        prior, prior_at = dict(usage), at
        prior_format = counter_format
    if not selected:
        raise ValueError("No measured usage increments in the requested window")
    return {"schema_version": 1, "run_id": manifest["run_id"],
            "requested_start": manifest["start"], "requested_end": manifest["end"],
            "counter_baseline_at": selected[0]["previous_counter_at"],
            "last_included_token_event": selected[-1]["at"], "observed_settings": settings,
            "observed_counter_formats": formats,
            "counter_selection": {"selected": chosen, "available_records": available,
                                  "note": "One cumulative scope only; mirrored legacy counters are not added to thread counters."},
            "total": totals(selected),
            "phases": {name: totals([e for e in selected if e["phase"] == name]) for name in PHASES},
            "events": selected,
            "limitations": ["Counter increments, not HTTP requests, causal attribution or money.",
                            "Cached input is included in input; reasoning is included in output.",
                            "Cross-phase, boundary and unmarked increments remain unclassified, included in total.",
                            "Only persisted counters through last_included_token_event are measured; later work is not zero.",
                            "No conversation bodies exported; phase labels require actual execution records."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New artifact only; never overwrite a frozen measurement")
    args = parser.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    with args.session.open(encoding="utf-8") as source:
        result = measure((json.loads(line) for line in source if line.strip()), json.loads(manifest_bytes))
    result["session_file"] = args.session.name
    result["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(json.dumps({"output": str(args.output), "total": result["total"],
                      "phases": result["phases"], "through": result["last_included_token_event"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
