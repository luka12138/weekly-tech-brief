#!/usr/bin/env python3
"""Read-only, version-bound JSON indexes and full-record views for brief research."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


INDEX_FIELDS = (
    "edge_id", "node_id", "name", "supplier", "customer", "source", "target",
    "company", "product", "product_or_service", "source_node", "target_node",
    "evidence_level", "confidence", "status", "changed_this_week", "evidence_date",
)


def encode(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def load_document(path: Path, expected: str | None = None) -> tuple[dict, str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"SHA-256 mismatch: {path}; rebuild index and re-review changes")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data, digest


def records(data: dict) -> dict:
    result = {}
    for key, value in data.items():
        pointer = "/" + encode(key)
        if isinstance(value, list):
            # Keep empty arrays visible and never infer review scope from weekly flags.
            if not value:
                result[pointer] = value
            for index, item in enumerate(value):
                result[f"{pointer}/{index}"] = item
        else:
            result[pointer] = value
    return result


def build_index(data: dict) -> dict:
    collections = {}
    for key, values in data.items():
        if not isinstance(values, list):
            continue
        rows = []
        omitted = set()
        for index, value in enumerate(values):
            row = {"pointer": f"/{encode(key)}/{index}"}
            if isinstance(value, dict):
                row["index"] = {field: value[field] for field in INDEX_FIELDS if field in value}
                omitted.update(set(value) - set(INDEX_FIELDS))
            else:
                row["value"] = value
            rows.append(row)
        collections[key] = {
            "pointer": "/" + encode(key), "count": len(values), "records": rows,
            "fields_requiring_expansion": sorted(omitted),
        }
    return {
        "view": "index_only_not_evidence",
        "metadata": {key: value for key, value in data.items() if not isinstance(value, list)},
        "collections": collections,
    }


def resolve(data: dict, pointer: str):
    if not pointer.startswith("/"):
        raise ValueError("Use a non-root JSON Pointer, e.g. /edges/0")
    value = data
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isascii() or not token.isdecimal() or str(int(token)) != token:
                raise ValueError(f"Invalid array index in pointer: {pointer}")
            value = value[int(token)]
        else:
            value = value[token]
    return value


def diff_records(previous: dict, current: dict) -> list[dict]:
    old, new = records(previous), records(current)
    changes = []
    for pointer in sorted(old.keys() | new.keys()):
        if (pointer in old and pointer in new
                and json.dumps(old[pointer], sort_keys=True) == json.dumps(new[pointer], sort_keys=True)):
            continue
        change = {"pointer": pointer}
        if pointer not in old:
            change.update(change="added", after=new[pointer])
        elif pointer not in new:
            change.update(change="removed", before=old[pointer])
        else:
            change.update(change="modified", before=old[pointer], after=new[pointer])
        changes.append(change)
    return changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True, help="Explicit current or frozen JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pointer", action="append", help="Repeat to read complete records")
    mode.add_argument("--previous", type=Path, help="Compare all fields to an explicit frozen JSON")
    parser.add_argument("--expect-sha256", help="Required for expansion; rejects a stale index")
    args = parser.parse_args(argv)
    if args.pointer and not args.expect_sha256:
        parser.error("--pointer requires --expect-sha256 from the index")
    try:
        data, digest = load_document(args.file, args.expect_sha256)
        output = {"file": str(args.file.resolve()), "sha256": digest}
        if args.pointer:
            output.update(view="full_records", records=[
                {"pointer": pointer, "value": resolve(data, pointer)} for pointer in args.pointer
            ])
        elif args.previous:
            previous, previous_digest = load_document(args.previous)
            output.update(
                view="structural_diff_not_weekly_news",
                previous_file=str(args.previous.resolve()), previous_sha256=previous_digest,
                changes=diff_records(previous, data),
            )
        else:
            output.update(build_index(data))
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"brief_context: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
