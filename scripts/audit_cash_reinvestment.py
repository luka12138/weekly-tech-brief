#!/usr/bin/env python3
"""Audit a declared cash-reinvestment convention without promoting its inputs to PIT.

This is a diagnostic, not a Wind field decoder or a complete corporate-action feed.
Cash is gross per share held before the action; shares are after/before the action.
The convention reinvests gross cash at the effective session's unadjusted close.
Rights, spin-offs and tax adjustments need separate typed handling and are rejected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path


def gross_close_return(previous_close, close, cash_per_old_share, shares_per_old_share=1.0):
    values = [previous_close, close, cash_per_old_share, shares_per_old_share]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Inputs must be finite numbers, not missing values or flags")
    if previous_close <= 0 or close <= 0 or shares_per_old_share <= 0 or cash_per_old_share < 0:
        raise ValueError("Invalid close, share multiplier or gross cash distribution")
    return (close * shares_per_old_share + cash_per_old_share) / previous_close - 1


def verify_file(root, reference):
    path = (root / reference["path"]).resolve()
    path.relative_to(root.resolve())
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != reference["sha256"]:
        raise ValueError("Evidence hash mismatch: " + str(path))
    return json.loads(raw)


def audit(root, spec):
    if spec["scope"] != "single_confirmed_cash_event_diagnostic":
        raise ValueError("This audit does not certify a complete action ledger")
    if spec["event"]["type"] != "ordinary_gross_cash_dividend":
        raise ValueError("Unsupported corporate action type")
    if spec["event"]["currency"] != spec["currency"]:
        raise ValueError("Dividend and security currencies differ")
    observations = verify_file(root, spec["observations"])
    pct = verify_file(root, spec["wind_pct_change_receipt"])
    if observations["instrument"]["symbol"] != spec["symbol"]:
        raise ValueError("Security identity mismatch")
    if observations["instrument"]["currency"] != spec["currency"]:
        raise ValueError("Price currency mismatch")
    out = pct["result"]
    if out["ErrorCode"] != 0 or out["Codes"] != [spec["symbol"]] or out["Fields"] != ["PCT_CHG"]:
        raise ValueError("Wind pct_chg receipt does not match the requested security")
    day = spec["event"]["effective_session"]
    i = observations["session_dates"].index(day)
    if i == 0:
        raise ValueError("No previous trading close")
    previous_close, close = observations["closes"][i-1:i+1]
    cash = spec["event"]["gross_cash_per_old_share"]
    cash_return = gross_close_return(previous_close, close, cash)
    wind_return = out["Data"][0][out["Times"].index(day)] / 100
    if not math.isfinite(wind_return):
        raise ValueError("Nonfinite Wind return")
    evidence = []
    for ref in spec["event"]["evidence"]:
        path = (root / ref["path"]).resolve()
        path.relative_to(root.resolve())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != ref["sha256"]:
            raise ValueError("Primary source hash mismatch")
        if not ref.get("locator") or not ref.get("supports"):
            raise ValueError("Missing evidence locator or scope")
        evidence.append(ref)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": spec["scope"], "symbol": spec["symbol"], "currency": spec["currency"],
        "effective_session": day, "event_date_basis": spec["event"]["effective_session_basis"],
        "convention": "Gross cash credited and reinvested at ex-session close; no withholding, fees or actual payment-date cash constraint",
        "previous_close": previous_close, "close": close, "gross_cash_per_old_share": cash,
        "price_return": close/previous_close-1,
        "gross_cash_close_reinvestment_return": cash_return,
        "wind_pct_chg_return": wind_return,
        "difference_basis_points": 10000*(wind_return-cash_return),
        "same_as_declared_cash_close_convention": math.isclose(wind_return, cash_return, abs_tol=1e-12),
        "primary_event_evidence": evidence,
        "complete_10_company_action_feed": False,
        "vendor_algorithm_globally_certified": False,
        "historical_price_version_certified": False,
        "report_total_return_status_promoted": False,
        "limitation": "One event checks a semantic difference. It cannot establish all action types, all dates, all markets, benchmark total returns or historical data vintages.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = audit(root, json.loads(args.spec.read_text()))
    with args.output.open("x") as target:
        json.dump(result, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
    print(json.dumps({k:result[k] for k in ["symbol", "effective_session", "gross_cash_close_reinvestment_return", "wind_pct_chg_return", "difference_basis_points", "historical_price_version_certified"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
