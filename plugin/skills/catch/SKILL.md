---
name: catch
description: Catch a thrown football. Worker side initializes micro-session; planner side absorbs worker results into trunk. Dyadic — detects session type automatically.
---

# /buffer:catch

Unpacks the football and acts. Behavior depends on the football's current state, detected automatically. Footballs live globally at `~/.claude/buffer/footballs/` — no project buffer discovery needed to catch.

## Script Tooling

**`buffer_football.py`** (plugin-relative, in `scripts/` next to this skill's parent directory) handles all football operations. Resolve the absolute path from this skill's base directory: `<base_directory>/../../scripts/buffer_football.py`.

---

## Step 1: Detect session and football state

```bash
python <scripts>/buffer_football.py status
```

The output includes `mode` (`"legacy"` or `"multi-ball"`) and `session_type`. Route based on `session_type`:

| session_type | Condition | Route |
|---|---|---|
| `"worker"` | Ball(s) in_flight | Worker Catch Branch |
| `"planner"` | Ball(s) returned | Planner Absorb Branch |
| `"planner"` | Ball(s) caught but stale (3+ days) | **Stale check**: "A football was caught on [date] but never returned. Absorb partial progress?" If yes → Planner Absorb. If no → STOP. |
| `"ambiguous"` | Both trunk and micro detected | **⚠ MANDATORY POPUP**: "Both trunk and micro-hot-layer detected. Are you the planner or the worker?" Route accordingly. |
| `"unknown"` / no balls | Nothing found | STOP: "No football found. Ask the planner to run /buffer:throw first." |

Check `in_flight`, `caught`, `returned` arrays and `stale_balls` in the status output.

---

## Worker Catch Branch

### Step 2W: Catch the ball

```bash
python <scripts>/buffer_football.py catch
```

This single call handles ball selection, validation, unpacking, and state transition (`in_flight` → `caught`). Returns:

- If **one ball** in flight: catches it, returns `{ "caught": true, "ball_id": "...", "throw_type": "...", "throw_count": N, "planner_payload": {...} }`
- If **multiple balls** in flight: returns `{ "action": "choose", "in_flight": [...] }` — present the list via **⚠ MANDATORY POPUP** and re-run with `--ball-id <selected>`.
- If **error**: show to user, STOP.

Note `throw_count` from the response — if `1`, heavy catch (first task). If `> 1`, lite catch (additional task).

### Step 3W (heavy — throw_count == 1): Initialize micro-hot-layer

Create the micro-hot-layer file at `~/.claude/buffer/footballs/micro-<ball_id>.json`.

```json
{
  "session_date": "YYYY-MM-DD",
  "catch_count": 1,
  "throw_count": 0,
  "active_task": "<current_task from planner_payload.thread>",
  "completed_tasks": [],
  "decisions_made": [],
  "flagged_for_trunk": []
}
```

**Adopt `dialogue_style` silently.** Read `planner_payload.context.dialogue_style`. Match that register from your first response onward. Do not announce it.

### Step 4W (lite — throw_count > 1): Update micro-hot-layer

Read the micro-hot-layer. Set `active_task` to `current_task` from the new thread. Increment `catch_count`. Write back.

### Step 5W: Orient

Present to yourself:
- **Thread:** `planner_payload.thread.description` and `current_task`
- **Files to touch:** `planner_payload.thread.files_to_touch`
- **Design docs:** `planner_payload.thread.design_docs` — read them now if present
- **Next action:** `planner_payload.thread.next_action`
- **Alpha refs:** `planner_payload.context.alpha_refs` — note for reference, load only if needed
- **Orientation:** `planner_payload.context.orientation_fragment`

Tell the user: "Worker micro-session initialized. Ready to work on: [current_task]"

### Step 6W: Play the full field

You have access to every skill, agent, and tool available. **Use them proactively** — the planner delegated this task because they trust you to execute autonomously.

**Mandatory plays** (use when the situation calls for it, without asking):
- **Code review**: After significant implementation, deploy `superpowers:code-reviewer` or `feature-dev:code-reviewer` on your own work before returning.
- **Parallel agents**: Dispatch independent subtasks in parallel via the Agent tool.
- **Test-driven development**: Write tests first or run existing tests after changes.
- **Plans for complex work**: Use `superpowers:writing-plans` or `superpowers:executing-plans` for multi-step tasks.

**Situational plays** (use judgment):
- `superpowers:systematic-debugging` for unexpected failures
- `superpowers:brainstorming` for design decisions with trade-offs
- `Explore` agent type for deep codebase understanding

**Operating principle**: Make every decision as the senior engineer on this task. Review your own code, test your changes, parallelize where possible, flag anything surprising.

Flag items for trunk carry-over:
```bash
python <scripts>/buffer_football.py flag \
  --type decision|alpha_entry|forward_note|open_thread \
  --content '<JSON>' \
  --rationale '<why this warrants verbatim carry-over>'
```
Add `--ball-id <id>` if multiple balls are active.

---

## Planner Absorb Branch

### Step 2P: Unpack and present worker output

```bash
python <scripts>/buffer_football.py unpack --ball-id <ball_id>
```

If error → show to user, STOP.

Present `worker_output` to the user:
- **Completed:** list items
- **Changes made:** list items
- **Surprised by:** list items (if any)
- **Worker's suggested next action:** show it

### Step 3P: Review flagged items

For each item in `worker_output.flagged_for_trunk`, present one at a time:

> "Worker flagged this for verbatim carry-over:
> Type: [type] | Rationale: [rationale]
> Content: [content]
>
> Accept verbatim / Rewrite / Skip?"

- **Accept:** add directly to trunk (alpha entry → alpha bin, decision → `recent_decisions`, forward note → `forward_notes.json`, open thread → `open_threads`)
- **Rewrite:** ask the planner how, then add
- **Skip:** discard

### Step 4P: Digest into trunk

Update `.claude/buffer/handoff.json`:
- Add completed tasks to `active_work.completed_this_session`
- Update `active_work.current_phase` and `next_action`
- Add new decisions to `recent_decisions`
- Update `open_threads` as needed

### Step 5P: Clear football_in_flight + Archive

```bash
python <scripts>/buffer_football.py archive --ball-id <ball_id>
```

Read `handoff.json`. Set `"football_in_flight": false`. Write back.

### Step 6P: Confirm

Tell the user: "Football absorbed and archived. Worker output digested into trunk."
