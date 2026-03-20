---
name: throw
description: Pack and throw a football. Planner side packs stepwise instructions for the worker; worker side returns verified results. Dyadic — detects session type automatically.
---

# /buffer:throw

Packs and throws a football. Footballs live globally at `~/.claude/buffer/footballs/`. Each ball carries the project location so workers find it regardless of cwd.

## Script Tooling

**`buffer_football.py`** (plugin-relative, in `scripts/` next to this skill's parent directory) handles all football operations. Resolve the absolute path from this skill's base directory: `<base_directory>/../../scripts/buffer_football.py`.

---

## Step 1: Detect session type

```bash
python <scripts>/buffer_football.py status
```

- `"planner"` or `"idle"` → Planner Branch — you're throwing a new ball
- `"worker"` → Worker Branch — you're returning results
- `"stale_worker"` → **⚠ MANDATORY POPUP**: "A ball is caught but has no active worker. Absorb it first or discard?" Then route accordingly.

Check `in_flight` array to see if other balls are already out.

---

## Planner Branch

The planner provides **diachronic input**: ordered steps with enough context that the worker can execute without guessing. The quality of the throw determines the quality of the catch.

### Step 2P: Choose throw type

- First throw to this worker → **heavy** (full context + dialogue style)
- Worker already warmed up → **lite** (task only)

### Step 3P: Build the thread

The thread is the planner's contract with the worker. It must be **stepwise and specific**.

Collect from the user (or derive from the current session state):

1. `description` — What is the worker being asked to do? (1-3 sentences, scope and purpose)
2. `steps` — **Required.** Ordered array of discrete steps. Each step:
   - `action`: What to do (imperative, specific — "Read X", "Build Y", "Run Z")
   - `files`: Files involved (paths)
   - `done_when`: How the worker knows this step is complete (observable condition)
3. `files_to_touch` — All files the worker may need to read or modify
4. `design_docs` — Specs, plans, or reference docs the worker should read before starting
5. `constraints` — What the worker must NOT do (boundaries, scope limits, protected files)

Build as JSON:
```json
{
  "description": "...",
  "steps": [
    {"action": "...", "files": ["..."], "done_when": "..."},
    {"action": "...", "files": ["..."], "done_when": "..."}
  ],
  "files_to_touch": ["..."],
  "design_docs": ["..."],
  "constraints": ["..."]
}
```

**Quality gate**: If the thread has no `steps` array or steps lack `done_when` conditions, push back. Vague throws produce vague results.

### Step 4P (heavy only): Collect alpha refs

Ask: "Which alpha refs are relevant? (e.g. `w:152`, `cw:44` — or blank for none)"

Format as JSON array: `["w:152"]` or `[]`.

### Step 5P: Pack

**Heavy:**
```bash
python <scripts>/buffer_football.py pack \
  --side planner --type heavy \
  --thread '<THREAD_JSON>' \
  --alpha-refs '<ALPHA_REFS_JSON>'
```

**Lite:**
```bash
python <scripts>/buffer_football.py pack \
  --side planner --type lite \
  --thread '<THREAD_JSON>'
```

The script returns the assigned `ball_id`.

### Step 6P: Set football_in_flight on trunk

Read `.claude/buffer/handoff.json`. Set `"football_in_flight": true`. Write back.

### Step 7P: Confirm

Show:
- Thread description, step count, and constraints
- Throw type + ball ID
- Alpha refs (if heavy)

Tell the user: "Football packed (ball: [ball_id]). Worker session runs `/buffer:catch` to begin."

---

## Worker Branch

The worker returns **synchronic output**: a state snapshot of what was done, what changed, and what was verified. The planner needs to absorb this without re-investigating.

### Step 2W: Choose return type

- Session end → **heavy** (full micro-hot-layer digest)
- More tasks coming → **lite** (output diff)

### Step 3W: Build the return report

Whether heavy or lite, the worker's return must meet these **hard requirements**:

1. **Step-by-step accounting**: For each step in the planner's `steps` array, report: done / partially done / skipped / blocked. No step goes unaccounted.
2. **Show work**: What was tried. If something failed before succeeding, say so. The planner needs the trajectory, not just the endpoint.
3. **Test evidence**: If tests were run, include: what was tested, how, and the result. "Tests pass" is not sufficient — name the tests or describe the verification.
4. **Deviation flagging**: Anything that diverged from the plan. If you changed approach mid-task, explain why. If you touched files not in `files_to_touch`, explain why.
5. **Surprises**: Anything the planner didn't anticipate that they should know about.

**Lite return** — collect from session state:
- Completed steps (by number/name from the plan)
- Changes made (files + what changed)
- Deviations from plan (if any)
- Next action for planner

**Heavy return** — the micro-hot-layer covers this automatically if maintained during the session. Review it before packing to ensure completeness.

### Step 4W: Pack return

Determine `ball_id` from the micro-hot-layer filename (`micro-<ball_id>.json` in `~/.claude/buffer/footballs/`).

**Heavy:**
```bash
python <scripts>/buffer_football.py pack --side worker --type heavy --ball-id <ball_id>
```

**Lite:**
```bash
python <scripts>/buffer_football.py pack \
  --side worker --type lite --ball-id <ball_id> \
  --completed '<JSON_ARRAY>' \
  --changes '<JSON_ARRAY>' \
  --next-action '<STRING>'
```

(If only one caught ball exists, `--ball-id` can be omitted.)

### Step 5W: Confirm

Tell the user: "Football returned (ball: [ball_id]). Planner session runs `/buffer:catch` to absorb."
