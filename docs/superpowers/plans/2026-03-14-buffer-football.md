# buffer:football Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the buffer:football cross-session delegation protocol — two dyadic skills (`/buffer:throw`, `/buffer:catch`), one script (`buffer_football.py`), one schema, and schema updates to hot-layer.

**Architecture:** `buffer_football.py` owns all football file I/O (status detection, pack/unpack, validate, flag, archive). Two SKILL.md files implement dyadic throw/catch behavior, delegating all file writes to the script. Skills never touch JSON directly. The football travels via a shared `.claude/buffer/football.json` in the project's buffer directory, accessible to both sessions.

**Tech Stack:** Python 3 stdlib + jsonschema (already a project dependency), existing `buffer_utils.py` via importlib (see `compact_hook.py` pattern), JSON Schema draft 2020-12 (matches existing schemas/).

**Spec:** `docs/superpowers/specs/2026-03-14-buffer-football-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `schemas/football.schema.json` | CREATE | Football envelope schema |
| `schemas/hot-layer.schema.json` | MODIFY | Add `football_in_flight` + `dialogue_style` |
| `plugin/scripts/buffer_football.py` | CREATE | All football lifecycle subcommands |
| `plugin/skills/throw/SKILL.md` | CREATE | Dyadic throw skill |
| `plugin/skills/catch/SKILL.md` | CREATE | Dyadic catch skill |
| `plugin/skills/off/SKILL.md` | MODIFY | Add in-flight guard (Step 0b) |
| `plugin/.claude-plugin/plugin.json` | MODIFY | 3.1.0 → 3.2.0 |
| `plugin/skills/on/SKILL.md` | MODIFY | Version string 3.1.0 → 3.2.0 + football_in_flight notice |
| `CHANGELOG.md` | MODIFY | Add 3.2.0 entry |
| `tests/test_buffer_football.py` | CREATE | ~15 tests for buffer_football.py |

---

## Chunk 1: Schema Foundation

### Task 1: football.schema.json

**Files:**
- Create: `schemas/football.schema.json`

**Read first:** `schemas/hot-layer.schema.json` (lines 1-10) for `$schema` URI and draft version to match.

- [ ] **Step 1: Create `schemas/football.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "football.schema.json",
  "title": "Football",
  "description": "Cross-session task delegation envelope for buffer:throw / buffer:catch",
  "type": "object",
  "required": ["schema_version", "mode", "state", "throw_type", "thrown_by", "throw_count", "thrown_at", "planner_payload"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {"type": "integer", "const": 1},
    "mode": {"type": "string", "const": "football"},
    "state": {"type": "string", "enum": ["in_flight", "caught", "returned", "absorbed"]},
    "throw_type": {"type": "string", "enum": ["heavy", "lite"]},
    "thrown_by": {"type": "string", "enum": ["planner", "worker"]},
    "throw_count": {"type": "integer", "minimum": 1},
    "thrown_at": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "planner_payload": {
      "type": "object",
      "required": ["thread"],
      "additionalProperties": false,
      "properties": {
        "thread": {
          "type": "object",
          "required": ["description", "current_task", "next_action"],
          "additionalProperties": false,
          "properties": {
            "description": {"type": "string", "minLength": 1},
            "current_task": {"type": "string", "minLength": 1},
            "files_to_touch": {"type": "array", "items": {"type": "string"}},
            "design_docs": {"type": "array", "items": {"type": "string"}},
            "next_action": {"type": "string", "minLength": 1}
          }
        },
        "context": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "relevant_decisions": {
              "type": "array",
              "items": {
                "type": "object",
                "additionalProperties": false,
                "properties": {
                  "what": {"type": "string"},
                  "chose": {"type": "string"},
                  "why": {"type": "string"}
                }
              }
            },
            "alpha_refs": {"type": "array", "items": {"type": "string"}},
            "orientation_fragment": {"type": "string"},
            "dialogue_style": {"type": "string"}
          }
        }
      }
    },
    "worker_output": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "completed": {"type": "array", "items": {"type": "string"}},
        "changes_made": {"type": "array", "items": {"type": "string"}},
        "surprised_by": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
        "flagged_for_trunk": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["type", "content", "rationale"],
            "additionalProperties": false,
            "properties": {
              "type": {"type": "string", "enum": ["alpha_entry", "forward_note", "decision", "open_thread"]},
              "content": {"type": "object"},
              "rationale": {"type": "string", "minLength": 1}
            }
          }
        }
      }
    }
  }
}
```

- [ ] **Step 2: Validate it's legal JSON**

```bash
python -c "import json; json.load(open('schemas/football.schema.json')); print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add schemas/football.schema.json
git commit -m "feat: add football.schema.json for buffer:football protocol"
```

---

### Task 2: Patch hot-layer.schema.json

**Files:**
- Modify: `schemas/hot-layer.schema.json`

**Read first:** Full `schemas/hot-layer.schema.json` — locate `properties.instance_notes.properties` and the top-level `properties` object.

- [ ] **Step 1: Verify the fields are absent**

```bash
python -c "
import json
with open('schemas/hot-layer.schema.json') as f:
    s = json.load(f)
print('dialogue_style present:', 'dialogue_style' in s['properties']['instance_notes']['properties'])
print('football_in_flight present:', 'football_in_flight' in s['properties'])
"
```
Expected: both `False`.

- [ ] **Step 2: Add `dialogue_style` to `instance_notes.properties`**

In `schemas/hot-layer.schema.json`, locate the `properties.instance_notes.properties` block. Insert after the last existing property inside that block (e.g., after `alpha_accessed`), before the closing `}` of `properties`. Do NOT add to `instance_notes.required` — it is optional.
```json
"dialogue_style": {
  "type": "string",
  "description": "1-2 sentence characterization of session conversational register. Adopted silently by next instance."
}
```

- [ ] **Step 3: Add `football_in_flight` to top-level properties**

In `schemas/hot-layer.schema.json`, locate the top-level `properties` object (containing `schema_version`, `layer`, etc.). Insert after the last existing top-level property, before the closing `}` of `properties`. Do NOT add to the top-level `required` array — it is optional. The existing `"additionalProperties": false` will automatically permit it once declared here.
```json
"football_in_flight": {
  "type": "boolean",
  "description": "Soft guard: true while a football is in flight to a worker session."
}
```

- [ ] **Step 4: Validate JSON and run existing schema tests**

```bash
python -c "import json; json.load(open('schemas/hot-layer.schema.json')); print('ok')"
pytest tests/test_validate.py -v
```
Expected: `ok` + all validate tests pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add schemas/hot-layer.schema.json
git commit -m "feat: add dialogue_style and football_in_flight to hot-layer schema"
```

---

## Chunk 2: buffer_football.py

### Task 3: status, validate, archive subcommands

**Files:**
- Create: `plugin/scripts/buffer_football.py`
- Create: `tests/test_buffer_football.py` (partial — grows across tasks)

**Read first:**
- `plugin/scripts/compact_hook.py` lines 32-47 — `find_buffer_dir` importlib wrapper pattern to copy.
- `tests/test_buffer_utils.py` lines 1-12 — importlib test import pattern.
- `tests/test_compact_hook.py` lines 1-40 — fixture patterns for buffer dir.

- [ ] **Step 1: Write failing tests**

Create `tests/test_buffer_football.py`:

```python
"""Tests for buffer_football.py — football lifecycle management."""
import json
import importlib.util
import os
import pytest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

# Load module via importlib (same pattern as test_buffer_utils.py)
_spec = importlib.util.spec_from_file_location(
    'buffer_football',
    os.path.join(os.path.dirname(__file__), '..', 'plugin', 'scripts', 'buffer_football.py'))
buffer_football = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(buffer_football)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _args(**kwargs):
    """Build argparse Namespace with safe defaults."""
    defaults = dict(cwd=None, football=None, side=None, type=None,
                    thread=None, alpha_refs=None, completed=None,
                    changes=None, next_action=None,
                    type_flag=None, content=None, rationale=None)
    defaults.update(kwargs)
    return Namespace(**defaults)


@pytest.fixture
def buffer_dir(tmp_path):
    """Buffer dir with .git marker required by buffer_utils git guard."""
    d = tmp_path / ".claude" / "buffer"
    d.mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    return d


@pytest.fixture
def planner_buffer_dir(buffer_dir):
    """Planner session: trunk hot layer present, no micro-hot-layer."""
    (buffer_dir / "handoff.json").write_text(json.dumps({
        "schema_version": 2, "layer": "hot",
        "orientation": {
            "core_insight": "sigma-TAP models PRAXIS via the L-matrix.",
            "practical_warning": "Do not impose ABM assumptions."
        },
        "instance_notes": {
            "from": "inst-1", "to": "inst-2",
            "dialogue_style": "Casual and collaborative.",
            "remarks": [], "open_questions": []
        },
        "recent_decisions": [],
        "active_work": {"current_phase": "planning", "completed_this_session": [],
                        "in_progress": None, "blocked_by": None,
                        "next_action": "Design football"},
        "open_threads": [], "natural_summary": "Planning session."
    }))
    return buffer_dir


@pytest.fixture
def worker_buffer_dir(buffer_dir):
    """Worker session: micro-hot-layer present, no trunk."""
    (buffer_dir / "football-micro.json").write_text(json.dumps({
        "session_date": "2026-03-14", "catch_count": 1, "throw_count": 1,
        "active_task": "Implement foo",
        "completed_tasks": ["Wrote tests"],
        "decisions_made": [], "flagged_for_trunk": []
    }))
    return buffer_dir


@pytest.fixture
def valid_football(buffer_dir):
    """A valid in_flight heavy football on disk."""
    data = {
        "schema_version": 1, "mode": "football", "state": "in_flight",
        "throw_type": "heavy", "thrown_by": "planner", "throw_count": 1,
        "thrown_at": "2026-03-14",
        "planner_payload": {
            "thread": {
                "description": "Implement the buffer football script",
                "current_task": "Write status subcommand",
                "files_to_touch": ["plugin/scripts/buffer_football.py"],
                "next_action": "Run pytest tests/test_buffer_football.py"
            },
            "context": {
                "relevant_decisions": [], "alpha_refs": ["w:152"],
                "orientation_fragment": "sigma-TAP models PRAXIS via the L-matrix.",
                "dialogue_style": "Casual and collaborative."
            }
        },
        "worker_output": {}
    }
    fp = buffer_dir / "football.json"
    fp.write_text(json.dumps(data))
    return fp


# ── status tests ──────────────────────────────────────────────────────────────

def test_status_detects_planner(planner_buffer_dir, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_status(_args())
    assert json.loads(capsys.readouterr().out)["session_type"] == "planner"


def test_status_detects_worker(worker_buffer_dir, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_status(_args())
    assert json.loads(capsys.readouterr().out)["session_type"] == "worker"


def test_status_ambiguous(buffer_dir, capsys):
    (buffer_dir / "handoff.json").write_text("{}")
    (buffer_dir / "football-micro.json").write_text("{}")
    with patch.object(buffer_football, 'find_buffer_dir', return_value=buffer_dir):
        buffer_football.cmd_status(_args())
    assert json.loads(capsys.readouterr().out)["session_type"] == "ambiguous"


def test_status_includes_football_state(planner_buffer_dir, valid_football, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_status(_args())
    out = json.loads(capsys.readouterr().out)
    assert out["football_state"] == "in_flight"
    assert out["throw_type"] == "heavy"


# ── validate tests ────────────────────────────────────────────────────────────

def test_validate_passes_valid(valid_football, capsys):
    buffer_football.cmd_validate(_args(football=str(valid_football)))
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_validate_fails_missing_fields(buffer_dir, capsys):
    bad = buffer_dir / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "mode": "football"}))
    with pytest.raises(SystemExit):
        buffer_football.cmd_validate(_args(football=str(bad)))
    assert json.loads(capsys.readouterr().out)["valid"] is False


# ── archive tests ─────────────────────────────────────────────────────────────

def test_archive_names_correctly(valid_football, capsys):
    buffer_football.cmd_archive(_args(football=str(valid_football)))
    out = json.loads(capsys.readouterr().out)
    dest = Path(out["archived_to"])
    assert dest.exists()
    assert dest.name == "2026-03-14-implement-the-buffer-football-script.json"
    assert not valid_football.exists()


def test_archive_short_description(buffer_dir, capsys):
    """Fewer than 5 words: use all available words."""
    fp = buffer_dir / "football.json"
    fp.write_text(json.dumps({
        "schema_version": 1, "mode": "football", "state": "absorbed",
        "throw_type": "heavy", "thrown_by": "planner", "throw_count": 2,
        "thrown_at": "2026-03-14",
        "planner_payload": {"thread": {"description": "Fix bug", "current_task": "x", "next_action": "y"}},
        "worker_output": {}
    }))
    buffer_football.cmd_archive(_args(football=str(fp)))
    dest = Path(json.loads(capsys.readouterr().out)["archived_to"])
    assert "fix-bug" in dest.name
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_buffer_football.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError` or `AttributeError` (script doesn't exist).

- [ ] **Step 3: Create `plugin/scripts/buffer_football.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""buffer_football.py — football lifecycle for buffer:throw / buffer:catch"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Load buffer_utils via importlib (same pattern as compact_hook.py)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'buffer_utils', os.path.join(_script_dir, 'buffer_utils.py'))
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)
find_buffer_dir = _utils.find_buffer_dir

SCHEMA_PATH = Path(_script_dir).parent.parent / "schemas" / "football.schema.json"


def _resolve_buffer(cwd):
    bd = find_buffer_dir(Path(cwd) if cwd else Path.cwd())
    if bd is None:
        print(json.dumps({"error": "buffer directory not found"}))
        sys.exit(1)
    return Path(bd)

def _football(bd): return Path(bd) / "football.json"
def _micro(bd):    return Path(bd) / "football-micro.json"
def _hot(bd):      return Path(bd) / "handoff.json"


def cmd_status(args):
    bd = _resolve_buffer(args.cwd)
    has_trunk = _hot(bd).exists()
    has_micro = _micro(bd).exists()
    if has_trunk and has_micro:
        session_type = "ambiguous"
        print("WARNING: both handoff.json and football-micro.json found", file=sys.stderr)
    elif has_trunk:
        session_type = "planner"
    elif has_micro:
        session_type = "worker"
    else:
        session_type = "unknown"
    fp = _football(bd)
    football_state = throw_type = None
    if fp.exists():
        with open(fp) as f:
            data = json.load(f)
        football_state = data.get("state")
        throw_type = data.get("throw_type")
    print(json.dumps({"session_type": session_type, "football_state": football_state,
                      "throw_type": throw_type, "buffer_dir": str(bd)}))


def cmd_validate(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"valid": False, "error": f"not found: {fp}"}))
        sys.exit(1)
    try:
        import jsonschema
        with open(fp) as f:
            data = json.load(f)
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(data, schema)
        print(json.dumps({"valid": True}))
    except ImportError:
        # Fail closed: unknown validity is not the same as valid
        print(json.dumps({"valid": None, "warning": "jsonschema not installed; validation skipped"}))
        sys.exit(2)  # exit code 2 = inconclusive (distinct from 1 = invalid)
    except jsonschema.ValidationError as e:
        print(json.dumps({"valid": False, "error": e.message}))
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"valid": False, "error": f"JSON error: {e}"}))
        sys.exit(1)


def _slug(description):
    words = description.strip().split()[:5]
    return "-".join(re.sub(r"[^\w]", "", w).lower() for w in words if w) or "football"


def cmd_archive(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"error": f"not found: {fp}"}))
        sys.exit(1)
    with open(fp) as f:
        data = json.load(f)
    desc = data.get("planner_payload", {}).get("thread", {}).get("description", "football")
    date = data.get("thrown_at", datetime.now().strftime("%Y-%m-%d"))
    archive_dir = fp.parent / "footballs"
    archive_dir.mkdir(exist_ok=True)
    dest = archive_dir / f"{date}-{_slug(desc)}.json"
    shutil.move(str(fp), str(dest))
    print(json.dumps({"archived_to": str(dest)}))


def main():
    parser = argparse.ArgumentParser(description="buffer:football lifecycle")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status");   p.add_argument("--cwd"); p.set_defaults(func=cmd_status)
    p = sub.add_parser("validate"); p.add_argument("--football", required=True); p.set_defaults(func=cmd_validate)
    p = sub.add_parser("archive");  p.add_argument("--football", required=True); p.set_defaults(func=cmd_archive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_buffer_football.py -v
```
Expected: all 8 tests passing.

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/buffer_football.py tests/test_buffer_football.py
git commit -m "feat: buffer_football.py — status, validate, archive (Task 3, TDD)"
```

---

### Task 4: pack subcommand (both sides)

**Files:**
- Modify: `plugin/scripts/buffer_football.py` — add `cmd_pack`, `_pack_planner`, `_pack_worker`
- Modify: `tests/test_buffer_football.py` — add pack tests

- [ ] **Step 1: Write failing tests**

Append to `tests/test_buffer_football.py`:

```python
# ── pack — planner heavy ──────────────────────────────────────────────────────

def test_pack_heavy_planner_creates_football(planner_buffer_dir, capsys):
    thread = {"description": "Build foo", "current_task": "Write tests", "next_action": "Run pytest"}
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_pack(_args(side="planner", type="heavy",
                                       thread=json.dumps(thread), alpha_refs='["w:152"]'))
    fp = planner_buffer_dir / "football.json"
    assert fp.exists()
    data = json.loads(fp.read_text())
    assert data["mode"] == "football"
    assert data["throw_count"] == 1
    assert data["thrown_by"] == "planner"
    assert data["state"] == "in_flight"
    assert data["planner_payload"]["context"]["dialogue_style"] == "Casual and collaborative."
    assert data["planner_payload"]["context"]["alpha_refs"] == ["w:152"]


def test_pack_lite_planner_omits_context(planner_buffer_dir, valid_football, capsys):
    thread = {"description": "Fix bug", "current_task": "Patch line 42", "next_action": "Run tests"}
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_pack(_args(side="planner", type="lite", thread=json.dumps(thread)))
    data = json.loads(valid_football.read_text())
    assert "context" not in data["planner_payload"]
    assert data["state"] == "in_flight"
    assert data["throw_count"] == 2   # incremented from existing 1


def test_pack_increments_throw_count(planner_buffer_dir, valid_football, capsys):
    thread = {"description": "Next task", "current_task": "Do it", "next_action": "Done"}
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_pack(_args(side="planner", type="lite", thread=json.dumps(thread)))
    assert json.loads(valid_football.read_text())["throw_count"] == 2


# ── pack — worker ─────────────────────────────────────────────────────────────

def test_pack_heavy_worker_uses_micro(worker_buffer_dir, valid_football, capsys):
    # valid_football fixture writes to buffer_dir; worker_buffer_dir IS buffer_dir
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_pack(_args(side="worker", type="heavy"))
    data = json.loads(valid_football.read_text())
    assert data["thrown_by"] == "worker"
    assert data["state"] == "returned"
    assert data["worker_output"]["completed"] == ["Wrote tests"]


def test_pack_lite_worker_takes_args(worker_buffer_dir, valid_football, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_pack(_args(side="worker", type="lite",
                                       completed='["Wrote foo.py"]',
                                       changes='["Added cmd_foo"]',
                                       next_action="Run full suite"))
    data = json.loads(valid_football.read_text())
    assert data["worker_output"]["completed"] == ["Wrote foo.py"]
    assert data["worker_output"]["next_action"] == "Run full suite"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_buffer_football.py -k "pack" -v 2>&1 | head -10
```
Expected: `AttributeError: module 'buffer_football' has no attribute 'cmd_pack'`

- [ ] **Step 3: Implement `cmd_pack`, `_pack_planner`, `_pack_worker` in `buffer_football.py`**

Add these functions (insert before `main()`):

```python
def _pack_planner(args, bd, fp, throw_count, today):
    existing = {}
    if fp.exists():
        with open(fp) as f:
            existing = json.load(f)
    thread = json.loads(args.thread) if args.thread else {}
    payload = {"thread": thread}
    if args.type == "heavy":
        context = {"relevant_decisions": [], "alpha_refs": [], "orientation_fragment": "", "dialogue_style": ""}
        hot = _hot(bd)
        if hot.exists():
            with open(hot) as f:
                trunk = json.load(f)
            o = trunk.get("orientation", {})
            frags = [o.get("core_insight", ""), o.get("practical_warning", "")]
            context["orientation_fragment"] = " ".join(f for f in frags if f)
            context["dialogue_style"] = trunk.get("instance_notes", {}).get("dialogue_style", "")
            context["relevant_decisions"] = trunk.get("recent_decisions", [])[:3]
        context["alpha_refs"] = json.loads(args.alpha_refs) if args.alpha_refs else []
        payload["context"] = context
    data = {**existing,
            "schema_version": 1, "mode": "football", "state": "in_flight",
            "throw_type": args.type, "thrown_by": "planner",
            "throw_count": throw_count, "thrown_at": today,
            "planner_payload": payload,
            "worker_output": existing.get("worker_output", {})}
    with open(fp, "w") as f:
        json.dump(data, f, indent=2)
    print(json.dumps({"packed": True, "throw_count": throw_count}))


def _pack_worker(args, bd, fp, throw_count, today):
    micro = {}
    micro_path = _micro(bd)
    if micro_path.exists():
        with open(micro_path) as f:
            micro = json.load(f)
    existing = {}
    if fp.exists():
        with open(fp) as f:
            existing = json.load(f)
    if args.type == "heavy":
        worker_output = {
            "completed": micro.get("completed_tasks", []),
            "changes_made": micro.get("decisions_made", []),
            "surprised_by": [],
            "next_action": micro.get("active_task", ""),
            "flagged_for_trunk": micro.get("flagged_for_trunk", []),
        }
    else:
        worker_output = {
            "completed": json.loads(args.completed) if args.completed else [],
            "changes_made": json.loads(args.changes) if args.changes else [],
            "surprised_by": [],
            "next_action": args.next_action or "",
            "flagged_for_trunk": micro.get("flagged_for_trunk", []),
        }
    existing.update({"throw_count": throw_count, "thrown_by": "worker",
                     "throw_type": args.type, "thrown_at": today,
                     "state": "returned", "worker_output": worker_output})
    with open(fp, "w") as f:
        json.dump(existing, f, indent=2)
    print(json.dumps({"packed": True, "throw_count": throw_count}))


def cmd_pack(args):
    bd = _resolve_buffer(args.cwd)
    fp = _football(bd)
    existing_count = 0
    if fp.exists():
        with open(fp) as f:
            existing_count = json.load(f).get("throw_count", 0)
    throw_count = existing_count + 1
    today = datetime.now().strftime("%Y-%m-%d")
    if args.side == "planner":
        _pack_planner(args, bd, fp, throw_count, today)
    else:
        _pack_worker(args, bd, fp, throw_count, today)
```

Add to `main()` before `args = parser.parse_args()`:
```python
p = sub.add_parser("pack")
p.add_argument("--side", choices=["planner", "worker"], required=True)
p.add_argument("--type", choices=["heavy", "lite"], required=True)
p.add_argument("--cwd"); p.add_argument("--thread"); p.add_argument("--alpha-refs", dest="alpha_refs")
p.add_argument("--completed"); p.add_argument("--changes"); p.add_argument("--next-action", dest="next_action")
p.set_defaults(func=cmd_pack)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_buffer_football.py -v
```
Expected: all 13 tests passing.

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/buffer_football.py tests/test_buffer_football.py
git commit -m "feat: buffer_football.py — cmd_pack planner + worker (Task 4, TDD)"
```

---

### Task 5: unpack and flag subcommands

**Files:**
- Modify: `plugin/scripts/buffer_football.py` — add `cmd_unpack`, `cmd_flag`
- Modify: `tests/test_buffer_football.py` — add unpack + flag tests

- [ ] **Step 1: Write failing tests**

Append to `tests/test_buffer_football.py`:

```python
# ── unpack ────────────────────────────────────────────────────────────────────

def test_unpack_returns_football(valid_football, capsys):
    buffer_football.cmd_unpack(_args(football=str(valid_football)))
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "football"
    assert out["planner_payload"]["thread"]["description"] == "Implement the buffer football script"


# ── flag ──────────────────────────────────────────────────────────────────────

def test_flag_appends_to_micro(worker_buffer_dir, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_flag(_args(
            type_flag="decision",
            content='{"what": "use digest", "chose": "digest", "why": "keeps trunk voice clean"}',
            rationale="Emerged during implementation"))
    micro = json.loads((worker_buffer_dir / "football-micro.json").read_text())
    assert len(micro["flagged_for_trunk"]) == 1
    assert micro["flagged_for_trunk"][0]["type"] == "decision"


def test_flag_accumulates_across_calls(worker_buffer_dir, capsys):
    """Flag called twice produces two entries — async mid-session use."""
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        for i in range(2):
            buffer_football.cmd_flag(_args(
                type_flag="alpha_entry",
                content=f'{{"key": "term_{i}", "definition": "def {i}"}}',
                rationale=f"Term {i} coined during work"))
    micro = json.loads((worker_buffer_dir / "football-micro.json").read_text())
    assert len(micro["flagged_for_trunk"]) == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_buffer_football.py -k "unpack or flag" -v 2>&1 | head -10
```
Expected: `AttributeError` (functions not yet defined).

- [ ] **Step 3: Implement `cmd_unpack` and `cmd_flag` in `buffer_football.py`**

```python
def cmd_unpack(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"error": f"not found: {fp}"}))
        sys.exit(1)
    with open(fp) as f:
        print(json.dumps(json.load(f), indent=2))


def cmd_flag(args):
    bd = _resolve_buffer(args.cwd)
    micro_path = _micro(bd)
    micro = {}
    if micro_path.exists():
        with open(micro_path) as f:
            micro = json.load(f)
    micro.setdefault("flagged_for_trunk", []).append({
        "type": args.type_flag,
        "content": json.loads(args.content),
        "rationale": args.rationale,
    })
    with open(micro_path, "w") as f:
        json.dump(micro, f, indent=2)
    print(json.dumps({"flagged": True, "total_flags": len(micro["flagged_for_trunk"])}))
```

Add to `main()`:
```python
p = sub.add_parser("unpack"); p.add_argument("--football", required=True); p.set_defaults(func=cmd_unpack)
p = sub.add_parser("flag")
p.add_argument("--type", dest="type_flag",
               choices=["alpha_entry", "forward_note", "decision", "open_thread"], required=True)
p.add_argument("--content", required=True); p.add_argument("--rationale", required=True)
p.add_argument("--cwd"); p.set_defaults(func=cmd_flag)
```

Note: `--type` arg uses `dest="type_flag"` to avoid shadowing Python's `type` builtin.

- [ ] **Step 4: Run full football test suite**

```bash
pytest tests/test_buffer_football.py -v
```
Expected: all ~16 tests passing.

- [ ] **Step 5: Run full project test suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: same pass count as before this chunk, plus ~16 new tests.

- [ ] **Step 6: Commit**

```bash
git add plugin/scripts/buffer_football.py tests/test_buffer_football.py
git commit -m "feat: buffer_football.py — unpack, flag (Task 5, TDD)"
```

---

## Chunk 3: Skills + Polish

### Task 6: /buffer:throw SKILL.md

**Files:**
- Create: `plugin/skills/throw/SKILL.md`

**Read first:** `plugin/skills/status/SKILL.md` (full) for format and step conventions. `plugin/skills/on/SKILL.md` lines 1-20 for YAML frontmatter format.

Note: `throw` is a directory name, not a Python identifier — no reserved-word conflict with the plugin's string-based dispatcher.

- [ ] **Step 1: Create `plugin/skills/throw/SKILL.md`**

```markdown
---
name: buffer:throw
description: Pack and throw a football. Planner side packs for the worker; worker side returns results. Dyadic — detects session type automatically.
---

# /buffer:throw

Packs the football for the other session to catch. Behavior depends on session type — detected automatically.

---

## Step 1: Detect session type

```bash
python plugin/scripts/buffer_football.py status
```

- `"planner"` → Planner Branch (Steps 2P–8P)
- `"worker"` → Worker Branch (Steps 2W–5W)
- `"ambiguous"` → **⚠ MANDATORY POPUP** via `AskUserQuestion`: "Both trunk and micro-hot-layer detected. Are you the planner or the worker?" If planner is selected, offer to absorb the stale micro-hot-layer before proceeding.
- `"unknown"` → STOP: "No buffer found. Run /buffer:on or /buffer:catch first."

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

### Step 6P: Validate

```bash
python plugin/scripts/buffer_football.py validate --football .claude/buffer/football.json
```

If `valid: false` → show error to user, STOP.

### Step 7P: Set football_in_flight on trunk

Read `.claude/buffer/handoff.json`. Set `"football_in_flight": true`. Write back.

### Step 8P: Confirm

Show the user:
- Thread description and current task
- Throw type + throw count
- Alpha refs (if heavy)

Tell the user: "Football packed. Share the project path with your worker session and have them run `/buffer:catch`."

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

**Heavy:**
```bash
python plugin/scripts/buffer_football.py pack --side worker --type heavy
```

**Lite:**
```bash
python plugin/scripts/buffer_football.py pack \
  --side worker --type lite \
  --completed '<JSON_ARRAY>' \
  --changes '<JSON_ARRAY>' \
  --next-action '<STRING>'
```

### Step 5W: Confirm

Tell the user: "Football returned. Have the planner session run `/buffer:catch`."
```

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/throw/SKILL.md
git commit -m "feat: /buffer:throw skill — dyadic planner/worker throw"
```

---

### Task 7: /buffer:catch SKILL.md

**Files:**
- Create: `plugin/skills/catch/SKILL.md`

- [ ] **Step 1: Create `plugin/skills/catch/SKILL.md`**

```markdown
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

### Step 2W: Unpack

```bash
python plugin/scripts/buffer_football.py unpack --football .claude/buffer/football.json
```

Note `throw_count` — if `1`, heavy catch (first task). If `> 1`, lite catch (additional task).

### Step 3W (heavy — throw_count == 1): Initialize micro-hot-layer

Create `.claude/buffer/football-micro.json`:
```json
{
  "session_date": "YYYY-MM-DD",
  "catch_count": 1,
  "throw_count": 1,
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

### Step 2P: Unpack and present worker output

```bash
python plugin/scripts/buffer_football.py unpack --football .claude/buffer/football.json
```

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
```

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/catch/SKILL.md
git commit -m "feat: /buffer:catch skill — dyadic worker init / planner absorb"
```

---

### Task 8: /buffer:off guard + version bump + CHANGELOG

**Files:**
- Modify: `plugin/skills/off/SKILL.md`
- Modify: `plugin/.claude-plugin/plugin.json`
- Modify: `plugin/skills/on/SKILL.md`
- Modify: `CHANGELOG.md`

**Read first:** `plugin/skills/off/SKILL.md` lines 1-50 — locate the `## Process` section and find **Step 1** (the first numbered step, which reads `handoff.json`). Insert the guard immediately before Step 1, not in the Shared Preamble above it. `plugin/.claude-plugin/plugin.json` to confirm version is `3.1.0`. `plugin/skills/on/SKILL.md` — grep for `buffer v3.1.0` to find the line to update.

- [ ] **Step 1: Add football_in_flight guard to /buffer:off**

In `plugin/skills/off/SKILL.md`, in the `## Process` section, insert a new `### Step 0b` immediately before `### Step 1`:

```markdown
### Step 0b: Check for in-flight football

Read `.claude/buffer/handoff.json`. If `football_in_flight == true`:

> "⚠️ A football is currently in flight to a worker session. Saving now means the worker's return throw will need to be caught in a new planner session.
>
> 1. Wait — catch the worker's return (/buffer:catch) before saving
> 2. Save anyway (football.json remains for manual recovery)
>
> Save anyway? (yes/no)"

If no → STOP. If yes → continue (football NOT auto-archived).
```

- [ ] **Step 2: Bump version in plugin.json**

Change `"version": "3.1.0"` → `"version": "3.2.0"` in `plugin/.claude-plugin/plugin.json`.

- [ ] **Step 3: Update version string and add football notice in on/SKILL.md**

Find `buffer v3.1.0 |` in `plugin/skills/on/SKILL.md` Step 8 output template and change to `buffer v3.2.0 |`.

Then, immediately after the `>7 days stale` note (around Step 8), add:

```markdown
If `football_in_flight` is `true` in the hot layer, add after the confirmation line: "Note: a football is in flight (thrown [thrown_at date]). Run `/buffer:catch` when the worker returns."
```

- [ ] **Step 4: Add CHANGELOG entry**

In `CHANGELOG.md`, insert before the `## [buffer 3.1.0]` section:

```markdown
## [buffer 3.2.0] - 2026-03-14

### buffer:football — Cross-Session Task Delegation
- **`/buffer:throw`** — dyadic skill: planner packs football (heavy = full context + dialogue style, lite = task only); worker returns results (lite = output diff, heavy = full micro-hot-layer).
- **`/buffer:catch`** — dyadic skill: worker initializes micro-session (adopts `dialogue_style` silently from first response); planner absorbs results, reviews flagged items, digests into trunk.
- **`buffer_football.py`** — script backing both skills: `status` (session detection), `pack`, `unpack`, `validate`, `flag`, `archive`. Importlib-based buffer_utils integration.
- **`schemas/football.schema.json`** — new schema for football envelope (heavy/lite, planner/worker payloads, flagged_for_trunk items).
- **`schemas/hot-layer.schema.json`** — adds optional `football_in_flight` boolean and `dialogue_style` to `instance_notes.properties`.
- **`/buffer:off` guard** — warns when a football is in flight before saving trunk.
- **~16 new tests**, all passing.
```

- [ ] **Step 5: Run full test suite**

```bash
pytest --tb=short -q
```
Expected: all tests passing. Note total count for the commit message.

- [ ] **Step 6: Commit**

```bash
git add plugin/skills/off/SKILL.md plugin/.claude-plugin/plugin.json plugin/skills/on/SKILL.md CHANGELOG.md
git commit -m "feat: v3.2.0 — buffer:off guard, version bump, CHANGELOG"
```

- [ ] **Step 7: Push**

```bash
git push
```

---

## Acceptance Criteria

- [ ] `pytest --tb=short -q` passes with ~16 new football tests and no regressions
- [ ] `python plugin/scripts/buffer_football.py status` detects planner vs worker correctly from buffer dir contents
- [ ] `python plugin/scripts/buffer_football.py validate --football <heavy_football>` returns `{"valid": true}`
- [ ] Heavy planner pack reads `dialogue_style` from trunk `instance_notes` and embeds it in the football
- [ ] Worker heavy return merges from `football-micro.json`; lite return takes explicit args
- [ ] `flag` called twice produces two entries in `football-micro.json`
- [ ] Archive produces `footballs/YYYY-MM-DD-{slug}.json` and removes `football.json`
- [ ] `/buffer:off` warns when `football_in_flight: true`
- [ ] `/buffer:on` surfaces informational notice when `football_in_flight: true`
- [ ] `/buffer:catch` detects stale footballs (caught 3+ days ago, never returned) and offers absorption
- [ ] Ambiguous session state (both trunk + micro present) prompts user to disambiguate via `AskUserQuestion`
