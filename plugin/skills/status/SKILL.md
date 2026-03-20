---
description: Display session health — model tier, buffer state, football status, context usage, and active markers. Use when the user wants to check session status, health, or context runway. Works everywhere including the desktop app.
---

# Buffer Status Check

Display a concise session health report. Read the following sources silently, then present the summary.

## Step 1: Read model tier

Read `~/.claude/buffer/.model_tier` (JSON: `{"model": "...", "tier": "..."`}).

If missing: report "Model: unknown (statusline not configured — run /buffer:setup-statusline)".
If present: note model name and tier (full/moderate/lean).

## Step 2: Read buffer state

Read `.claude/buffer/.session_active` (JSON: `{"date": "YYYY-MM-DD", "off_count": N}`).
Read `.claude/buffer/handoff.json` (extract `buffer_mode`, `open_threads` count, `session_meta.date`, `active_work.current_phase`, `active_work.in_progress`).

If neither file exists, report "Buffer not configured for this project."

Check save staleness: if `session_meta.date` is >2 days old, flag it.

## Step 3: Read football state

Read `~/.claude/buffer/football-registry.json`. Count balls by state (in_flight, caught, returned). List each with ball_id and thrown_at date.

## Step 4: Check marker files

Check existence of:
- `.claude/buffer/.distill_active` — distillation in progress
- `.claude/buffer/.compact_marker` — compaction occurred, context was reset
- `.claude/buffer/.buffer_loaded` — sigma hook active

## Step 5: Check compaction directives

Read `.claude/buffer/compact-directives.md` if it exists.
- If missing: note "Directives: not configured"
- If present: count on-disk files listed, active threads listed, and vocabulary terms listed.

## Step 6: Assess context health

Based on your own context awareness, estimate:
- Current context usage (approximate percentage)
- Whether compaction is approaching (>70% = caution, >85% = consider saving)

## Step 7: Present the report

Output a single formatted block:

```
Session Health
─────────────
Model:       [name] → [tier] tier
Buffer:      [on | saved | off xN | --]
Mode:        [full | lite | not configured]
Phase:       [current_phase or "none"]
In progress: [in_progress or "none"]
Threads:     [N open]
Saved:       [session_meta.date] ([N days ago])
Depth:       [off_count save cycles]

Context:     [~X% used] [green/caution/critical]
Markers:     [distill active | compacted | none]
Directives:  [active (N files, M threads, K vocab) | not configured]

Footballs:   [summary line]
             [tree of ball_id, state, date — if any]

Recommendation: [based on context % and session depth]
```

If model tier is `moderate` or `lean`, append:
```
Note: Running on [model] — compact summaries are trimmed for context efficiency.
```

Recommendations:
- Context <70%, depth 0-1: "Healthy. Continue working."
- Context 70-85%, any depth: "Caution. Consider running /buffer:off soon."
- Context >85%: "Critical. Run /buffer:off now to preserve session state."
- Depth >=3, any context: "Deep session (N save cycles). Context nuance may be degraded."
