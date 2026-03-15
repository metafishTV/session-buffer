#!/usr/bin/env python3
"""
sigma-TAP Claude Code status line script.
Reads session JSON from stdin, outputs a compact status line.
"""

import json
import os
import sys


def read_handoff(buffer_dir):
    handoff_path = os.path.join(buffer_dir, "handoff.json")
    if not os.path.isfile(handoff_path):
        return None
    try:
        with open(handoff_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_git_branch(cwd):
    # Read git branch without subprocess: parse .git/HEAD directly.
    git_head = os.path.join(cwd, ".git", "HEAD")
    if not os.path.isfile(git_head):
        # Walk up to find repo root.
        parts = cwd.replace("\\", "/").split("/")
        for i in range(len(parts) - 1, 0, -1):
            candidate = "/".join(parts[:i]) + "/.git/HEAD"
            if os.path.isfile(candidate):
                git_head = candidate
                break
        else:
            return None
    try:
        with open(git_head, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        # Detached HEAD — show short hash.
        return content[:7]
    except Exception:
        return None


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    # Context pressure (headroom check)
    used_pct = data.get('used_percentage')

    cwd = data.get("cwd") or data.get("workspace", {}).get("current_dir") or os.getcwd()
    # Normalise Windows backslashes.
    cwd = cwd.replace("\\", "/")

    buffer_dir = os.path.join(cwd, ".claude", "buffer").replace("\\", "/")

    handoff = read_handoff(buffer_dir)

    parts = []

    if handoff is None:
        parts.append("buf:off")
    else:
        # 1. Buffer mode (full/lite).
        buf_mode = handoff.get("buffer_mode", "?")
        parts.append(f"buf:{buf_mode}")

        # 2. Active work phase.
        active_work = handoff.get("active_work") or {}
        phase = active_work.get("current_phase")
        if phase:
            # Truncate long phase descriptions to first 20 chars.
            short = phase if len(phase) <= 20 else phase[:18] + ".."
            parts.append(f"phase:{short}")

        # 3. Open threads count.
        threads = handoff.get("open_threads") or []
        if threads:
            parts.append(f"threads:{len(threads)}")

        # 4. Last handoff date.
        meta = handoff.get("session_meta") or {}
        date = meta.get("date")
        if date:
            parts.append(f"saved:{date}")

        # 5. Distill active.
        distill_marker = os.path.join(buffer_dir, ".distill_active")
        if os.path.isfile(distill_marker):
            parts.append("distill:active")

        # 6. Compact marker (compaction just happened, not yet recovered).
        compact_marker = os.path.join(buffer_dir, ".compact_marker")
        if os.path.isfile(compact_marker):
            parts.append("compacted")

        # 7. Sigma regime.
        sigma_regime = os.path.join(buffer_dir, ".sigma_regime")
        if os.path.isfile(sigma_regime):
            parts.append("regime:on")

    # 7. Git branch (always shown).
    branch = get_git_branch(cwd)
    if branch:
        parts.append(branch)

    # Context pressure indicator (after all other segments)
    if used_pct is not None:
        try:
            pct = float(used_pct)
            pct_int = int(pct)
            if pct >= 93:
                parts.append(f"ctx:{pct_int}%!!")
            elif pct >= 85:
                parts.append(f"ctx:{pct_int}%!")
            elif pct >= 70:
                parts.append(f"ctx:{pct_int}%")
        except (ValueError, TypeError):
            pass

    print(" | ".join(parts))


if __name__ == "__main__":
    main()
