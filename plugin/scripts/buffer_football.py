#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""buffer_football.py — football lifecycle for buffer:throw / buffer:catch

Footballs are stored globally at ~/.claude/buffer/footballs/ with a registry
at ~/.claude/buffer/football-registry.json. Each ball carries project_root
and buffer_dir so workers can find the project regardless of cwd.

Commands: status, pack, catch, unpack, archive, intercept, flag, validate.
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
# Path helpers — global (plugin-native) football storage
# ---------------------------------------------------------------------------

GLOBAL_DIR = Path(os.path.expanduser('~')) / '.claude' / 'buffer'

def _global_footballs():  return GLOBAL_DIR / 'footballs'
def _global_registry():   return GLOBAL_DIR / 'football-registry.json'
def _global_archive():    return GLOBAL_DIR / 'football-archive'

def _ball_file(ball_id):
    return _global_footballs() / f"{ball_id}.json"

def _ball_micro(ball_id):
    return _global_footballs() / f"micro-{ball_id}.json"

# Project buffer helpers — only for reading trunk context, not football storage
def _hot(bd):         return Path(bd) / "handoff.json"

def _resolve_buffer(cwd):
    """Find project buffer dir. Returns None instead of exiting if not found."""
    bd = find_buffer_dir(Path(cwd) if cwd else Path.cwd())
    return Path(bd) if bd else None

def _resolve_buffer_or_exit(cwd):
    """Find project buffer dir, exit with error if not found."""
    bd = _resolve_buffer(cwd)
    if bd is None:
        print(json.dumps({"error": "buffer directory not found"}))
        sys.exit(1)
    return bd

# Legacy project-local paths (for migration only)
def _legacy_football(bd):    return Path(bd) / "football.json"
def _legacy_micro(bd):       return Path(bd) / "football-micro.json"
def _legacy_registry(bd):    return Path(bd) / "football-registry.json"
def _legacy_balls_dir(bd):   return Path(bd) / "footballs"
def _legacy_ball_micro(bd, ball_id):
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


def _read_registry():
    """Read the global football registry, self-healing from ball files if needed.

    If the registry is missing or empty but ball files exist on disk,
    rebuilds the registry from the ball files. This handles:
    - Balls thrown by older plugin versions that predated the registry
    - Failed writes where the ball file was created but registry update failed
    - Any other registry/ball-file desync
    """
    rp = _global_registry()
    registry = _read_json(rp) if rp.exists() else None

    # Self-heal: scan ball files on disk and reconcile with registry
    balls_dir = _global_footballs()
    if balls_dir.exists():
        disk_balls = {}
        for f in balls_dir.iterdir():
            if f.suffix == '.json' and not f.name.startswith('micro-'):
                ball_id = f.stem
                disk_balls[ball_id] = f

        if disk_balls:
            registry_balls = registry.get("balls", {}) if registry else {}
            missing = set(disk_balls.keys()) - set(registry_balls.keys())

            if missing:
                if registry is None:
                    registry = {"schema_version": 1, "balls": {}}
                for ball_id in missing:
                    data = _read_json(disk_balls[ball_id])
                    if data and data.get("mode") == "football":
                        registry.setdefault("balls", {})[ball_id] = {
                            "state": data.get("state", "unknown"),
                            "target": data.get("target", "instance"),
                            "thrown_at": data.get("thrown_at", ""),
                            "project_root": data.get("project_root", ""),
                        }
                if missing:
                    _write_registry(registry)
                    print(f"Registry self-healed: added {len(missing)} ball(s) "
                          f"from disk ({', '.join(sorted(missing))})",
                          file=sys.stderr)

    return registry


def _write_registry(registry):
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(_global_registry()), registry)


def _slug(description):
    """Generate a kebab-case slug from first 3 words of a description."""
    words = description.strip().split()[:3]
    return "-".join(re.sub(r"[^\w]", "", w).lower() for w in words if w) or "football"


def _generate_ball_id(description):
    """Generate a ball ID: {MMDD}-{slug}-{N} with auto-increment."""
    today = datetime.now(timezone.utc)
    prefix = today.strftime("%m%d") + "-" + _slug(description)
    balls_dir = _global_footballs()
    n = 1
    while True:
        ball_id = f"{prefix}-{n}"
        if not (balls_dir / f"{ball_id}.json").exists():
            return ball_id
        n += 1


def _migrate_legacy(bd):
    """Migrate project-local football files to global storage. Returns registry or None."""
    migrated = False
    registry = _read_registry()

    # Migrate multi-ball registry + balls
    legacy_reg_path = _legacy_registry(bd)
    if legacy_reg_path.exists():
        legacy_reg = _read_json(legacy_reg_path)
        if registry is None:
            registry = legacy_reg
        else:
            # Merge balls into existing global registry
            for bid, info in legacy_reg.get("balls", {}).items():
                if bid not in registry.get("balls", {}):
                    registry.setdefault("balls", {})[bid] = info
        # Move ball files
        legacy_bd = _legacy_balls_dir(bd)
        if legacy_bd.exists():
            _global_footballs().mkdir(parents=True, exist_ok=True)
            for f in legacy_bd.iterdir():
                dest = _global_footballs() / f.name
                if not dest.exists():
                    f.rename(dest)
                else:
                    f.unlink()  # duplicate
            # Remove empty dir
            try:
                legacy_bd.rmdir()
            except OSError:
                pass
        # Move micro files
        for bid in legacy_reg.get("balls", {}):
            lm = _legacy_ball_micro(bd, bid)
            if lm.exists():
                dest = _ball_micro(bid)
                dest.parent.mkdir(parents=True, exist_ok=True)
                lm.rename(dest)
        legacy_reg_path.unlink()
        migrated = True

    # Migrate legacy single-ball football.json
    legacy_fp = _legacy_football(bd)
    if legacy_fp.exists():
        data = _read_json(legacy_fp)
        if data:
            # Assign a ball_id and move to global
            desc = data.get("planner_payload", {}).get("thread", {}).get("description", "migrated")
            ball_id = _generate_ball_id(desc)
            data["ball_id"] = ball_id
            _global_footballs().mkdir(parents=True, exist_ok=True)
            atomic_write_json(str(_ball_file(ball_id)), data)
            if registry is None:
                registry = {"schema_version": 1, "balls": {}}
            registry["balls"][ball_id] = {
                "state": data.get("state", "unknown"),
                "target": data.get("target", "instance"),
                "thrown_at": data.get("thrown_at", ""),
                "file": f"footballs/{ball_id}.json",
            }
        legacy_fp.unlink()
        # Migrate legacy micro
        lm = _legacy_micro(bd)
        if lm.exists():
            dest = _ball_micro(ball_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            lm.rename(dest)
        migrated = True

    if migrated and registry:
        _write_registry(registry)
        print(f"Migrated football files to global storage (~/.claude/buffer/footballs/)",
              file=sys.stderr)

    return registry if migrated else None


def _get_balls_by_state(registry, state):
    """Return list of (ball_id, ball_info) with the given state."""
    if not registry:
        return []
    return [(bid, info) for bid, info in registry.get("balls", {}).items()
            if info.get("state") == state]


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def cmd_status(args):
    # Try to find project buffer (optional — status works without it)
    bd = _resolve_buffer(args.cwd)

    # Check for legacy project-local files and migrate if found
    if bd:
        legacy_fp = _legacy_football(bd)
        legacy_reg = _legacy_registry(bd)
        if legacy_fp.exists() or legacy_reg.exists():
            _migrate_legacy(bd)

    # Read global registry
    registry = _read_registry()

    if registry is None:
        # No footballs anywhere
        result = {
            "session_type": "idle",
            "mode": "global",
            "ball_count": 0,
            "in_flight": [],
            "caught": [],
            "returned": [],
            "balls": {},
        }
        if bd:
            result["buffer_dir"] = str(bd)
        print(json.dumps(result))
        return

    balls = registry.get("balls", {})

    # Detect active micro files (worker in progress)
    active_micros = []
    for ball_id in balls:
        if _ball_micro(ball_id).exists():
            active_micros.append(ball_id)

    # Build per-ball status
    ball_states = {}
    stale_balls = []
    for ball_id, info in balls.items():
        state = info.get("state", "unknown")
        ball_states[ball_id] = {
            "state": state,
            "target": info.get("target", "instance"),
            "thrown_at": info.get("thrown_at"),
            "has_micro": _ball_micro(ball_id).exists(),
            "project_root": info.get("project_root", ""),
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

    # Session type derived strictly from ball state — no trunk/CWD inference.
    # Only states that are unambiguous get a definitive label.
    if active_micros:
        session_type = "worker"        # micro file = definitively a worker in progress
    elif caught and not active_micros:
        session_type = "stale_worker"  # caught but no micro — orphaned catch
    elif returned:
        session_type = "planner"       # returned balls need planner review
    elif in_flight:
        # In-flight balls are visible to ANY session — could be the planner
        # who threw them or a new worker. Don't assume; let the skill route.
        session_type = "has_in_flight"
    else:
        session_type = "idle"          # no actionable balls

    result = {
        "session_type": session_type,
        "mode": "global",
        "ball_count": len(balls),
        "in_flight": in_flight,
        "caught": caught,
        "returned": returned,
        "balls": ball_states,
    }
    if bd:
        result["buffer_dir"] = str(bd)
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
    registry = _read_registry()

    if not ball_id:
        # Auto-select: find single returned or absorbed ball
        if registry:
            returned = _get_balls_by_state(registry, "returned")
            absorbed = _get_balls_by_state(registry, "absorbed")
            candidates = returned + absorbed
            if len(candidates) == 1:
                ball_id = candidates[0][0]
            elif len(candidates) > 1:
                print(json.dumps({
                    "action": "choose",
                    "message": "Multiple balls to archive. Which one?",
                    "candidates": [bid for bid, _ in candidates],
                }))
                return
            else:
                print(json.dumps({"error": "no balls to archive"}))
                sys.exit(1)
        else:
            print(json.dumps({"error": "no football registry found"}))
            sys.exit(1)

    if not registry or ball_id not in registry.get("balls", {}):
        print(json.dumps({"error": f"ball not found: {ball_id}"}))
        sys.exit(1)

    ball_path = _ball_file(ball_id)
    if not ball_path.exists():
        print(json.dumps({"error": f"ball file not found: {ball_path}"}))
        sys.exit(1)

    data = _read_json(ball_path)
    data["state"] = "absorbed"

    # Move to archive
    archive_dir = _global_archive()
    archive_dir.mkdir(parents=True, exist_ok=True)
    desc = data.get("planner_payload", {}).get("thread", {}).get("description", "football")
    date = data.get("thrown_at", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = archive_dir / f"{date}-{_slug(desc)}-{ts}.json"
    atomic_write_json(str(dest), data)

    # Remove active ball file
    ball_path.unlink()

    # Update registry — remove from active balls
    del registry["balls"][ball_id]
    _write_registry(registry)

    # Clean up micro file
    micro = _ball_micro(ball_id)
    if micro.exists():
        micro.unlink()

    print(json.dumps({"archived": ball_id, "archived_to": str(dest)}))


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
    if bd:
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


def _pack_planner(args, bd, today):
    """Create a new ball with project location embedded."""
    registry = _read_registry() or {"schema_version": 1, "balls": {}}
    thread = json.loads(args.thread) if args.thread else {}
    desc = thread.get("description", "football")
    ball_id = _generate_ball_id(desc)
    target = getattr(args, 'target', 'instance') or 'instance'

    # Resolve project root from buffer dir
    project_root = ""
    buffer_dir = ""
    if bd:
        buffer_dir = str(bd)
        # Strip .claude/buffer to get project root
        bd_str = str(bd).replace('\\', '/')
        for suffix in ['/.claude/buffer/', '/.claude/buffer']:
            if bd_str.endswith(suffix):
                project_root = bd_str[:-len(suffix)]
                if '\\' in str(bd):
                    project_root = project_root.replace('/', '\\')
                break

    payload = {"thread": thread}
    if args.type == "heavy":
        payload["context"] = _build_planner_context(bd, args)

    ball_data = {
        "schema_version": 2,
        "mode": "football",
        "ball_id": ball_id,
        "state": "in_flight",
        "target": target,
        "throw_type": args.type,
        "thrown_by": "planner",
        "throw_count": 1,
        "thrown_at": today,
        "project_root": project_root,
        "buffer_dir": buffer_dir,
        "planner_payload": payload,
        "worker_output": {},
    }

    _global_footballs().mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(_ball_file(ball_id)), ball_data)

    # Update global registry
    registry["balls"][ball_id] = {
        "state": "in_flight",
        "target": target,
        "thrown_at": today,
        "project_root": project_root,
    }
    _write_registry(registry)
    print(json.dumps({
        "packed": True, "ball_id": ball_id,
        "project_root": project_root, "buffer_dir": buffer_dir,
    }))


def _pack_worker(args, today):
    """Worker return — packs output onto the ball in global storage."""
    ball_id = getattr(args, 'ball_id', None)
    if not ball_id:
        # Auto-detect: find the single caught ball with a micro file
        registry = _read_registry() or {}
        caught = _get_balls_by_state(registry, "caught")
        active = [(bid, info) for bid, info in caught
                  if _ball_micro(bid).exists()]
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

    ball_path = _ball_file(ball_id)
    micro_path = _ball_micro(ball_id)
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

    # Update global registry
    registry = _read_registry()
    if registry and ball_id in registry.get("balls", {}):
        registry["balls"][ball_id]["state"] = "returned"
        _write_registry(registry)

    # Clean up micro file
    if micro_path.exists():
        micro_path.unlink()

    print(json.dumps({"packed": True, "ball_id": ball_id, "throw_count": throw_count}))


def cmd_pack(args):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.side == "planner":
        bd = _resolve_buffer_or_exit(args.cwd)
        _pack_planner(args, bd, today)
    else:
        _pack_worker(args, today)


# ---------------------------------------------------------------------------
# Subcommand: unpack
# ---------------------------------------------------------------------------

def cmd_unpack(args):
    """Unpack a ball from global storage."""
    ball_id = getattr(args, 'ball_id', None)
    if not ball_id:
        # Auto-select: find single returned ball
        registry = _read_registry() or {}
        returned = _get_balls_by_state(registry, "returned")
        if len(returned) == 1:
            ball_id = returned[0][0]
        elif len(returned) > 1:
            print(json.dumps({
                "action": "choose",
                "message": "Multiple returned balls. Which one?",
                "returned": [{"ball_id": bid, "thrown_at": info.get("thrown_at")}
                             for bid, info in returned],
            }))
            return
        else:
            print(json.dumps({"error": "no returned balls to unpack"}))
            sys.exit(1)

    ball_path = _ball_file(ball_id)
    if not ball_path.exists():
        print(json.dumps({"error": f"ball not found: {ball_id}"}))
        sys.exit(1)
    data = _read_json(ball_path)
    print(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: catch
# ---------------------------------------------------------------------------

def cmd_catch(args):
    """Catch a ball from global storage.

    If --ball-id is given, catches that specific ball.
    If omitted, auto-selects if exactly one in_flight ball exists.
    If multiple are in_flight, returns the list for the skill to prompt.
    """
    registry = _read_registry()

    if registry is None:
        print(json.dumps({"error": "no footballs found — run /buffer:throw first"}))
        sys.exit(1)

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
            print(json.dumps({
                "action": "choose",
                "message": "Multiple balls in flight. Which one?",
                "in_flight": [
                    {"ball_id": bid, "thrown_at": info.get("thrown_at"),
                     "target": info.get("target"),
                     "project_root": info.get("project_root", ""),
                     "description": _read_json(_ball_file(bid))
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
    ball_path = _ball_file(ball_id)
    ball_data = _read_json(ball_path)
    if not ball_data:
        print(json.dumps({"error": f"ball file missing or corrupt: {ball_path}"}))
        sys.exit(1)

    # Set state to caught
    ball_data["state"] = "caught"
    atomic_write_json(str(ball_path), ball_data)

    # Update registry
    registry["balls"][ball_id]["state"] = "caught"
    _write_registry(registry)

    print(json.dumps({
        "caught": True,
        "ball_id": ball_id,
        "throw_type": ball_data.get("throw_type"),
        "throw_count": ball_data.get("throw_count"),
        "has_prior_progress": "prior_worker_progress" in ball_data,
        "project_root": ball_data.get("project_root", ""),
        "buffer_dir": ball_data.get("buffer_dir", ""),
        "planner_payload": ball_data.get("planner_payload", {}),
    }))


# ---------------------------------------------------------------------------
# Subcommand: intercept
# ---------------------------------------------------------------------------

def cmd_intercept(args):
    """Intercept a caught ball — pack partial progress back onto the ball
    and set it in_flight for a new worker to catch.
    """
    registry = _read_registry()
    if registry is None:
        print(json.dumps({"error": "no football registry found"}))
        sys.exit(1)

    ball_id = getattr(args, 'ball_id', None)
    balls = registry.get("balls", {})

    if not ball_id:
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
                     "description": _read_json(_ball_file(bid))
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

    ball_path = _ball_file(ball_id)
    ball_data = _read_json(ball_path)

    # Read micro file for partial progress
    micro_path = _ball_micro(ball_id)
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
        existing_prior = ball_data.get("prior_worker_progress", [])
        if isinstance(existing_prior, dict):
            existing_prior = [existing_prior]
        existing_prior.append(prior_progress)
        ball_data["prior_worker_progress"] = existing_prior
        micro_path.unlink()

    ball_data["state"] = "in_flight"
    ball_data["intercepted"] = True
    atomic_write_json(str(ball_path), ball_data)

    registry["balls"][ball_id]["state"] = "in_flight"
    _write_registry(registry)

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
    """Flag an item for trunk carry-over on the active micro file."""
    ball_id = getattr(args, 'ball_id', None)

    if not ball_id:
        # Auto-detect: find the single caught ball with a micro file
        registry = _read_registry() or {}
        caught = _get_balls_by_state(registry, "caught")
        active = [(bid, info) for bid, info in caught
                  if _ball_micro(bid).exists()]
        if len(active) == 1:
            ball_id = active[0][0]
        elif len(active) == 0:
            print(json.dumps({"error": "no active worker session found — specify --ball-id"}))
            sys.exit(1)
        else:
            print(json.dumps({
                "error": "multiple active balls — specify --ball-id",
                "active_balls": [bid for bid, _ in active],
            }))
            sys.exit(1)

    micro_path = _ball_micro(ball_id)
    micro = _read_json(micro_path)
    micro.setdefault("flagged_for_trunk", []).append({
        "type": args.type_flag,
        "content": json.loads(args.content),
        "rationale": args.rationale,
    })
    atomic_write_json(str(micro_path), micro)
    print(json.dumps({"flagged": True, "ball_id": ball_id, "total_flags": len(micro["flagged_for_trunk"])}))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="buffer:football lifecycle — global storage at ~/.claude/buffer/footballs/")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- status ---
    p = sub.add_parser("status", help="Show football status (global registry + optional project context)")
    p.add_argument("--cwd", help="Working directory for project buffer detection (optional)")
    p.set_defaults(func=cmd_status)

    # --- validate ---
    p = sub.add_parser("validate", help="Validate a football file against schema")
    p.add_argument("--football", required=True, help="Path to football JSON file")
    p.set_defaults(func=cmd_validate)

    # --- archive ---
    p = sub.add_parser("archive", help="Archive an absorbed/returned ball")
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.set_defaults(func=cmd_archive)

    # --- pack (throw) ---
    p = sub.add_parser("pack", help="Pack a football (planner throw or worker return)")
    p.add_argument("--side", choices=["planner", "worker"], required=True)
    p.add_argument("--type", choices=["heavy", "lite"], required=True)
    p.add_argument("--cwd", help="Working directory (planner needs this to find project buffer)")
    p.add_argument("--thread", help="Thread JSON (planner)")
    p.add_argument("--alpha-refs", dest="alpha_refs", help="Alpha refs JSON array (planner heavy)")
    p.add_argument("--completed", help="Completed items JSON array (worker lite)")
    p.add_argument("--changes", help="Changes JSON array (worker lite)")
    p.add_argument("--next-action", dest="next_action", help="Next action string (worker lite)")
    p.add_argument("--ball-id", dest="ball_id", default=None, help="Ball ID (worker return)")
    p.add_argument("--target", choices=["instance", "subagent"], default="instance")
    p.set_defaults(func=cmd_pack)

    # --- unpack ---
    p = sub.add_parser("unpack", help="Unpack a returned ball")
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.set_defaults(func=cmd_unpack)

    # --- catch ---
    p = sub.add_parser("catch", help="Catch an in-flight ball (worker side)")
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.set_defaults(func=cmd_catch)

    # --- intercept ---
    p = sub.add_parser("intercept", help="Intercept a caught ball (redirect to new worker)")
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.set_defaults(func=cmd_intercept)

    # --- flag ---
    p = sub.add_parser("flag", help="Flag an item for trunk carry-over")
    p.add_argument("--type", dest="type_flag",
                   choices=["alpha_entry", "forward_note", "decision", "open_thread"],
                   required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--rationale", required=True)
    p.add_argument("--ball-id", dest="ball_id", default=None)
    p.set_defaults(func=cmd_flag)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
