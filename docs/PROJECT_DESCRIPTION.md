# Meta Dashboard Pipeline — Project Description

_Last updated: July 2026, following a full repo survey._

## Purpose

A Python ETL pipeline that pulls organic and paid performance data from
Meta's Graph API (Facebook Page Insights, Instagram Media Insights, Ads
Insights) into BigQuery, powering a dashboard that answers: **"How is our
Meta performance trending year-over-year, and what's driving the change?"**

## Architecture

```
Meta Dashboard Pipeline/
├── .env.example
├── .gitignore
├── CLAUDE.md                 # governs agent behavior in this repo
├── requirements.txt
├── docs/
│   ├── PROJECT_DESCRIPTION.md   (this file)
│   ├── ROADMAP.md
│   └── deepseek_prompting_best_practices.md
├── config/                    # reserved, currently empty
├── scripts/                   # diagnostic / one-off, not pipeline code
│   ├── diagnose_all_page_metrics.py
│   ├── diagnose_candidate_page_metrics.py
│   ├── diagnose_page_fans.py
│   ├── diagnose_token_190.py
│   └── run_fb_page_extraction.py
├── src/
│   ├── extraction/
│   │   ├── auth.py            # Page Access Token resolution via /me/accounts
│   │   ├── config_loader.py   # loads/validates .env credentials
│   │   └── fb_page_insights.py # fetch/parse/extract/write_csv for FB Page insights
│   ├── transformation/        # reserved, currently empty
│   └── loading/                # reserved, currently empty
└── tests/
    ├── test_auth.py
    ├── test_config_loader.py
    └── test_fb_page_insights.py
```

## Design Decisions (Locked)

- **API version:** v25.0, pinned. Do not bump without explicit request.
- **Extraction pattern per data source:** `fetch_raw()` → `parse()` →
  `extract()` (composes fetch+parse) → `write_csv()`.
- **Auth:** Single `SYSTEM_USER_TOKEN`, exchanged for a Page Access Token via
  `/me/accounts` (`auth.py`). No app ID/secret flow — this matches actual
  Business Manager setup, not the generic OAuth pattern in most docs.
- **HTTP:** `urllib`, manual pagination via `paging.next`. No `requests`/`httpx`
  unless explicitly approved.
- **Secrets:** `python-dotenv` + `.env`, never hardcoded, never printed or
  logged — including in diagnostic script output, which must be redacted.
- **Testing:** No piece is "done" without a passing test file in `tests/`.
- **Time grains:** Daily/weekly/monthly/yearly must be pulled as **separate**
  API calls — reach is deduplicated and not additive across periods.
- **Scope discipline:** Post-level metrics, Instagram, and Ads are each
  separate pieces of work, not bundled into whatever's currently being built.

## Current State

- **FB Page Insights extraction:** built and tested. `auth.py`,
  `config_loader.py`, `fb_page_insights.py` — 17 tests passing.
- **Page metrics availability:** confirmed via `diagnose_all_page_metrics.py`
  — 37 of 80 Page-level metrics succeed on v25.0; 43 fail (mostly the
  deprecated `page_impressions_*` / `page_fans_*` / `page_posts_impressions_*`
  families, plus 4 monetization metrics requiring admin access). The
   pipeline's actual metrics (`page_media_view`, `page_total_media_view_unique`,
  `page_views_total`, `page_follows`) are valid FB Page Insights metric names.
  (These replaced earlier IG-derived names — `reach`, `impressions`,
  `follower_count` — that caused HTTP 400 errors against the FB endpoint.)
- **Instagram Media extraction:** not started. `IG_USER_ID` exists in config
  but has no corresponding extraction module yet. Metric availability was
  probed via `scripts/diagnose_all_ig_media_metrics.py` — **IMAGE**, **VIDEO**,
  and **CAROUSEL_ALBUM** each support 7 of 10 candidate metrics (reach, saved,
  likes, comments, shares, total_interactions, views). **REELS** and **STORY**
  metric lists are defined but untested (no live Reels or Stories at probe
  time).
- **Ads Insights extraction:** not started. `AD_ACCOUNT_ID` exists in config
  (optional, meant to be auto-discovered) but has no corresponding code yet.
- **Transformation layer:** not started (`src/transformation/` empty).
- **BigQuery loading layer:** not started (`src/loading/` empty).
- **Version control:** repo is **not yet a git repository** — no commit
  history exists.
- **Packaging:** no `__init__.py` files anywhere; tests and scripts use
  `sys.path.insert()` to make imports work rather than a proper package
  structure. Not currently causing problems, but worth revisiting before the
  codebase grows further.

## Known Deferred Gaps (intentional — do not silently fix)

- No retry/backoff for transient Graph API errors (code 2 / Instagram code
  80002).
- Missing-vs-zero ambiguity: an empty insights value for a given day is
  currently indistinguishable from a real zero.
- Ads Insights reach-summation correctness (reach is deduplicated; summing
  daily values across a range double-counts).
- No re-fetch mechanism for Meta's ~28-day data-finalization lag.
- **Stories excluded from IG media-level insights.** The `/{ig-user-id}/media`
  endpoint does not return Stories (active-only via `/{ig-user-id}/stories`,
  no API access to archived Stories). Media-level extraction will therefore
  miss Story performance entirely — a systematic gap for an account that runs
  Stories frequently. Possible mitigations: daily `/{ig-user-id}/stories`
  polling to capture per-Story insights before they expire, or relying on
  account-level `/{ig-user-id}/insights` (scope: Phase 2).

## Open Questions (as of July 2026 — resolve opportunistically)

1. ~~What did `diagnose_token_190.py` actually find? No output was saved.~~
   **Resolved.** The 4 calls confirmed that token (code 190) errors no longer
   occur with the current SYSTEM_USER_TOKEN + Page Access Token exchange.
   Saved output at `scripts/output/diagnose_token_190_output.txt`.
2. ~~What did `diagnose_candidate_page_metrics.py` find for the 8 candidate
   metrics it tested? No output was saved.~~
   **Resolved.** All 8 candidate metrics succeeded on v25.0 — including the
   one (`page_fans`) that had previously errored under the old token setup.
   Saved output at `scripts/output/diagnose_candidate_page_metrics_output.txt`.
3. ~~Did the Page-token exchange actually change the outcome for `page_fans` in
   `diagnose_page_fans.py`? No output was saved.~~
   **Resolved.** Yes — the Page Access Token resolved `page_fans`; the
   raw SYSTEM_USER_TOKEN alone returned error code 190. Also surfaced
   `page_views` → `page_views_total` as the API's canonical metric name.
   Saved output at `scripts/output/diagnose_page_fans_output.txt`.
4. Has `run_fb_page_extraction.py` ever completed a successful end-to-end
   run? No CSV output or log currently exists in the repo.

## Working Method & Tools

- **DeepSeek** (terminal coding agent) — primary execution environment for
  writing and running pipeline code. Replaced Claude Code as of mid-2026.
- **Claude** — prompt engineering only. Claude designs structured prompts for
  DeepSeek to execute; Claude does not write or run pipeline code directly.
- **`CLAUDE.md`** — governs DeepSeek's behavior in this repo (discuss-before-act
  for unstructured requests, scope discipline, secret-handling rules).
- **`docs/deepseek_prompting_best_practices.md`** — prompting patterns
  specific to working with DeepSeek's harness/modes.
