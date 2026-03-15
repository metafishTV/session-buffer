#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""buffer_football.py — football lifecycle for buffer:throw / buffer:catch"""

import argparse
import importlib.util
import json
import os
import re
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
    stale = False
    if fp.exists():
        with open(fp) as f:
            data = json.load(f)
        football_state = data.get("state")
        throw_type = data.get("throw_type")
        if football_state == "caught":
            thrown_at = data.get("thrown_at", "")
            try:
                age = (datetime.now() - datetime.strptime(thrown_at, "%Y-%m-%d")).days
                stale = age >= 3
            except ValueError:
                pass
    result = {"session_type": session_type, "football_state": football_state,
              "throw_type": throw_type, "buffer_dir": str(bd)}
    if stale:
        result["stale"] = True
    print(json.dumps(result))


def cmd_validate(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"valid": False, "error": f"not found: {fp}"}))
        sys.exit(1)
    import jsonschema
    try:
        with open(fp) as f:
            data = json.load(f)
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(data, schema)
        print(json.dumps({"valid": True}))
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
    data["state"] = "absorbed"
    desc = data.get("planner_payload", {}).get("thread", {}).get("description", "football")
    date = data.get("thrown_at", datetime.now().strftime("%Y-%m-%d"))
    archive_dir = fp.parent / "footballs"
    archive_dir.mkdir(exist_ok=True)
    dest = archive_dir / f"{date}-{_slug(desc)}.json"
    with open(dest, "w") as f:
        json.dump(data, f, indent=2)
    fp.unlink()
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
