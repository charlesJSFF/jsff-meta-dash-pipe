# Meta Dashboard Pipeline — Roadmap

_Last updated: July 2026, following a full repo survey._

## Phase 0 — Stabilize & Document (current phase)

- [x] Survey full repo state (structure, tests, scripts, gaps)
- [x] Write PROJECT_DESCRIPTION.md and this roadmap
- [X] **Replace CLAUDE.md with .clinerules.** The project switched from
      Claude Code to Cline (running on DeepSeek); Cline reads `.clinerules`,
      not `CLAUDE.md`. Delete `CLAUDE.md` once `.clinerules` is committed.
- [X] **Delete `docs/meta_api_reference.md` and
      `docs/relevant_api_reference.md`.** Confirmed not useful going
      forward — clean break, no replacement reference doc for now.
- [X] **Initialize git.** No commit history currently exists — no rollback
      safety net for any of this. Should happen before new extraction
      modules get built, not after.
- [x] Close the three unresolved diagnostic-output gaps by rerunning each
      script and saving redacted output, mirroring the pattern
      diagnose_all_page_metrics.py already established:
  - diagnose_token_190.py — what did the 4 calls actually find about error 190?
  - diagnose_candidate_page_metrics.py — which of the 8 candidate metrics passed?
  - diagnose_page_fans.py — did the token exchange change the outcome?
- [ ] Confirmed: run_fb_page_extraction.py completed successfully with
      corrected FB Page metric names. CSV output saved at
      scripts/output/run_fb_page_extraction_output.csv.
      **Reopened 2026-07-16** — the script as currently written always
      requests exactly a 7-day window, but the saved CSV has 13 rows
      spanning dates that partly postdate the file's own creation
      timestamp; no other script in the repo can produce this file.
      Provenance is unresolved — see
      docs/meta_graph_api_reference.md sec 8.

## Phase 1 — Instagram Media Insights

- [ ] **Open question: no confirmed cumulative follower-total metric on IG.**
      `follower_count` was assumed to be a lifetime snapshot (matching FB's
      `page_follows`), but a live query (June 18–July 1, 2026 window) showed
      daily values fluctuating in the single-to-double digits (11, 6, 3, 8,
      14, 24...) — inconsistent with a cumulative total for an established
      Page. This is actually a daily net-change metric; Meta's API
      description ("Total number of unique accounts following this
      profile") is misleading. Correct FB pairing is
      `page_daily_follows_unique` <-> `follower_count`, not `page_follows`.
      No validated IG equivalent to `page_follows` (cumulative) currently
      exists — week/days_28/lifetime periods all failed for this metric.
      Decide before building IG extraction: (a) reconstruct a running
      total from a baseline snapshot + summed deltas, or (b) accept IG
      side shows growth-rate only, not absolute follower count, as an
      intentional platform asymmetry.
- [ ] Build an IG-equivalent of diagnose_all_page_metrics.py against
      /{ig-id}/media insights fields (reach, views, etc.), to establish
      which metrics are actually valid per media type — the FB approach
      already proved this is worth doing before writing extraction code, not
      after.
- [ ] Build src/extraction/ig_media_insights.py following the same
      fetch_raw() -> parse() -> extract() -> write_csv() pattern.
- [ ] Handle the known media-type-specific gotcha: views is valid for
      Reels/Stories but can error (400) on VIDEO+FEED and CAROUSEL_ALBUM
      posts, and older pre-Business-conversion posts return error subcode
      2108006.
- [ ] Tests in tests/test_ig_media_insights.py.

## Phase 2 — Ads Insights

- [ ] Build src/extraction/ads_insights.py for /{ad-account-id}/insights
      at level=ad.
- [ ] Confirm AD_ACCOUNT_ID auto-discovery — config_loader.py currently
      treats it as optional, but no auto-discovery logic exists yet if it's
      unset. Decide whether that's this phase's job or a separate piece.
- [ ] Handle the creative-lookup join (/{ad-id} -> creative.object_story_id
      etc.) if the dashboard needs paid->organic attribution — confirm this is
      actually needed before building it.
- [ ] Tests.

## Phase 3 — Transformation Layer

- [ ] Define what "transformation" actually needs to do for this dashboard —
      currently unspecified beyond the empty src/transformation/ stub.
      Likely candidates: reshaping per-source CSVs into a common schema,
      joining paid and organic data, computing YoY deltas.

## Phase 4 — BigQuery Loading Layer

- [ ] Schema design per table/data source.
- [ ] Load logic (src/loading/), currently not started at all.

## Phase 5 — Dashboard

- Out of this pipeline's direct scope, but the thing all of the above exists
  to feed. Worth revisiting requirements here once Phases 1-4 clarify what
  data is actually available.

## Ongoing / Not Currently Scheduled

- **Packaging** — no __init__.py files; imports rely on sys.path hacks.
  Not causing problems yet. Revisit if it starts creating friction, not
  proactively.
- **Retry/backoff** (error code 2, Instagram 80002) — deferred per
  CLAUDE.md. Revisit only when explicitly requested.
- **Missing-vs-zero ambiguity** in Page Insights values — deferred per
  CLAUDE.md. Revisit only when explicitly requested.
- **Data-finalization lag** (Meta's ~28-day attribution reprocessing) — no
  re-fetch mechanism exists. Not yet prioritized.
