# Meta Graph API v25.0 Reference — General / Platform-Interaction Level

_Synthesized 2026-07-16 from the diagnostic scripts in `scripts/` and their
saved output in `scripts/output/`; restructured 2026-07-16 out of the
original single-file `meta_graph_api_ref.md` per
`scripts/output/diagnostic_audit_2026-07-16.md` §4. Page ID under test
throughout: `145245558842140` ("J. Stockard Fly Fishing"). IG User ID under
test: `17841401980438718`._

## Purpose

This is a living reference of **confirmed** Graph API v25.0 behavior that
applies across metrics and across the two platforms this pipeline pulls
from — auth, pagination, range caps, value shapes, and known gotchas. For
per-metric detail, see the companion files:

- [`metric_reference_fb_page.md`](metric_reference_fb_page.md) — one row
  per confirmed FB Page Insights metric.
- [`metric_reference_ig.md`](metric_reference_ig.md) — IG media-level and
  account-level metric detail.

Every claim below is traceable to a specific saved output file — cited by
filename and line number — and inference is labeled as such wherever the
evidence doesn't fully prove the claim.

**Scope discipline:** FB Page Insights and Instagram Insights are two
platforms with materially different API behavior (different range caps,
different response shapes, different parameter models). **Findings for one
platform are not to be generalized to the other** — e.g. FB's 90-day
`since`/`until` range cap is a FB Page Insights finding specifically and
says nothing about IG's range behavior, which is a materially different,
separately-confirmed 30-day cap. Ads Insights, Post-level metrics, and
breakdowns/`fields` params are explicitly **out of scope** for this
document — restated here so it isn't silently assumed covered.

**This is not the full universe of Graph API behavior.** It reflects only
what the scripts in this repo actually tested, against one Page and one IG
account, over a handful of runs in July 2026. Anything not called out here
(other periods, other Pages/accounts, other token types, breakdowns/`fields`
params, Post-level metrics, behavior after a future API version bump) is
simply unknown, not confirmed-absent.

---

## 1. Auth pattern

`auth.py`'s `get_page_access_token()` exchanges a System User token for a
Page Access Token via `/me/accounts`, matching on `page_id`, with a
fallback to the raw System User token (plus a printed warning) if the
Page isn't found in the response. This exists to guard against Graph API
error `code=190` ("This method must be called with a Page Access Token"),
which some Graph API surfaces raise when called with a User-level token
instead of a Page-level one.

**`code=190` has never been reproduced anywhere in this repo's
diagnostics, under either token type.** Three scripts were written
specifically to probe it (`diagnose_token_190.py`,
`diagnose_candidate_page_metrics.py`, `diagnose_page_fans.py`); across all
three, every observed failure is `code=100` ("The value must be a valid
insights metric" — an invalid/legacy metric name), never `code=190`. In
`diagnose_page_fans.py` specifically, the same `code=100` error occurs
identically under both the raw System User token and the exchanged Page
token for the same metric (`page_fans`) — the exchange did not change the
outcome for any call that failed.

**Practical implication:** the `/me/accounts` exchange currently exists in
this codebase for a failure mode that has never actually been observed
against this Page/token combination. This isn't evidence the exchange is
unnecessary — the failure mode it guards against may simply not have been
triggered by any metric name tested so far, or may be specific to a
different Graph API surface (e.g. non-Insights endpoints) not exercised
here. It's flagged so a future session doesn't assume the exchange is
validated by these diagnostics, and doesn't remove it on the mistaken
belief that its target failure mode was disproven rather than simply
unobserved.

Sources: `diagnose_token_190_output.txt` (Call 3, lines 62-71),
`diagnose_page_fans_output.txt` (Calls 1 and 3),
`diagnose_candidate_page_metrics_output.txt` (all 8 candidates).

## 2. Versioning

API version **v25.0**, pinned — do not bump without explicit request (see
`PROJECT_DESCRIPTION.md` Design Decisions).

- Page ID under test: `145245558842140` ("J. Stockard Fly Fishing")
- IG User ID under test: `17841401980438718`

## 3. Pagination

Facebook Page Insights supports `paging.next`/`paging.previous` cursors.
Two materially different query patterns exist, with two separately
confirmed behaviors:

- **`since`+`until` pairs**: subject to the 90-day range cap — see §5.
- **`since`-only (no `until`)**: returns everything from `since` through
  "now" in a **single response**, not chunked. Confirmed across
  `page_media_view`, `page_video_views`, `page_post_engagements`, and
  `page_views_total`, all four periods, anchored ~3 years back — every
  `day`/`week`/`days_28` combo returned the full ~1094-day span in one
  call. There is **no fixed auto-pagination window size** (a previously
  observed ~560-day span was an artifact of one specific `since` anchor,
  not a constant — re-tested with two different anchors, 558d and 1093d,
  each simply matching since-to-now). Source:
  `diagnose_since_only_pagination_output.txt:1-150, 166-169`.

**Cursor-following is not a valid method for probing historical depth
beyond the first hop.** The API's own `paging.previous`/`paging.next`
cursors are themselves `since`+`until` pairs, so following one backward
hits the same 90-day rejection on the very first hop regardless of how far
back real data actually goes. True historical depth is confirmed back to
at least 2023-07-18 for `page_media_view`/`day`; deeper than that is
genuinely unknown (this walk was only attempted for that one
metric/period). Source: `diagnose_since_only_pagination_output.txt:181`.

## 4. Value-shape taxonomy

Three shapes have been observed across FB and IG:

- **Scalar** (default) — a plain integer `value` per data point. Applies
  to 32 of FB's 37 confirmed metrics and to all IG media-level metrics.
- **FB dict-valued** — 5 of FB's 37 metrics return a `dict`-shaped
  `value` with metric-specific keys (e.g. `total`/`paid`/`unpaid`). Full
  list and key sets in `metric_reference_fb_page.md`.
- **IG account-level hour-keyed dict** — `online_followers` returns a
  dict keyed by hour-of-day string `"0"`–`"23"`, one such dict per
  day/`end_time`. A third, distinct shape from either of the above. See
  `metric_reference_ig.md`.

**Check shape before assuming scalar** — don't assume a metric returns a
plain integer without checking its row in the per-metric reference.

## 5. Range caps by platform

| Platform / surface | Cap | Mechanism | Confirmed how |
|---|---|---|---|
| FB Page Insights (`day`/`week`/`days_28`, `since`+`until`) | 90 days full-coverage max | Inferred — 182-day window rejected with `code=100 subcode=1504016`; escalation ladder never tested a value between 90 and 182, so 90 is the last-known-good rung, not an API-stated number | `diagnose_page_metric_params_output.txt:170` |
| FB Page Insights (`since`-only, no `until`) | No fixed cap — spans `since` → "now" in one response | N/A — not chunked; confirmed across two different anchor distances (558d and 1093d), both returned in full | `diagnose_since_only_pagination_output.txt:166-169` |
| FB Page Insights `period=lifetime` | N/A — never returns ranged data | Bare-accepted with no range params; adding `since`/`until` returns 200 with empty `values` for 34/37 metrics, outright rejection for 3 | `diagnose_page_metric_params_output.txt:395` |
| IG account-level insights (all combos) | 30 days, hard | API states it explicitly: `code=100`, "There cannot be more than 30 days (2592000 s) between since and until." | `diagnose_ig_account_insights_params_output.txt:254` (repeated identically for all 16 range-tested combos) |
| IG media-level insights | N/A — no `period`/`since`/`until` parameter exists at all | Scoped to the individual media object's lifetime by design | `diagnose_all_ig_media_metrics_output.txt`, `diagnose_ig_media_reels_stories_output.txt` — no range params ever sent |

**Do not generalize across platforms** — the FB 90-day figure and the IG
30-day figure are two separate, separately-confirmed constants for two
different endpoints, not the same cap observed twice. Both were only
confirmed for this one Page/account/token — not established as
platform-wide constants.

## 6. Rolling-window semantics (FB Page Insights)

**`week` and `days_28` are same-cadence daily rolling sums, not calendar
buckets.** Querying `period=week` or `period=days_28` over an N-day window
returns the same number of data points, at the same one-point-per-day
cadence, as `period=day` over that same window — e.g. for
`page_post_engagements`, a 30-day window returns 29 points for `day`, 29
for `week`, and 29 for `days_28` alike. If `week`/`days_28` were genuine
non-overlapping calendar buckets, a 30-day window would return roughly 4-5
points for `week` and ~1 for `days_28`, not 29. This is a direct
structural observation, confirmed for every metric that supports
`week`/`days_28` with a date range.

The response metadata explicitly labels these as rolling windows ending on
each day, not calendar buckets (e.g. `page_total_actions`'s `period=week`
title is `"Weekly Total: total action count per Page"`, description
`"Weekly: The number of clicks..."` — trailing-7-day-sum language, not
"the total for calendar week N").

**Numeric confirmation is metric-dependent, not universal.** Only
`page_post_engagements` and `page_fan_adds_by_paid_non_paid_unique` have
nonzero sample values suggestive of the rolling-sum arithmetic (e.g.
`page_post_engagements` day values 123/110 on 2026-07-14/15, with
`week` values 778/775 and `days_28` values 2772/2783 on those same
`end_time`s — directionally consistent, roughly 6-7x/25x, but not a
mathematically verified sum). The other 35 metrics rely on
title/description labeling + point-cadence only, not a nonzero numeric
example. Source: `diagnose_page_metric_params_output.txt` lines 71-91
(`page_total_actions`, all-zero), 420-720 (`page_post_engagements`),
756-1091 (`page_fan_adds_by_paid_non_paid_unique`).

**Do not treat `week`/`days_28` as a way to get pre-aggregated calendar-week
or calendar-month rows.** This directly affects
`PROJECT_DESCRIPTION.md`'s "Time grains" design decision, which currently
says grains "must be pulled as separate API calls" without noting they're
all daily-cadence rolling sums under the hood — worth revisiting when the
transformation layer is built (`src/transformation/`, currently empty).

## 7. Known systemic gaps / gotchas

- **Missing-vs-zero ambiguity** — an empty insights value for a given day
  is indistinguishable from a real zero. Known deferred gap per
  `PROJECT_DESCRIPTION.md`.
- **~28-day data-finalization lag** — Meta's insights reprocess for about
  28 days after the fact. `run_fb_page_extraction_output.csv` shows 5
  trailing days of all-zero values for `page_media_view` /
  `page_total_media_view_unique` / `page_views_total` while `page_follows`
  keeps incrementing — consistent with (but not confirmed to be) this lag.
  **Note:** the provenance of that CSV file itself is an open question —
  see the "Open provenance question" callout below; treat the CSV as
  illustrative, not as confirmed evidence of a real finalization-lag
  observation.
- **Rate-limit codes** the pipeline should eventually handle: FB codes
  `4, 17, 32, 613` (from `diagnose_page_metric_params.py`'s detection
  logic, never actually triggered in a saved run — that code path is
  unverified in practice), plus the already-known-deferred general code
  `2` and IG's `80002`. Retry/backoff itself stays deferred per
  `.clinerules`.
- **Redact only at output boundaries.** An early version of
  `diagnose_since_only_pagination.py` redacted the raw HTTP response text
  (stripping the access-token substring) *before* parsing it as JSON.
  Because this API's `paging.next`/`paging.previous` URLs carry the live
  token as one of their own query parameters, that redaction step
  corrupted the token substring embedded inside those URLs — turning it
  into `***REDACTED***` before the JSON was ever parsed, producing a
  confusing downstream "cannot parse access token" error that looked like
  a genuine auth failure but was self-inflicted. **Lesson:** redact
  secrets only at the point of output (printing or writing to disk), after
  all JSON parsing and any logic that needs to act on a raw URL (e.g.
  cursor-following) is complete. The fixed version's `api_get()` docstring
  and its `_redact()`/`redact_url()` split in
  `diagnose_since_only_pagination.py` is a reference pattern for future
  scripts.
- **Write diagnostic output files via the script's own
  `open(path, "w", encoding="utf-8")`, not shell `>` redirection.**
  PowerShell's default `>` redirection encoding is UTF-16LE, which
  corrupted `scripts/output/diagnose_all_ig_media_metrics_output.txt` (the
  6 earliest diagnostic scripts only `print()` to stdout and relied on
  shell redirection to save output). The 4 newest diagnostic scripts
  already write their own UTF-8 output files directly — follow that
  pattern for any new diagnostic script.
- **Monetization-metric permission split is unexplained.** The Page
  token's `/me/accounts` response shows the `VIEW_MONETIZATION_INSIGHTS`
  task granted (`diagnose_page_fans_output.txt:40`), yet 4 monetization
  metrics (`page_daily_video_ad_break_*` ×3,
  `creator_monetization_qualified_views`) fail with a `code=200`
  permissions error while 2 others (`content_monetization_earnings`,
  `monetization_approximate_earnings`) succeed on the same token. Not
  investigated further — flagged as open.

## 8. Open provenance question — not a settled fact

**`run_fb_page_extraction_output.csv` (and the byte-identical root-level
`fb_page_insights.csv`)** contain 13 rows spanning 2026-07-08 through
2026-07-20. Investigated 2026-07-16:

- Both files were added to git in a single commit, `495900a`
  (2026-07-16 17:10:36), as identical blobs — not in the earlier commit
  their filesystem mtimes (2026-07-14 20:06) would suggest.
- `scripts/run_fb_page_extraction.py`, as currently written, always
  requests exactly a 7-day window (`until = date.today() - 1 day`,
  `since = until - 6 days`) — it cannot produce a 13-row file spanning 13
  calendar days from a single run, under any value of "today."
  Five of the 13 rows (07-16 through 07-20) also postdate the files'
  own filesystem creation timestamp by 2-6 days, which isn't physically
  possible for genuine API response data.
- A repo-wide search for the specific values in the file (`13738`,
  `13772`) and the date strings `2026-07-16` through `2026-07-20` found no
  other script, fixture, or notebook capable of producing this data —
  only the two CSV files themselves and doc files that cite them.

**No firm conclusion is drawn here.** The evidence is consistent with the
file having been manually assembled (e.g. to illustrate the
finalization-lag pattern) rather than produced by a genuine end-to-end run
of `run_fb_page_extraction.py`, but this repo's contents alone can't
confirm or rule out other explanations (a process outside this repo, a
manually-specified date range, etc.). `ROADMAP.md`'s Phase 0 "confirmed
successful run" checkbox has been reopened pending this — see
`ROADMAP.md`. The CSV files themselves have not been modified or deleted.

### 8.1 Addendum (2026-07-17) — live run produces fb_page_insights.csv at repo root

A live end-to-end run of `scripts/run_fb_page_extraction.py` at 2026-07-17
17:48 wrote its output to `fb_page_insights.csv` at the repo root (2051
bytes, 7 rows covering 2026-07-10 through 2026-07-16). This confirms the
script's hardcoded output path (`scripts/run_fb_page_extraction.py` lines
23-25: `os.path.join(os.path.dirname(__file__), "..", "fb_page_insights.csv")`).

The stale file at `scripts/output/run_fb_page_extraction_output.csv` (456
bytes, last modified 2026-07-14 20:06) was **not** touched by this run. Its
provenance remains unexplained — see the main §8 analysis above. The byte
identity previously noted between the two files is now **broken**: the live
file and the stale file differ in size (2051 vs 456 bytes) and content.

**Implications for the open provenance question:**
- The root-level `fb_page_insights.csv` is now demonstrably the script's
  genuine output from a live run on 2026-07-17. This does **not** explain
  the 13-row, 456-byte file at `scripts/output/` or its earlier mtime
  paradox — those facts remain unresolved and are consistent with the
  "manually assembled" theory described in §8.
- The old 13-row `fb_page_insights.csv` (the one that was byte-identical to
  `scripts/output/run_fb_page_extraction_output.csv`) was overwritten by
  this live run and is no longer present in the working tree. It remains
  recoverable from git history — it was committed at commit `495900a`
  (2026-07-16 17:10:36) per the original §8 finding — via
  `git show 495900a:fb_page_insights.csv`. Whether to restore it for
  further investigation, or treat the new live-data file as the correct
  ongoing baseline, is an open decision not made here.

## 9. Explicitly out of scope

Ads Insights, Post-level metrics, and breakdowns/`fields` params were never
tested by any script in this repo and are not covered by this document or
its companion metric-reference files.

## 10. Migration notes

`src/extraction/fb_page_insights.py` (lines 51, 84, 122) previously
referenced `docs/relevant_api_reference.md`, which `ROADMAP.md` records as
deleted in Phase 0. Those references have been repointed to this file. No
stale doc-path reference was found in `auth.py` on inspection (correcting
an earlier audit note that flagged it alongside `fb_page_insights.py`).

`diagnose_all_page_metrics.py` and `diagnose_candidate_page_metrics.py`
docstrings still reference `docs/meta_api_reference.md`, also deleted per
`ROADMAP.md`. Left as-is per this pass's scope (no `.py` script edits) —
worth a follow-up docstring fix whenever those scripts are next touched.
