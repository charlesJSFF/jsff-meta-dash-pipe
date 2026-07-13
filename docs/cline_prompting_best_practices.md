# Cline Prompting Best Practices — Meta Dashboard Pipeline

_Reference for writing prompts that will be executed by Cline (running on
DeepSeek) against this repo. Read alongside `.clinerules`, which governs
agent behavior directly; this doc is about how to prompt well within those
rules._

## Modes: use the right one on purpose

Cline has two visible modes, cycled in the UI:

- **Plan mode** — read-only investigation. Cline reads files and proposes an
  approach; it does not modify anything until you approve. Use this for
  surveys, diagnostics, "what's actually going on here" tasks — anything
  where you want a report or a plan before any change is made.
- **Act mode** — Cline executes: edits files, runs commands, and (depending
  on your auto-approve settings) may ask for approval on sensitive actions.
  Use this for actual implementation once scope is confirmed.

Cline can be configured to auto-transition from Plan to Act without a manual
approval step. **Don't rely on that in this repo** — there's no git history
yet (see roadmap Phase 0), so there's no safety net if something goes wrong.
Say explicitly in the prompt that Plan → Act requires your confirmation, and
revisit this once git is initialized and commits are being made regularly.

When writing a prompt, say explicitly which mode it's meant for. Don't rely
on Cline inferring it.

## Structure every prompt the same way

The six-part structure that worked for Claude Code carries over directly —
it's tool-agnostic, not Claude-Code-specific:

1. **Context** — what this piece is, where it fits in the pipeline.
2. **Scope** — explicit in-bounds and out-of-bounds. Always restate the
   default out-of-bounds list unless deliberately overriding it: no repo
   structure changes, no new dependencies without flagging first, no
   touching `.env` or printing its contents, no scope creep beyond the
   current piece.
3. **Files to touch** — exact paths. If a file shouldn't exist yet, say so,
   so the agent doesn't preemptively scaffold neighboring pieces.
4. **Constraints** — only the locked decisions relevant to this piece, not
   the whole list every time.
5. **Acceptance criteria** — testable definition of done. A test file is
   required, not optional.
6. **Stop conditions** — when to stop and ask rather than assume (new
   dependency, file outside listed paths, structural decision, scope not
   covered by the prompt).

## Secret handling — be explicit every time

`.clinerules` requires token/secret redaction in all diagnostic output.
Because this is enforced at the agent level rather than by a language
feature, don't assume it's automatic — restate it in any prompt that touches
`auth.py`, `.env`, or runs a script that prints API responses:

> "Redact any token, secret, or credential value from all output, including
> URLs and response bodies, before printing or saving it."

## Live API calls need explicit permission, every time

Several existing scripts (`diagnose_*`) make live calls to the Meta Graph
API. Because these cost API quota, can trip rate limits, and touch a
production Page/Ad account, prompts should say explicitly whether live calls
are:
- allowed (e.g. "run this against the live API and save output to X")
- or forbidden (e.g. survey/investigation prompts — "do not make any live
  API calls")

Don't leave this to inference from mode alone — Act mode doesn't
automatically mean "live calls are fine."

## Output persistence

This repo has already hit the problem of diagnostic scripts running
successfully but not saving their output anywhere (`diagnose_token_190.py`,
`diagnose_candidate_page_metrics.py`, `diagnose_page_fans.py` all lack saved
results). When a prompt involves a diagnostic script, say explicitly where
output should be saved, mirroring `diagnose_all_page_metrics.py`'s pattern of
writing a redacted `.txt` output file alongside the script.

## Session continuity

Cline generally supports session save/resume, but don't rely on implicit
memory of earlier sessions carrying architectural decisions forward. Point
back to `.clinerules`, `docs/PROJECT_DESCRIPTION.md`, and `docs/ROADMAP.md`
explicitly in prompts for new pieces of work, especially after a gap in
activity — treat each new prompt as if Cline is seeing the repo fresh, since
the model or Cline version may have changed since the last session.
