# Meta Graph API v25.0 Reference — FB Page & Instagram Insights

_Synthesized 2026-07-16 from the diagnostic scripts in `scripts/` and their
saved output in `scripts/output/`. Page ID under test throughout:
`145245558842140` ("J. Stockard Fly Fishing"). IG User ID under test:
`17841401980438718`._

## Purpose

This is a living reference of **confirmed** Graph API v25.0 behavior for two
platforms this pipeline pulls from — Facebook Page Insights
(`/{page-id}/insights`) and Instagram Insights (media-level,
`/{ig-media-id}/insights`, and account-level, `/{ig-user-id}/insights`) —
built from actual API responses captured by this repo's diagnostic scripts.
Its job is to let a future session answer "how does metric X actually
behave" by reading this doc, instead of re-running diagnostics or
re-reading raw JSON dumps.

**Scope discipline:** FB Page Insights and Instagram Insights are two
platforms with materially different API behavior (different range caps,
different response shapes, different parameter models), documented in
separate sections below (§1–2 for FB, §3–4 for Instagram). **Findings for
one platform are not to be generalized to the other** — e.g. FB's 90-day
`since`/`until` range cap (§1.2) is a FB Page Insights finding specifically
and says nothing about IG's range behavior, which is a materially different,
separately-confirmed 30-day cap (§4.3). Ads Insights remains explicitly out
of scope for this document.

**This is not the full universe of Graph API behavior.** It reflects only
what the scripts in this repo actually tested, against one Page and one IG
account, over a handful of runs in July 2026. Anything not called out here
(other periods, other Pages/accounts, other token types, breakdowns/`fields`
params, Post-level metrics, behavior after a future API version bump) is
simply unknown, not confirmed-absent. Every claim below is traceable to a
specific saved output file — cited by filename and line number — and
inference is labeled as such wherever the evidence doesn't fully prove the
claim.

---

## 1. FB Page Insights — General Behavior (applies across metrics)

### 1.1 Metric-name validity (v25.0)

`scripts/diagnose_all_page_metrics.py` tested 80 Page-level metric names
(everything listed under Page metrics on the v25.0 `availmetrics` doc,
excluding `post_*` metrics which are a different endpoint) one at a time
with `period=day`, no date range. Result (`diagnose_all_page_metrics_output.txt`):

- **37 succeeded** (200, `data` present) — see §2 for the full list.
- **43 failed**, in two distinct failure modes:
  - **`code=100` "(#100) The value must be a valid insights metric"** (39
    metrics) — the name itself is rejected outright on v25.0. Families:
    `page_tab_views_*` (3), `page_impressions*` (8), `page_posts_impressions*`
    (10), `page_fans*`/`page_fan_adds*`/`page_fan_removes*` (8),
    `page_video_views_10s*` (7), `page_uploaded_*` (3). A scraped fragment of
    Meta's own v25.0 docs page (`scripts/output/_temp_metric_extracts.txt`)
    independently labels `page_impressions_unique` **"Deprecated above Graph
    API v25"** in its own description text — this corroborates but doesn't
    fully explain the whole `code=100` list (the doc text wasn't checked
    metric-by-metric here; treat "deprecated" as confirmed for
    `page_impressions_unique` specifically, plausible-but-unverified for its
    siblings).
  - **`code=200` "Monetization metrics are only visible for Page admins with
    access to monetization insights"** (4 metrics) —
    `page_daily_video_ad_break_ad_impressions_by_crosspost_status`,
    `page_daily_video_ad_break_cpm_by_crosspost_status`,
    `page_daily_video_ad_break_earnings_by_crosspost_status`,
    `creator_monetization_qualified_views`. This is a **permission** failure,
    not a naming failure — see the open question in §6 about why these 4
    fail while `content_monetization_earnings` and
    `monetization_approximate_earnings` succeed on the same token.

### 1.2 The 90-day `since`/`until` range cap

`scripts/diagnose_page_metric_params.py` swept all 37 confirmed-valid
metrics × periods `{day, week, days_28, lifetime}`, escalating the window
7d → 30d → 90d → 182d → 365d → 456d and checking that the returned data
actually covered the requested range (not just a 200 status).

**Confirmed: every one of the 37 metrics, on every one of `day`, `week`, and
`days_28`, accepts up to a 90-day window with full coverage, and a 182-day
window is uniformly rejected** with `code=100 subcode=1504016 msg=Invalid
parameter` (e.g. `diagnose_page_metric_params_output.txt:170`). No metric in
this run ever reached the 365d or 456d rungs of the escalation ladder — the
cap was hit at 182d for all of them, so 90 days is the confirmed ceiling and
365d+ was never actually attempted against a still-accepting endpoint.

This cap was **not** confirmed against `period=lifetime` — see §1.3, `lifetime`
never returns ranged data at all, so the 90-day figure is a `day`/`week`/`days_28`
finding specifically, not a Page Insights-wide constant. It was also only
confirmed for this one Page; whether it's a per-Page, per-app, or
platform-wide constant is not established here.

**`since`+`until` pairs vs. `since`-only queries — two separate parameter
patterns, two separate confirmed behaviors.** Everything above in this
section is specifically about queries that pass **both** `since` and
`until`. A follow-up diagnostic, `scripts/diagnose_since_only_pagination.py`
(output: `diagnose_since_only_pagination_output.txt`), tested the other
case — `since` supplied, `until` omitted entirely — and found materially
different behavior:

- **Confirmed:** a `since`-only query returns everything from `since`
  through "now" in a **single response**, not chunked at 90 days. Tested
  across `page_media_view`, `page_video_views`, `page_post_engagements`,
  and `page_views_total`, all four periods (`day`/`week`/`days_28`/
  `lifetime`), anchored ~3 years back — every `day`/`week`/`days_28` combo
  returned the full ~1094-day span in one call (`lifetime` returned 0
  points for all of them, consistent with §1.3's existing finding that
  `lifetime` doesn't support ranged queries at all, `since`-only or
  otherwise). See `diagnose_since_only_pagination_output.txt:1-150`.
- **The previously-observed "~560-day auto-page size" is not a real, fixed
  constant.** The manual Graph API Explorer check that originally prompted
  this investigation had observed a ~560-day span for
  `page_media_view`/`day` with `until` omitted, which looked at the time
  like it might be a fixed auto-pagination window. That observation was a
  reasonable read of the one data point available — the issue is only that
  a single data point can't establish a constant. This diagnostic re-ran
  the same query with two different `since` anchors (~560 days back and
  ~3 years back) specifically to test that: the returned span tracked the
  distance from `since` to "now" in **both** cases (558d and 1093d
  respectively, each matching since-to-now almost exactly — see
  `diagnose_since_only_pagination_output.txt:166-169`), not a shared fixed
  figure. **There is no confirmed ~560-day (or any other fixed-size)
  auto-pagination window** — `since`-only responses simply span from
  `since` to "now," whatever that distance happens to be.
- **True historical depth: confirmed back to at least 2023-07-18 for
  `page_media_view`/`day`; deeper than that is unknown, and here's why.**
  The single `since`-only call above already confirms real data exists
  back to 2023-07-18. To probe further back, the diagnostic followed the
  response's `paging.previous` cursor one hop backward — and that hop was
  rejected with the identical `code=100 subcode=1504016` signature as the
  `since`+`until` cap documented earlier in this section
  (`diagnose_since_only_pagination_output.txt:181`). This is **not**
  evidence of a data boundary at 2023-07-18: the API's own
  `paging.previous`/`paging.next` cursors are themselves `since`+`until`
  pairs (visible directly in the cursor URLs — e.g. `since=2020-07-18&
  until=2023-07-17`, a 1094-day span), so following one back hits the same
  90-day rejection on the very first hop regardless of how far back real
  data actually goes. **Cursor-following is not a valid method for probing
  historical depth beyond the first hop** — this is a limitation of that
  probing technique, not a confirmed data boundary. True depth beyond
  2023-07-18 remains genuinely unknown. (This walk was only attempted for
  `page_media_view`/`day`; the other three metrics and remaining periods
  weren't walked backward.)

### 1.3 `period=lifetime` does not support `since`/`until`

For 34 of the 37 metrics, `period=lifetime` is **bare-accepted** (no error
when queried alone) but **returns `200` with an empty `data[].values` array**
the moment a `since`/`until` range is added — e.g.
`diagnose_page_metric_params_output.txt:395`: `"- 7d (...): ACCEPTED, but no
data points returned"`. This pattern repeats identically for every metric
that accepts `lifetime` at all (grep `period=lifetime` in that file for the
full list) — there is no case in this run where a ranged `lifetime` query
returned partial/truncated data; it's either full daily-cadence data (for
`day`/`week`/`days_28`) or nothing.

Three metrics reject `period=lifetime` outright, with two different error
shapes:
- `page_video_views_by_uploaded_hosted` and `content_monetization_earnings`:
  `code=100 msg=(#100) For field 'insights': Param period must be one of
  {day, week, days_28}` (lines 6833, 12880) — a clean, self-explanatory
  rejection.
- `page_media_view`: `code=1 subcode=99 msg=An unknown error occurred`
  (line 3049) — an opaque, non-descriptive error for what is presumably the
  same underlying "lifetime not supported for this metric" condition. Flagged
  as an anomaly worth re-checking rather than treated as equivalent to the
  clean rejection above.

**Practical implication (not a design decision — just the fact):** none of
the 37 metrics offer a usable ranged "all-time total" query via this
endpoint's `lifetime` period. A running/lifetime total would have to come
from some other mechanism (a snapshot-based metric like `page_follows`, or
client-side accumulation).

### 1.4 The day / week / days_28 "rolling sum," not a distinct bucket

**This is the nuance to read carefully — it is confirmed by response
labeling, and confirmed by response point-cadence, but numeric confirmation
is metric-dependent.**

Structural fact, true for every metric that supports `week`/`days_28` with a
date range: querying `period=week` or `period=days_28` over an N-day window
returns **the same number of data points, at the same one-point-per-day
cadence, as `period=day` over that same window** — e.g. for
`page_post_engagements`, a 30-day window returns 29 points for `day`, 29
points for `week`, and 29 points for `days_28` alike (lines 439, 550, 661).
If `week`/`days_28` were genuine non-overlapping calendar buckets, a 30-day
window would return roughly 4-5 points for `week` and ~1 for `days_28`, not
29. This part is a direct structural observation, not an inference.

The response metadata explicitly labels these as rolling windows ending on
each day, not calendar buckets: for `page_total_actions`, `period=week`'s
`title` is `"Weekly Total: total action count per Page"` and `description`
is `"Weekly: The number of clicks..."` (line 200) — language consistent
with a trailing-7-day sum ending on `end_time`, not "the total for calendar
week N." Same pattern for `days_28` (`"28 Days Total..."`, line 382).

**Numeric confirmation status, by metric:**
- `page_total_actions`: all sampled values were **zero** across day/week/
  days_28 (lines 71-91). The rolling-sum claim for this metric rests on
  title/description labeling and point-cadence only — **not yet confirmed by
  a nonzero numeric example.**
- `page_post_engagements`: sampled values are nonzero and **consistent with**
  a rolling sum — e.g. day values on 2026-07-14/07-15 were 123/110, and the
  `week` values on those same `end_time`s were 778/775, `days_28` were
  2772/2783 (lines 420-720). This is suggestive (roughly 6-7x for week, ~25x
  for days_28, in the right ballpark) but **not a mathematically verified
  sum** — the full run of intervening daily values wasn't cross-checked
  against the weekly total in this synthesis.
- `page_fan_adds_by_paid_non_paid_unique`: similarly nonzero and
  directionally consistent (`unpaid` day values ~1-6, `week` unpaid=30,
  `days_28` unpaid=92 for the same window; lines 756-1091) — same caveat as
  above, suggestive not proven.
- All other metrics: not individually checked for this nuance in this
  synthesis pass; assume the same day-cadence/rolling-window structure
  applies (confirmed structurally per metric — see §1.4's opening
  paragraph, which holds for every metric in the sweep) but numeric
  verification wasn't attempted beyond the three above.

**Do not treat `week`/`days_28` as a way to get pre-aggregated calendar-week
or calendar-month rows.** They are same-cadence daily series with a wider
lookback window baked into each point.

### 1.5 Error code 190 vs 100 — not actually reproduced

Three scripts (`diagnose_token_190.py`, `diagnose_candidate_page_metrics.py`,
`diagnose_page_fans.py`) were written to investigate an original `code=190`
("This method must be called with a Page Access Token") error. **In the
saved output of all three, `code=190` never appears once.** Every failure
observed is `code=100` "(#100) The value must be a valid insights metric" —
i.e., an invalid/legacy metric name, not a token-type problem:

- `diagnose_token_190_output.txt`: Calls 1, 2, and 4 (Page fields, token
  permissions, token identity) all succeed with the raw System User token.
  Call 3 (`metric=page_views`) fails with `code=100` — `page_views` is
  simply not a valid v25.0 metric name (see §1.6), tested here with **no
  Page-token exchange at all** (the script uses `config.system_user_token`
  directly for every call — it does not exercise the exchange path).
- `diagnose_page_fans_output.txt`: `metric=page_fans` fails with **the same
  `code=100` error under both** the raw System User token (Call 1) and the
  exchanged Page Access Token (Call 3). The token exchange made **no
  observable difference** to this call's outcome.
- `diagnose_candidate_page_metrics_output.txt`: all 8 candidates tested with
  the exchanged Page token; failures are `code=100` for genuinely-invalid
  names (`page_impressions*_unique`), never `code=190`.

**Conclusion actually supported by the evidence:** on the current token/Page
setup, `code=190` does not reproduce regardless of token type, and the
Page-token exchange does not change outcomes for calls that fail — those
calls fail because the metric name itself is invalid on v25.0, not because
of token type. See §5 for how this conflicts with the existing docs'
narrative.

### 1.6 Legacy → current metric name mapping

- **`page_views` → `page_views_total`**: `page_views` fails with `code=100`
  (confirmed, `diagnose_token_190_output.txt:62-71`); `page_views_total`
  succeeds and carries the description "Total views count per Page" (line
  12127) — descriptively the natural successor. **This mapping is inferred
  by elimination + description match, not confirmed by any explicit Meta
  migration statement in the captured material.**
- **`page_fans` → no confirmed successor.** `page_fans` fails with
  `code=100` in every test (§1.5). `page_follows` succeeds and describes
  itself as "The number of followers of your Facebook Page or profile...
  calculated as follows minus unfollows over the lifetime" (matches
  Facebook's Likes→Follows rebrand narrative) — a **plausible** successor,
  but this synthesis found no direct evidence (no paired before/after test)
  confirming `page_follows` is the intended 1:1 replacement for `page_fans`
  specifically. Treat as a reasonable hypothesis, not a confirmed mapping.
- No other legacy→current renames were specifically tested for in this
  material.

### 1.7 Value shapes: most metrics are scalar; five are dict-valued

Of the 37 confirmed-valid metrics, **32 return a plain integer** `value` per
data point. **Five return a `dict`-shaped `value`:**

| Metric | `value` keys observed |
|---|---|
| `page_fan_adds_by_paid_non_paid_unique` | `total`, `paid`, `unpaid` |
| `page_video_views_by_paid_non_paid` | `total`, `unpaid`, `paid` |
| `page_video_views_by_uploaded_hosted` | `page_uploaded`, `page_uploaded_from_crossposts`, `page_uploaded_from_shares`, `page_hosted_crosspost`, `page_hosted_share`, `page_owned` |
| `page_actions_post_reactions_total` | dynamic — only reaction types with nonzero activity that day appear (e.g. one day had just `{"like": 15}`, another `{"like": 12, "love": 1}`, line 5443-5460). **A missing key was not explicitly confirmed to mean zero** — inferred from the pattern, not tested against a day with a documented zero for a present-elsewhere key. |
| `content_monetization_earnings` | `currency` (string, `"USD"`), `microAmount` (int, `0` in all samples) |

`monetization_approximate_earnings` — despite also being a monetization
metric — returns a **plain scalar**, not a dict. Don't assume "monetization
metric" implies dict-shaped value.

### 1.8 Response `id` field can name a different internal metric

`page_video_views_by_uploaded_hosted`'s response `id` field reads
`.../insights/page_video_view_count_by_uploaded_hosted/day` — a different
string than the requested/returned `name` field
(`page_video_views_by_uploaded_hosted`, line 6255 vs 6306). This is the only
such mismatch found across all 37 metrics (checked programmatically against
every sampled `name`/`id` pair in the file). Worth knowing if any future code
tries to match on the `id` field rather than `name`.

### 1.9 Rate limiting

`diagnose_page_metric_params.py` has explicit rate-limit detection (codes
4, 17, 32, 613) and stops the sweep immediately if hit, saving partial
results. **This particular run completed all 37 metrics without triggering
it** — the rate-limit-stop code path itself is unexercised/unverified by
this data.

### 1.10 Diagnostic methodology note: redact only at output boundaries

Worth generalizing to any future diagnostic script in this project, not
just the one that surfaced it: an early version of
`scripts/diagnose_since_only_pagination.py` redacted the raw HTTP response
text (stripping the access-token substring) **before** parsing it as JSON.
Because this API's `paging.next`/`paging.previous` URLs carry the live
token as one of their own query parameters, that redaction step corrupted
the token substring embedded inside those URLs — turning it into
`***REDACTED***` before the JSON was ever parsed. The visible symptom was
a confusing downstream "cannot parse access token" error on the next
cursor-following request, which looked like a genuine auth failure but was
actually self-inflicted by redacting mid-pipeline, not a real API problem.

**Lesson:** redact secrets only at the point of output (printing or
writing to disk), after all JSON parsing — and any logic that needs to act
on a raw URL, such as following a paging cursor — is complete. Keep the
raw, unredacted parsed response in memory for as long as the script needs
it; pass everything through a redaction step only at the boundary where it
is about to be displayed or persisted. The fixed version's `api_get()`
docstring and its `_redact()`/`redact_url()` split in
`scripts/diagnose_since_only_pagination.py` reflects this and can be used
as a reference pattern for future scripts.

---

## 2. FB Page Insights — Per-Metric Reference

All 37 metrics below follow the **default pattern** unless an exception is
noted in the "Deviates?" column:

> **Default pattern:** `period` ∈ `{day, week, days_28}` all bare-accepted;
> `since`/`until` accepted on all three with **90-day confirmed max
> full-coverage lookback**, 182-day rejected (`code=100 subcode=1504016`);
> `period=lifetime` bare-accepted but returns **no data** once a range is
> added; scalar integer `value`.

Source for every row is `scripts/output/diagnose_page_metric_params_output.txt`
(cited as `params.txt:<line>` = the `METRIC:` header line for that block —
read forward from there for the full day/week/days_28/lifetime detail and
sample payloads). Sample payloads are **not re-pasted here**; the source
file has one full JSON sample per accepted period+window combination, and
re-pasting 37×3 payloads would make this doc unusable as a quick reference.

| Metric | Deviates from default pattern? | Source |
|---|---|---|
| `page_total_actions` | No (values sampled all zero — see §1.4) | params.txt:57 |
| `page_post_engagements` | No | params.txt:398 |
| `page_fan_adds_by_paid_non_paid_unique` | Dict-valued (§1.7) | params.txt:739 |
| `page_lifetime_engaged_followers_unique` | No (name says "lifetime" but behaves like every other metric — its own `lifetime` *period* is still non-rangeable like the rest) | params.txt:1224 |
| `page_daily_follows` | **Yes** — `week` and `days_28` are bare-accepted but return **no data for any window tested**, including 7d (not just beyond 90d). Effectively day-only in practice despite accepting the period param. | params.txt:1565 |
| `page_daily_follows_unique` | No | params.txt:1690 |
| `page_daily_unfollows_unique` | No | params.txt:2031 |
| `page_follows` | No | params.txt:2372 |
| `page_media_view` | **Yes** — `period=lifetime` rejected outright with an opaque `code=1 subcode=99 "An unknown error occurred"` (not the clean "must be one of" message other rejections use) | params.txt:2713 |
| `page_total_media_view_unique` | No | params.txt:3052 |
| `page_actions_post_reactions_like_total` | No | params.txt:3393 |
| `page_actions_post_reactions_love_total` | No | params.txt:3734 |
| `page_actions_post_reactions_wow_total` | No | params.txt:4075 |
| `page_actions_post_reactions_haha_total` | No | params.txt:4416 |
| `page_actions_post_reactions_sorry_total` | No | params.txt:4757 |
| `page_actions_post_reactions_anger_total` | No | params.txt:5098 |
| `page_actions_post_reactions_total` | Dict-valued, dynamic keys (§1.7) | params.txt:5439 |
| `page_video_views` | No | params.txt:5904 |
| `page_video_views_by_uploaded_hosted` | **Yes** — dict-valued (§1.7); `period=lifetime` rejected with clean `code=100` "must be one of {day,week,days_28}"; response `id` names a different internal metric (§1.8) | params.txt:6245 |
| `page_video_views_paid` | No | params.txt:6836 |
| `page_video_views_organic` | No | params.txt:7177 |
| `page_video_views_by_paid_non_paid` | Dict-valued (§1.7) | params.txt:7518 |
| `page_video_views_autoplayed` | No | params.txt:8003 |
| `page_video_views_click_to_play` | No | params.txt:8344 |
| `page_video_views_unique` | No | params.txt:8685 |
| `page_video_repeat_views` | No | params.txt:9026 |
| `page_video_complete_views_30s` | No | params.txt:9367 |
| `page_video_complete_views_30s_paid` | No | params.txt:9708 |
| `page_video_complete_views_30s_organic` | No | params.txt:10049 |
| `page_video_complete_views_30s_autoplayed` | No | params.txt:10390 |
| `page_video_complete_views_30s_click_to_play` | No | params.txt:10731 |
| `page_video_complete_views_30s_unique` | No | params.txt:11072 |
| `page_video_complete_views_30s_repeat_views` | No | params.txt:11413 |
| `page_video_view_time` | No | params.txt:11754 |
| `page_views_total` | No — legacy name was `page_views` (§1.6, inferred) | params.txt:12095 |
| `content_monetization_earnings` | **Yes** — dict-valued `{currency, microAmount}`; `period=lifetime` rejected with clean `code=100` "must be one of {day,week,days_28}" | params.txt:12436 |
| `monetization_approximate_earnings` | No — scalar despite being a monetization metric, unlike `content_monetization_earnings` | params.txt:12883 |

None of the 37 metrics reached `SAFE_FOR_FULL_YOY` classification (the
script's own >=365-day threshold) — all 37 are `RANGE_LIMITED` at 90 days.
See the script's own summary block at `params.txt:1-51`.

---

## 3. Instagram Media-Level Insights

_IG User ID under test: `17841401980438718`. Endpoint:
`GET /{ig-media-id}/insights`. Two scripts contribute to this section: the
original sweep, `scripts/diagnose_all_ig_media_metrics.py` (run 2026-07-14,
output `diagnose_all_ig_media_metrics_output.txt`, covering IMAGE, VIDEO,
CAROUSEL_ALBUM), and the newer gap-closing script,
`scripts/diagnose_ig_media_reels_stories.py` (run 2026-07-16, output
`diagnose_ig_media_reels_stories_output.txt`, covering REELS and STORY).
Both are cited below as `media.txt` and `reels.txt` respectively._

**Section choice, per this task's brief:** media-level and account-level IG
insights are presented as two separate top-level sections (§3, §4) rather
than one combined "Instagram" section, because they are structurally
distinct surfaces — different endpoints, different parameter models (no
`period`/`since`/`until` at all for media-level; both for account-level),
and different response shapes — and folding them together would obscure
that distinction the way it obscured the FB/IG distinction in the old
single-platform doc.

No `period`, `since`, or `until` parameter was ever sent to
`/{ig-media-id}/insights` in either script — media-level insights are
inherently scoped to the individual media object's lifetime, not a date
range. (The response nonetheless echoes `"period": "lifetime"` for every
metric — see §3.6.)

### 3.1 Candidate-metric methodology

Both scripts test the **same 10-candidate set** — `reach`, `saved`,
`likes`, `comments`, `shares`, `total_interactions`, `engagement`,
`impressions`, `video_views`, `views` — against whichever media type they
cover. This set was kept identical across IMAGE/VIDEO/CAROUSEL_ALBUM/REELS
specifically so results are directly comparable type-to-type, even though
REELS (and, untested, STORY) may have additional dedicated metrics not
covered by this set — see §6 (Gaps).

### 3.2 Confirmed results, by media type

| Media Type | Succeeded (7) | Failed (3) | Payloads captured? | Source |
|---|---|---|---|---|
| IMAGE | reach, saved, likes, comments, shares, total_interactions, views | engagement, impressions, video_views | No — status only | media.txt:13-23 |
| VIDEO | (same 7) | (same 3) | No — status only | media.txt:25-35 |
| CAROUSEL_ALBUM | (same 7) | (same 3) | No — status only | media.txt:37-47 |
| REELS | (same 7) | (same 3) | **Yes** — redacted, values truncated to 3 | reels.txt:9-19, 42-166 |
| STORY | — | — | N/A — BLOCKED, see §3.4 | reels.txt:21-26 |

**All four testable media types produced byte-identical success/failure
sets for this 10-metric candidate list.** The original sweep did not save
full response payloads for IMAGE/VIDEO/CAROUSEL_ALBUM (status only,
SUCCESS/FAIL per metric); the newer script additionally captured one
redacted sample payload per succeeding metric for REELS specifically (see
§3.6 for what those show).

### 3.3 The REELS discovery-bug (methodology callout)

**This is a methodology lesson independent of the specific metric
findings, worth reading by anyone writing a future script that buckets IG
media by type.**

The original `diagnose_all_ig_media_metrics.py`'s discovery phase queries
`/{ig-user-id}/media` for the `media_type` field and buckets results into
IMAGE / VIDEO / CAROUSEL_ALBUM / REELS / STORY. But per the Graph API,
`media_type` **only ever returns `IMAGE`, `VIDEO`, or `CAROUSEL_ALBUM`** —
Reels are returned with `media_type=VIDEO` and are distinguishable only via
a separate field, `media_product_type` (observed values: `FEED`, `REELS`).
The original script never queried `media_product_type`, so its "REELS: not
found" result (`media.txt:6`, "REELS: not found (no Reels found in recent
media)") **could never have matched REELS regardless of whether Reels
content existed** — it was not a reliable test of Reels' existence, just an
artifact of checking the wrong field.

The newer script queried `media_product_type` explicitly and found **15
REELS items among the 50 most recent media items** (`reels.txt:7`, "
`media_product_type` breakdown: `{'FEED': 35, 'REELS': 15}`"), immediately
disproving the "no Reels" conclusion. This is a factual observation about
what the two scripts' queries actually checked, not a fix applied to the
original file (left unmodified per its own task brief).

**Takeaway for future code:** never bucket IG media by `media_type` alone
if REELS needs to be distinguished from FEED video — query
`media_product_type` instead (or in addition).

### 3.4 STORY: blocked, not silently omitted

STORY is documented here as **blocked**, not untested-and-ignored. The
newer script checked two places, neither of which is guesswork:

1. `/{ig-user-id}/media` filtered for `media_product_type == "STORY"` — 0
   found among the 50 most recent items (`reels.txt:22`).
2. The dedicated `/{ig-user-id}/stories` edge (active-Stories-only, since
   Stories expire ~24h and don't persist on `/media`) — 0 active items
   returned (`reels.txt:23-25`).

Both the original sweep (2026-07-14) and the newer sweep (2026-07-16) found
zero live Story content. This is **consistent with** "no Story was posted
in the last 24h at either run time," not conclusive proof Stories
categorically don't work for this account/token — a real test requires
re-running within 24h of an actual Story post (see §6).

Separately: the original script also defined a STORY-specific candidate
metric list (`reach`, `replies`, `navigation`, `taps_forward`, `taps_back`,
`exits`, `total_interactions`), different from the general 10 used
elsewhere — but since no Story content was ever found in either run,
**neither** that STORY-specific list **nor** the general-10 list has
actually been tested against live Story data.

### 3.5 Failure-mode detail for the 3 consistently-failing candidates

All three fail identically (same failure mode) across every media type
tested, including REELS:

- **`engagement`** — `code=100`, "(#100) metric[0] must be one of the
  following values: impressions, reach, replies, saved, likes, comments,
  shares, total_interactions, follows, profile_visits, profile_activity,
  navigation, ig_reels_video_view_total_time, ig_reels_avg_watch_time,
  views, reels_skip_rate, reposts, facebook_views, crossposted_views,
  total_views, total_likes, total_comments, link_clicks" — not a valid
  Media Insights metric name at all, for any tested media type
  (`reels.txt:16`).
- **`video_views`** — the identical "must be one of" error and list as
  `engagement` (`reels.txt:18`) — also not a valid metric name.
- **`impressions`** — `code=100`, but the **message text varies by media
  type**: IMAGE and CAROUSEL_ALBUM get "(#100) Starting from version v22.0
  and above, the impressions metric is no longer supported for the queried
  media" (`media.txt:21,45`); VIDEO and REELS get "(#100) The Media
  Insights API does not support the impressions metric for this media
  product type" (`media.txt:33`, `reels.txt:17`). Both are rejections of
  the same underlying request; the wording difference is noted as an
  observation, not independently explained.

**Cross-type observation:** the enumerated "must be one of" list for
`engagement`/`video_views` is textually identical across IMAGE and REELS
despite `media_type` differing between them (checked directly; VIDEO and
CAROUSEL_ALBUM were not byte-compared against this exact string in this
synthesis pass, only visually similar) — and includes clearly Reels-only
names (`ig_reels_avg_watch_time`, `reels_skip_rate`) even in the IMAGE
response. This suggests the API returns a fixed, non-media-type-scoped
list in this particular error message rather than filtering it per media
type — an observation, not a confirmed API design fact.

### 3.6 Value shape and sample payloads

Every succeeding media-level metric returns `"period": "lifetime"` in the
response (even though `period` was never sent as a request parameter) and
a **single-element `values` array** with a **plain scalar integer**
`value` — no dict-shaped values were observed at the media level (contrast
with FB's 5 dict-valued metrics, §1.7, and IG account-level's
`online_followers`, §4.5). Sample payloads for REELS's 7 succeeding
metrics are saved in full (redacted, truncated to 3 values — though every
media-level metric only ever returns 1 value point anyway) at
`reels.txt:42-166`; representative example (`reels.txt:42-58`):

```json
{
  "data": [
    {
      "name": "reach",
      "period": "lifetime",
      "values": [{"value": 4569}],
      "title": "Accounts reached",
      "description": "The number of unique accounts that have seen this reel...",
      "id": "17874602505612323/insights/reach/lifetime"
    }
  ]
}
```

No equivalent saved payloads exist for IMAGE/VIDEO/CAROUSEL_ALBUM (the
original script recorded SUCCESS/FAIL status only) — not re-created here,
per the task's read-only/no-new-diagnostics scope.

---

## 4. Instagram Account-Level Insights

_IG User ID under test: `17841401980438718`. Endpoint:
`GET /{ig-user-id}/insights`. Two scripts contribute: the discovery sweep,
`scripts/diagnose_all_ig_account_metrics.py` (run 2026-07-14, output
`diagnose_all_ig_account_metrics.txt`, 25 candidate metric names × 77
metric/period/metric_type combos, 17 SUCCESS), and the newer
parameter-space script, `scripts/diagnose_ig_account_insights_params.py`
(run 2026-07-16, output `diagnose_ig_account_insights_params_output.txt`),
which starts from those 17 confirmed-valid combos and sweeps `since`/
`until` range acceptance using the same escalation-ladder approach as the
FB parameter-space script (§1.2): 7d → 30d → 90d → 182d → 365d → 456d,
stopping at first rejection or non-full-coverage response. Cited below as
`account.txt` (discovery) and `params2.txt` (range sweep)._

**Structural difference from FB Page Insights, worth reading before the
rest of this section:** IG account metrics queried with
`metric_type=total_value` return a single `total_value: {"value": N}`
object per data entry, **not** a `values: [{value, end_time}, ...]` time
series. There is no per-day breakdown to check against a requested
`since`/`until` window for those combos — see §4.4.

### 4.1 Valid metric+period(+metric_type) combos (17 of 25 candidates tested)

- **`reach`** — `period` ∈ `{day, week, days_28}` all SUCCESS
  (time-series); `period=lifetime` FAILS ("incompatible").
- **`follower_count`** — `period=day` SUCCESS (time-series); `week`,
  `days_28`, `lifetime` all FAIL; `metric_type=total_value` is
  incompatible with this metric for any period.
- **`online_followers`** — `period=lifetime` SUCCESS, but see §4.5 for its
  distinct dict-of-hours value shape; `period=day` FAILS.
- **12 metrics require `metric_type=total_value` AND `period=day`
  together** (no other period grain works for any of them —
  `days_28`/`lifetime` + `total_value` all fail): `accounts_engaged`,
  `total_interactions`, `likes`, `comments`, `saves`, `shares`, `replies`,
  `views`, `follows_and_unfollows`, `profile_links_taps`, `profile_views`,
  `website_clicks`. See §4.4 for their range-coverage caveat and §4.6 for
  a `follows_and_unfollows`-specific anomaly.

8 candidates were confirmed genuinely invalid at this endpoint (`code=100`
"must be one of the following values"): `impressions`, `email_contacts`,
`phone_call_clicks`, `text_message_clicks`, `audience_city`,
`audience_country`, `audience_gender_age`, `audience_locale`
(`account.txt:67-79`).

### 4.2 Re-test consistency

All 17 previously-confirmed-valid combos were re-tested by the newer
script and **none regressed** — same bare-acceptance results both times
(`params2.txt:133,168-169`, "Rejected outright on re-test: (none)").

### 4.3 The 30-day range cap — confirmed hard limit

**Confirmed, not inferred: IG account-level insights reject any
`since`/`until` window wider than 30 days with an explicit rejection
message**, `code=100`, "(#100) There cannot be more than 30 days
(2592000 s) between since and until." (e.g. `params2.txt:254`, and
repeated identically for every one of the 16 range-tested combos). This is
a materially different mechanism from FB's 90-day cap (§1.2, which is
never stated explicitly by the API — it's inferred from a 182-day
rejection with no data-coverage check ever failing at 90d) — here the API
says so directly, in its own words, every time.

The 30-day window itself is **ACCEPTED** for all 16 range-tested combos.
Because the rejection lands at 90d — not 182d as with FB — the ladder never
reaches beyond that point for any combo in this run, making **30 days the
confirmed ceiling** for IG account-level insights (contrast with FB Page
Insights' 90-day ceiling, §1.2 — these are separate findings for separate
platforms, per this doc's scope discipline).

`online_followers`/`lifetime` is an exception to this pattern — its own
range-cap status was never actually determined; see §4.5.

### 4.4 `total_value` metrics: range accepted, coverage unverifiable

**This is the nuance to read carefully, per the task brief — do not smooth
this into "confirmed working."** For all 12 `total_value`-shaped metrics,
the 7d and 30d windows are **ACCEPTED** (200, `total_value` present) and
the 90d window is **REJECTED** with the identical 30-day-cap message as the
time-series metrics (§4.3) — so the *cap itself* is confirmed identically
for both shapes. But **whether an accepted window's returned total
actually reflects that whole window is not independently verifiable**:
there's no per-day breakdown in a `total_value` response to check earliest/
latest dates against the request, the way both this script and the FB
script do for time-series-shaped responses. The diagnostic script itself
labels this explicitly as `RANGE_ACCEPTED_BUT_UNVERIFIABLE` rather than
asserting full coverage (`params2.txt:144-157`).

The values sampled are at least **directionally consistent** with correct
windowing (e.g. `likes`: 304 at 7d vs. 3068 at 30d, `params2.txt:758,778`;
bigger window → bigger total) — suggestive, not proof, the same
"suggestive not proven" discipline already applied to FB's rolling-sum
nuance (§1.4).

### 4.5 `online_followers`/`lifetime` — a third value shape

`online_followers` returns values shaped as a **dict keyed by hour-of-day
string `"0"`–`"23"`**, mapping to the online-follower count at that hour,
one such dict per day/`end_time` (`params2.txt:513-541`) — a shape
distinct from both FB's dict-valued metrics (§1.7) and IG account-level's
`total_value` shape (§4.4).

Its own range-cap status is **undetermined**, not confirmed either way:
the coverage-tolerance check used by the range-sweep script requires
`back_gap <= 0d` for `period=lifetime`, and even the 7d window's `back_gap`
came out to 1 day — so it was classified `TRUNCATED`
(`RANGE_ACCEPTED_BUT_NO_COVERAGE_CONFIRMED`, `params2.txt:501`) and the
escalation ladder never proceeded past 7d for this metric. This is a
tolerance/methodology artifact of the sweep script, not a confirmed
different API behavior — flagged as a gap (§6), not asserted as fact
either way.

### 4.6 `follows_and_unfollows` — missing `total_value` key anomaly

Unlike its 11 `total_value` siblings — all of which show an explicit
`"total_value": {"value": N}` in every sample, including explicit zeros
(e.g. `replies`: `{"value": 0}`, `params2.txt:954`) —
`follows_and_unfollows`' response has **no `total_value` key at all** in
either its 7d or 30d sample this run (`params2.txt:1043-1058,1062-1075`):
the entry has only `name`/`period`/`title`/`description`/`id`. The
diagnostic script's own shape-detector labels this response `"unknown"`
rather than `"total_value"` as a direct consequence (`params2.txt:1040`).
Not explained further here — flagged as an open anomaly (§6).

### 4.7 The cumulative-follower-total question — confirmed answer

**Direct answer, confirmed via a live API validation error, not inferred
from partial testing:** no IG account-level Insights metric produces a
genuine cumulative/lifetime follower total.

This run forced the Graph API's own validation error by requesting a
deliberately-invalid metric name, capturing the **complete, live-enumerated
list of all 28 valid `/{ig-user-id}/insights` metric names**
(`params2.txt:17-44`): `reach`, `follower_count`, `website_clicks`,
`profile_views`, `online_followers`, `accounts_engaged`,
`total_interactions`, `likes`, `comments`, `shares`, `saves`, `replies`,
`engaged_audience_demographics`, `reached_audience_demographics`,
`follower_demographics`, `follows_and_unfollows`, `profile_links_taps`,
`views`, `threads_likes`, `threads_replies`, `reposts`, `quotes`,
`threads_followers`, `threads_follower_demographics`, `content_views`,
`threads_views`, `threads_clicks`, `threads_reposts`. None of these 28
names reads as a cumulative/lifetime follower total distinct from
`follower_count` — a direct observation of the complete enumerated set,
not an inference from whichever candidates happened to be tried.

`follower_count` itself is confirmed `day`-only and daily-delta shaped, not
a running total — a fresh sample this run showed values `6, 13, 6, 9, 7, 2`
across `2026-07-09`–`2026-07-14` (`params2.txt:64-89`), consistent with
ROADMAP.md's prior finding of small fluctuating daily values. `week`/
`days_28`/`lifetime` are all rejected for this metric (§4.1) — no period
grain turns it into a running total.

**Separately — noted as a distinct option, not a fix, per the task
brief's instruction not to resolve this as a design decision:** `GET
/{ig-user-id}?fields=followers_count,follows_count,media_count` (a
different endpoint entirely — the IG User node's own fields, **not** an
Insights call, no `period`/`since`/`until`) does return a genuine
cumulative total at query time — `followers_count: 16184` in this run's
sample (`params2.txt:110-115`). This is a **live snapshot only**: no
history, no date range, no way to ask "what was it on date X." Whether or
how to use this field (e.g. daily snapshotting to build a history) is an
extraction-design decision, **explicitly not made here** — flagged as the
concrete option for a later session to evaluate.

### 4.8 Sample payloads

Full sample payloads (redacted, values arrays truncated) for every
range-tested combo at 7d/30d windows, plus the 90d rejection message, are
in `params2.txt`'s DETAIL section (`params2.txt:171` onward) — one block
per combo, in the same "cite, don't re-paste everything" style as the FB
per-metric reference (§2). Only the illustrative examples above are
reproduced in this doc.

---

## 5. Discrepancies vs. `PROJECT_DESCRIPTION.md` / `ROADMAP.md`

Per the task brief, these are **flagged, not resolved** — a human should
reconcile the source docs separately.

1. **`PROJECT_DESCRIPTION.md` Open Question #3 (lines 120-125) claims the
   Page Access Token "resolved" `page_fans`, and that the raw System User
   token "returned error code 190."** The actual saved output
   (`diagnose_page_fans_output.txt`) does not support this: both the System
   User token and the exchanged Page token return the **identical**
   `code=100` "value must be a valid insights metric" error for `page_fans`
   — never `code=190`, and the token exchange changes nothing about the
   outcome. `page_fans` is independently confirmed invalid on v25.0 by
   `diagnose_all_page_metrics_output.txt` regardless of token. See §1.5.

2. **`PROJECT_DESCRIPTION.md` Open Question #1 (lines 111-114) claims the 4
   calls in `diagnose_token_190.py` confirmed "token (code 190) errors no
   longer occur... with the current SYSTEM_USER_TOKEN + Page Access Token
   exchange."** But `diagnose_token_190.py` (read directly, see the script
   itself) never performs a Page Access Token exchange at all — all 4 calls
   use `config.system_user_token` directly. The claim describes a mechanism
   the script doesn't actually test. Separately, `code=190` isn't
   reproduced by this script either way (it never appears in the output) —
   so there's nothing here confirming a *190-specific* fix, exchange-based
   or otherwise. See §1.5.

3. **Not a discrepancy, but worth confirming was checked:** the task brief
   that spawned this synthesis anticipated finding
   `PROJECT_DESCRIPTION.md` citing `reach`, `impressions`, and
   `follower_count` as *working* FB Page metrics, conflicting with the
   confirmed-valid list. On inspection, `PROJECT_DESCRIPTION.md` lines
   71-73 actually says the opposite — it correctly identifies these as
   **IG-derived names that caused HTTP 400 errors against the FB endpoint**
   and were replaced. This is consistent with the diagnostic output (none
   of `reach`/`impressions`/`follower_count` appear in the 37-metric
   success list, and aren't valid FB Page Insights metric names at all).
   Recorded here so a future reader doesn't re-check the same thing.

4. **`PROJECT_DESCRIPTION.md`'s "Time grains" design decision (line 57-58)**
   states "Daily/weekly/monthly/yearly must be pulled as **separate** API
   calls." Two things worth a human's attention here, not resolved:
   - The Graph API's actual `period` values are only `{day, week, days_28,
     lifetime}` — there is no literal `month` or `year` period parameter.
     If "monthly/yearly" refers to a period value to request, that value
     doesn't exist; if it refers to a transformation-layer aggregation
     built from daily data, the doc doesn't say so explicitly.
   - Per §1.4, `week` and `days_28` are **not** distinct non-overlapping
     buckets the way "weekly" might imply to a reader planning separate
     pulls per grain — they're daily-cadence rolling sums. Whether the
     pipeline's eventual design should pull `week`/`days_28` at all (versus
     deriving weekly/monthly rollups from the `day` series only) is a design
     question, not addressed here.

5. **`PROJECT_DESCRIPTION.md` line 66-71's count** ("37 of 80 Page-level
   metrics succeed... 43 fail") **matches** `diagnose_all_page_metrics_output.txt`
   exactly. No discrepancy — noted so it isn't re-checked.

6. **`PROJECT_DESCRIPTION.md` (lines 76-80) attributes REELS being untested
   to "no live Reels or Stories at probe time."** The newer REELS/STORY
   diagnostic (`diagnose_ig_media_reels_stories_output.txt`, 2026-07-16)
   found **15 REELS items** among the 50 most recent media items — REELS
   content did exist. The original script's "REELS: not found" conclusion
   was a **false negative**: its discovery phase buckets media by the
   `media_type` field, which the Graph API only ever reports as IMAGE,
   VIDEO, or CAROUSEL_ALBUM — Reels report `media_type=VIDEO` and are
   distinguishable only via the separate `media_product_type` field, which
   the original script never queried. `PROJECT_DESCRIPTION.md`'s "no live
   Reels at probe time" explanation is not supported by this finding for
   REELS specifically (STORY's "no live content" explanation is unaffected
   — see §3.4). See §3.3 for the full discovery-bug writeup.

7. **`ROADMAP.md` Phase 1 (lines 52-55) states:** "Handle the known
   media-type-specific gotcha: views is valid for Reels/Stories but can
   error (400) on VIDEO+FEED and CAROUSEL_ALBUM posts, and older
   pre-Business-conversion posts return error subcode 2108006." This does
   not match what's actually been tested: `views` **succeeded** (200, with
   data) for IMAGE, VIDEO, and CAROUSEL_ALBUM in the original sweep, and for
   REELS in the newer sweep — no 400 error was observed for `views` against
   any sampled media item in either run (see §3.2). The subcode `2108006`
   pre-Business-conversion claim was never independently tested here (no
   specifically-old/non-Business post was probed), so that part is neither
   confirmed nor refuted by this material — flagged, not resolved.

---

## 6. Gaps — what is still not known

- **Rolling-sum numeric confirmation for most metrics.** Only
  `page_post_engagements` and `page_fan_adds_by_paid_non_paid_unique` have
  nonzero sample values suggestive of the rolling-sum behavior, and even
  those weren't mathematically verified against a full daily series. The
  other 35 metrics rely on title/description labeling + point-cadence only.
- **90-day cap not confirmed for `lifetime`.** `lifetime` never returns
  ranged data at all (§1.3), so whether it has its own distinct range cap
  (as opposed to simply not supporting ranges) is unknown.
- **90-day cap not confirmed beyond 182d as the rejection point** — the
  escalation ladder's 365d/456d rungs were never reached for any metric in
  this run because 182d rejected first for all 37. Whether 90 is a hard
  platform constant or happens to be this Page's/app's current limit is
  unknown.
- **True historical depth beyond 2023-07-18 is unknown** (§1.2). A
  `since`-only query confirms real data back to that date for
  `page_media_view`/`day`; probing further back via `paging.previous`
  cursor-following doesn't work, because each cursor is itself a
  `since`+`until` pair and hits the same 90-day rejection on the first
  backward hop regardless of true depth. No method that actually reaches
  further back than 2023-07-18 was found in this diagnostic pass. Also,
  the backward walk itself was only attempted for `page_media_view`/`day`
  — the other three metrics and remaining periods tested for the
  `since`-only behavior weren't walked backward at all.
- **The `page_daily_video_ad_break_*` (×3) / `creator_monetization_qualified_views`
  vs. `content_monetization_earnings` / `monetization_approximate_earnings`
  permission split is unexplained.** The Page token's `/me/accounts`
  response shows the `VIEW_MONETIZATION_INSIGHTS` task granted
  (`diagnose_page_fans_output.txt:40`), yet 4 monetization metrics fail with
  a permissions error while 2 others succeed on the same token. Not
  investigated further here — flagged as open.
- **`page_actions_post_reactions_total`'s missing-key semantics** — inferred
  to mean zero for that reaction type, never explicitly confirmed (§1.7).
- **The `page_video_views_by_uploaded_hosted` / `page_media_view` /
  `content_monetization_earnings` `lifetime`-rejection reasons aren't
  understood** — no obvious shared property distinguishes these 3 from the
  other 34 that accept `lifetime` bare.
- **No rate-limit stop was ever exercised** in the saved runs — the
  rate-limit-handling code path in `diagnose_page_metric_params.py` (partial
  save + resume) is unverified in practice.
- **Legacy-name mappings (`page_views`→`page_views_total`,
  `page_fans`→`page_follows`?) are inferred, not confirmed** by any direct
  Meta migration statement — see §1.6.
- **Only one Page and one token were tested throughout.** Nothing here
  establishes whether any of this (the 90-day cap, the permission splits,
  the rolling-sum behavior) generalizes to other Pages, other apps, or other
  token/permission configurations.
- **`run_fb_page_extraction_output.csv`** (the one real end-to-end pipeline
  run captured) shows 5 trailing days of all-zero values for
  `page_media_view`/`page_total_media_view_unique`/`page_views_total` while
  `page_follows` keeps incrementing normally. This is consistent with (but
  not confirmed to be) the "missing-vs-zero ambiguity" /
  data-finalization-lag gaps `PROJECT_DESCRIPTION.md` already lists as known
  deferred issues — not independently diagnosed here, just noted as a data
  point that might be relevant to those existing open items.
- **Post-level metrics, breakdowns/`fields` params, and any period other
  than `{day, week, days_28, lifetime}`** were never tested — out of scope
  for every script surveyed here.
- **STORY remains completely untested for media-level insights.** Blocked
  at both probe times (2026-07-14 original sweep and 2026-07-16 REELS/STORY
  sweep) via both the `/media` edge (filtered by `media_product_type`) and
  the dedicated `/{ig-user-id}/stories` edge. Consistent with "no Story was
  posted in the last 24h at either run," not proof the metrics/endpoint
  don't work — needs a re-run within 24h of an actual Story post. See §3.4.
- **REELS' own dedicated metrics were never tested.** The enumeration in
  §3.5's "must be one of" error lists Reels-specific names (`plays`,
  `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`,
  `reels_skip_rate`, etc.) — only the same 10 general candidates used for
  IMAGE/VIDEO/CAROUSEL_ALBUM were tried against REELS, for cross-type
  comparability. Whether REELS' dedicated metrics work is unknown.
- **STORY's own dedicated candidate list** (`reach`, `replies`,
  `navigation`, `taps_forward`, `taps_back`, `exits`, `total_interactions`
  — defined in `diagnose_all_ig_media_metrics.py` but superseded by the
  general-10 list in the newer script for comparability) has never been
  tested against live content either.
- **Account-level `total_value` coverage is unverifiable for all 12
  `total_value`-shaped metrics** (§4.4). Range acceptance was confirmed, but
  whether the returned total actually reflects the full requested window
  (vs., say, always just "today") was not independently confirmed — there's
  no per-day breakdown to check earliest/latest dates against.
- **`online_followers`/`lifetime`'s actual range cap is undetermined.** The
  escalation ladder stopped at 7d due to a coverage-tolerance artifact
  (§4.5), not an API rejection, so whether it shares the 30-day cap the
  other 16 combos hit is unknown.
- **`follows_and_unfollows`' missing `total_value` key is unexplained**
  (§4.6) — unlike its 11 total_value siblings, its response omits the
  `total_value` field entirely rather than showing an explicit zero.
- **The IG account-level 30-day cap, like the FB 90-day cap, was only
  confirmed for one IG account/token** — not established as a platform-wide
  constant.
- **The follower-tracking design choice is unresolved, by design.** Whether
  and how to use the non-Insights `followers_count` snapshot field (e.g.
  daily snapshotting to build a history) to work around the lack of a
  cumulative IG Insights metric is flagged per the task brief as an open
  extraction-design decision — not resolved or recommended here. See §4.7.
