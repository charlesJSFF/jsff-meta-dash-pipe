# FB Page Insights — Per-Metric Reference (Graph API v25.0)

_Restructured 2026-07-16 out of the original single-file
`meta_graph_api_ref.md` §1.1/§1.7/§2 per
`scripts/output/diagnostic_audit_2026-07-16.md` §4. See
[`meta_graph_api_reference.md`](meta_graph_api_reference.md) for auth,
pagination, range-cap, and rolling-window behavior that applies across all
of these metrics. Page ID under test: `145245558842140`._

## Metric-name validity (v25.0)

`scripts/diagnose_all_page_metrics.py` tested 80 Page-level metric names
(everything listed under Page metrics on the v25.0 `availmetrics` doc,
excluding `post_*` metrics which are a different endpoint) one at a time
with `period=day`, no date range. Result
(`diagnose_all_page_metrics_output.txt`):

- **37 succeeded** (200, `data` present) — full per-metric table below.
- **43 failed**, in two distinct failure modes:
  - **`code=100` "(#100) The value must be a valid insights metric"** (39
    metrics) — the name itself is rejected outright on v25.0. Families:
    `page_tab_views_*` (3), `page_impressions*` (8), `page_posts_impressions*`
    (10), `page_fans*`/`page_fan_adds*`/`page_fan_removes*` (8),
    `page_video_views_10s*` (7), `page_uploaded_*` (3).
  - **`code=200` "Monetization metrics are only visible for Page admins with
    access to monetization insights"** (4 metrics) —
    `page_daily_video_ad_break_ad_impressions_by_crosspost_status`,
    `page_daily_video_ad_break_cpm_by_crosspost_status`,
    `page_daily_video_ad_break_earnings_by_crosspost_status`,
    `creator_monetization_qualified_views`. A **permission** failure, not a
    naming failure — see the monetization permission-split open question in
    `meta_graph_api_reference.md` §7.

## Legacy → current metric name mapping

- **`page_views` → `page_views_total`**: `page_views` fails with `code=100`
  (confirmed, `diagnose_token_190_output.txt:62-71`); `page_views_total`
  succeeds and carries the description "Total views count per Page" —
  descriptively the natural successor. **Inferred by elimination +
  description match, not confirmed by any explicit Meta migration
  statement in the captured material.**
- **`page_fans` → no confirmed successor.** `page_fans` fails with
  `code=100` in every test. `page_follows` succeeds and describes itself
  as "The number of followers of your Facebook Page or profile... calculated
  as follows minus unfollows over the lifetime" (matches Facebook's
  Likes→Follows rebrand narrative) — a **plausible** successor, but no
  direct evidence (no paired before/after test) confirms `page_follows` is
  the intended 1:1 replacement for `page_fans` specifically. Treat as a
  reasonable hypothesis, not a confirmed mapping.
- No other legacy→current renames were specifically tested.

## Cumulative vs. delta — the two follower-count candidates

**Open design decision, not resolved here** (see
`scripts/output/diagnostic_audit_2026-07-16.md` §3.4): which of these, if
either, is the right FB-side pairing for IG's `follower_count` in a YoY
follower chart. Both metrics' shape is stated unambiguously below so that
decision doesn't require re-deriving the distinction from scratch:

| Metric | Shape | Evidence |
|---|---|---|
| `page_follows` | **Cumulative.** "Lifetime Total Follows" per its own description text. Confirmed nonzero, monotonically-plausible values in `run_fb_page_extraction_output.csv` (13738 → 13772 across the file's 8 real-looking days) — see `meta_graph_api_reference.md` §8 for that file's own unresolved provenance caveat. | `params.txt:2372` |
| `page_daily_follows_unique` | **Delta.** Daily net-new count, not cumulative — resets per period rather than accumulating. | `params.txt:1690` |

**The pipeline currently pulls `page_follows` (cumulative) as part of
`DEFAULT_METRICS` in `src/extraction/fb_page_insights.py` — not
`page_daily_follows_unique`.** IG's `follower_count` is itself a
confirmed daily-delta metric (see `metric_reference_ig.md` §4.7), so
pairing it with FB's cumulative `page_follows` would be a unit mismatch if
a directly-comparable YoY follower chart is the goal. Whether to switch to
`page_daily_follows_unique`, reconstruct a running total from a baseline +
summed deltas, or accept the platform asymmetry is a Phase 1/2 design
decision — not resolved here.

## Value shapes: most metrics are scalar; five are dict-valued

Of the 37 confirmed-valid metrics, **32 return a plain integer** `value`
per data point. **Five return a `dict`-shaped `value`:**

| Metric | `value` keys observed |
|---|---|
| `page_fan_adds_by_paid_non_paid_unique` | `total`, `paid`, `unpaid` |
| `page_video_views_by_paid_non_paid` | `total`, `unpaid`, `paid` |
| `page_video_views_by_uploaded_hosted` | `page_uploaded`, `page_uploaded_from_crossposts`, `page_uploaded_from_shares`, `page_hosted_crosspost`, `page_hosted_share`, `page_owned` |
| `page_actions_post_reactions_total` | dynamic — only reaction types with nonzero activity that day appear (e.g. one day had just `{"like": 15}`, another `{"like": 12, "love": 1}`). **A missing key was not explicitly confirmed to mean zero** — inferred from the pattern, not tested against a day with a documented zero for a present-elsewhere key. |
| `content_monetization_earnings` | `currency` (string, `"USD"`), `microAmount` (int, `0` in all samples) |

`monetization_approximate_earnings` — despite also being a monetization
metric — returns a **plain scalar**, not a dict. Don't assume "monetization
metric" implies dict-shaped value.

**Response `id` field can name a different internal metric:**
`page_video_views_by_uploaded_hosted`'s response `id` field reads
`.../insights/page_video_view_count_by_uploaded_hosted/day` — a different
string than the requested/returned `name` field
(`page_video_views_by_uploaded_hosted`). The only such mismatch found
across all 37 metrics — worth knowing if any future code tries to match on
`id` rather than `name`.

## Per-metric reference (all 37)

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
sample payloads). Sample payloads are **not re-pasted here**.

| Metric | Deviates from default pattern? | Legacy name replaced | Cumulative/delta | Source |
|---|---|---|---|---|
| `page_total_actions` | No (values sampled all zero) | — | delta (per-period count) | params.txt:57 |
| `page_post_engagements` | No | — | delta (per-period count) | params.txt:398 |
| `page_fan_adds_by_paid_non_paid_unique` | Dict-valued | — | delta | params.txt:739 |
| `page_lifetime_engaged_followers_unique` | No (name says "lifetime" but behaves like every other metric — its own `lifetime` *period* is still non-rangeable like the rest) | — | delta (per-period unique count) | params.txt:1224 |
| `page_daily_follows` | **Yes** — `week`/`days_28` bare-accepted but return no data for any window tested, including 7d. Effectively day-only in practice. | — | delta | params.txt:1565 |
| `page_daily_follows_unique` | No | — | **delta** (see follower-pairing section above) | params.txt:1690 |
| `page_daily_unfollows_unique` | No | — | delta | params.txt:2031 |
| `page_follows` | No | inferred successor to `page_fans` (unconfirmed) | **cumulative** (see follower-pairing section above) | params.txt:2372 |
| `page_media_view` | **Yes** — `period=lifetime` rejected outright with opaque `code=1 subcode=99 "An unknown error occurred"` | — | delta | params.txt:2713 |
| `page_total_media_view_unique` | No | — | delta | params.txt:3052 |
| `page_actions_post_reactions_like_total` | No | — | delta | params.txt:3393 |
| `page_actions_post_reactions_love_total` | No | — | delta | params.txt:3734 |
| `page_actions_post_reactions_wow_total` | No | — | delta | params.txt:4075 |
| `page_actions_post_reactions_haha_total` | No | — | delta | params.txt:4416 |
| `page_actions_post_reactions_sorry_total` | No | — | delta | params.txt:4757 |
| `page_actions_post_reactions_anger_total` | No | — | delta | params.txt:5098 |
| `page_actions_post_reactions_total` | Dict-valued, dynamic keys | — | delta | params.txt:5439 |
| `page_video_views` | No | — | delta | params.txt:5904 |
| `page_video_views_by_uploaded_hosted` | **Yes** — dict-valued; `period=lifetime` rejected with clean `code=100` "must be one of {day,week,days_28}"; response `id` names a different internal metric | — | delta | params.txt:6245 |
| `page_video_views_paid` | No | — | delta | params.txt:6836 |
| `page_video_views_organic` | No | — | delta | params.txt:7177 |
| `page_video_views_by_paid_non_paid` | Dict-valued | — | delta | params.txt:7518 |
| `page_video_views_autoplayed` | No | — | delta | params.txt:8003 |
| `page_video_views_click_to_play` | No | — | delta | params.txt:8344 |
| `page_video_views_unique` | No | — | delta | params.txt:8685 |
| `page_video_repeat_views` | No | — | delta | params.txt:9026 |
| `page_video_complete_views_30s` | No | — | delta | params.txt:9367 |
| `page_video_complete_views_30s_paid` | No | — | delta | params.txt:9708 |
| `page_video_complete_views_30s_organic` | No | — | delta | params.txt:10049 |
| `page_video_complete_views_30s_autoplayed` | No | — | delta | params.txt:10390 |
| `page_video_complete_views_30s_click_to_play` | No | — | delta | params.txt:10731 |
| `page_video_complete_views_30s_unique` | No | — | delta | params.txt:11072 |
| `page_video_complete_views_30s_repeat_views` | No | — | delta | params.txt:11413 |
| `page_video_view_time` | No | — | delta | params.txt:11754 |
| `page_views_total` | No | inferred successor to `page_views` | delta | params.txt:12095 |
| `content_monetization_earnings` | **Yes** — dict-valued `{currency, microAmount}`; `period=lifetime` rejected with clean `code=100` "must be one of {day,week,days_28}" | — | delta | params.txt:12436 |
| `monetization_approximate_earnings` | No — scalar despite being a monetization metric, unlike `content_monetization_earnings` | — | delta | params.txt:12883 |

None of the 37 metrics reached `SAFE_FOR_FULL_YOY` classification (the
script's own >=365-day threshold) — all 37 are `RANGE_LIMITED` at 90 days.
See the script's own summary block at `params.txt:1-51`.

## Gaps — what is still not known

- **Rolling-sum numeric confirmation for most metrics** — see
  `meta_graph_api_reference.md` §6.
- **90-day cap not confirmed for `lifetime`**, and **not confirmed beyond
  182d as the actual rejection point** — see
  `meta_graph_api_reference.md` §5.
- **The `page_daily_video_ad_break_*`/`creator_monetization_qualified_views`
  vs. `content_monetization_earnings`/`monetization_approximate_earnings`
  permission split is unexplained** — see `meta_graph_api_reference.md` §7.
- **`page_actions_post_reactions_total`'s missing-key semantics** —
  inferred to mean zero for that reaction type, never explicitly
  confirmed.
- **The `page_video_views_by_uploaded_hosted` / `page_media_view` /
  `content_monetization_earnings` `lifetime`-rejection reasons aren't
  understood** — no obvious shared property distinguishes these 3 from the
  other 34 that accept `lifetime` bare.
- **No rate-limit stop was ever exercised** in the saved runs.
- **Legacy-name mappings are inferred, not confirmed** by any direct Meta
  migration statement.
- **Only one Page and one token were tested throughout** — nothing here
  establishes generalization to other Pages, apps, or token/permission
  configurations.
