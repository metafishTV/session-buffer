# buffer:football — Cross-Session Task Delegation

**Date:** 2026-03-14
**Status:** Design / Pre-implementation
**Plugin:** buffer v3.2.0 (target)

---

## Overview

`buffer:football` is a lightweight, task-scoped delegation protocol that lets a **planner session** pass bounded work to a **worker session** and receive results back — without the worker ever touching the main trunk. The football is a self-contained, portable micro-context: logically derived from the trunk, operationally independent of it.

**The metaphor:** The planner and worker play catch. `/buffer:throw` and `/buffer:catch` are the only two verbs. Each is dyadic — it detects which side of the exchange is calling it and behaves accordingly.

**The problem it solves:** A planner session is doing high-level design work. It wants to delegate a specific coding (or research, or writing) task to another session — but spinning up a full `/buffer:on` for the worker is expensive, creates trunk authority conflicts, and gives the worker far more context than they need. The football packages exactly what the worker needs, nothing more, and keeps the planner as the sole trunk author.

---

## Core Constraints

1. **Worker does not run `/buffer:on`.** `/buffer:catch` is the worker's entire session initialization. The football is their whole world.
2. **Trunk authority is the planner's exclusively.** The worker never reads or writes the trunk hot layer. All worker output travels back through the football.
3. **One active football at a time.** Not a technical limitation — a design choice. A single in-flight football keeps the planner's mental model clean. Parallel workers are a future extension.
4. **Digest, not merge.** When the planner catches a return throw, they read the worker's output and rewrite the relevant trunk sections themselves. The worker's voice does not overwrite the planner's. Exception: flagged items nominated for verbatim carry-over (see below).

---

## Throw Symmetry

Each direction has exactly one heavy throw and potentially many lite throws:

| Direction | Type | When | Contents |
|-----------|------|------|----------|
| Planner → Worker | **Heavy** | First throw (worker setup) | Full micro-context: thread, decisions, alpha refs, orientation fragment, `dialogue_style` |
| Planner → Worker | **Lite** | Subsequent throws (worker already warm) | New task thread + updated file targets only |
| Worker → Planner | **Lite** | Mid-session, between tasks | Output diff: completed, changes, surprises, next_action |
| Worker → Planner | **Heavy** | End of worker session | Full accumulated micro-hot-layer + all flagged items |

A full session exchange looks like:

```
planner: /buffer:throw   → heavy (worker setup)
worker:  /buffer:catch   → micro-session initialized
worker:  /buffer:throw   → lite return (task 1 done)
planner: /buffer:catch   → digest task 1, update trunk
planner: /buffer:throw   → lite (task 2)
worker:  /buffer:catch   → new task loaded
worker:  /buffer:throw   → heavy return (session end)
planner: /buffer:catch   → full digest, archive football
```

---

## Football File

**Location:** `.claude/buffer/football.json` (active); `.claude/buffer/footballs/YYYY-MM-DD-{thread-slug}.json` (archive after absorption).

**Session discovery:** Both sessions share the same project root and therefore the same `.claude/buffer/` directory. The planner communicates the project path to the worker out-of-band on first throw (states it in the throw message).

```json
{
  "schema_version": 1,
  "mode": "football",
  "state": "in_flight | caught | returned | absorbed",
  "throw_type": "heavy | lite",
  "thrown_by": "planner | worker",
  "throw_count": 0,
  "thrown_at": "YYYY-MM-DD",
  "planner_payload": {
    "thread": {
      "description": "What the worker is being asked to do",
      "current_task": "The specific task for this throw",
      "files_to_touch": ["path/to/file.py"],
      "design_docs": ["path/to/spec.md"],
      "next_action": "Concrete first step for the worker"
    },
    "context": {
      "relevant_decisions": [
        { "what": "...", "chose": "...", "why": "..." }
      ],
      "alpha_refs": ["w:152", "cw:44"],
      "orientation_fragment": "2-3 sentences of project identity drawn from trunk orientation block",
      "dialogue_style": "Verbatim from trunk instance_notes.dialogue_style"
    }
  },
  "worker_output": {
    "completed": [],
    "changes_made": [],
    "surprised_by": [],
    "next_action": "",
    "flagged_for_trunk": [
      {
        "type": "alpha_entry | forward_note | decision | open_thread",
        "content": {},
        "rationale": "Why this warrants verbatim carry-over into the trunk"
      }
    ]
  }
}
```

**Lite throw behavior:** On a lite planner→worker throw, `planner_payload.context` is omitted entirely. The worker already has it loaded from the heavy catch. Only `planner_payload.thread` is updated.

**`throw_count`:** Increments on every throw (planner or worker). `pack` reads the existing `throw_count` (defaulting to 0 if no `football.json` exists yet) and writes `throw_count + 1`. A worker can use this to detect whether it's receiving its first task (`throw_count == 1`) or a subsequent one.

---

## Micro-Hot-Layer (Worker Side)

The worker maintains a lightweight accumulator at `.claude/buffer/football-micro.json`. It persists across lite catches within the same worker session, becoming the heavy return payload at session end.

```json
{
  "session_date": "YYYY-MM-DD",
  "catch_count": 0,
  "throw_count": 0,
  "active_task": "Current task description",
  "completed_tasks": [],
  "decisions_made": [],
  "flagged_for_trunk": []
}
```

`flagged_for_trunk` in the micro-hot-layer accumulates items added via `buffer_football.py flag` at any point during the worker session — not only at throw time. Workers should flag items as they discover them.

---

## Skill Commands

Both skills are **dyadic**: they call `buffer_football.py status` first to determine session type (planner vs. worker) and football state (in_flight / caught / returned), then branch behavior accordingly.

**Note on naming:** `throw` and `catch` are reserved words in several languages (Java, C++, JavaScript). As skill directory names they are plain strings — the plugin loader uses string-based dispatch, not attribute reflection, so there is no conflict. `buffer_football.py` subcommands are named `pack`, `unpack`, `flag`, `validate`, `archive` (no reserved-word overlap).

### `/buffer:throw`

**If planner session (no `football-micro.json` present, trunk hot layer present):**
- Prompts: heavy or lite?
- Heavy: reads trunk hot layer, extracts thread + relevant decisions + alpha refs + orientation fragment + `dialogue_style`. Runs `buffer_football.py validate`. Writes `football.json`. Sets `football_in_flight: true` on the trunk hot layer.
- Lite: reads existing `football.json`, updates `planner_payload.thread` only. Does not re-pack context. Sets `state: in_flight`.
- Both: presents football summary to planner for confirmation before writing.

**If worker session (`football-micro.json` present):**
- Prompts: lite return (task done, more work coming) or heavy return (session end)?
- Lite: writes `worker_output` fields (completed, changes_made, surprised_by, next_action) from micro-hot-layer. Sets `state: returned`.
- Heavy: writes full micro-hot-layer content + all accumulated `flagged_for_trunk` items. Sets `state: returned`.

### `/buffer:catch`

**If worker session (football `thrown_by: "planner"`, state `in_flight`):**
- Heavy catch (first catch, `throw_count == 1`): loads full `planner_payload`. Initializes `football-micro.json`. Adopts `dialogue_style` silently — same mechanic as `/buffer:on` Step 7. No announcement. Sets `state: caught`.
- Lite catch (subsequent): loads new `planner_payload.thread`, appends to micro-hot-layer `active_task`. Sets `state: caught`. Worker continues without reset.

**If planner session (football `thrown_by: "worker"`, state `returned`):**
- Presents `worker_output` to planner: completed tasks, changes, surprises, next_action.
- Presents `flagged_for_trunk` items one at a time: **accept verbatim / rewrite / skip**.
- Guides planner through updating trunk hot layer (completed tasks, decisions, updated `next_action`).
- Clears `football_in_flight` from trunk. Runs `buffer_football.py archive`. Sets `state: absorbed`.

---

## Subjective Continuity

The worker session should feel to the user — and to itself — like a direct extension of the planner, not a fresh stranger. Three mechanisms accomplish this:

1. **`dialogue_style`** — verbatim from the planner's `instance_notes.dialogue_style`. Adopted silently on heavy catch. The worker matches the conversational register from its first message.
2. **Orientation fragment** — Drawn from the trunk's `orientation` block: `core_insight` (primary) plus up to two adjacent fields (e.g., `practical_warning`, source taglines) as needed to reach 2-3 sentences. If `orientation` is absent or minimal (e.g., lite-mode trunks), the field is omitted from the payload rather than padded.
3. **Relevant decisions** — the worker inherits the decisions that bear on its work, so it reasons within the same constraints as the planner.

---

## Script: `buffer_football.py`

Lives in `plugin/scripts/`. Imports `buffer_utils` for buffer path discovery.

| Subcommand | Args | Behavior |
|------------|------|----------|
| `status` | — | Detects session type (planner/worker) and football state. Returns `{session_type, football_state, throw_type}`. Planner = trunk hot layer present; worker = `football-micro.json` present. Edge case: if both present, returns `ambiguous` — skill presents `AskUserQuestion`: "Both trunk and football-micro detected. Are you the planner or the worker?" If planner, offers to absorb the stale micro-hot-layer. |
| `pack` | `--side planner\|worker --type heavy\|lite` | Writes or updates `football.json`. Heavy planner pack pulls from trunk hot layer; heavy worker pack pulls from micro-hot-layer. |
| `unpack` | `--football football.json` | Reads football, returns structured output for skill to present. |
| `flag` | `--type <type> --content <json> --rationale <str>` | Appends typed item to `football-micro.json` `flagged_for_trunk`. Can be called anytime during worker session. |
| `validate` | `--football football.json` | Validates against `schemas/football.schema.json`. Called before every throw and catch. |
| `archive` | `--football football.json` | Moves to `footballs/YYYY-MM-DD-{thread-slug}.json`. Thread slug = first 5 words of `thread.description`, hyphenated, lowercased. If fewer than 5 words, use all available words. |

---

## Schema

**`schemas/football.schema.json`** — added alongside existing 8 schemas in the `schemas/` directory. Validates top-level structure, required fields by `throw_type` (heavy vs. lite), and `flagged_for_trunk` item types.

---

## Integration Points

- **Trunk hot layer:** Gains optional field `football_in_flight: true|false`. Soft guard — informational only, no hook blocks.
- **`/buffer:on` guard:** If `football_in_flight: true` on the trunk hot layer, surface after the Step 8 confirmation line: "Note: a football is in flight (thrown [thrown_at date]). Run `/buffer:catch` when the worker returns." Informational only.
- **`/buffer:off` guard:** If planner runs `/buffer:off` while `football_in_flight: true`, the skill warns before proceeding: "A football is in flight. Consider catching it before saving to avoid losing the worker's output." Does not block.
- **Stale football detection:** On planner `/buffer:catch`, if `football.json` state is `caught` (worker took it but never returned) and `thrown_at` is 3+ days old, surface: "A football was caught on [date] but never returned. Absorb the worker's partial progress from `football-micro.json`?" Soft guard — the planner can absorb partial micro-hot-layer contents or dismiss. 3 days reflects the tight-delegation-loop intent; footballs are scoped tasks, not long-running work.
- **`buffer_utils.py`:** `buffer_football.py` imports it for buffer path discovery. No changes needed to `buffer_utils`.
- **`schemas/`:** One new schema file (`football.schema.json`). `schemas/hot-layer.schema.json` requires two modifications: (a) add optional `football_in_flight` boolean to top-level properties; (b) add `dialogue_style` string to `instance_notes.properties` (field was added in v3.1.0 but not yet reflected in the schema).

---

## Tests: `tests/test_buffer_football.py`

~15 tests:

| Test | Covers |
|------|--------|
| `test_pack_heavy_planner` | Heavy throw creates correct full structure |
| `test_pack_lite_planner` | Lite throw omits context block |
| `test_pack_heavy_worker` | Heavy worker return includes micro-hot-layer |
| `test_pack_lite_worker` | Lite worker return includes only output fields |
| `test_status_detects_planner` | Trunk hot layer present → planner |
| `test_status_detects_worker` | Micro-hot-layer present → worker |
| `test_status_ambiguous` | Both present → returns ambiguous, skill disambiguates |
| `test_stale_football_detection` | `caught` state + 3+ days old → surfaces absorption prompt |
| `test_stale_football_fresh` | `caught` state + <3 days → no warning |
| `test_flag_appends_to_micro` | Flag command appends typed item correctly |
| `test_flag_async` | Flag mid-session, not just at throw time |
| `test_validate_passes_valid` | Valid football → no error |
| `test_validate_fails_missing_fields` | Missing required field → error |
| `test_archive_names_correctly` | Thread slug from first 5 words, hyphenated |
| `test_throw_count_increments` | Increments on each pack call |
| `test_lite_omits_context` | Lite planner pack → no context block in output |
| `test_worker_inherits_dialogue_style` | `dialogue_style` present in heavy planner payload |

---

## Files Summary

| File | Action | Est. Lines |
|------|--------|-----------|
| `plugin/skills/throw/SKILL.md` | CREATE | 80 |
| `plugin/skills/catch/SKILL.md` | CREATE | 80 |
| `plugin/scripts/buffer_football.py` | CREATE | 150 |
| `schemas/football.schema.json` | CREATE | 60 |
| `tests/test_buffer_football.py` | CREATE | 140 |
| `plugin/.claude-plugin/plugin.json` | MODIFY — 3.1.0 → 3.2.0 | 1 |
| `plugin/skills/on/SKILL.md` | MODIFY — add football_in_flight notice after Step 8 confirm | +3 |
| `plugin/skills/off/SKILL.md` | MODIFY — add football_in_flight guard | +5 |
| `schemas/hot-layer.schema.json` | MODIFY — add `football_in_flight` + `dialogue_style` to instance_notes | +5 |
| `CHANGELOG.md` | MODIFY — add 3.2.0 entry | +10 |

---

## Resolved Questions

- **Ambiguous session detection:** When both trunk hot layer and `football-micro.json` are present, the skill asks via `AskUserQuestion` rather than blocking. If planner is selected, offers stale micro-hot-layer absorption.
- **Stale football threshold:** 3 days. Footballs are scoped tasks — if unreturned in 3 days, the worker likely forgot or abandoned. Soft warning, not deletion.
- **`/buffer:on` awareness:** Planner starting a new session is informed if a football is in flight. Informational only.

## Open Questions

- Should the worker be able to initiate a throw *without* a prior planner catch (e.g., to flag something urgent mid-task)? Current design says no — throws and catches alternate. Flagging via `buffer_football.py flag` is the async channel instead.
- Future: multiple simultaneous footballs (e.g., parallel worker sessions). Would require `footballs/{id}.json` rather than a single `football.json`. Deferred — single active football is the right starting constraint.
