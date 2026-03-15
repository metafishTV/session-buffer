---
name: buffer:catch
description: Catch a thrown football. Worker side initializes micro-session; planner side absorbs worker results into trunk. Dyadic — detects session type automatically.
---

# /buffer:catch

Unpacks the football and acts. Behavior depends on the football's current state, detected automatically.

---

## Step 1: Detect session and football state

```bash
python plugin/scripts/buffer_football.py status
```

Route:
- `session_type == "worker"` AND `football_state == "in_flight"` → Worker Catch Branch
- `session_type == "planner"` AND `football_state == "returned"` → Planner Absorb Branch
- `session_type == "planner"` AND `football_state == "caught"` → **Stale Football Check**: read `thrown_at` from `football.json`. If 3+ days old, surface: "A football was caught on [date] but never returned. Absorb the worker's partial progress from `football-micro.json`?" If yes → Planner Absorb Branch (treat micro-hot-layer as partial heavy return). If no → STOP.
- `session_type == "ambiguous"` → **⚠ MANDATORY POPUP** via `AskUserQuestion`: "Both trunk and micro-hot-layer detected. Are you the planner or the worker?" Route accordingly.
- `football_state == null` → STOP: "No football found. Ask the planner to run /buffer:throw first."
- Any other combination → STOP: tell the user what was found, ask them to verify session state.

---

## Worker Catch Branch

### Step 2W: Validate and Unpack

```bash
python plugin/scripts/buffer_football.py validate --football .claude/buffer/football.json
python plugin/scripts/buffer_football.py unpack --football .claude/buffer/football.json
```

If `valid: false` → show error to user, STOP.

Note `throw_count` — if `1`, heavy catch (first task). If `> 1`, lite catch (additional task).

### Step 3W (heavy — throw_count == 1): Initialize micro-hot-layer

Create `.claude/buffer/football-micro.json`:
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

**Adopt `dialogue_style` silently.** Read `planner_payload.context.dialogue_style`. From your first response onward, match that conversational register — tone, cadence, formality. Do not announce it. Just be it.

### Step 4W (lite — throw_count > 1): Update micro-hot-layer

Read `football-micro.json`. Set `active_task` to `current_task` from the new thread. Increment `catch_count`. Write back.

### Step 5W: Set state to `caught`

Read `football.json`. Set `"state": "caught"`. Write back.

### Step 6W: Orient

Present to yourself:
- **Thread:** `planner_payload.thread.description` and `current_task`
- **Files to touch:** `planner_payload.thread.files_to_touch`
- **Design docs:** `planner_payload.thread.design_docs` — read them now if present
- **Next action:** `planner_payload.thread.next_action`
- **Alpha refs:** `planner_payload.context.alpha_refs` — note for reference, load only if needed
- **Orientation:** `planner_payload.context.orientation_fragment`

Tell the user: "Worker micro-session initialized. Ready to work on: [current_task]"

Flag items for trunk carry-over at any time using:
```bash
python plugin/scripts/buffer_football.py flag \
  --type decision|alpha_entry|forward_note|open_thread \
  --content '<JSON>' \
  --rationale '<why this warrants verbatim carry-over>'
```

---

## Planner Absorb Branch

### Step 2P: Validate, unpack, and present worker output

```bash
python plugin/scripts/buffer_football.py validate --football .claude/buffer/football.json
python plugin/scripts/buffer_football.py unpack --football .claude/buffer/football.json
```

If `valid: false` → show error to user, STOP.

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

Guide the planner through updating `.claude/buffer/handoff.json`:
- Add completed tasks to `active_work.completed_this_session`
- Update `active_work.current_phase` and `next_action`
- Add new decisions to `recent_decisions`
- Update `open_threads` as needed

### Step 5P: Clear football_in_flight

Read `handoff.json`. Set `"football_in_flight": false`. Write back.

### Step 6P: Archive

```bash
python plugin/scripts/buffer_football.py archive --football .claude/buffer/football.json
```

### Step 7P: Confirm

Tell the user: "Football absorbed and archived. Worker output digested into trunk."
