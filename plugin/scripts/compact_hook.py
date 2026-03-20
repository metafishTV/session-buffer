#!/usr/bin/env python3
"""
Session Buffer — Compact Hook

Handles context preservation across Claude Code compaction events.

Pre-compact: Autosaves hot layer and writes .compact_marker file.
Post-compact: If marker exists, injects sigma trunk summary into AI context.

Called by hooks/hooks.json via the plugin system.
Usage: run_python compact_hook.py [pre-compact|post-compact]
"""

import sys
import os
import io
import json
from pathlib import Path
from datetime import datetime, timezone

# Force UTF-8 on Windows (buffer data contains unicode)
# Guard: only wrap when running as main script, not when imported by sigma_hook
if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_buffer_utils_mod = None
_read_model_tier = None

def _load_buffer_utils():
    global _buffer_utils_mod, _read_model_tier
    if _buffer_utils_mod is not None:
        return _buffer_utils_mod
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _buffer_utils_mod = mod
        _read_model_tier = getattr(mod, 'read_model_tier', None)
        return mod
    except Exception:
        return None


def _get_tier():
    """Get current model tier from state file written by statusline."""
    _load_buffer_utils()  # idempotent — fast-path if already loaded
    if _read_model_tier:
        _, tier = _read_model_tier()
        return tier
    return 'full'


def find_buffer_dir(start_path):
    """Find buffer dir via registry lookup + git-guarded walk-up.

    Delegates to buffer_utils.find_buffer_dir. See buffer_utils.py for details.
    """
    try:
        utils = _load_buffer_utils()
        if utils:
            return utils.find_buffer_dir(start_path)
    except Exception:
        pass
    # Fallback: original walk-up (no git guard) if buffer_utils fails
    current = os.path.abspath(start_path)
    while True:
        candidate = os.path.join(current, '.claude', 'buffer', 'handoff.json')
        if os.path.exists(candidate):
            return os.path.join(current, '.claude', 'buffer')
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def read_json(path):
    """Read JSON file, return dict or None. BOM-safe (utf-8-sig)."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def write_json(path, data):
    """Write dict to JSON file (atomic: temp-file-then-rename)."""
    import tempfile
    dir_name = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_hook_input():
    """Read hook input JSON from stdin (non-blocking)."""
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            return json.loads(stdin_data)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def generate_directive_context(buffer_dir, tier='full'):
    """Generate compaction directive context from compact-directives.md and session depth.

    Tier scaling:
      full:     All sections (on-disk, threads, vocabulary, depth).
      moderate: Skip vocabulary section.
      lean:     Only active threads + session depth. Skip on-disk paths, vocabulary.

    Returns a formatted string to append to the post-compaction injection.
    Returns empty string if no directives file exists or it's empty.
    """
    directives_path = os.path.join(buffer_dir, 'compact-directives.md')

    # Read directives file
    try:
        with open(directives_path, 'r', encoding='utf-8-sig') as f:
            directives_text = f.read().strip()
    except (FileNotFoundError, OSError):
        return ''

    if not directives_text:
        return ''

    # Parse sections from the markdown
    sections = {}
    current_section = None
    current_lines = []

    for line in directives_text.split('\n'):
        if line.startswith('## '):
            if current_section:
                sections[current_section] = '\n'.join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = '\n'.join(current_lines).strip()

    # Read session depth from .session_active
    # off_count = number of /buffer:off save cycles this session, used as depth proxy
    depth = 0
    session_active_path = os.path.join(buffer_dir, '.session_active')
    try:
        with open(session_active_path, 'r', encoding='utf-8-sig') as f:
            session_data = json.load(f)
            depth = int(session_data.get('off_count', 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        depth = 0

    # Build output — only renders On Disk, Active Threads, Session Vocabulary,
    # and Session Depth. "Already Persisted" stays in the directives file for
    # human reference but is not injected (redundant with On Disk paths).
    lines = []
    lines.append('--- COMPACTION DIRECTIVES ---')
    lines.append('')

    # On Disk section (skip for lean — model can read files on demand)
    if tier != 'lean':
        on_disk = sections.get('On Disk', '')
        if on_disk:
            lines.append('CONTEXT ON DISK (recoverable via tools):')
            for item in on_disk.split('\n'):
                item = item.strip()
                if item.startswith('- '):
                    lines.append(item)
            lines.append('')

    # Active Threads section (always shown)
    threads = sections.get('Active Threads', '')
    if threads:
        lines.append('ACTIVE THREADS:')
        for item in threads.split('\n'):
            item = item.strip()
            if item.startswith('- '):
                lines.append(item)
        lines.append('')

    # Session Vocabulary section (skip for moderate and lean)
    if tier == 'full':
        vocab = sections.get('Session Vocabulary', '')
        if vocab and vocab.strip():
            lines.append('SESSION VOCABULARY:')
            for item in vocab.split('\n'):
                item = item.strip()
                if item.startswith('- '):
                    lines.append(item)
            lines.append('')

    # Session depth and adaptive guidance
    lines.append(f'SESSION DEPTH: {depth} save cycles.')
    if depth <= 1:
        lines.append(
            'Full thread detail and rationale should be available '
            'in the compaction summary above.'
        )
    elif depth == 2:
        lines.append(
            'This is a deep session. Prioritize continuity and active focus. '
            'Details are in git and the buffer trunk.'
        )
    else:
        lines.append(
            'Significant context recycling. Focus on: what we are doing, why, '
            'and the next step. All detail is on disk.'
        )
    lines.append('')

    lines.append(
        'The buffer plugin has re-injected essential context above. '
        'Use /buffer:on if you need full trunk reconstruction.'
    )

    return '\n'.join(lines)


def detect_layer_limits(cwd):
    """Check project configs for hot-max, warm-max, cold-max overrides.

    Checks (later source wins):
      1. .claude/skills/buffer/on.md (project skill config)
      2. .claude/buffer.local.md (userconfig)

    Returns (hot_max, warm_max, cold_max) with defaults for any not overridden.
    """
    import re
    limits = {'hot': 200, 'warm': 500, 'cold': 500}
    for filepath in [
        os.path.join(cwd, '.claude', 'skills', 'buffer', 'on.md'),
        os.path.join(cwd, '.claude', 'buffer.local.md'),
    ]:
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            for layer in ('hot', 'warm', 'cold'):
                match = re.search(
                    rf'{layer}[_\s-]*max[^:\d]*:?\s*(\d+)', content, re.IGNORECASE
                )
                if match:
                    limits[layer] = int(match.group(1))
        except OSError:
            pass
    return limits['hot'], limits['warm'], limits['cold']


# ---------------------------------------------------------------------------
# Pre-compact: autosave hot layer before compaction
# ---------------------------------------------------------------------------

def cmd_pre_compact(hook_input):
    """Save hot layer state and write a compact marker before context is compressed."""
    cwd = hook_input.get('cwd', os.getcwd())
    buffer_dir = find_buffer_dir(cwd)

    if not buffer_dir:
        sys.exit(0)  # No buffer -> allow compaction

    hot_path = os.path.join(buffer_dir, 'handoff.json')
    hot = read_json(hot_path)

    if not hot:
        sys.exit(0)  # No valid hot layer -> allow compaction

    # Validate hot layer structure (warn but don't block — PreCompact cannot block)
    if not isinstance(hot, dict) or 'schema_version' not in hot:
        print("compact_hook: hot layer corrupt or missing schema_version", file=sys.stderr)
        sys.exit(0)  # Cannot block compaction, just skip

    # Update date
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if 'session_meta' not in hot:
        hot['session_meta'] = {}
    hot['session_meta']['date'] = today

    # Try to capture current HEAD commit
    try:
        import subprocess
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5, cwd=cwd
        )
        if result.returncode == 0:
            hot['session_meta']['commit'] = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Append compaction marker to natural_summary
    summary = hot.get('natural_summary', '')
    if '[compacted]' not in summary:
        hot['natural_summary'] = (
            summary + ' [compacted] Context compacted -- '
            'hot layer preserved by pre-compact hook.'
        )

    # Write marker file so post-compact knows compaction occurred
    marker_path = os.path.join(buffer_dir, '.compact_marker')
    try:
        with open(marker_path, 'w') as f:
            f.write(today)
    except OSError:
        pass

    # Save hot layer
    write_json(hot_path, hot)

    # Emit telemetry event (Layer 3 — fail-silent)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        _tel_spec = importlib.util.spec_from_file_location(
            'telemetry', os.path.join(script_dir, 'telemetry.py'))
        _tel_mod = importlib.util.module_from_spec(_tel_spec)
        _tel_spec.loader.exec_module(_tel_mod)

        # Read context pressure from hook input
        used_pct = hook_input.get('used_percentage')
        context_pct = int(float(used_pct)) if used_pct is not None else None

        # Compute cache ratio
        cr = None
        cache_read = hook_input.get('cache_read_input_tokens')
        cache_creation = hook_input.get('cache_creation_input_tokens')
        input_tok = hook_input.get('input_tokens')
        if cache_read is not None and cache_creation is not None and input_tok is not None:
            cr = round(_tel_mod.cache_ratio(
                float(cache_read), float(cache_creation), float(input_tok)), 2)

        # Read session depth
        off_count = 0
        session_active_path = os.path.join(buffer_dir, '.session_active')
        try:
            with open(session_active_path, 'r', encoding='utf-8-sig') as f:
                sa = json.load(f)
                off_count = int(sa.get('off_count', 0))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            pass

        # Count open threads
        threads = hot.get('open_threads', [])
        thread_count = len(threads) if isinstance(threads, list) else 0

        # Read headroom tier
        headroom_tier = None
        tier_path = os.path.join(buffer_dir, '.sigma_headroom_tier')
        try:
            with open(tier_path, 'r', encoding='utf-8-sig') as f:
                headroom_tier = f.read().strip() or None
        except (FileNotFoundError, OSError):
            pass

        # Read model tier
        _load_buffer_utils()
        model_tier = _get_tier()

        event = {
            'event': 'compact',
            'threads': thread_count,
            'off_count': off_count,
            'headroom_tier': headroom_tier,
            'model_tier': model_tier,
        }
        if context_pct is not None:
            event['context_pct'] = context_pct
        if cr is not None:
            event['cache_ratio'] = cr

        _tel_mod.emit(buffer_dir, event)
    except Exception:
        pass  # Fail-silent: telemetry must never block compaction

    sys.exit(0)  # Allow compaction


# ---------------------------------------------------------------------------
# Post-compact: inject buffer context into the post-compaction instance
# ---------------------------------------------------------------------------

def detect_distill_in_progress(cwd):
    """Check for signs of an active distillation that was interrupted by compaction.

    Looks for ephemeral files the distill process creates during extraction:
    - _distill_text.txt (extracted text from PDF/web/image/recording)
    - _distill_scan.py (scan script)
    - _distill_extract.py (extraction script)
    - _distill_figures/ (figure extraction output)
    Also checks for very recently modified distillation .md files.
    """
    result = {}
    repo = Path(cwd)

    # Check for extracted text file (strongest signal)
    text_file = repo / '_distill_text.txt'
    if text_file.exists():
        result['extracted_text'] = str(text_file)
        # Read first few lines to identify the source
        try:
            with open(text_file, 'r', encoding='utf-8-sig', errors='replace') as f:
                header_lines = []
                for i, line in enumerate(f):
                    if i >= 10:
                        break
                    header_lines.append(line.rstrip())
                result['text_preview'] = header_lines
                # Count total lines for size indication
                f.seek(0)
                result['text_lines'] = sum(1 for _ in f)
        except OSError:
            pass

    # Check for scan/extract scripts (means extraction phase)
    for script_name in ['_distill_scan.py', '_distill_extract.py']:
        script = repo / script_name
        if script.exists():
            result.setdefault('ephemeral_scripts', []).append(script_name)

    # Check for figure extraction output
    fig_dir = repo / '_distill_figures'
    if fig_dir.exists() and fig_dir.is_dir():
        try:
            fig_count = len(list(fig_dir.glob('*.png')))
            result['figures_extracted'] = fig_count
        except OSError:
            pass

    # Check for distillation directory and very recent .md files (last 10 min)
    import time
    now = time.time()
    distill_dirs = [
        repo / 'docs' / 'references' / 'distilled',
        repo / 'docs' / 'distilled',
        repo / 'distilled',
    ]
    for d in distill_dirs:
        if d.exists():
            try:
                for md in d.glob('*.md'):
                    mtime = md.stat().st_mtime
                    distill_window = int(os.environ.get(
                        'BUFFER_DISTILL_WINDOW', 600))
                    if now - mtime < distill_window:  # Default: 10 minutes
                        result.setdefault('recent_distillations', []).append({
                            'file': md.name,
                            'seconds_ago': int(now - mtime)
                        })
            except OSError:
                pass
            break  # Only check first existing dir

    # Check for project distill skill config
    project_skill = repo / '.claude' / 'skills' / 'distill' / 'SKILL.md'
    if project_skill.exists():
        result['has_project_skill'] = True

    return result if result else None


def build_compact_summary(hot, buffer_dir, hot_max, warm_max, cold_max, tier='full'):
    """Build a concise buffer summary for post-compaction context injection.

    Tier scaling:
      full:     All sections. Current behavior.
      moderate: Skip narrative. Trim briefing (20->10 lines), remarks (5->3), questions (3->2).
      lean:     Session state, active work, orientation, open threads, natural summary, layer sizes only.

    Shorter than a full buffer read -- focuses on orientation and active work
    state rather than deep reference material.
    """
    lines = []
    lines.append("POST-COMPACTION SIGMA TRUNK RECOVERY")
    lines.append("=" * 40)
    lines.append("")
    lines.append(
        "Context compaction detected. The buffer system preserved hot-layer "
        "state before compaction. Below is the reconstructed context."
    )
    lines.append("")

    # --- Session state ---
    meta = hot.get('session_meta', {})
    mode = hot.get('buffer_mode', 'unknown')
    lines.append(f"Mode: {mode} | Schema: v{hot.get('schema_version', '?')}")
    lines.append(
        f"Last: {meta.get('date', '?')} | "
        f"Commit: {meta.get('commit', '?')} ({meta.get('branch', '?')}) | "
        f"Tests: {meta.get('tests', '?')}"
    )
    lines.append("")

    # --- Active work ---
    aw = hot.get('active_work', {})
    if aw:
        lines.append("## Active Work")
        lines.append(f"Phase: {aw.get('current_phase', '?')}")
        completed = aw.get('completed_this_session', [])
        if completed:
            for c in completed[-3:]:  # Last 3 only
                lines.append(f"  done: {c}")
            if len(completed) > 3:
                lines.append(f"  ... and {len(completed) - 3} more")
        ip = aw.get('in_progress')
        if ip:
            lines.append(f"In progress: {ip}")
        blocked = aw.get('blocked_by')
        if blocked:
            lines.append(f"BLOCKED: {blocked}")
        na = aw.get('next_action')
        if na:
            lines.append(f"Next: {na}")
        lines.append("")

    # --- Orientation (core insight only) ---
    orient = hot.get('orientation', {})
    if orient:
        lines.append("## Orientation")
        ci = orient.get('core_insight', '')
        if ci:
            lines.append(ci)
        pw = orient.get('practical_warning', '')
        if pw:
            lines.append(f"WARNING: {pw}")
        lines.append("")

    # --- Open threads ---
    threads = hot.get('open_threads', [])
    if threads:
        lines.append(f"## Open Threads ({len(threads)})")
        for t in threads:
            status = t.get('status', '?')
            desc = t.get('thread', '?')
            ref = t.get('ref', '')
            # Lean: status + thread only, no refs
            if tier == 'lean':
                lines.append(f"  [{status}] {desc}")
            else:
                ref_str = f" -> {ref}" if ref else ""
                lines.append(f"  [{status}] {desc}{ref_str}")
        lines.append("")

    # --- Recent decisions ---
    decisions = hot.get('recent_decisions', [])
    if decisions:
        limit = 2 if tier == 'lean' else 3
        lines.append(f"## Recent Decisions ({len(decisions)})")
        for d in decisions[-limit:]:
            lines.append(f"  {d.get('what', '?')} -> {d.get('chose', '?')}")
        if len(decisions) > limit:
            lines.append(f"  ... and {len(decisions) - limit} more")
        lines.append("")

    # --- Instance notes (skip for lean) ---
    if tier != 'lean':
        notes = hot.get('instance_notes', {})
        if notes:
            lines.append("## Instance Notes")
            remarks = notes.get('remarks', [])
            remarks_limit = 3 if tier == 'moderate' else 5
            for r in remarks[:remarks_limit]:
                lines.append(f"  * {r}")
            if len(remarks) > remarks_limit:
                lines.append(f"  ... and {len(remarks) - remarks_limit} more")
            oq = notes.get('open_questions', [])
            if oq:
                oq_limit = 2 if tier == 'moderate' else 3
                for q in oq[:oq_limit]:
                    lines.append(f"  ? {q}")
            lines.append("")

    # --- Session briefing (skip for lean) ---
    if tier != 'lean':
        briefing_path = os.path.join(buffer_dir, 'briefing.md')
        if os.path.isfile(briefing_path):
            try:
                with open(briefing_path, 'r', encoding='utf-8-sig') as f:
                    briefing_text = f.read().strip()
                if briefing_text:
                    lines.append("## Session Briefing (from last handoff)")
                    briefing_lines = briefing_text.split('\n')
                    max_lines = 10 if tier == 'moderate' else 20
                    for bl in briefing_lines[:max_lines]:
                        lines.append(bl)
                    if len(briefing_lines) > max_lines:
                        lines.append(
                            f"... ({len(briefing_lines) - max_lines} more lines "
                            "in .claude/buffer/briefing.md)"
                        )
                    lines.append("")
            except (IOError, UnicodeDecodeError):
                pass

    # --- Recent beta narrative (skip for moderate and lean) ---
    if tier == 'full':
        beta_path = os.path.join(buffer_dir, 'beta', 'narrative.jsonl')
        if os.path.isfile(beta_path):
            try:
                beta_entries = []
                with open(beta_path, 'r', encoding='utf-8-sig') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                e = json.loads(line)
                                if e.get('r', 0) >= 0.5 and not e.get('promoted'):
                                    beta_entries.append(e)
                            except json.JSONDecodeError:
                                pass
                if beta_entries:
                    lines.append("## Session Narrative (high-relevance)")
                    for e in beta_entries[-5:]:
                        tick = e.get('tick', '?')
                        r_val = e.get('r', 0)
                        text = e.get('text', '')
                        lines.append(f"  [{tick}] (r={r_val:.1f}) {text}")
                    lines.append("")
            except (IOError, UnicodeDecodeError):
                pass

    # --- Natural summary ---
    ns = hot.get('natural_summary', '')
    if ns:
        lines.append("## Natural Summary")
        lines.append(ns)
        lines.append("")

    # --- Concept map digest (skip for lean) ---
    if tier != 'lean':
        cmd = hot.get('concept_map_digest', {})
        if cmd:
            meta_cm = cmd.get('_meta', {})
            total = meta_cm.get('total_entries', '?')
            flagged = cmd.get('flagged', [])
            lines.append(f"## Concept Map: {total} entries")
            if flagged:
                lines.append(f"FLAGGED: {', '.join(str(f) for f in flagged)}")
            recent = cmd.get('recent_changes', [])
            if recent:
                lines.append(f"Recent changes: {len(recent)} entries")
            lines.append("")

    # --- Convergence web digest (skip for lean) ---
    if tier != 'lean':
        cwd_digest = hot.get('convergence_web_digest', {})
        if cwd_digest:
            cw_meta = cwd_digest.get('_meta', {})
            cw_total = cw_meta.get('total_entries', '?')
            lines.append(f"## Convergence Web: {cw_total} entries")
            lines.append("")

    # --- Memory config (skip for lean) ---
    if tier != 'lean':
        mc = hot.get('memory_config', {})
        if mc:
            lines.append(f"## Memory: integration={mc.get('integration', '?')}")
            lines.append(f"Path: {mc.get('path', '?')}")
            lines.append("")

    # --- Layer sizes ---
    hot_lines = len(json.dumps(hot, indent=2).split('\n'))
    warm_path = os.path.join(buffer_dir, hot.get('warm_ref', 'handoff-warm.json'))
    cold_path = os.path.join(buffer_dir, hot.get('cold_ref', 'handoff-cold.json'))

    warm_lines = 0
    cold_lines = 0
    try:
        with open(warm_path, 'r', encoding='utf-8-sig') as f:
            warm_lines = len(f.readlines())
    except (FileNotFoundError, OSError):
        pass
    try:
        with open(cold_path, 'r', encoding='utf-8-sig') as f:
            cold_lines = len(f.readlines())
    except (FileNotFoundError, OSError):
        pass

    # --- Alpha bin status ---
    alpha_idx_path = os.path.join(buffer_dir, 'alpha', 'index.json')
    alpha_summary = ''
    if os.path.exists(alpha_idx_path):
        try:
            with open(alpha_idx_path, 'r', encoding='utf-8-sig') as f:
                alpha_idx = json.load(f)
            alpha_s = alpha_idx.get('summary', {})
            fw = alpha_s.get('total_framework', 0)
            cs = alpha_s.get('total_cross_source', 0)
            cw = alpha_s.get('total_convergence_web', 0)
            sources = alpha_s.get('total_sources', 0)
            alpha_summary = f" | Alpha: {fw + cs + cw} refs ({sources} sources)"
        except (json.JSONDecodeError, OSError):
            alpha_summary = ' | Alpha: present (index unreadable)'

    lines.append(f"## Layer Sizes: Hot {hot_lines}/{hot_max} | Warm {warm_lines}/{warm_max} | Cold {cold_lines}/{cold_max}{alpha_summary}")
    lines.append("")

    # --- Distill-in-progress detection ---
    # Derive cwd from buffer_dir (go up from .claude/buffer/ to repo root)
    repo_root = str(Path(buffer_dir).parent.parent)
    distill_state = detect_distill_in_progress(repo_root)
    if distill_state:
        lines.append("## DISTILLATION IN PROGRESS (interrupted by compaction)")
        lines.append("")
        if 'extracted_text' in distill_state:
            tl = distill_state.get('text_lines', '?')
            lines.append(f"Extracted text: {distill_state['extracted_text']} ({tl} lines)")
            preview = distill_state.get('text_preview', [])
            if preview:
                lines.append("First lines:")
                for pl in preview[:5]:
                    if pl.strip():
                        lines.append(f"  | {pl[:120]}")
        if 'ephemeral_scripts' in distill_state:
            lines.append(f"Ephemeral scripts present: {', '.join(distill_state['ephemeral_scripts'])}")
        if 'figures_extracted' in distill_state:
            lines.append(f"Figures extracted: {distill_state['figures_extracted']}")
        if 'recent_distillations' in distill_state:
            for rd in distill_state['recent_distillations']:
                lines.append(f"Recently modified: {rd.get('file', '?')} ({rd.get('seconds_ago', '?')}s ago)")
        if distill_state.get('has_project_skill'):
            lines.append("Project distill skill: exists")
        lines.append("")
        lines.append("DISTILL RECOVERY: The extracted text file is on disk. Resume from")
        lines.append("the analytic passes (Pass 2+). Do NOT re-extract. Read the text")
        lines.append("file, confirm the source label with the user, then continue the")
        lines.append("pipeline from where it was interrupted.")
        lines.append("")

    # --- Compaction directives ---
    directive_context = generate_directive_context(buffer_dir, tier=tier)
    if directive_context:
        lines.append(directive_context)

    # --- Consistency check directive ---
    lines.append("=" * 40)
    lines.append("REQUIRED: Post-Compaction Consistency Check")
    lines.append("1. Compare active_work and open_threads against your compaction summary")
    lines.append("2. Fix any hot-layer mismatches (hot only -- do NOT touch warm)")
    lines.append("3. Verify natural_summary has [compacted] marker")
    lines.append("4. Arm autosave")
    if distill_state:
        lines.append("5. Resume interrupted distillation (see DISTILL RECOVERY above)")
    else:
        lines.append("5. Resume user's work")

    return "\n".join(lines)


def cmd_post_compact(hook_input):
    """Inject buffer context after compaction (only if marker exists)."""
    cwd = hook_input.get('cwd', os.getcwd())
    buffer_dir = find_buffer_dir(cwd)

    empty_output = {
        "additional_context": "",
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": ""
        }
    }

    if not buffer_dir:
        json.dump(empty_output, sys.stdout, ensure_ascii=False)
        sys.exit(0)

    # Guard: only inject if pre-compact wrote a marker
    marker_path = os.path.join(buffer_dir, '.compact_marker')
    if not os.path.exists(marker_path):
        json.dump(empty_output, sys.stdout, ensure_ascii=False)
        sys.exit(0)

    # TTL check: if marker is older than 24 hours, it's stale
    import time
    try:
        marker_age = time.time() - os.path.getmtime(marker_path)
        if marker_age > 86400:  # 24 hours
            print("compact: stale .compact_marker found (>24h old) — cleaning up",
                  file=sys.stderr)
            try:
                os.remove(marker_path)
            except OSError:
                pass
            json.dump(empty_output, sys.stdout, ensure_ascii=False)
            sys.exit(0)
    except OSError:
        pass

    hot_path = os.path.join(buffer_dir, 'handoff.json')
    hot = read_json(hot_path)

    if not hot:
        json.dump(empty_output, sys.stdout, ensure_ascii=False)
        sys.exit(0)

    # Detect layer limit overrides
    hot_max, warm_max, cold_max = detect_layer_limits(cwd)

    # Detect model tier for context scaling
    _load_buffer_utils()
    tier = _get_tier()

    # Build concise summary for injection (tier-scaled)
    context = build_compact_summary(hot, buffer_dir, hot_max, warm_max, cold_max, tier=tier)

    # Clean up marker
    try:
        os.remove(marker_path)
    except OSError:
        pass

    # Output JSON for hook system
    output = {
        "additional_context": context,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context
        }
    }
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(
            "Usage: compact_hook.py <pre-compact|post-compact>\n\n"
            "  pre-compact   Autosave hot layer before context compaction\n"
            "  post-compact  Inject buffer context after compaction\n\n"
            "Called by the plugin hook system. Reads hook input JSON from stdin.",
            file=sys.stderr
        )
        sys.exit(0 if '--help' in sys.argv else 1)

    hook_input = read_hook_input()

    command = sys.argv[1]
    if command == 'pre-compact':
        cmd_pre_compact(hook_input)
    elif command == 'post-compact':
        cmd_post_compact(hook_input)
    else:
        print(f"compact_hook: unknown command '{command}'", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
