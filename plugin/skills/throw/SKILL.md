---
name: throw
description: Pack and throw a football. Planner side packs for the worker; worker side returns results. Dyadic — detects session type automatically.
---

# /buffer:throw

Packs the football for the other session to catch. Behavior depends on session type — detected automatically. Footballs are stored globally at `~/.claude/buffer/footballs/`. Each ball carries the project location so workers can find it.

---

## Step 1: Detect session type

```bash
python plugin/scripts/buffer_football.py status
```

- `"planner"` → Planner Branch (Steps 2P–7P)
- `"worker"` → Worker Branch (Steps 2W–5W)
- `"ambiguous"` → **⚠ MANDATORY POPUP** via `AskUserQuestion`: "Both trunk and micro-hot-layer detected. Are you the planner or the worker?" If planner, offer to absorb the stale micro-hot-layer before proceeding.
- `"unknown"` → STOP: "No buffer found. Run /buffer:on or /buffer:catch first."

Check `in_flight` array in status output to see if other balls are already out.

---

## Planner Branch

### Step 2P: Choose throw type

Ask:
> "First throw to this worker session (heavy — full context + dialogue style), or are they already running (lite — task only)?"

- First throw → **heavy**
- Worker already warmed up → **lite**

### Step 3P: Collect thread

Ask for:
- `description` — What is the worker being asked to do? (1-2 sentences)
- `current_task` — The specific task for this throw (1 sentence)
- `files_to_touch` — Comma-separated file paths (or blank)
- `design_docs` — Relevant spec/plan paths (or blank)
- `next_action` — Concrete first step for the worker

Build as JSON:
```json
{
  "description": "...",
  "current_task": "...",
  "files_to_touch": ["..."],
  "design_docs": ["..."],
  "next_action": "..."
}
```

### Step 4P (heavy only): Collect alpha refs

Ask: "Which alpha refs are relevant? (e.g. `w:152`, `cw:44` — or blank for none)"

Format as JSON array: `["w:152"]` or `[]`.

### Step 5P: Pack

**Heavy:**
```bash
python plugin/scripts/buffer_football.py pack \
  --side planner --type heavy \
  --thread '<THREAD_JSON>' \
  --alpha-refs '<ALPHA_REFS_JSON>'
```

**Lite:**
```bash
python plugin/scripts/buffer_football.py pack \
  --side planner --type lite \
  --thread '<THREAD_JSON>'
```

The script returns the assigned `ball_id` in the output. Note it for the user.

### Step 6P: Set football_in_flight on trunk

Read `.claude/buffer/handoff.json`. Set `"football_in_flight": true`. Write back.

### Step 7P: Confirm

Show the user:
- Thread description and current task
- Throw type + ball ID
- Alpha refs (if heavy)

Tell the user: "Football packed (ball: [ball_id]). Share the project path with your worker session and have them run `/buffer:catch`."

---

## Worker Branch

### Step 2W: Choose return type

Ask:
> "Session end (heavy — full micro-hot-layer) or finishing one task with more coming (lite — output diff)?"

- Session end → **heavy**
- More tasks coming → **lite**

### Step 3W (lite only): Collect output

Ask:
- Completed (comma-separated): what did you finish?
- Changes made (comma-separated): key files/decisions
- Next action for the planner

### Step 4W: Pack return

Determine the `ball_id` from the micro-hot-layer filename (`micro-<ball_id>.json` in `~/.claude/buffer/footballs/`).

**Heavy:**
```bash
python plugin/scripts/buffer_football.py pack --side worker --type heavy --ball-id <ball_id>
```

**Lite:**
```bash
python plugin/scripts/buffer_football.py pack \
  --side worker --type lite --ball-id <ball_id> \
  --completed '<JSON_ARRAY>' \
  --changes '<JSON_ARRAY>' \
  --next-action '<STRING>'
```

(If only one caught ball exists, `--ball-id` can be omitted — the script auto-detects.)

### Step 5W: Confirm

Tell the user: "Football returned (ball: [ball_id]). Have the planner session run `/buffer:catch`."
