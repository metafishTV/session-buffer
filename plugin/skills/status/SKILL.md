---
description: Display session health — buffer state, context usage, session depth, and active markers. Use when the user wants to check session status, health, or context runway.
---

# Buffer Status Check

Display a concise session health report. Read the following sources silently, then present the summary.

## Step 1: Read buffer state

Read `.claude/buffer/.session_active` (JSON: `{"date": "YYYY-MM-DD", "off_count": N}`).
Read `.claude/buffer/handoff.json` (extract `buffer_mode`, `open_threads` count, `session_meta.date`, `active_work.current_phase`, `active_work.in_progress`).

If neither file exists, report "Buffer not configured for this project."

## Step 2: Check marker files

Check existence of:
- `.claude/buffer/.distill_active` — distillation in progress
- `.claude/buffer/.compact_marker` — compaction occurred, context was reset
- `.claude/buffer/.buffer_loaded` — sigma hook active

## Step 2b: Check compaction directives

Read `.claude/buffer/compact-directives.md` if it exists.
- If missing: note "Directives: not configured"
- If present: count on-disk files listed, active threads listed, and vocabulary terms listed. Note "Directives: active"

Check if CLAUDE.md contains a `## Compaction Guidance` section.
- If missing: note "CLAUDE.md compaction section: not present"
- If present: note "CLAUDE.md compaction section: active"

## Step 3: Assess context health

Based on your own context awareness, estimate:
- Current context usage (approximate percentage)
- Whether compaction is approaching (>70% = caution, >85% = consider saving)

## Step 4: Present the report

Output a single formatted block. Use this exact layout:

```
Session Health
---
Buffer:    [on | saved | off xN | --]
Mode:      [full | lite | not configured]
Threads:   [N open]
Phase:     [current_phase or "none"]
In progress: [in_progress or "none"]
Saved:     [session_meta.date or "never"]
Session depth: [off_count saves this session]

Context:   [~X% used] [green/caution/critical]
Markers:   [distill active | compacted | none]
Directives: [active (N files, M threads, K vocab) | not configured]
CLAUDE.md:  [compaction section active | not present]

Recommendation: [based on context % and session depth]
```

Recommendations:
- Context <70%, depth 0-1: "Healthy. Continue working."
- Context 70-85%, any depth: "Caution. Consider running /buffer:off soon."
- Context >85%: "Critical. Run /buffer:off now to preserve session state."
- Depth >=3, any context: "Deep session (N save cycles). Context nuance may be degraded. Consider starting fresh."
