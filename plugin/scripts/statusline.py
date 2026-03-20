#!/usr/bin/env python3
"""
Session Buffer — Claude Code Status Line

Two-line ANSI-colored statusline showing model tier, buffer state, git info,
context pressure, cost, and football state. Also performs headroom tier
detection and writes model state for other scripts to read.

Receives session JSON from Claude Code via stdin.
Must never crash — all reads wrapped in try/except.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time

# Load sibling modules via importlib (fail-silent — statusline must never crash)
_script_dir = os.path.dirname(os.path.abspath(__file__))

_telemetry_mod = None
try:
    _spec = importlib.util.spec_from_file_location(
        'telemetry', os.path.join(_script_dir, 'telemetry.py'))
    _telemetry_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_telemetry_mod)
except Exception:
    pass

_buffer_utils = None
try:
    _spec = importlib.util.spec_from_file_location(
        'buffer_utils', os.path.join(_script_dir, 'buffer_utils.py'))
    _buffer_utils = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_buffer_utils)
except Exception:
    pass

# ANSI colors
G = '\033[32m'   # green
Y = '\033[33m'   # yellow
R = '\033[31m'   # red
C = '\033[36m'   # cyan
D = '\033[2m'    # dim
B = '\033[1m'    # bold
Z = '\033[0m'    # reset

GIT_CACHE_DIR = os.environ.get('TEMP', '/tmp')
GIT_CACHE_MAX_AGE = 5  # seconds


def _git_cache_path(cwd):
    """Per-project git cache file to avoid cross-contamination in multi-session setups."""
    import hashlib
    cwd_hash = hashlib.md5(cwd.encode()).hexdigest()[:8]
    return os.path.join(GIT_CACHE_DIR, f'cc-statusline-git-{cwd_hash}')


def get_git_info(cwd):
    """Get branch + staged/modified counts, cached to avoid lag."""
    cache_file = _git_cache_path(cwd)
    try:
        age = time.time() - os.path.getmtime(cache_file) if os.path.exists(cache_file) else 999
    except OSError:
        age = 999

    if age <= GIT_CACHE_MAX_AGE:
        try:
            with open(cache_file, encoding='utf-8') as f:
                parts = f.read().strip().split('|')
            if len(parts) == 3:
                return parts[0], int(parts[1] or 0), int(parts[2] or 0)
        except Exception:
            pass

    try:
        subprocess.check_output(['git', '-C', cwd, 'rev-parse', '--git-dir'],
                                stderr=subprocess.DEVNULL)
        branch = subprocess.check_output(
            ['git', '-C', cwd, 'branch', '--show-current'],
            text=True, stderr=subprocess.DEVNULL).strip()
        staged = subprocess.check_output(
            ['git', '-C', cwd, 'diff', '--cached', '--numstat'],
            text=True, stderr=subprocess.DEVNULL).strip()
        modified = subprocess.check_output(
            ['git', '-C', cwd, 'diff', '--numstat'],
            text=True, stderr=subprocess.DEVNULL).strip()
        s = len(staged.split('\n')) if staged else 0
        m = len(modified.split('\n')) if modified else 0
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(f"{branch}|{s}|{m}")
        except OSError:
            pass
        return branch, s, m
    except Exception:
        return '', 0, 0


def get_buffer_state(cwd):
    """Read buffer state using find_buffer_dir (registry-based, not CWD-relative)."""
    buffer_dir = None
    if _buffer_utils:
        buffer_dir = _buffer_utils.find_buffer_dir(cwd)
    if not buffer_dir:
        # Fallback: CWD-relative
        candidate = os.path.join(cwd, '.claude', 'buffer')
        if os.path.isdir(candidate):
            buffer_dir = candidate

    if not buffer_dir:
        return '--', 0, False, False, buffer_dir

    handoff_path = os.path.join(buffer_dir, 'handoff.json')
    if not os.path.isfile(handoff_path):
        return '--', 0, False, False, buffer_dir

    try:
        with open(handoff_path, 'r', encoding='utf-8') as f:
            h = json.load(f)
        threads = len(h.get('open_threads', []))
    except Exception:
        threads = 0

    session_marker = os.path.join(buffer_dir, '.session_active')
    if os.path.isfile(session_marker):
        try:
            with open(session_marker, 'r', encoding='utf-8') as f:
                marker = json.load(f)
            off_count = marker.get('off_count', 0)
        except Exception:
            off_count = 0
        mode = f'off x{off_count}' if off_count > 0 else 'on'
    else:
        mode = 'saved'

    distill = os.path.isfile(os.path.join(buffer_dir, '.distill_active'))
    compacted = os.path.isfile(os.path.join(buffer_dir, '.compact_marker'))
    return mode, threads, distill, compacted, buffer_dir


def get_football_summary():
    """Get active football count from global registry."""
    if not _buffer_utils:
        return 0, 0
    try:
        reg = _buffer_utils.read_football_registry()
        balls = reg.get('balls', {})
        in_flight = sum(1 for b in balls.values() if b.get('state') == 'in_flight')
        caught = sum(1 for b in balls.values() if b.get('state') == 'caught')
        return in_flight, caught
    except Exception:
        return 0, 0


def _detect_headroom(buffer_dir, context_window):
    """Detect tier crossings and emit telemetry. Returns (used_pct, tier)."""
    if not context_window or not _telemetry_mod or not buffer_dir:
        return None, None

    used_pct = context_window.get('used_percentage')
    if used_pct is None:
        return None, None

    try:
        used_pct = float(used_pct)
    except (ValueError, TypeError):
        return None, None

    current_tier = _telemetry_mod.tier_from_percentage(used_pct)

    tier_path = os.path.join(buffer_dir, '.sigma_headroom_tier')
    last_tier = None
    try:
        with open(tier_path, 'r', encoding='utf-8') as f:
            last_tier = f.read().strip() or None
    except (FileNotFoundError, OSError):
        pass

    if current_tier != last_tier:
        try:
            if current_tier is not None:
                with open(tier_path, 'w', encoding='utf-8') as f:
                    f.write(current_tier)
            else:
                try:
                    os.remove(tier_path)
                except FileNotFoundError:
                    pass
        except OSError:
            pass

        if current_tier is not None:
            cur_usage = context_window.get('current_usage') or {}
            cr = None
            cache_read = cur_usage.get('cache_read_input_tokens')
            cache_creation = cur_usage.get('cache_creation_input_tokens')
            input_tok = cur_usage.get('input_tokens')
            if cache_read is not None and cache_creation is not None and input_tok is not None:
                cr = _telemetry_mod.cache_ratio(
                    float(cache_read), float(cache_creation), float(input_tok))
            event = {
                'event': 'headroom_warning',
                'context_pct': int(used_pct),
                'tier': current_tier,
            }
            if cr is not None:
                event['cache_ratio'] = round(cr, 2)
            _telemetry_mod.emit(buffer_dir, event)

    return used_pct, current_tier


def make_bar(pct, width=10):
    """Context bar with color thresholds."""
    color = R if pct >= 90 else Y if pct >= 70 else G
    filled = pct * width // 100
    empty = width - filled
    return f"{color}{'#' * filled}{'-' * empty}{Z}"


def fmt_duration(ms):
    s = ms // 1000
    return f"{s // 60}m {s % 60}s"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("[statusline: no data]")
        return

    # Session data from Claude Code stdin JSON
    model_name = data.get('model', {}).get('display_name', '?')
    cwd = data.get('cwd', '') or data.get('workspace', {}).get('current_dir', '')
    ctx = data.get('context_window', {})
    pct = int(ctx.get('used_percentage', 0) or 0)
    window_size = ctx.get('context_window_size', 200000)

    cost_data = data.get('cost', {})
    cost = cost_data.get('total_cost_usd', 0) or 0
    duration = cost_data.get('total_duration_ms', 0) or 0
    lines_add = cost_data.get('total_lines_added', 0) or 0
    lines_rm = cost_data.get('total_lines_removed', 0) or 0

    # Cache hit ratio
    usage = ctx.get('current_usage') or {}
    cache_read = usage.get('cache_read_input_tokens', 0) or 0
    cache_write = usage.get('cache_creation_input_tokens', 0) or 0
    input_tokens = usage.get('input_tokens', 0) or 0
    total_input = cache_read + cache_write + input_tokens
    cache_pct = int(cache_read * 100 / total_input) if total_input > 0 else 0

    # Model tier — compute and persist for other scripts
    tier = 'full'
    if _buffer_utils:
        tier = _buffer_utils.model_tier_from_name(model_name)
        _buffer_utils.write_model_tier(model_name, tier)

    # Git info (cached)
    branch, staged, modified = get_git_info(cwd) if cwd else ('', 0, 0)

    # Buffer state (registry-based discovery)
    buf_mode, threads, distill_active, was_compacted, buffer_dir = (
        get_buffer_state(cwd) if cwd else ('off', 0, False, False, None))

    # Football state
    fb_in_flight, fb_caught = get_football_summary()

    # Headroom detection (writes tier file + telemetry)
    _detect_headroom(buffer_dir, ctx)

    # === Line 1: identity + git + buffer + football ===
    dir_name = os.path.basename(cwd) if cwd else '?'
    tier_label = f" ({tier})" if tier != 'full' else ''
    parts1 = [f"{C}[{model_name}{tier_label}]{Z} {dir_name}"]

    if branch:
        git_str = f"{G}{branch}{Z}"
        if staged > 0:
            git_str += f" {G}+{staged}{Z}"
        if modified > 0:
            git_str += f" {Y}~{modified}{Z}"
        parts1.append(git_str)

    buf_str = f"buf:{buf_mode}"
    if threads > 0:
        buf_str += f" thr:{threads}"
    if distill_active:
        buf_str += f" {Y}distill{Z}"
    if was_compacted:
        buf_str += f" {R}compacted{Z}"
    parts1.append(buf_str)

    fb_total = fb_in_flight + fb_caught
    if fb_total > 0:
        parts1.append(f"fb:{fb_total}")

    # === Line 2: context + cost + duration + lines ===
    bar = make_bar(pct)
    if pct >= 90:
        ctx_str = f"{bar} {R}{B}{pct}%{Z}"
    elif pct >= 70:
        ctx_str = f"{bar} {Y}{pct}%{Z}"
    else:
        ctx_str = f"{bar} {pct}%"

    if window_size > 200000:
        ctx_str += f" {C}1M{Z}"

    if total_input > 0:
        ctx_str += f" {D}cache:{cache_pct}%{Z}"

    parts2 = [ctx_str]
    parts2.append(f"{Y}${cost:.2f}{Z}")
    parts2.append(fmt_duration(duration))

    if lines_add > 0 or lines_rm > 0:
        parts2.append(f"{G}+{lines_add}{Z}{R}-{lines_rm}{Z}")

    exceeds_200k = data.get('exceeds_200k_tokens', False)
    if exceeds_200k:
        parts2.append(f"{R}!200k{Z}")

    sep = f" {D}|{Z} "
    print(sep.join(parts1))
    print(sep.join(parts2))


if __name__ == '__main__':
    main()
