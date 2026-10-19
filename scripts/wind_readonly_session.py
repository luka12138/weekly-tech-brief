#!/usr/bin/env python3
"""Keep one authenticated WindPy session for explicitly requested read-only calls."""
from __future__ import annotations

import json
import math
import os
import sys
import argparse
from datetime import date, datetime, timezone
from pathlib import Path


def clean(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": repr(value)}
    if isinstance(value, (list, tuple)):
        return [clean(x) for x in value]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    return value


def required_result_valid(result):
    values = [v for row in (result.get("Data") or []) for v in (row if isinstance(row, list) else [row])]
    valid = lambda v: (isinstance(v, str) and bool(v.strip())) or (type(v) in (int, float) and math.isfinite(v))
    return result.get("ErrorCode") == 0 and bool(values) and all(valid(v) for v in values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    if bool(args.store) != bool(args.run):
        parser.error('--store and --run must be provided together')
    root = Path(__file__).resolve().parents[1]
    raw = root / "logs/wind_raw"
    raw.mkdir(exist_ok=True)
    os.chmod(raw, 0o700)
    sys.path.insert(0, "/Applications/Wind API.app/Contents/python")
    from WindPy import w

    print(json.dumps({"stage": "import_ok", "pid": os.getpid()}), flush=True)
    start = w.start(waitTime=120)
    print(json.dumps({"stage": "start", "error_code": start.ErrorCode,
                      "connected": w.isconnected()}), flush=True)
    if start.ErrorCode != 0:
        return
    lines = [json.dumps(j, ensure_ascii=False) for j in json.loads(args.jobs.read_text())] if args.jobs else sys.stdin
    for line in lines:
        if not line.strip():
            continue
        request = json.loads(line)
        if request.get("method") == "exit":
            break
        if request.get("method") not in {"wss", "wsd", "tdays", "wset"}:
            raise ValueError("Only explicit read-only data calls are allowed")
        identity = request["id"]
        if not identity.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Invalid receipt ID")
        destination = raw / (identity + ".json")
        if destination.exists():
            raise FileExistsError(destination)
        began = datetime.now(timezone.utc).isoformat()
        result = getattr(w, request["method"])(*request["args"])
        receipt = {"request": request, "started_at": began,
                   "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "result": clean({key: getattr(result, key, None)
                                    for key in ["ErrorCode", "Codes", "Fields", "Times", "Data"]})}
        from weekly_data_store import immutable, ingest
        immutable(destination, (json.dumps(receipt, ensure_ascii=False, indent=2,
                                          allow_nan=False) + "\n").encode('utf-8'))
        os.chmod(destination, 0o600)
        check = json.loads(destination.read_text(encoding="utf-8"))
        if check["request"]["id"] != identity or check["result"] is None:
            raise RuntimeError("Receipt readback failed")
        result_data = check["result"]
        if args.store:
            ingest(args.store, args.run, check)
        print(json.dumps({"stage": "result", "id": identity,
                          "path": str(destination), "error_code": result_data["ErrorCode"],
                          "codes": result_data["Codes"], "fields": result_data["Fields"],
                          "times_count": len(result_data["Times"] or []),
                          "nonempty_values": sum(v is not None for row in (result_data["Data"] or []) for v in (row if isinstance(row,list) else [row]))},
                         ensure_ascii=False, allow_nan=False), flush=True)
        if request.get("require_nonempty"):
            if not required_result_valid(result_data):
                raise RuntimeError("Required Wind control is empty or failed; stop this download batch")


if __name__ == "__main__":
    main()
