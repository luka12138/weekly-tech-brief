# Weekly Tech Brief

This repository stores weekly Chinese morning briefs for major technology companies, plus the structured supply-chain baseline used for week-over-week comparison.

The current brief covers ten companies:

- Apple
- Microsoft
- Alphabet / Google
- Amazon / AWS
- Meta
- NVIDIA
- Tesla
- Samsung Electronics
- SK Hynix
- TSMC

## Current Report

Open the latest report here:

- [reports/latest.md](reports/latest.md)

The dated report files are kept in `reports/`, for example:

- [reports/2026-06-29_weekly_morning_brief.md](reports/2026-06-29_weekly_morning_brief.md)

## Repository Layout

```text
reports/
  latest.md
  YYYY-MM-DD_weekly_morning_brief.md

state/
  supply_graph_baseline.json

scripts/
  validate_weekly_brief.py
```

`reports/latest.md` is the stable entry point for the newest brief.

`state/supply_graph_baseline.json` stores the structured supply-chain graph used by the next weekly run. It is intentionally versioned so weekly relationship changes can be compared against the previous baseline.

`scripts/validate_weekly_brief.py` is the quality gate. It validates the report before committing or pushing new results.

## Brief Contents

Each weekly brief is expected to include:

1. Top 5-8 major events of the week
2. Impact overview table for all ten companies
3. Company-by-company event summaries with dates, impact, confidence, and source links
4. Cross-company and supply-chain observations
5. Next-week watchlist
6. Supply-chain relationship graph and week-over-week changes
7. Self-check section

The supply-chain section uses matching `Edge ID`s across:

- Mermaid graph in the Markdown report
- Section 6.2 supply relationship table
- `state/supply_graph_baseline.json`

This is required so the next run can compare relationships reliably.

## Validation

Run the validator before committing generated output:

```bash
python3 scripts/validate_weekly_brief.py \
  --report reports/2026-06-29_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --latest reports/latest.md
```

The validator checks:

- JSON baseline parses correctly
- Coverage dates are present in the report
- All ten companies are represented
- `reports/latest.md` links to an existing report
- Mermaid graph, section 6.2 table, and JSON baseline have the same `Edge ID`s
- Low-confidence or media-reported relationships include limitation language

## Manual Update Flow

After generating or editing a weekly brief:

```bash
python3 scripts/validate_weekly_brief.py \
  --report reports/YYYY-MM-DD_weekly_morning_brief.md \
  --baseline state/supply_graph_baseline.json \
  --latest reports/latest.md

git status
git add reports/ state/ scripts/
git commit -m "chore: add weekly brief YYYY-MM-DD"
git push
```

If validation fails, fix the report or JSON baseline before committing.

## Automation Flow

The intended production flow is:

1. Windows desktop runs the scheduled Codex automation every Monday at 09:00 Asia/Shanghai.
2. The automation reads `reports/latest.md` and `state/supply_graph_baseline.json`.
3. It generates the new weekly brief and updated supply-chain baseline.
4. It runs `scripts/validate_weekly_brief.py`.
5. If validation passes, it commits and pushes to GitHub.
6. Mac or any other device pulls from GitHub and reads `reports/latest.md`.

Recommended Mac viewing command:

```bash
cd "/Users/qzdmbp/Documents/每周简报"
git pull
open reports/latest.md
```

## Evidence Rules

The brief should prefer:

- Company newsroom or official blog posts
- Investor relations pages
- Regulatory, exchange, government, or court filings
- Major wire services and reputable financial media

Media reports, market views, or unconfirmed supply-chain claims must be clearly labeled. They should not be treated as confirmed facts or new relationships.

## Privacy And Safety

Do not commit:

- GitHub tokens
- API keys
- `.env` files
- Local Codex configuration
- Browser cookies or exported credentials

The repository is public, so generated reports and JSON baselines should be treated as publicly visible.
