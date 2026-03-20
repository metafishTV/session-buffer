---
name: catch
description: Catch a thrown football. Worker side reads instructions fully then executes; planner side verifies worker output then absorbs into trunk. Dyadic — detects session type automatically.
---

# /buffer:catch

Catches a football and acts. Behavior depends on ball state, detected automatically. Footballs live globally at `~/.claude/buffer/footballs/`.

## Script Tooling

**`buffer_football.py`** (plugin-relative, in `scripts/` next to this skill's parent directory) handles all football operations. Resolve the absolute path from this skill's base directory: `<base_directory>/../../scripts/buffer_football.py`.

---

## Step 1: Detect session and football state

```bash
python <scripts>/buffer_football.py status
```

Route based on `session_type` (derived from ball states, not trunk):

| session_type | Meaning | Route |
|---|---|---|
| `"worker"` | Ball(s) in_flight or actively caught | Worker Catch Branch |
| `"planner"` | Ball(s) returned | Planner Absorb Branch |
| `"stale_worker"` | Ball caught but no micro file | **Stale check**: "A football was caught but never worked on. Absorb partial progress?" If yes → Planner Absorb. If no → STOP. |
| `"idle"` | No actionable balls | STOP: "No football in flight. Run /buffer:throw first." |

---

## Worker Catch Branch

### Step 2W: Catch the ball

```bash
python <scripts>/buffer_football.py catch
```

Returns:
- **One ball** in flight: catches it → `{ "caught": true, "ball_id": "...", "planner_payload": {...} }`
- **Multiple balls** in flight: `{ "action": "choose", "in_flight": [...] }` → **⚠ MANDATORY POPUP**, then re-run with `--ball-id <selected>`.
- **Error**: show to user, STOP.

Note `throw_count`: if `1` → heavy catch (first task). If `> 1` → lite catch (continuation).

### Step 3W (heavy — throw_count == 1): Initialize micro-hot-layer

Create `~/.claude/buffer/footballs/micro-<ball_id>.json`:

```json
{
  "session_date": "YYYY-MM-DD",
  "catch_count": 1,
  "throw_count": 0,
  "active_step": 1,
  "steps_status": [],
  "completed_tasks": [],
  "decisions_made": [],
  "deviations": [],
  "flagged_for_trunk": []
}
```

**Adopt `dialogue_style` silently.** Read `planner_payload.context.dialogue_style`. Match that register. Don't announce it.

### Step 4W (lite — throw_count > 1): Update micro-hot-layer

Read the micro-hot-layer. Update `active_step`. Increment `catch_count`. Write back.

### Step 5W: Full instruction read-through (MANDATORY)

**You must read every part of the planner's instructions before doing any work.** This is not optional. The planner compressed project trajectory into these instructions — skimming loses critical context.

Read and internalize, in order:

1. **Design docs**: `planner_payload.thread.design_docs` — read each file NOW. Not later. Not "if needed." Now.
2. **Steps**: `planner_payload.thread.steps` — read every step, every `done_when` condition. Understand the full sequence before starting step 1.
3. **Constraints**: `planner_payload.thread.constraints` — boundaries you must not cross.
4. **Files to touch**: `planner_payload.thread.files_to_touch` — your operating scope.
5. **Alpha refs**: `planner_payload.context.alpha_refs` — load and read if present.
6. **Orientation**: `planner_payload.context.orientation_fragment` — project context.

After reading everything, present a brief confirmation to the user:

```
Caught ball [ball_id]. Instructions received:
- [N] steps, first: [step 1 action]
- Scope: [files summary]
- Constraints: [constraints summary]
- Design docs read: [list]
Ready to execute.
```

### Step 6W: Execute with rigor

Work through the planner's steps in order. For each step:

1. Execute the action
2. Verify the `done_when` condition is met
3. Update `steps_status` in the micro-hot-layer: `{"step": N, "status": "done|blocked|skipped", "notes": "..."}`
4. If deviating from plan, log to `deviations` in micro with rationale

**Use every tool available.** The planner delegated this because they trust autonomous execution:

- **Code review**: After significant implementation, run `superpowers:code-reviewer` or `feature-dev:code-reviewer` on your own work.
- **Parallel agents**: Dispatch independent subtasks via the Agent tool.
- **Tests**: Run existing tests after changes. If writing new code, write tests.
- **Plans**: Use `superpowers:writing-plans` for complex multi-step work within a step.
- **Debugging**: Use `superpowers:systematic-debugging` for unexpected failures.

**Hard requirements during execution:**

- **Show work**: If something fails before succeeding, record both the failure and the fix. The planner needs the trajectory.
- **Test evidence**: If you run tests, record what was tested and the result. "Tests pass" is insufficient.
- **Deviation flagging**: If you touch files not in scope or change approach, log it with rationale.
- **No silent failures**: If a step can't be completed, flag it explicitly. Don't skip and hope.

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

### Step 2P: Unpack the return

```bash
python <scripts>/buffer_football.py unpack --ball-id <ball_id>
```

If error → show to user, STOP.

### Step 3P: Verify worker output

Present `worker_output` to the user with verification:

**Step accounting** — for each step the planner originally specified:
- Was it completed? Show the worker's status + notes.
- If skipped or blocked, show rationale.
- If no status reported for a step, flag the gap.

**Quality check:**
- Did the worker show work (failures, iterations) or just endpoints?
- Did the worker provide test evidence or just claims?
- Are there deviations? Were they justified?
- Are there surprises the planner should act on?

Present concisely:
```
Worker report for ball [ball_id]:
- Steps: [N/M completed] [list any blocked/skipped]
- Deviations: [count — list if any]
- Surprises: [list if any]
- Test evidence: [present/absent]
- Suggested next action: [worker's suggestion]
```

### Step 4P: Review flagged items

For each item in `worker_output.flagged_for_trunk`, present one at a time:

> "Worker flagged for carry-over:
> Type: [type] | Rationale: [rationale]
> Content: [content]
>
> Accept verbatim / Rewrite / Skip?"

- **Accept**: add to trunk (alpha → alpha bin, decision → `recent_decisions`, forward note → `forward_notes.json`, open thread → `open_threads`)
- **Rewrite**: ask the planner how, then add
- **Skip**: discard

### Step 5P: Digest into trunk

Update `.claude/buffer/handoff.json`:
- Add completed tasks to `active_work.completed_this_session`
- Update `active_work.current_phase` and `next_action`
- Add new decisions to `recent_decisions`
- Update `open_threads` as needed

### Step 6P: Archive + Confirm

```bash
python <scripts>/buffer_football.py archive --ball-id <ball_id>
```

Read `handoff.json`. Set `"football_in_flight": false`. Write back.

Tell the user: "Football absorbed and archived. [N/M] steps completed. Trunk updated."
