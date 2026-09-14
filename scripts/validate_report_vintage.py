#!/usr/bin/env python3
"""Keep revised display reports separate from original-time backtest inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


MARKER = "<!-- report-vintage: revised -->"


def check_vintage(report: Path, *, for_backtest: bool = False) -> str:
    root = report.resolve().parent.parent
    registry = root / "state/report_vintages.json"
    text = report.read_text(encoding="utf-8")
    entries = json.loads(registry.read_text(encoding="utf-8")).get("reports", {}) if registry.exists() else {}
    entry = entries.get(report.name[:10])
    if entry is None:
        if MARKER in text or for_backtest:
            raise ValueError("报告缺少可核验的版本登记，不能推定原报告日期已可用")
        return ""
    if entry.get("current_sha256") != hashlib.sha256(report.read_bytes()).hexdigest():
        raise ValueError("版本登记哈希已过期，须记录真实修订时间并重新核验")
    if entry.get("version_type") != "retrospective_revision" or MARKER not in text:
        raise ValueError("修订版缺少一致的版本类型或正文标识")
    if "禁止作为原周一" not in text or not entry.get("revised_at"):
        raise ValueError("修订版必须说明真实修订时间和回测限制")
    revised_at = datetime.fromisoformat(entry["revised_at"])
    if revised_at.utcoffset() is None or revised_at.date().isoformat() < report.name[:10]:
        raise ValueError("修订时间必须带时区且不得早于原报告日期")
    if entry.get("backtest_eligible_for_original_report_time") is not False:
        raise ValueError("事后修订版必须显式排除原周一回测资格")
    if not entry.get("original_snapshot_commit") or not entry.get("pre_correction_sha256"):
        raise ValueError("修订版缺少原提交或替换前文件哈希")
    archive = root / entry["archive_path"]
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != entry.get("archive_sha256"):
        raise ValueError("替换前归档缺失或哈希不一致")
    if for_backtest:
        raise ValueError("当前文件是事后修订展示版，禁止作为原周一实时回测输入；原始版本也须另核发布时点")
    return "版本隔离校验通过；修订版不具备原周一回测资格"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--for-backtest", action="store_true")
    args = parser.parse_args()
    try:
        print(check_vintage(args.report, for_backtest=args.for_backtest))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit(f"版本校验失败：{exc}") from exc


if __name__ == "__main__":
    main()
