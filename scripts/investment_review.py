#!/usr/bin/env python3
"""Validate and render a frozen investment review; never fetch live market data."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from validate_point_in_time import publication_bounds
from market_observations import calculate_price_observation
from reporting_window import validate_declared_window, reporting_window


COMPANIES = (
    "Apple", "Microsoft", "Alphabet / Google", "Amazon / AWS", "Meta", "NVIDIA",
    "Tesla", "OpenAI", "Anthropic", "Samsung Electronics", "SK Hynix", "TSMC",
)
ACTIVATION_DATE = date(2026, 10, 12)
MARKER = "<!-- investment-review: 1 -->"
BEGIN = "<!-- investment-review:start -->"
END = "<!-- investment-review:end -->"
POLICY_REGISTERED_AT = "2026-10-10T02:51:49Z"
SHANGHAI = timezone(timedelta(hours=8))
POLICY = {
    "version": 1, "return_sessions": 5, "volatility_sessions": 20,
    "annualization": 252, "return_baseline": "zero_excess_return",
    "volatility_baseline": "trailing_rv20",
    "entry": "first_regular_open_strictly_after_delivery",
    "pnl": "disabled_until_costs_and_execution_are_verified",
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def fields(value: object, names: str, label: str) -> dict:
    require(isinstance(value, dict), f"{label}: expected object")
    require(set(value) == set(names.split()), f"{label}: unexpected or missing fields")
    return value


def nonempty(value: object, label: str) -> None:
    require(isinstance(value, str) and bool(value.strip()), f"{label}: missing text")


def timestamp(value: str) -> datetime:
    require(isinstance(value, str), "timestamp must be text")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.utcoffset() is not None, "timestamp requires timezone")
    return result


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def source_bounds(source: dict) -> tuple[datetime, datetime, bool]:
    value = source["availability"]
    require(isinstance(value, dict) and set(value) in ({"claim_first_public_at"}, {"claim_first_public_interval"}), "source requires exact time or full conservative interval")
    return publication_bounds({**value, "support": source["availability_basis"]}, source["path"])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection_digest(coverage: dict) -> str:
    """Bind research decisions, not coverage's eventual report hash (a cycle)."""
    selected = {cid for row in coverage["company_conclusions"].values() for cid in row["selected_candidate_ids"]}
    projection = {
        "report_date": coverage["report_date"],
        "selection_policy": coverage["selection_policy"],
        "company_conclusions": coverage["company_conclusions"],
        "selected_candidates": [c for c in coverage["candidates"] if c["id"] in selected],
    }
    return hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def local_file(root: Path, name: str) -> Path:
    nonempty(name, "path")
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "snapshot path escapes repository")
    require(path.is_file(), f"snapshot missing: {name}")
    return path


def reference(ref: object, root: Path) -> Path:
    ref = fields(ref, "path sha256", "file reference")
    path = local_file(root, ref["path"])
    require(digest(path) == ref["sha256"], f"snapshot hash mismatch: {ref['path']}")
    return path


def ids(value: object, allowed: set, label: str, required: bool = False) -> None:
    require(isinstance(value, list) and all(isinstance(x, str) for x in value), f"{label}: expected IDs")
    require(len(value) == len(set(value)), f"{label}: duplicate IDs")
    require(set(value) <= allowed and (bool(value) or not required), f"{label}: missing/unknown ID")


def calculate_market(raw: dict, cutoff: datetime, available: datetime) -> dict:
    fields(raw, "instrument sessions", "market data")
    instrument = fields(raw["instrument"], "symbol venue currency benchmark calendar price_basis", "instrument")
    for key, value in instrument.items():
        nonempty(value, key)
    require(instrument["price_basis"] == "total_return_asof_cutoff", "future-adjusted prices are not eligible")
    rows = raw["sessions"]
    require(isinstance(rows, list) and 1 <= len(rows) <= 60, "market requires 1-60 actual sessions")
    closes, returns, benchmarks = [], [], []
    for row in rows:
        fields(row, "close_at stock_return benchmark_return", "session")
        close = timestamp(row["close_at"])
        require(close < cutoff and close <= available, "future/unavailable market observation")
        require(not closes or close > closes[-1], "sessions must be unique and ascending")
        for key in ("stock_return", "benchmark_return"):
            value = row[key]
            require(type(value) in (int, float) and math.isfinite(value) and value > -1, f"invalid {key}")
        closes.append(close)
        returns.append(row["stock_return"])
        benchmarks.append(row["benchmark_return"])
    require(len({x.astimezone(SHANGHAI).date() for x in closes}) == len(closes), "duplicate daily session")
    indices = [i for i, close in enumerate(closes) if cutoff - timedelta(days=7) <= close]
    logs = [math.log1p(x) for x in returns]
    def rv(values: list) -> float | None:
        return statistics.stdev(values[-20:]) * math.sqrt(252) if len(values) >= 20 else None
    current = rv(logs)
    previous = rv(logs[:indices[0]]) if indices else None
    stock = math.prod(1 + returns[i] for i in indices) - 1 if indices else None
    bench = math.prod(1 + benchmarks[i] for i in indices) - 1 if indices else None
    return {
        "week_return": stock, "excess_return": stock - bench if indices else None,
        "rv20": current, "rv20_change": current - previous if current is not None and previous is not None else None,
        "week_shock": math.sqrt(252 * statistics.mean(logs[i] ** 2 for i in indices)) if indices else None,
        "sessions": len(indices), "last_close": rows[-1]["close_at"], "instrument": instrument,
    }


def validate_snapshot(data: dict, root: Path, *, allow_preview: bool = False) -> dict:
    names = "schema_version kind report_date cutoff generated_at policy_registered_at policy coverage sources companies"
    version = data.get("schema_version")
    require(type(version) is int and version in {1, 2}, "unsupported schema")
    fields(data, names + (" observations" if version == 2 else "") + (" cutoff_policy" if 'cutoff_policy' in data else ""), "investment review")
    require(data["kind"] in {"production", "design_preview"}, "unknown kind")
    preview = data["kind"] == "design_preview"
    require(not preview or allow_preview, "design preview cannot be published")
    day = date.fromisoformat(data["report_date"])
    require(day.weekday() == 0, "report date must be Monday")
    cutoff = timestamp(data["cutoff"])
    validate_declared_window(data, cutoff_key='cutoff')
    generated = timestamp(data["generated_at"])
    require(generated <= utc_now() + timedelta(minutes=5), "generation time is in the future")
    require(preview or generated >= cutoff, "production created before complete reporting week")
    require(data["policy_registered_at"] == POLICY_REGISTERED_AT, "v1 registration cannot be backdated")
    require(timestamp(data["policy_registered_at"]) < cutoff, "policy registered after cutoff")
    require(data["policy"] == POLICY, "policy differs from pre-registered v1; do not tune historical windows")
    require(all(type(data["policy"][key]) is type(value) for key, value in POLICY.items()), "invalid policy field type")
    conclusions = None
    if preview:
        require(data["coverage"] is None, "preview must not claim research coverage")
    else:
        ref = fields(data["coverage"], "path selection_sha256", "coverage reference")
        coverage_path = local_file(root, ref["path"])
        require(coverage_path == (root / "logs" / f"{data['report_date']}_research_coverage.json").resolve(), "use the canonical coverage ledger")
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        require(selection_digest(coverage) == ref["selection_sha256"], "coverage selection hash mismatch")
        require(coverage.get("report_date") == data["report_date"], "coverage date mismatch")
        require(coverage.get('cutoff_policy') == data.get('cutoff_policy'), 'investment/coverage cutoff policies differ')
        require(coverage.get("selection_policy") == "company_top5", "top5 coverage required")
        conclusions = coverage["company_conclusions"]
    sources = data["sources"]
    require(isinstance(sources, dict), "sources must be keyed by stable ID")
    for key, source in sources.items():
        nonempty(key, "source ID")
        fields(source, "path sha256 url availability retrieved_at version locator availability_basis", "source")
        require(isinstance(source["url"], str) and source["url"].startswith(("https://", "http://")), "source URL required")
        for name in ("version", "locator", "availability_basis"):
            nonempty(source[name], name)
        _, available, interval = source_bounds(source)
        retrieved = timestamp(source["retrieved_at"])
        require((available <= cutoff if interval else available < cutoff) and available <= retrieved <= generated, "source version unavailable at cutoff or invalid retrieval")
        reference({k: source[k] for k in ("path", "sha256")}, root)
    observations = data.get("observations", {})
    require(isinstance(observations, dict) and not set(observations).intersection(sources), "observation IDs must be separate from PIT sources")
    for key, observation in observations.items():
        fields(observation, "path sha256 url retrieved_at version locator limitation", "price observation")
        for name in ("url", "version", "locator", "limitation"):
            nonempty(observation[name], name)
        require(observation["url"].startswith("https://"), "observation source URL required")
        require(timestamp(observation["retrieved_at"]) <= generated, "observation retrieved after snapshot generation")
        reference({k: observation[k] for k in ("path", "sha256")}, root)
    companies = data["companies"]
    require(isinstance(companies, list) and [c.get("company") for c in companies if isinstance(c, dict)] == list(COMPANIES), "all 12 companies required in fixed order")
    metrics, hypothesis_ids = {}, set()
    for row in companies:
        fields(row, "company selected_candidate_ids market_status market_source limitation associations hypothesis", "company")
        company, selected = row["company"], row["selected_candidate_ids"]
        ids(selected, set(selected) if isinstance(selected, list) else set(), "selected candidates")
        require(len(selected) <= 5, "company exceeds five independent events")
        if conclusions is not None:
            require(selected == conclusions[company]["selected_candidate_ids"], "selection differs from coverage")
        if preview:
            require(not selected and row["hypothesis"] is None and not row["associations"], "preview cannot invent selected facts or forecasts")
        require(row["market_status"] in {"verified", "unavailable", "not_mapped", "observed"}, "invalid market status")
        nonempty(row["limitation"], "market scope and limitation")
        if row["market_status"] == "verified":
            require(row["market_source"] in sources, "verified market requires frozen source")
            source = sources[row["market_source"]]
            raw = json.loads(local_file(root, source["path"]).read_text(encoding="utf-8"))
            metrics[company] = calculate_market(raw, cutoff, source_bounds(source)[1])
        elif row["market_status"] == "observed":
            require(version == 2 and row["market_source"] in observations, "observed prices require a separate frozen observation")
            raw = json.loads(local_file(root, observations[row["market_source"]]["path"]).read_text(encoding="utf-8"))
            metrics[company] = calculate_price_observation(raw, cutoff, root)
        else:
            require(row["market_source"] is None, "missing market data must not carry a price proxy")
            metrics[company] = None
        require(isinstance(row["associations"], list), "associations must be a list")
        for association in row["associations"]:
            require(row["market_status"] == "verified", "unqualified observations cannot support event attribution")
            fields(association, "candidate_id precision publication_start publication_end resolution source_ids interpretation alternatives", "association")
            require(association["candidate_id"] in selected, "association introduces unselected event")
            require(association["precision"] in {"exact", "interval"}, "unknown publication time cannot be attributed")
            start, end = timestamp(association["publication_start"]), timestamp(association["publication_end"])
            require(cutoff - timedelta(days=7) <= start <= end and (end < cutoff if association["precision"] == "exact" else end <= cutoff), "event outside reporting window")
            require(association["precision"] != "exact" or start == end, "exact event has an interval")
            require(association["resolution"] in {"weekly", "session"}, "invalid association resolution")
            require(association["precision"] == "exact" or association["resolution"] == "weekly", "date interval cannot imply exact session reaction")
            require(metrics[company] is not None, "association requires verified market series")
            ids(association["source_ids"], set(sources), "association sources", True)
            require(any(source_bounds(sources[sid]) == (start, end, association["precision"] == "interval") for sid in association["source_ids"]), "event precision/bounds must match cited source")
            for name in ("interpretation", "alternatives"):
                nonempty(association[name], name)
        hypothesis = row["hypothesis"]
        if hypothesis is None:
            continue
        fields(hypothesis, "id candidate_ids direction volatility expectation_kind expectation source_ids transmission financial_scale realization_horizon falsification alternatives", "hypothesis")
        nonempty(hypothesis["id"], "hypothesis ID")
        require(hypothesis["id"] not in hypothesis_ids, "duplicate hypothesis ID")
        hypothesis_ids.add(hypothesis["id"])
        ids(hypothesis["candidate_ids"], set(selected), "hypothesis candidates", True)
        require(hypothesis["direction"] in {"up", "down", "mixed", "abstain"}, "invalid direction")
        require(hypothesis["volatility"] in {"rising", "falling", "uncertain"}, "invalid volatility view")
        require(hypothesis["expectation_kind"] in {"company_guidance", "consensus", "research_assumption", "unknown"}, "unpriced is not an observable expectation type")
        ids(hypothesis["source_ids"], set(sources), "expectation sources", hypothesis["expectation_kind"] in {"company_guidance", "consensus"})
        for name in ("expectation", "transmission", "financial_scale", "realization_horizon", "falsification", "alternatives"):
            nonempty(hypothesis[name], name)
    require(len(hypothesis_ids) <= 3, "v1 supports at most three hypotheses; never fill quota")
    return metrics


def percent(value: float | None, *, change: bool = False) -> str:
    return "待接入 / 样本不足" if value is None else f"{value * 100:+.2f}{'个百分点' if change else '%'}"


def headers(data: dict) -> list[str]:
    if data["schema_version"] == 2:
        return ["公司", "证券 / 币种 / 基准", "回报口径 / 数据版本", "本周回报", "相对基准回报", "RV20", "RV20周变化", "本周冲击", "本周交易日 / 收盘样本", "末次收盘（本币）", "入选事件", "限制"]
    return HEADERS


def view_rows(data: dict, metrics: dict) -> list[list[str]]:
    result = []
    for row in data["companies"]:
        m = metrics[row["company"]]
        instrument = m["instrument"] if m else None
        if data["schema_version"] == 1:
            # Historical v1 snapshots must keep their exact frozen rendering.
            label = f"{instrument['symbol']} / {instrument['currency']} / {instrument['benchmark']}" if instrument else "未接入直接证券序列"
            numbers = [percent(m[key] if m else None, change=key == "rv20_change") for key in ("week_return", "excess_return", "rv20", "rv20_change", "week_shock")]
            result.append([row["company"], label, *numbers, str(m["sessions"]) if m else "未知", m["last_close"] if m else "未知", "、".join(row["selected_candidate_ids"]) or ("未执行研究" if data["kind"] == "design_preview" else "无入选项"), row["limitation"]])
            continue
        benchmark_label = f"{m['benchmark_name']}（{instrument['benchmark']}）" if m and m.get('basis') == 'price_observation' else instrument['benchmark'] if instrument else ''
        label = f"{instrument['symbol']} / {instrument['currency']} / {benchmark_label}" if instrument else ("未建立直接证券映射" if row["market_status"] == "not_mapped" else "证券行情未取得")
        numbers = []
        for key in ("week_return", "excess_return", "rv20", "rv20_change", "week_shock"):
            value = m[key] if m else None
            if value is not None:
                numbers.append(f"{value*100:.2f}%" if key in {"rv20", "week_shock"} else percent(value, change=key in {"rv20_change", "excess_return"}))
            elif row["market_status"] == "not_mapped":
                numbers.append("不适用：未建立直接证券映射")
            elif m and key == "excess_return":
                numbers.append("基准数据缺失")
            elif m and key in {"rv20", "rv20_change"}:
                needed = "本期或前期20个收益不足" if key == "rv20_change" else "不足20个有效日收益"
                numbers.append(needed)
            else:
                numbers.append("行情未取得" if m is None else "本周无有效收益")
        observed = row["market_status"] == "observed"
        basis = "价格回报；当前提取版本；历史PIT未认证" if observed else ("总回报；截止前合格版本" if m else "不适用" if row["market_status"] == "not_mapped" else "行情缺失")
        sessions = f"{m['sessions']}日 / {m['quote_count']}个收盘" if observed else str(m["sessions"]) if m else "不适用" if row["market_status"] == "not_mapped" else "未取得"
        price_text = f"{m['last_close_price']:,.6f}".rstrip('0').rstrip('.') if observed else None
        last = f"{m['last_close']} · {price_text}" if observed else m["last_close"] if m else "不适用" if row["market_status"] == "not_mapped" else "未取得"
        result.append([row["company"], label, *([basis] if data["schema_version"] == 2 else []), *numbers, sessions, last, "、".join(row["selected_candidate_ids"]) or ("未执行研究" if data["kind"] == "design_preview" else "无入选项"), row["limitation"]])
    return result


HEADERS = ["公司", "证券 / 币种 / 基准", "本周总回报", "超额回报", "RV20", "RV20周变化", "本周冲击", "交易日数", "末次收盘", "入选事件", "限制"]


def hypothesis_lines(row: dict) -> list[str]:
    h = row["hypothesis"]
    if h is None:
        return []
    return [f"{h['id']} · {row['company']} · {', '.join(h['candidate_ids'])}",
            f"方向观点：{h['direction']}；波动观点：{h['volatility']}",
            f"预期基线（{h['expectation_kind']}）：{h['expectation']}",
            f"传导：{h['transmission']}", f"财务量级：{h['financial_scale']}",
            f"兑现窗口：{h['realization_horizon']}", f"证伪条件：{h['falsification']}",
            f"其他解释：{h['alternatives']}", f"证据：{', '.join(h['source_ids']) or '无可核预期；仅研究假设'}"]


def markdown(data: dict, metrics: dict, snapshot_hash: str) -> str:
    def cell(value: str) -> str:
        return html.escape(value).replace("|", "&#124;").replace("\n", "<br>")
    title = "设计预览，未执行本期研究，不可作投资信号" if data["kind"] == "design_preview" else "价格观察：当前提取的历史收盘版本，历史PIT未认证；不等于新闻导致涨跌" if data.get("observations") else "截止前观察，不等于新闻导致涨跌"
    table_headers = headers(data)
    lines = [BEGIN, "## 0. 市场反应与投资假设", title,
             f"信息截止（排他）：{data['cutoff']}；快照 SHA256：`{snapshot_hash}`。",
             "| " + " | ".join(table_headers) + " |", "| " + " | ".join(["---"] * len(table_headers)) + " |"]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in view_rows(data, metrics))
    if data["schema_version"] == 2:
        lines.append("")
    lines.append("RV20与本周冲击均为年化值；冲击为日对数收益均方根，非去均值波动率。RV20变化可能来自旧冲击退出窗口。缺失不等于零。")
    if data.get("observations"):
        lines.append("本期价格口径：未复权收盘的简单收益，未计现金分红；相对基准回报为同币种、相同本地交易日的价格回报之差。RV20及冲击也采用价格收益，除权除息可能影响数值。它们不冒充含分红总回报，不进入严格PIT回测或新闻因果归因。基准按用户2026-10-19指示固定：纳斯达克综合IXIC.GI、韩国综合KS11.KS、台湾加权TWII.TW；本期没有日本上市标的。")
    for row in data["companies"]:
        for a in row["associations"]:
            lines.append(f"- 关联说明（非因果）：{cell(row['company'])} / {cell(a['candidate_id'])}；公开范围 {cell(a['publication_start'])} 至 {cell(a['publication_end'])}，{a['resolution']}精度；{cell(a['interpretation'])}。其他解释：{cell(a['alternatives'])}；证据：{cell(', '.join(a['source_ids']))}。")
        lines.extend(f"- {cell(line)}" for line in hypothesis_lines(row))
    if not any(row["hypothesis"] for row in data["companies"]):
        lines.append("本期无冻结投资假设；不以无观点充当看平，也不为填满数量补写。")
    lines.append("后验结果另存，当前页不载入。评估预注册：发布后首个常规开盘起5个交易日超额回报、20个交易日波动；尚非交易收益承诺。")
    for key, source in data["sources"].items():
        left, right, interval = source_bounds(source)
        timing = f"[{left.isoformat()}, {right.isoformat()})" if interval else left.isoformat()
        lines.append(f"- 证据 {cell(key)}：[来源]({cell(source['url'])})；{cell(source['path'])}；版本 {cell(source['version'])}；可得 {cell(timing)}；SHA256 `{source['sha256']}`；定位 {cell(source['locator'])}；依据 {cell(source['availability_basis'])}。")
    for key, source in data.get("observations", {}).items():
        lines.append(f"- 行情观察 {cell(key)}：[Wind API]({cell(source['url'])})；{cell(source['path'])}；实际取数 {cell(source['retrieved_at'])}；SHA256 `{source['sha256']}`；{cell(source['limitation'])}。")
    lines.append(END)
    return "\n".join(lines)


def html_view(data: dict, metrics: dict, snapshot_hash: str) -> str:
    esc = html.escape
    rows = "".join("<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>" for row in view_rows(data, metrics))
    hypotheses = "".join("<article>" + "".join(f"<p>{esc(line)}</p>" for line in hypothesis_lines(row)) + "</article>" for row in data["companies"] if row["hypothesis"])
    title = "设计预览 · 非正式周报" if data["kind"] == "design_preview" else "冻结观察 · 非因果归因"
    text = markdown(data, metrics, snapshot_hash)
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>AI公司周报 · 投资研究版 v1</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;color:#20252b;background:#fff;font:15px/1.6 system-ui,sans-serif;letter-spacing:0}}header,main,footer{{max-width:1500px;margin:auto;padding:24px}}header{{border-bottom:2px solid #1b795b}}h1{{font-size:26px;margin:6px 0}}h2{{font-size:19px;margin:24px 0 12px}}p{{margin:8px 0;overflow-wrap:anywhere}}.tag{{color:#8c4212;background:#fff0df;padding:4px 8px;font-size:13px}}.muted{{color:#5b626b}}nav{{display:flex;gap:24px;flex-wrap:wrap}}a{{color:#16624d}}.scroll{{overflow-x:auto;border-top:1px solid #c9cdd1}}table{{border-collapse:collapse;width:100%;font-size:13px}}th{{background:#eef3f1;text-align:left}}td,th{{padding:12px 10px;border-bottom:1px solid #dce0e3;vertical-align:top;min-width:100px}}td:first-child,th:first-child{{min-width:170px}}td:last-child{{min-width:240px}}article{{border-top:1px solid #dce0e3;padding:12px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 ui-monospace,monospace}}summary{{cursor:pointer;color:#16624d}}footer{{border-top:1px solid #dce0e3;font-size:13px}}@media print{{.scroll{{overflow:visible}}table{{font-size:9px}}td,th{{min-width:0!important;padding:4px}}}}
</style>
<header><span class="tag">{title}</span><h1>AI公司周报 · 投资研究版</h1><p>{esc(data['report_date'])} / 信息截止：{esc(data['cutoff'])}（排他）</p><nav><a href="#market">市场反应</a><a href="#hypotheses">投资假设</a><a href="#evidence">冻结证据</a></nav></header>
<main><section id="market"><h2>市场反应</h2><p class="muted">12家公司固定样本；价格观察采用当前提取版本时，历史PIT未认证，未计现金分红。关联不等于因果。</p><div class="scroll" role="region" aria-label="12家公司市场数据" tabindex="0"><table><thead><tr>{''.join(f'<th scope="col">{esc(h)}</th>' for h in headers(data))}</tr></thead><tbody>{rows}</tbody></table></div><p class="muted">RV20为20日对数收益样本标准差，按252日年化。本周冲击为日对数收益均方根的年化值；不是波动预测。RV20周变化单位为百分点，旧冲击退出也会改变数值。</p></section>
<section id="hypotheses"><h2>投资假设</h2>{hypotheses or '<p>暂无冻结假设。无观点不等于看平，未接入数据不等于零。</p>'}<p class="muted">方向与波动分别判断。后验评估不载入此冻结页。</p></section>
<section id="evidence"><h2>冻结证据</h2><details><summary>查看同源Markdown与证据索引</summary><pre>{esc(text)}</pre></details><p class="muted">生成：{esc(data['generated_at'])} / SHA256：{snapshot_hash}</p></section></main>
<footer>设计与方法验收不证明投资有效性。缺少合格行情时，仅保留核证研究与明确限制。</footer></html>'''


def preflight_layout(report: Path, text: str) -> date | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}", report.name)
    require(match is not None, "missing report date")
    day = date.fromisoformat(match.group())
    if day < ACTIVATION_DATE and MARKER not in text:
        return None
    require(MARKER in text, "new report requires investment-review marker")
    require(text.count(BEGIN) == 1 and text.count(END) == 1, "requires one frozen investment block")
    require(text.index(BEGIN) < text.index(END) < text.find("## 1."), "investment block must precede section 1")
    return day


def check_report(report: Path, root: Path | None = None) -> str:
    root = root or report.parent.parent
    text = report.read_text(encoding="utf-8")
    day = preflight_layout(report, text)
    if day is None:
        return "旧期不追加强制投资模块；不赋予预测回测资格"
    snapshot = root / "logs" / f"{day}_investment_review.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    require(data["report_date"] == day.isoformat(), "investment date mismatch")
    metrics = validate_snapshot(data, root)
    actual = text[text.index(BEGIN):text.index(END) + len(END)]
    require(actual == markdown(data, metrics, digest(snapshot)), "report differs from frozen investment snapshot")
    return "投资快照结构/时点边界/同源显示通过；当前提取版本的价格观察不获历史PIT认证" if data.get("observations") else "投资快照结构/PIT边界/同源显示通过；不认证事实语义、预测能力或已发布"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-preview", action="store_true")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--html", type=Path)
    args = parser.parse_args()
    if args.report:
        require(not args.snapshot and not args.markdown and not args.html, "report check is read-only")
        print(check_report(args.report, args.root))
        return
    require(args.snapshot is not None, "--snapshot required")
    data = json.loads(args.snapshot.read_text(encoding="utf-8"))
    metrics = validate_snapshot(data, args.root, allow_preview=args.allow_preview)
    outputs = [path.resolve() for path in (args.markdown, args.html) if path]
    require(len(outputs) == len(set(outputs)), "output paths must be distinct")
    require(all(not path.exists() for path in outputs), "renderer never overwrites a frozen output; use a new path")
    for path, renderer in ((args.markdown, markdown), (args.html, html_view)):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(renderer(data, metrics, digest(args.snapshot)) + "\n", encoding="utf-8")
    print("投资快照检查完成；数据可得性依据与投资语义仍须人工复核")


if __name__ == "__main__":
    main()
