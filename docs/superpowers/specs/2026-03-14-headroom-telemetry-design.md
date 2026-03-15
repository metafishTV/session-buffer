# Compaction Directives: Layers 2-3 — Headroom Check + Telemetry

**Date:** 2026-03-14
**Status:** Design / Pre-implementation
**Plugin:** buffer v3.3.0 (target)
**Parent design:** `docs/plans/2026-03-14-compaction-directives-design.md`

---

## Overview

Layer 2 (headroom check) gives both the user and the AI awareness of context pressure — how full the context window is, and when compaction should happen. Layer 3 (telemetry) records compaction events, headroom warnings, and session summaries to an append-only log, laying the data foundation for Layer 4 (praxes / self-tuning, deferred).

These layers are designed and implemented together because they share hook touch points and data flow: the headroom check produces warnings that the telemetry layer records.

---

## Layer 2: Headroom Check

### Tier Thresholds

| Context % | Tier | Statusline (CLI) | Sigma Hook Injection (all platforms) |
|---|---|---|---|
| < 70% | — | No indicator | No injection |
| 70-85% | `watch` | `ctx:72%` | "Context at 72%." |
| 85-93% | `warn` | `ctx:87%!` | "Context at 87%. Consider compacting before starting heavy work. Directives are ready." |
| 93%+ | `critical` | `ctx:95%!!` | "Context at 95% — compaction imminent. Run /compact now; directives will preserve active threads and vocabulary." |

### Design Principles

1. **Inform, never block.** Warnings are informational. Claude uses judgment about whether to suggest compacting. The user decides.
2. **Universal injection.** Sigma hook injects at all tiers for all platforms (CLI and desktop app). CLI users get the statusline as bonus passive awareness. Desktop app users have no statusline, so sigma injection is their only channel.
3. **Once per tier crossing.** The sigma hook tracks the last emitted tier in memory. A warning is injected only when the tier changes (e.g., crossing from `watch` to `warn`), not on every message above threshold. This prevents repetitive injection.
4. **No operation gating.** The headroom check does not gate specific operations (distillation, buffer:on, etc.). It surfaces pressure; Claude decides whether to act.

### Data Sources

The sigma hook already receives session JSON via stdin on every `UserPromptSubmit` event. The relevant fields:

- `remaining_percentage` / `used_percentage` — context pressure
- `cache_read_input_tokens`, `cache_creation_input_tokens`, `input_tokens` — for cache ratio calculation

Cache ratio = `cache_read / (cache_read + cache_creation + input)`. Low cache ratio + high context = compaction will be aggressive. This informs the injection message but does not change tier thresholds.

### Statusline Integration

`statusline.py` already reads session JSON. Add a `ctx:XX%` segment after existing segments when `used_percentage >= 70`:

- `70-84%`: `ctx:72%`
- `85-92%`: `ctx:87%!`
- `93%+`: `ctx:95%!!`

---

## Layer 3: Telemetry

### Storage

**File:** `.claude/buffer/telemetry.jsonl` — append-only, one JSON object per line.

**Lifecycle:** Persists across sessions. No reset, no rotation. At ~100 bytes per event and typical usage (a few compactions per session, a few sessions per day), this file would take months to reach even 100KB.

### Event Types

#### Compaction Event

Emitted by `compact_hook.py pre-compact` when compaction fires.

```json
{
  "ts": "2026-03-14T15:30:00Z",
  "event": "compact",
  "context_pct": 93,
  "cache_ratio": 0.42,
  "off_count": 1,
  "threads": 3,
  "headroom_tier": "critical"
}
```

- `context_pct`: context usage percentage at compaction time
- `cache_ratio`: cache read ratio at compaction time
- `off_count`: session depth from `.session_active`
- `threads`: count of open threads in hot layer
- `headroom_tier`: what the headroom check was showing when compaction hit (`null` if below 70%, `"watch"`, `"warn"`, or `"critical"`). Tells Layer 4: "we warned at X tier, compaction hit at Y% — did the user act on the warning?"

#### Headroom Warning Event

Emitted by `sigma_hook.py` when injecting a headroom warning (once per tier crossing).

```json
{
  "ts": "2026-03-14T15:25:00Z",
  "event": "headroom_warning",
  "context_pct": 87,
  "cache_ratio": 0.31,
  "tier": "warn"
}
```

Emitted once per tier crossing per session — not on every message. The sigma hook tracks "last tier emitted" in memory and only emits when the tier changes.

#### Session End Event

Emitted by `/buffer:off` Step 13 (session markers section).

```json
{
  "ts": "2026-03-14T16:15:00Z",
  "event": "session_end",
  "compactions": 2,
  "off_count": 3,
  "warnings_emitted": 4,
  "peak_context_pct": 96
}
```

- `compactions`: count of compaction events this session (from telemetry file scan or `.session_active`)
- `warnings_emitted`: count of headroom warnings emitted this session
- `peak_context_pct`: highest context percentage observed this session

### Telemetry Utility

**New file:** `plugin/scripts/telemetry.py` — small shared utility imported by sigma_hook and compact_hook via the existing importlib pattern.

```python
def emit(buffer_dir, event_dict):
    """Append a timestamped event to telemetry.jsonl."""
    # Auto-adds "ts" field with ISO 8601 UTC timestamp
    # Appends one JSON line to buffer_dir/telemetry.jsonl
    # Creates file if it doesn't exist
    # Fail-silent: telemetry should never break the hook
```

**Fail-silent principle:** Telemetry emission must never cause a hook to fail. If the file can't be written, the emit function logs to stderr and returns. The hook continues normally.

---

## Integration Points

| File | Change | Layer |
|---|---|---|
| `plugin/scripts/sigma_hook.py` | Add context pressure check from session JSON. Inject warning at all tiers. Track last tier to avoid repetition. Emit `headroom_warning` to telemetry on tier crossing. | L2 + L3 |
| `plugin/scripts/compact_hook.py` | In `pre-compact`: emit `compact` event to telemetry with context %, cache ratio, headroom tier, thread count, off_count. | L3 |
| `plugin/scripts/statusline.py` | Add `ctx:XX%` segment when `used_percentage >= 70`. | L2 |
| `plugin/skills/off/SKILL.md` | In Step 13 (session markers): emit `session_end` event to telemetry with session summary stats. | L3 |
| `plugin/scripts/telemetry.py` | CREATE — shared emit utility. | L3 |

**No new hooks needed.** Everything piggybacks on existing hook events (PreCompact, UserPromptSubmit, `/buffer:off`).

**No new schemas.** Telemetry is unvalidated JSONL — an append-only log, not structured state. Schema validation would add overhead with no benefit for a log file.

---

## Tests: `tests/test_telemetry.py`

~10 tests:

| Test | Covers |
|---|---|
| `test_emit_creates_file` | First emit creates telemetry.jsonl |
| `test_emit_appends` | Multiple emits append lines, don't overwrite |
| `test_emit_auto_timestamps` | `ts` field added automatically |
| `test_emit_fail_silent` | Unwritable path doesn't raise |
| `test_tier_from_percentage` | 0→None, 70→watch, 85→warn, 93→critical |
| `test_tier_boundary_exact` | Exact boundary values (70, 85, 93) |
| `test_cache_ratio_calculation` | cache_read / (read + creation + input) |
| `test_cache_ratio_zero_division` | All zeros → 0.0, not crash |
| `test_once_per_crossing` | Same tier twice → only one emit |
| `test_tier_upgrade_emits` | watch→warn crossing emits new event |

---

## Files Summary

| File | Action | Est. Lines |
|---|---|---|
| `plugin/scripts/telemetry.py` | CREATE | 40 |
| `tests/test_telemetry.py` | CREATE | 100 |
| `plugin/scripts/sigma_hook.py` | MODIFY — add headroom check + telemetry emit | +30 |
| `plugin/scripts/compact_hook.py` | MODIFY — add telemetry emit in pre-compact | +10 |
| `plugin/scripts/statusline.py` | MODIFY — add ctx:XX% segment | +10 |
| `plugin/skills/off/SKILL.md` | MODIFY — add telemetry emit in Step 13 | +5 |
| `plugin/.claude-plugin/plugin.json` | MODIFY — 3.2.0 → 3.3.0 | 1 |
| `plugin/skills/on/SKILL.md` | MODIFY — version string 3.2.0 → 3.3.0 | 1 |
| `CHANGELOG.md` | MODIFY — add 3.3.0 entry | +10 |

---

## Resolved Questions

- **Where do warnings surface?** Both statusline (CLI) and sigma hook injection (all platforms). Sigma injects at all tiers for universality.
- **Gate specific operations?** No. Inform, don't gate. Claude uses judgment.
- **Once per message or once per crossing?** Once per tier crossing. Prevents repetitive injection.
- **Telemetry file lifecycle?** Persist across sessions, append-only. No rotation needed at expected data volumes.
- **What data does telemetry capture?** Events + headroom recommendations + cache ratio. Enough for Layer 4 to learn warning-to-compaction correlation.
- **Fail behavior?** Telemetry is fail-silent. Headroom check is informational only.

## Open Questions

- **Layer 4 (Praxes) design.** Deferred until telemetry accumulates enough data. The telemetry schema is designed to support it — tier + context % + cache ratio at warning and compaction time gives the correlation data needed for self-tuning thresholds.
- **Telemetry pruning.** Not needed at current scale. If the file ever gets large (thousands of sessions), a simple "keep last N events" trim during `/buffer:off` would suffice. Deferred.
