#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""buffer_football.py — football lifecycle for buffer:throw / buffer:catch

Supports both legacy single-ball mode (football.json) and multi-ball mode
(football-registry.json + footballs/*.json). Multi-ball adds intercept
capability and parallel worker sessions.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load buffer_utils via importlib (same pattern as compact_hook.py)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'buffer_utils', os.path.join(_script_dir, 'buffer_utils.py'))
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)
find_buffer_dir = _utils.find_buffer_dir

# Load safe_io via importlib (same pattern)
try:
    _sio_spec = importlib.util.spec_from_file_location(
        'safe_io', os.path.join(_script_dir, 'safe_io.py'))
    _sio = importlib.util.module_from_spec(_sio_spec)
    _sio_spec.loader.exec_module(_sio)
    atomic_write_json = _sio.atomic_write_json
    check_schema_version = _sio.check_schema_version
    SchemaVersionError = _sio.SchemaVersionError
except Exception:
    # Fallback: if safe_io is unavailable, define stubs so the script doesn't break
    def atomic_write_json(path, data, indent=2):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
    def check_schema_version(data, max_supported, path='<unknown>'):
        return data.get('schema_version', 1) if isinstance(data, dict) else 1
    class SchemaVersionError(ValueError):
        pass

SCHEMA_PATH = Path(_script_dir).parent.parent / "schemas" / "football.schema.json"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _resolve_buffer(cwd):
    bd = find_buffer_dir(Path(cwd) if cwd else Path.cwd())
    if bd is None:
        print(json.dumps({"error": "buffer directory not found"}))
        sys.exit(1)
    return Path(bd)

def _football(bd):    return Path(bd) / "football.json"
def _micro(bd):       return Path(bd) / "football-micro.json"
def _hot(bd):         return Path(bd) / "handoff.json"
def _registry(bd):    return Path(bd) / "football-registry.json"
def _balls_dir(bd):   return Path(bd) / "footballs"

def _ball_file(bd, ball_id):
    return _balls_dir(bd) / f"{ball_id}.json"

def _ball_micro(bd, ball_id):
    return Path(bd) / f"football-micro-{ball_id}.json"


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _read_json(path):
    """Read a JSON file, returning {} on missing/corrupt."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _read_registry(bd):
    """Read the multi-ball registry. Returns None if not in multi-ball mode."""
    rp = _registry(bd)
    if not rp.exists():
        return None
    return _read_json(rp)


def _write_registry(bd, registry):
    atomic_write_json(str(_registry(bd)), registry)


def _is_multiball(bd):
    return _registry(bd).exists()


def _slug(description):
    """Generate a kebab-case slug from first 3 words of a description."""
    words = description.strip().split()[:3]
    return "-".join(re.sub(r"[^\w]", "", w).lower() for w in words if w) or "football"


def _generate_ball_id(bd, description):
    """Generate a ball ID: {MMDD}-{slug}-{N} with auto-increment."""
    today = datetime.now(timezone.utc)
    prefix = today.strftime("%m%d") + "-" + _slug(description)
    balls_dir = _balls_dir(bd)
    n = 1
    while True:
        ball_id = f"{prefix}-{n}"
        if not (balls_dir / f"{ball_id}.json").exists():
            return ball_id
        n += 1


def _get_balls_by_state(registry, state):
    """Return list of (ball_id, ball_info) with the given state."""
    if not registry:
        return []
    return [(bid, info) for bid, info in registry.get("balls", {}).items()
            if info.get("state") == state]


# ---------------------------------------------------------------------------
# Legacy single-ball helpers (preserved for backward compatibility)
# ---------------------------------------------------------------------------

def _legacy_status(bd):
    """Status check for legacy single-ball mode."""
    has_trunk = _hot(bd).exists()
    has_micro = _micro(bd).exists()
    fp = _football(bd)
    football_state = throw_type = None
    stale = False
    fb_data = {}
    if fp.exists():
        fb_data = _read_json(fp)
        football_state = fb_data.get("state")
    if has_trunk and has_micro:
        session_type = "ambiguous"
        print("WARNING: both handoff.json and football-micro.json found", file=sys.stderr)
    elif has_trunk and football_state == "in_flight":
        session_type = "ambiguous"
    elif has_trunk:
        session_type = "planner"
    elif has_micro:
        session_type = "worker"
    else:
        session_type = "unknown"
    if fp.exists():
        try:
            check_schema_version(fb_data, max_supported=1, path=str(fp))
        except SchemaVersionError as e:
            print(f"warning: {e}", file=sys.stderr)
        if fb_data == {}:
            print("warning: football.json is empty — treating as corrupt", file=sys.stderr)
            football_state = "corrupt"
        throw_type = fb_data.get("throw_type")
        if football_state == "caught":
            thrown_at = fb_data.get("thrown_at", "")
            try:
                age = (datetime.now(timezone.utc) - datetime.strptime(thrown_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
                stale = age >= 3
            except ValueError:
                pass
    result = {"session_type": session_type, "football_state": football_state,
              "throw_type": throw_type, "buffer_dir": str(bd), "mode": "legacy"}
    if stale:
        result["stale"] = True
    return result


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def cmd_status(args):
    bd = _resolve_buffer(args.cwd)
    registry = _read_registry(bd)

    if registry is None:
        # Legacy single-ball mode
        print(json.dumps(_legacy_status(bd)))
        return

    # Multi-ball mode
    has_trunk = _hot(bd).exists()
    balls = registry.get("balls", {})

    # Detect session type from micro files
    active_micros = []
    for ball_id in balls:
        if _ball_micro(bd, ball_id).exists():
            active_micros.append(ball_id)

    if has_trunk and active_micros:
        session_type = "ambiguous"
    elif has_trunk:
        session_type = "planner"
    elif active_micros:
        session_type = "worker"
    else:
        session_type = "unknown"

    # Build per-ball status
    ball_states = {}
    stale_balls = []
    for ball_id, info in balls.items():
        state = info.get("state", "unknown")
        ball_states[ball_id] = {
            "state": state,
            "target": info.get("target", "instance"),
            "thrown_at": info.get("thrown_at"),
            "has_micro": _ball_micro(bd, ball_id).exists(),
        }
        if state == "caught":
            thrown_at = info.get("thrown_at", "")
            try:
                age = (datetime.now(timezone.utc) - datetime.strptime(thrown_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
                if age >= 3:
                    stale_balls.append(ball_id)
            except ValueError:
                pass

    in_flight = [bid for bid, s in ball_states.items() if s["state"] == "in_flight"]
    caught = [bid for bid, s in ball_states.items() if s["state"] == "caught"]
    returned = [bid for bid, s in ball_states.items() if s["state"] == "returned"]

    result = {
        "session_type": session_type,
        "mode": "multi-ball",
        "buffer_dir": str(bd),
        "ball_count": len(balls),
        "in_flight": in_flight,
        "caught": caught,
        "returned": returned,
        "balls": ball_states,
    }
    if stale_balls:
        result["stale_balls"] = stale_balls
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# Subcommand: validate
# ---------------------------------------------------------------------------

def cmd_validate(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"valid": False, "error": f"not found: {fp}"}))
        sys.exit(1)
    import jsonschema
    try:
        with open(fp, encoding='utf-8-sig') as f:
            data = json.load(f)
        with open(SCHEMA_PATH, encoding='utf-8-sig') as f:
            schema = json.load(f)
        jsonschema.validate(data, schema)
        print(json.dumps({"valid": True}))
    except jsonschema.ValidationError as e:
        print(json.dumps({"valid": False, "error": e.message}))
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"valid": False, "error": f"JSON error: {e}"}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand: archive
# ---------------------------------------------------------------------------

def cmd_archive(args):
    ball_id = getattr(args, 'ball_id', None)

    if ball_id:
        # Multi-ball archive — needs buffer discovery
        bd = _resolve_buffer(args.cwd)
        registry = _read_registry(bd)
        if not registry or ball_id not in registry.get("balls", {}):
            print(json.dumps({"error": f"ball not found: {ball_id}"}))
            sys.exit(1)
        ball_path = _ball_file(bd, ball_id)
        if not ball_path.exists():
            print(json.dumps({"error": f"ball file not found: {ball_path}"}))
            sys.exit(1)
        data = _read_json(ball_path)
        data["state"] = "absorbed"
        atomic_write_json(str(ball_path), data)
        # Update registry
        registry["balls"][ball_id]["state"] = "absorbed"
        _write_registry(bd, registry)
        # Clean up micro file
        micro = _ball_micro(bd, ball_id)
        if micro.exists():
            micro.unlink()
        print(json.dumps({"archived": ball_id, "file": str(ball_path)}))
        return

    # Legacy archive — --football path takes priority
    if args.football:
        fp = Path(args.football)
        archive_dir = fp.parent / "footballs"
    else:
        bd = _resolve_buffer(args.cwd)
        fp = _football(bd)
        archive_dir = _balls_dir(bd)
    if not fp.exists():
        print(json.dumps({"error": f"not found: {fp}"}))
        sys.exit(1)
    try:
        with open(fp, encoding='utf-8-sig') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"error": f"corrupt football file: {fp}"}))
        sys.exit(1)
    data["state"] = "absorbed"
    desc = data.get("planner_payload", {}).get("thread", {}).get("description", "football")
    date = data.get("thrown_at", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    archive_dir.mkdir(exist_ok=True)
    dest = archive_dir / f"{date}-{_slug(desc)}.json"
    atomic_write_json(str(dest), data)
    fp.unlink()
    print(json.dumps({"archived_to": str(dest)}))


# ---------------------------------------------------------------------------
# Subcommand: pack (throw)
# ---------------------------------------------------------------------------

def _build_planner_context(bd, args):
    """Build the context payload for a heavy planner throw."""
    context = {
        "relevant_decisions": [],
        "alpha_refs": [],
        "orientation_fragment": "",
        "dialogue_style": None,
    }
    hot = _hot(bd)
    if hot.exists():
        trunk = _read_json(hot)
        if trunk == {} or "orientation" not in trunk:
            print("warning: handoff.json is empty/hollow — planner context will be blank",
                  file=sys.stderr)
        o = trunk.get("orientation", {})
        frags = [o.get("core_insight", ""), o.get("practical_warning", "")]
        context["orientation_fragment"] = " ".join(f for f in frags if f)
        context["dialogue_style"] = trunk.get("instance_notes", {}).get("dialogue_style", None)
        context["relevant_decisions"] = trunk.get("recent_decisions", [])[:3]
    context["alpha_refs"] = json.loads(args.alpha_refs) if args.alpha_refs else []
    return context


def _pack_planner_multiball(args, bd, today):
    """Create a new ball in multi-ball mode."""
    registry = _read_registry(bd) or {"schema_version": 1, "balls": {}}
    thread = json.loads(args.thread) if args.thread else {}
    desc = thread.get("description", "football")
    ball_id = _generate_ball_id(bd, desc)
    target = getattr(args, 'target', 'instance') or 'instance'

    payload = {"thread": thread}
    if args.type == "heavy":
        payload["context"] = _build_planner_context(bd, args)

    ball_data = {
        "schema_version": 1,
        "mode": "football",
        "ball_id": ball_id,
        "state": "in_flight",
        "target": target,
        "throw_type": args.type,
        "thrown_by": "planner",
        "throw_count": 1,
        "thrown_at": today,
        "planner_payload": payload,
        "worker_output": {},
    }

    balls_dir = _balls_dir(bd)
    balls_dir.mkdir(exist_ok=True)
    atomic_write_json(str(_ball_file(bd, ball_id)), ball_data)

    # Update registry
    registry["balls"][ball_id] = {
        "state": "in_flight",
        "target": target,
        "thrown_at": today,
        "file": f"footballs/{ball_id}.json",
    }
    _write_registry(bd, registry)
    print(json.dumps({"packed": True, "ball_id": ball_id, "mode": "multi-ball"}))


def _pack_worker_multiball(args, bd, today):
    """Worker return for a specific ball."""
    ball_id = getattr(args, 'ball_id', None)
    if not ball_id:
        # Auto-detect: find the single caught ball with a micro file
        registry = _read_registry(bd) or {}
        caught = _get_balls_by_state(registry, "caught")
        active = [(bid, info) for bid, info in caught
                  if _ball_micro(bd, bid).exists()]
        if len(active) == 1:
            ball_id = active[0][0]
        elif len(active) == 0:
            print(json.dumps({"error": "no active caught ball found"}))
            sys.exit(1)
        else:
            print(json.dumps({
                "error": "multiple caught balls — specify --ball-id",
                "caught_balls": [bid for bid, _ in active],
            }))
            sys.exit(1)

    ball_path = _ball_file(bd, ball_id)
    micro_path = _ball_micro(bd, ball_id)
    existing = _read_json(ball_path)
    micro = _read_json(micro_path)

    if micro == {}:
        print("warning: micro file empty — worker output may be incomplete", file=sys.stderr)

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

    throw_count = existing.get("throw_count", 0) + 1
    existing.update({
        "throw_count": throw_count,
        "thrown_by": "worker",
        "throw_type": args.type,
        "thrown_at": today,
        "state": "returned",
        "worker_output": worker_output,
    })
    atomic_write_json(str(ball_path), existing)

    # Update registry
    registry = _read_registry(bd)
    if registry and ball_id in registry.get("balls", {}):
        registry["balls"][ball_id]["state"] = "returned"
        _write_registry(bd, registry)

    # Clean up micro file so status doesn't report stale worker state
    if micro_path.exists():
        micro_path.unlink()

    print(json.dumps({"packed": True, "ball_id": ball_id, "throw_count": throw_count}))


def _pack_planner_legacy(args, bd, fp, throw_count, today):
    """Legacy single-ball planner pack."""
    existing = _read_json(fp)
    thread = json.loads(args.thread) if args.thread else {}
    payload = {"thread": thread}
    if args.type == "heavy":
        payload["context"] = _build_planner_context(bd, args)
    data = {**existing,
            "schema_version": 1, "mode": "football", "state": "in_flight",
            "throw_type": args.type, "thrown_by": "planner",
            "throw_count": throw_count, "thrown_at": today,
            "planner_payload": payload,
            "worker_output": existing.get("worker_output", {})}
    atomic_write_json(str(fp), data)
    print(json.dumps({"packed": True, "throw_count": throw_count, "mode": "legacy"}))


def _pack_worker_legacy(args, bd, fp, throw_count, today):
    """Legacy single-ball worker pack."""
    micro = _read_json(_micro(bd))
    if micro == {}:
        print("warning: football-micro.json is empty — worker output may be incomplete",
              file=sys.stderr)
    existing = _read_json(fp)
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
    atomic_write_json(str(fp), existing)
    print(json.dumps({"packed": True, "throw_count": throw_count, "mode": "legacy"}))


def cmd_pack(args):
    bd = _resolve_buffer(args.cwd)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    multiball = _is_multiball(bd) or getattr(args, 'multiball', False)

    if multiball:
        if args.side == "planner":
            _pack_planner_multiball(args, bd, today)
        else:
            _pack_worker_multiball(args, bd, today)
    else:
        # Legacy single-ball
        fp = _football(bd)
        existing_count = 0
        if fp.exists():
            try:
                with open(fp, encoding='utf-8-sig') as f:
                    existing_count = json.load(f).get("throw_count", 0)
            except (json.JSONDecodeError, OSError):
                print("warning: football.json corrupt — throw_count reset to 0",
                      file=sys.stderr)
        throw_count = existing_count + 1
        if args.side == "planner":
            _pack_planner_legacy(args, bd, fp, throw_count, today)
        else:
            _pack_worker_legacy(args, bd, fp, throw_count, today)


# ---------------------------------------------------------------------------
# Subcommand: unpack
# ---------------------------------------------------------------------------

def cmd_unpack(args):
    # Legacy unpack: --football path takes priority (no buffer discovery needed)
    if args.football:
        fp = Path(args.football)
        if not fp.exists():
            print(json.dumps({"error": f"not found: {fp}"}))
            sys.exit(1)
        try:
            with open(fp, encoding='utf-8-sig') as f:
                data = json.load(f)
            try:
                check_schema_version(data, max_supported=1, path=str(fp))
            except SchemaVersionError as e:
                print(f"warning: {e}", file=sys.stderr)
            print(json.dumps(data, indent=2))
        except (json.JSONDecodeError, OSError) as e:
            print(json.dumps({"error": f"corrupt football file: {e}"}))
            sys.exit(1)
        return

    # Buffer discovery needed for multi-ball or legacy fallback
    bd = _resolve_buffer(args.cwd)
    ball_id = getattr(args, 'ball_id', None)

    if ball_id:
        # Multi-ball unpack
        ball_path = _ball_file(bd, ball_id)
        if not ball_path.exists():
            print(json.dumps({"error": f"ball not found: {ball_id}"}))
            sys.exit(1)
        data = _read_json(ball_path)
        print(json.dumps(data, indent=2))
        return

    # Legacy fallback: unpack football.json from buffer dir
    fp = _football(bd)
    if not fp.exists():
        print(json.dumps({"error": f"not found: {fp}"}))
        sys.exit(1)
    try:
        with open(fp, encoding='utf-8-sig') as f:
            data = json.load(f)
        try:
            check_schema_version(data, max_supported=1, path=str(fp))
        except SchemaVersionError as e:
            print(f"warning: {e}", file=sys.stderr)
        print(json.dumps(data, indent=2))
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"corrupt football file: {e}"}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand: catch
# ---------------------------------------------------------------------------

def cmd_catch(args):
    """Catch a ball — returns ball data for the skill to orient from.

    If --ball-id is given, catches that specific ball.
    If omitted, auto-selects if exactly one in_flight ball exists.
    If multiple are in_flight, returns the list for the skill to prompt.
    """
    bd = _resolve_buffer(args.cwd)
    registry = _read_registry(bd)

    if registry is None:
        # Legacy mode — no catch command needed, skill reads football.json directly
        print(json.dumps({"mode": "legacy", "message": "use legacy catch flow"}))
        return

    balls = registry.get("balls", {})
    ball_id = getattr(args, 'ball_id', None)

    if not ball_id:
        in_flight = _get_balls_by_state(registry, "in_flight")
        if len(in_flight) == 0:
            print(json.dumps({"error": "no balls in flight"}))
            sys.exit(1)
        elif len(in_flight) == 1:
            ball_id = in_flight[0][0]
        else:
            # Multiple in flight — return list for skill to prompt user
            print(json.dumps({
                "action": "choose",
                "message": "Multiple balls in flight. Which one?",
                "in_flight": [
                    {"ball_id": bid, "thrown_at": info.get("thrown_at"),
                     "target": info.get("target"),
                     "description": _read_json(_ball_file(bd, bid))
                        .get("planner_payload", {}).get("thread", {})
                        .get("description", "?")}
                    for bid, info in in_flight
                ],
            }))
            return

    # Catch the specific ball
    if ball_id not in balls:
        print(json.dumps({"error": f"ball not found: {ball_id}"}))
        sys.exit(1)
    if balls[ball_id].get("state") != "in_flight":
        print(json.dumps({
            "error": f"ball {ball_id} is not in_flight (state: {balls[ball_id].get('state')})",
        }))
        sys.exit(1)

    # Read ball data
    ball_path = _ball_file(bd, ball_id)
    ball_data = _read_json(ball_path)
    if not ball_data:
        print(json.dumps({"error": f"ball file missing or corrupt: {ball_path}"}))
        sys.exit(1)

    # Set state to caught
    ball_data["state"] = "caught"
    atomic_write_json(str(ball_path), ball_data)

    # Update registry
    registry["balls"][ball_id]["state"] = "caught"
    _write_registry(bd, registry)

    print(json.dumps({
        "caught": True,
        "ball_id": ball_id,
        "throw_type": ball_data.get("throw_type"),
        "throw_count": ball_data.get("throw_count"),
        "has_prior_progress": "prior_worker_progress" in ball_data,
        "planner_payload": ball_data.get("planner_payload", {}),
    }))


# ---------------------------------------------------------------------------
# Subcommand: intercept
# ---------------------------------------------------------------------------

def cmd_intercept(args):
    """Intercept a caught ball — pack partial progress back onto the ball
    and set it in_flight for a new worker to catch.

    Used when a worker's context window caps out or the user wants to
    redirect the ball to a different worker.
    """
    bd = _resolve_buffer(args.cwd)
    registry = _read_registry(bd)

    if registry is None:
        print(json.dumps({"error": "intercept requires multi-ball mode"}))
        sys.exit(1)

    ball_id = getattr(args, 'ball_id', None)
    balls = registry.get("balls", {})

    if not ball_id:
        # Auto-select if exactly one ball is caught
        caught = _get_balls_by_state(registry, "caught")
        if len(caught) == 0:
            print(json.dumps({"error": "no caught balls to intercept"}))
            sys.exit(1)
        elif len(caught) == 1:
            ball_id = caught[0][0]
        else:
            print(json.dumps({
                "action": "choose",
                "message": "Multiple caught balls. Which one to intercept?",
                "caught": [
                    {"ball_id": bid, "thrown_at": info.get("thrown_at"),
                     "description": _read_json(_ball_file(bd, bid))
                        .get("planner_payload", {}).get("thread", {})
                        .get("description", "?")}
                    for bid, info in caught
                ],
            }))
            return

    if ball_id not in balls:
        print(json.dumps({"error": f"ball not found: {ball_id}"}))
        sys.exit(1)

    state = balls[ball_id].get("state")
    if state != "caught":
        print(json.dumps({
            "error": f"ball {ball_id} cannot be intercepted (state: {state}, must be caught)",
        }))
        sys.exit(1)

    # Read ball data
    ball_path = _ball_file(bd, ball_id)
    ball_data = _read_json(ball_path)

    # Read micro file for partial progress
    micro_path = _ball_micro(bd, ball_id)
    micro = _read_json(micro_path)
    prior_progress = None

    if micro:
        prior_progress = {
            "intercepted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "completed_tasks": micro.get("completed_tasks", []),
            "decisions_made": micro.get("decisions_made", []),
            "active_task_at_intercept": micro.get("active_task", ""),
            "flagged_for_trunk": micro.get("flagged_for_trunk", []),
            "catch_count": micro.get("catch_count", 0),
        }
        # Append to any existing prior progress chain
        existing_prior = ball_data.get("prior_worker_progress", [])
        if isinstance(existing_prior, dict):
            existing_prior = [existing_prior]  # normalize legacy single-intercept
        existing_prior.append(prior_progress)
        ball_data["prior_worker_progress"] = existing_prior

        # Clean up micro file
        micro_path.unlink()

    # Set back to in_flight
    ball_data["state"] = "in_flight"
    ball_data["intercepted"] = True
    atomic_write_json(str(ball_path), ball_data)

    # Update registry
    registry["balls"][ball_id]["state"] = "in_flight"
    _write_registry(bd, registry)

    print(json.dumps({
        "intercepted": True,
        "ball_id": ball_id,
        "had_partial_progress": prior_progress is not None,
        "total_intercepts": len(ball_data.get("prior_worker_progress", [])),
    }))


# ---------------------------------------------------------------------------
# Subcommand: flag
# ---------------------------------------------------------------------------

def cmd_flag(args):
    bd = _resolve_buffer(args.cwd)
    ball_id = getattr(args, 'ball_id', None)

    if ball_id:
        # Multi-ball flag
        micro_path = _ball_micro(bd, ball_id)
    elif _is_multiball(bd):
        # Auto-detect: find the single caught ball with a micro file
        registry = _read_registry(bd)
        caught = _get_balls_by_state(registry, "caught")
        active = [(bid, info) for bid, info in caught
                  if _ball_micro(bd, bid).exists()]
        if len(active) == 1:
            ball_id = active[0][0]
            micro_path = _ball_micro(bd, ball_id)
        elif len(active) == 0:
            print(json.dumps({
                "error": "no caught balls with active micro files — specify --ball-id",
            }))
            sys.exit(1)
        else:
            print(json.dumps({
                "error": "multiple active balls — specify --ball-id",
                "active_balls": [bid for bid, _ in active],
            }))
            sys.exit(1)
    else:
        # Legacy
        micro_path = _micro(bd)

    micro = _read_json(micro_path)
    micro.setdefault("flagged_for_trunk", []).append({
        "type": args.type_flag,
        "content": json.loads(args.content),
        "rationale": args.rationale,
    })
    atomic_write_json(str(micro_path), micro)
    print(json.dumps({"flagged": True, "total_flags": len(micro["flagged_for_trunk"])}))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="buffer:football lifecycle (multi-ball)")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- status ---
    p = sub.add_parser("status")
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_status)

    # --- validate ---
    p = sub.add_parser("validate")
    p.add_argument("--football", required=True)
    p.set_defaults(func=cmd_validate)

    # --- archive ---
    p = sub.add_parser("archive")
    p.add_argument("--football", default=None)
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_archive)

    # --- pack (throw) ---
    p = sub.add_parser("pack")
    p.add_argument("--side", choices=["planner", "worker"], required=True)
    p.add_argument("--type", choices=["heavy", "lite"], required=True)
    p.add_argument("--cwd")
    p.add_argument("--thread")
    p.add_argument("--alpha-refs", dest="alpha_refs")
    p.add_argument("--completed")
    p.add_argument("--changes")
    p.add_argument("--next-action", dest="next_action")
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.add_argument("--target", choices=["instance", "subagent"], default="instance")
    p.add_argument("--multiball", action="store_true",
                   help="Force multi-ball mode (creates registry if needed)")
    p.set_defaults(func=cmd_pack)

    # --- unpack ---
    p = sub.add_parser("unpack")
    p.add_argument("--football", default=None)
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_unpack)

    # --- catch ---
    p = sub.add_parser("catch")
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_catch)

    # --- intercept ---
    p = sub.add_parser("intercept")
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_intercept)

    # --- flag ---
    p = sub.add_parser("flag")
    p.add_argument("--type", dest="type_flag",
                   choices=["alpha_entry", "forward_note", "decision", "open_thread"],
                   required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--rationale", required=True)
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_flag)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
