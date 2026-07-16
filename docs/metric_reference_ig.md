# Instagram Insights — Metric Reference (Graph API v25.0)

_Restructured 2026-07-16 out of the original single-file
`meta_graph_api_ref.md` §3-4 per
`scripts/output/diagnostic_audit_2026-07-16.md` §4. See
[`meta_graph_api_reference.md`](meta_graph_api_reference.md) for auth,
pagination, range-cap, and value-shape behavior that applies across
platforms. IG User ID under test: `17841401980438718`._

**Section choice:** media-level and account-level IG insights are two
structurally distinct surfaces — different endpoints, different parameter
models (no `period`/`since`/`until` at all for media-level; both for
account-level), and different response shapes — presented as two separate
sections below rather than folded together, the same way FB and IG are
kept separate at the top level.

---

## 1. Media-Level Insights

_Endpoint: `GET /{ig-media-id}/insights`. Two scripts contribute: the
original sweep, `scripts/diagnose_all_ig_media_metrics.py` (run
2026-07-14, output `diagnose_all_ig_media_metrics_output.txt`, covering
IMAGE, VIDEO, CAROUSEL_ALBUM), and the newer gap-closing script,
`scripts/diagnose_ig_media_reels_stories.py` (run 2026-07-16, output
`diagnose_ig_media_reels_stories_output.txt`, covering REELS and STORY).
Cited below as `media.txt` and `reels.txt` respectively._

No `period`, `since`, or `until` parameter was ever sent to
`/{ig-media-id}/insights` in either script — media-level insights are
inherently scoped to the individual media object's lifetime, not a date
range. (The response nonetheless echoes `"period": "lifetime"` for every
metric.)

### 1.1 The `media_type` vs. `media_product_type` gotcha — read this first

**This is the single highest-value methodology fact for Phase 1 IG
extraction work.** The Graph API's `media_type` field on
`/{ig-user-id}/media` only ever returns `IMAGE`, `VIDEO`, or
`CAROUSEL_ALBUM` — Reels are returned with `media_type=VIDEO` and are
distinguishable only via a separate field, `media_product_type` (observed
values: `FEED`, `REELS`). A script that buckets IG media by `media_type`
alone will silently miss all Reels content.

This is exactly what happened once already: the original
`diagnose_all_ig_media_metrics.py`'s discovery phase bucketed by
`media_type` and never queried `media_product_type`, producing a "REELS:
not found (no Reels found in recent media)" result (`media.txt:6`) that
**could never have matched REELS regardless of whether Reels content
existed** — not a reliable test of Reels' existence, just an artifact of
checking the wrong field. The newer script queried `media_product_type`
explicitly and found **15 REELS items among the 50 most recent media
items** (`reels.txt:7`, "`media_product_type` breakdown: `{'FEED': 35,
'REELS': 15}`"), disproving the "no Reels" conclusion.

**Takeaway for future code:** never bucket IG media by `media_type` alone
if REELS needs to be distinguished from FEED video — query
`media_product_type` instead (or in addition).

### 1.2 Candidate-metric methodology

Both scripts test the **same 10-candidate set** — `reach`, `saved`,
`likes`, `comments`, `shares`, `total_interactions`, `engagement`,
`impressions`, `video_views`, `views` — against whichever media type they
cover, kept identical across IMAGE/VIDEO/CAROUSEL_ALBUM/REELS specifically
so results are directly comparable type-to-type. REELS (and, untested,
STORY) may have additional dedicated metrics not covered by this set —
see §1.6 (Gaps).

### 1.3 Confirmed results, by media type

| Media Type | Succeeded (7) | Failed (3) | Payloads captured? | Source |
|---|---|---|---|---|
| IMAGE | reach, saved, likes, comments, shares, total_interactions, views | engagement, impressions, video_views | No — status only | media.txt:13-23 |
| VIDEO | (same 7) | (same 3) | No — status only | media.txt:25-35 |
| CAROUSEL_ALBUM | (same 7) | (same 3) | No — status only | media.txt:37-47 |
| REELS | (same 7) | (same 3) | **Yes** — redacted, values truncated to 3 | reels.txt:9-19, 42-166 |
| STORY | — | — | N/A — BLOCKED, see §1.5 | reels.txt:21-26 |

**All four testable media types produced byte-identical success/failure
sets for this 10-metric candidate list.**

### 1.4 Failure-mode detail for the 3 consistently-failing candidates

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
  product type" (`media.txt:33`, `reels.txt:17`).

**Cross-type observation:** the enumerated "must be one of" list for
`engagement`/`video_views` is textually identical across IMAGE and REELS
despite `media_type` differing between them, and includes clearly
Reels-only names (`ig_reels_avg_watch_time`, `reels_skip_rate`) even in
the IMAGE response — suggests the API returns a fixed, non-media-type-scoped
list in this particular error message rather than filtering it per media
type. An observation, not a confirmed API design fact.

### 1.5 STORY: blocked, not silently omitted

STORY is documented here as **blocked**, not untested-and-ignored. The
newer script checked two places:

1. `/{ig-user-id}/media` filtered for `media_product_type == "STORY"` — 0
   found among the 50 most recent items (`reels.txt:22`).
2. The dedicated `/{ig-user-id}/stories` edge (active-Stories-only, since
   Stories expire ~24h and don't persist on `/media`) — 0 active items
   returned (`reels.txt:23-25`).

Both the original sweep (2026-07-14) and the newer sweep (2026-07-16)
found zero live Story content. This is **consistent with** "no Story was
posted in the last 24h at either run time," not conclusive proof Stories
categorically don't work for this account/token — a real test requires
re-running within 24h of an actual Story post.

A STORY-specific candidate metric list (`reach`, `replies`, `navigation`,
`taps_forward`, `taps_back`, `exits`, `total_interactions`) was defined by
the original script but never tested against live content, since no Story
content was ever found.

### 1.6 Value shape and sample payloads

Every succeeding media-level metric returns `"period": "lifetime"` and a
**single-element `values` array** with a **plain scalar integer** `value`
— no dict-shaped values observed at the media level. Representative
example (`reels.txt:42-58`):

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
original script recorded SUCCESS/FAIL status only).

### 1.7 Gaps

- **STORY remains completely untested** for media-level insights, at
  both media-level (blocked, no live content) and its dedicated candidate
  list.
- **REELS' own dedicated metrics were never tested** — the "must be one
  of" enumeration lists Reels-specific names (`plays`,
  `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`,
  `reels_skip_rate`, etc.); only the general-10 candidates were tried.
- `ROADMAP.md` Phase 1 (as of before this restructure) stated `views` can
  error 400 on VIDEO+FEED/CAROUSEL_ALBUM and that older
  pre-Business-conversion posts return subcode `2108006`. **Neither claim
  is supported by tested data**: `views` succeeded (200, with data) for
  every media type tested, in both scripts, with no 400 observed. The
  subcode `2108006` claim was never independently tested (no old/
  non-Business post was sampled) — flagged, not resolved.

---

## 2. Account-Level Insights

_Endpoint: `GET /{ig-user-id}/insights`. Two scripts contribute: the
discovery sweep, `scripts/diagnose_all_ig_account_metrics.py` (run
2026-07-14, output `diagnose_all_ig_account_metrics.txt`, 25 candidate
metric names × 77 metric/period/metric_type combos, 17 SUCCESS), and the
newer parameter-space script,
`scripts/diagnose_ig_account_insights_params.py` (run 2026-07-16, output
`diagnose_ig_account_insights_params_output.txt`), which starts from
those 17 confirmed-valid combos and sweeps `since`/`until` range
acceptance using the same escalation-ladder approach as the FB
parameter-space script: 7d → 30d → 90d → 182d → 365d → 456d, stopping at
first rejection or non-full-coverage response. Cited below as
`account.txt` (discovery) and `params2.txt` (range sweep)._

**Structural difference from FB Page Insights:** IG account metrics
queried with `metric_type=total_value` return a single
`total_value: {"value": N}` object per data entry, **not** a
`values: [{value, end_time}, ...]` time series. There is no per-day
breakdown to check against a requested `since`/`until` window for those
combos — see §2.4.

### 2.1 Valid metric+period(+metric_type) combos (17 of 25 candidates tested)

- **`reach`** — `period` ∈ `{day, week, days_28}` all SUCCESS
  (time-series); `period=lifetime` FAILS ("incompatible").
- **`follower_count`** — `period=day` SUCCESS (time-series); `week`,
  `days_28`, `lifetime` all FAIL; `metric_type=total_value` is
  incompatible with this metric for any period.
- **`online_followers`** — `period=lifetime` SUCCESS, distinct dict-of-hours
  value shape (§2.5); `period=day` FAILS.
- **12 metrics require `metric_type=total_value` AND `period=day`
  together** (no other period grain works for any of them —
  `days_28`/`lifetime` + `total_value` all fail): `accounts_engaged`,
  `total_interactions`, `likes`, `comments`, `saves`, `shares`, `replies`,
  `views`, `follows_and_unfollows`, `profile_links_taps`, `profile_views`,
  `website_clicks`. See §2.4 for their range-coverage caveat and §2.6 for
  a `follows_and_unfollows`-specific anomaly.

8 candidates were confirmed genuinely invalid at this endpoint (`code=100`
"must be one of the following values"): `impressions`, `email_contacts`,
`phone_call_clicks`, `text_message_clicks`, `audience_city`,
`audience_country`, `audience_gender_age`, `audience_locale`
(`account.txt:67-79`).

### 2.2 Re-test consistency

All 17 previously-confirmed-valid combos were re-tested by the newer
script and **none regressed** — same bare-acceptance results both times
(`params2.txt:133,168-169`, "Rejected outright on re-test: (none)").

### 2.3 The 30-day range cap — confirmed hard limit

See `meta_graph_api_reference.md` §5 for the cross-platform range-cap
table. IG account-level's 30-day cap is **explicitly stated by the API**
(`code=100`, "There cannot be more than 30 days (2592000 s) between since
and until" — `params2.txt:254`, repeated for every one of the 16
range-tested combos), unlike FB's 90-day cap, which is only inferred from
a 182-day rejection.

`online_followers`/`lifetime` is an exception to this pattern — its own
range-cap status was never actually determined; see §2.5.

### 2.4 `total_value` metrics: range accepted, coverage unverifiable

**Do not smooth this into "confirmed working."** For all 12
`total_value`-shaped metrics, the 7d and 30d windows are **ACCEPTED**
(200, `total_value` present) and the 90d window is **REJECTED** with the
identical 30-day-cap message as the time-series metrics — so the *cap
itself* is confirmed identically for both shapes. But **whether an
accepted window's returned total actually reflects that whole window is
not independently verifiable**: there's no per-day breakdown in a
`total_value` response to check earliest/latest dates against the
request. The diagnostic script itself labels this explicitly as
`RANGE_ACCEPTED_BUT_UNVERIFIABLE` rather than asserting full coverage
(`params2.txt:144-157`).

The values sampled are at least **directionally consistent** with correct
windowing (e.g. `likes`: 304 at 7d vs. 3068 at 30d, `params2.txt:758,778`;
bigger window → bigger total) — suggestive, not proof.

### 2.5 `online_followers`/`lifetime` — a third value shape

`online_followers` returns values shaped as a **dict keyed by hour-of-day
string `"0"`–`"23"`**, mapping to the online-follower count at that hour,
one such dict per day/`end_time` (`params2.txt:513-541`) — a shape
distinct from both FB's dict-valued metrics and IG's `total_value` shape.

Its own range-cap status is **undetermined**, not confirmed either way:
the coverage-tolerance check used by the range-sweep script requires
`back_gap <= 0d` for `period=lifetime`, and even the 7d window's
`back_gap` came out to 1 day — so it was classified `TRUNCATED`
(`RANGE_ACCEPTED_BUT_NO_COVERAGE_CONFIRMED`, `params2.txt:501`) and the
escalation ladder never proceeded past 7d for this metric. A
tolerance/methodology artifact of the sweep script, not a confirmed
different API behavior.

### 2.6 `follows_and_unfollows` — missing `total_value` key anomaly

Unlike its 11 `total_value` siblings — all of which show an explicit
`"total_value": {"value": N}` in every sample, including explicit zeros
(e.g. `replies`: `{"value": 0}`, `params2.txt:954`) —
`follows_and_unfollows`' response has **no `total_value` key at all** in
either its 7d or 30d sample this run (`params2.txt:1043-1058,1062-1075`):
the entry has only `name`/`period`/`title`/`description`/`id`. The
diagnostic script's own shape-detector labels this response `"unknown"`
rather than `"total_value"` as a direct consequence (`params2.txt:1040`).
Not explained further — flagged as an open anomaly.

### 2.7 The cumulative-follower-total question — confirmed answer

**Direct, unambiguous answer, confirmed via a live API validation error,
not inferred from partial testing: no IG account-level Insights metric
produces a genuine cumulative/lifetime follower total.**

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
names is a cumulative/lifetime follower total distinct from
`follower_count`.

`follower_count` itself is confirmed `day`-only and **daily-delta
shaped, not a running total** — a fresh sample this run showed values `6,
13, 6, 9, 7, 2` across `2026-07-09`–`2026-07-14` (`params2.txt:64-89`),
consistent with a prior live-query finding of small fluctuating daily
values. `week`/`days_28`/`lifetime` are all rejected for this metric — no
period grain turns it into a running total.

**Distinct option, not a fix, noted here for a later design decision:**
`GET /{ig-user-id}?fields=followers_count,follows_count,media_count` (a
different endpoint entirely — the IG User node's own fields, **not** an
Insights call, no `period`/`since`/`until`) does return a genuine
cumulative total at query time — `followers_count: 16184` in this run's
sample (`params2.txt:110-115`). This is a **live snapshot only**: no
history, no date range, no way to ask "what was it on date X." Whether or
how to use this field (e.g. daily snapshotting to build a history) is an
extraction-design decision, **not made here** — see the corresponding
open item in `metric_reference_fb_page.md`'s follower-pairing section.

### 2.8 Sample payloads

Full sample payloads (redacted, values arrays truncated) for every
range-tested combo at 7d/30d windows, plus the 90d rejection message, are
in `params2.txt`'s DETAIL section (`params2.txt:171` onward) — one block
per combo. Only the illustrative examples above are reproduced in this
doc.

### 2.9 Gaps

- **Account-level `total_value` coverage is unverifiable** for all 12
  `total_value`-shaped metrics — see §2.4.
- **`online_followers`/`lifetime`'s actual range cap is undetermined** —
  see §2.5.
- **`follows_and_unfollows`' missing `total_value` key is unexplained** —
  see §2.6.
- **The IG account-level 30-day cap was only confirmed for one IG
  account/token** — not established as a platform-wide constant.
- **The follower-tracking design choice is unresolved, by design** —
  whether/how to use the non-Insights `followers_count` snapshot field
  (e.g. daily snapshotting to build a history) to work around the lack of
  a cumulative IG Insights metric is an open extraction-design decision.
