#!/usr/bin/env python3
"""
Session Buffer — Buffer Manager

Mechanical operations for the session buffer (sigma trunk + alpha/beta bins).
Handles JSON merge, ID assignment, conservation enforcement, MEMORY.md sync,
alpha bin queries, and beta bin narrative capture.

Commands:
  handoff        — Full pipeline: update + migrate + sync (preferred)
  update         — Merge session alpha stash into hot+warm layers
  migrate        — Conservation: hot→warm→cold when bounds exceeded
  validate       — Check layer sizes, schema, and alpha integrity
  sync           — MEMORY.md status sync + project registry
  read           — Parse hot layer, resolve warm pointers, output reconstruction
  next-id        — Get next sequential ID for a layer (scans alpha too)
  alpha-read     — Read alpha bin index, output summary
  alpha-query    — Query alpha by ID, source, or concept (retrieves referent files)
  alpha-write    — Write entries to alpha bin (stdin JSON, auto-ID, index update)
  alpha-delete   — Delete entries from alpha bin (removes files + index)
  alpha-validate — Check alpha bin integrity (index vs files on disk)
  beta-append    — Append narrative entry to beta bin (stdin JSON)
  beta-read      — Read beta bin entries with optional filters
  beta-promote   — Mark entries above threshold as promoted (adaptive)
  beta-purge     — Remove promoted + low-relevance old entries

Usage: run_python buffer_manager.py <command> [options]
"""

import sys
import os
import io
import json
import re
import copy
import argparse
from pathlib import Path
from datetime import date, datetime, timezone

# Force UTF-8 stdout/stderr on Windows (buffer data may contain unicode)
# Guard: only wrap when running as main script, not when imported by tests
if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Concept key normalization — canonical source: schemas/normalize.py
# ---------------------------------------------------------------------------

try:
    _schema_dir = str(Path(__file__).resolve().parent.parent.parent / 'schemas')
    if _schema_dir not in sys.path:
        sys.path.insert(0, _schema_dir)
    from normalize import normalize_key
except (ImportError, Exception):
    def normalize_key(text):
        """Normalize a concept name to a marker key (fallback)."""
        s = text.strip().lower()
        s = re.sub(r'\(.*?\)', '', s)
        s = re.sub(r'[^a-z0-9\s_]', '', s)
        s = re.sub(r'\s+', '_', s.strip())
        return s[:40]


# ---------------------------------------------------------------------------
# Constants (defaults — can be overridden per-project in skill config)
# ---------------------------------------------------------------------------

HOT_MAX_LINES = 200
WARM_MAX_LINES_DEFAULT = 500
COLD_MAX_LINES = 500
SCHEMA_VERSION = 2

# Scope mapping: legacy buffer_mode values to normalized scope values
SCOPE_MAP = {
    'project': 'full',
    'memory': 'lite',
    'minimal': 'lite',
    'full': 'full',
    'lite': 'lite',
}


def is_full_mode(mode):
    """Check if buffer mode supports full features (concept maps, convergence webs)."""
    return mode in ('project', 'full')


def is_active_mode(mode):
    """Check if buffer mode supports active work tracking (decisions, threads, notes)."""
    return mode in ('memory', 'project', 'full', 'lite', 'unknown')


def _parse_limits_from_file(filepath, limits):
    """Parse layer limits from a file (skill config or userconfig).

    Looks for lines like: hot_max: 250, warm-max: 800, cold_max: 750
    Updates limits dict in place for any found values.
    """
    if not os.path.exists(filepath):
        return
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


def detect_layer_limits(cwd):
    """Detect project-level overrides for hot-max, warm-max, cold-max.

    Checks two sources (later source wins):
      1. .claude/skills/buffer/on.md (project skill config)
      2. .claude/buffer.local.md (userconfig — takes precedence)

    Returns dict with resolved limits (defaults for any not overridden).
    """
    limits = {
        'hot': HOT_MAX_LINES,
        'warm': WARM_MAX_LINES_DEFAULT,
        'cold': COLD_MAX_LINES,
    }
    # Project skill config (base)
    _parse_limits_from_file(
        os.path.join(cwd, '.claude', 'skills', 'buffer', 'on.md'), limits)
    # Userconfig (overrides skill config)
    _parse_limits_from_file(
        os.path.join(cwd, '.claude', 'buffer.local.md'), limits)
    return limits


def resolve_limits(args):
    """Resolve layer limits: CLI flags > project skill config > defaults.

    Returns (hot_max, warm_max, cold_max) tuple.
    """
    # Start from defaults
    hot_max = HOT_MAX_LINES
    warm_max = WARM_MAX_LINES_DEFAULT
    cold_max = COLD_MAX_LINES

    # Try project-level auto-detection from buffer-dir parent
    buf_dir = getattr(args, 'buffer_dir', None)
    if buf_dir:
        # buffer_dir is typically <project>/.claude/buffer/
        # project root is two levels up
        project_root = str(Path(buf_dir).parent.parent)
        if os.path.isdir(project_root):
            detected = detect_layer_limits(project_root)
            hot_max = detected['hot']
            warm_max = detected['warm']
            cold_max = detected['cold']

    # CLI flags override everything
    if getattr(args, 'hot_max', None) is not None:
        hot_max = args.hot_max
    if getattr(args, 'warm_max', None) is not None:
        warm_max = args.warm_max
    if getattr(args, 'cold_max', None) is not None:
        cold_max = args.cold_max

    return hot_max, warm_max, cold_max


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def read_json(path: str) -> dict:
    """Read a JSON file, return empty dict if not found."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: failed to read {path}: {e}", file=sys.stderr)
        return {}


def write_json(path: str, data: dict) -> None:
    """Write data to a JSON file with consistent formatting."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8'
    )


def count_json_lines(data: dict) -> int:
    """Count lines in the JSON serialization of data."""
    return len(json.dumps(data, indent=2, ensure_ascii=False).split('\n'))


def next_id_in_entries(entries: list, prefix: str) -> str:
    """Find the next sequential ID for a prefix (w:, c:, cw:)."""
    max_n = 0
    pattern = re.compile(rf'^{re.escape(prefix)}(\d+)$')
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get('id', '')
        m = pattern.match(entry_id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}{max_n + 1}"


def collect_all_entries(layer: dict, prefix: str) -> list:
    """Collect all entries with a given ID prefix from a layer."""
    entries = []

    if prefix == 'w:':
        # Warm: concept_map groups + convergence_web + decisions_archive + validation_log
        concept_map = layer.get('concept_map', {})
        for group_name, group_entries in concept_map.items():
            if isinstance(group_entries, list):
                entries.extend(group_entries)
        cw = layer.get('convergence_web', {})
        entries.extend(cw.get('entries', []))
        entries.extend(layer.get('decisions_archive', []))
        entries.extend(layer.get('validation_log', []))

    elif prefix == 'c:':
        # Cold: all sections
        for key in ['archived_decisions', 'superseded_mappings', 'dialogue_trace']:
            entries.extend(layer.get(key, []))

    elif prefix == 'cw:':
        # Convergence web only
        cw = layer.get('convergence_web', {})
        entries.extend(cw.get('entries', []))

    return entries


def resolve_see_refs(hot: dict, warm: dict, cold: dict) -> list:
    """Collect all 'see' references from hot layer and resolve them."""
    refs = set()

    # Gather from decisions
    for d in hot.get('recent_decisions', []):
        for ref in d.get('see', []):
            refs.add(ref)

    # Gather from threads
    for t in hot.get('open_threads', []):
        for ref in t.get('see', []):
            refs.add(ref)

    # Gather from digests
    digest = hot.get('concept_map_digest', {})
    for change in digest.get('recent_changes', []):
        refs.add(change.get('id', ''))
    for flagged_id in digest.get('flagged', []):
        refs.add(flagged_id)

    cw_digest = hot.get('convergence_web_digest', {})
    for flagged_id in cw_digest.get('flagged', []):
        refs.add(flagged_id)

    refs.discard('')

    # Build lookup dicts for O(1) resolution instead of linear scans
    resolved = []
    warm_by_id = {e['id']: e for e in collect_all_entries(warm, 'w:') if 'id' in e}
    cold_by_id = {e['id']: e for e in collect_all_entries(cold, 'c:') if 'id' in e}
    cw_by_id = {e['id']: e for e in warm.get('convergence_web', {}).get('entries', []) if 'id' in e}

    for ref_id in sorted(refs):
        entry = None
        source = None

        # Check warm
        w = warm_by_id.get(ref_id)
        if w:
            if 'migrated_to' in w:
                # Follow redirect to cold
                cold_target = cold_by_id.get(w['migrated_to'])
                if cold_target:
                    entry = cold_target
                    source = f"cold (via redirect from {ref_id})"
                else:
                    entry = w
                    source = "warm (redirect — target not found in cold)"
            else:
                entry = w
                source = "warm"

        # Check convergence web
        if not entry:
            cw = cw_by_id.get(ref_id)
            if cw:
                entry = cw
                source = "convergence_web"

        # Check cold
        if not entry:
            c = cold_by_id.get(ref_id)
            if c:
                if 'archived_to' in c:
                    entry = c
                    source = f"cold (archived to tower-{c['archived_to']})"
                else:
                    entry = c
                    source = "cold"

        if entry:
            resolved.append({'ref': ref_id, 'source': source, 'entry': entry})
        else:
            resolved.append({'ref': ref_id, 'source': 'NOT FOUND', 'entry': None})

    return resolved


def resolve_scope(buffer_mode: str) -> str:
    """Map a buffer_mode value to a normalized scope ('full' or 'lite')."""
    return SCOPE_MAP.get(buffer_mode, 'lite')


# ---------------------------------------------------------------------------
# Subcommand: read
# ---------------------------------------------------------------------------

def format_section(title: str, content: str) -> str:
    """Format a section with a title."""
    return f"\n--- {title} ---\n{content}"


def cmd_read(args):
    """Reconstruct context from buffer layers. Output to stdout."""
    buf_dir = Path(args.buffer_dir)
    hot = read_json(buf_dir / 'handoff.json')
    warm = read_json(buf_dir / 'handoff-warm.json')
    cold = read_json(buf_dir / 'handoff-cold.json')

    if not hot:
        print("No buffer found.", file=sys.stderr)
        sys.exit(1)

    mode = hot.get('buffer_mode', 'unknown')
    out = []

    # Header
    out.append("=== BUFFER RECONSTRUCTION ===")
    out.append(f"Mode: {mode} | Schema: v{hot.get('schema_version', '?')}")
    out.append(f"Sessions since full scan: {hot.get('sessions_since_full_scan', '?')}"
               f"/{hot.get('full_scan_threshold', '?')}")

    # Session meta
    meta = hot.get('session_meta', {})
    out.append(format_section("Session", '\n'.join([
        f"Date: {meta.get('date', '?')}",
        f"Commit: {meta.get('commit', '?')} ({meta.get('branch', '?')})",
        f"Tests: {meta.get('tests', '?')}",
        f"Files: {', '.join(meta.get('files_modified', [])[:10])}"
        + (" ..." if len(meta.get('files_modified', [])) > 10 else ""),
    ])))

    # Active work (memory + project modes)
    if is_active_mode(mode):
        aw = hot.get('active_work', {})
        if aw:
            lines = [f"Phase: {aw.get('current_phase', '?')}"]
            for item in aw.get('completed_this_session', []):
                lines.append(f"  done: {item}")
            if aw.get('in_progress'):
                lines.append(f"In progress: {aw['in_progress']}")
            if aw.get('blocked_by'):
                lines.append(f"BLOCKED: {aw['blocked_by']}")
            if aw.get('next_action'):
                lines.append(f"Next: {aw['next_action']}")
            out.append(format_section("Active Work", '\n'.join(lines)))

    # Orientation
    ori = hot.get('orientation', {})
    if ori:
        lines = [f"Core: {ori.get('core_insight', '')}"]
        if ori.get('practical_warning'):
            lines.append(f"Warning: {ori['practical_warning']}")
        for k, v in ori.get('why_keys', {}).items():
            lines.append(f"  {k}: {v}")
        out.append(format_section("Orientation", '\n'.join(lines)))

    # Open threads (memory + project modes)
    if is_active_mode(mode):
        threads = hot.get('open_threads', [])
        if threads:
            lines = []
            for i, t in enumerate(threads, 1):
                ref = f" -> {t['ref']}" if t.get('ref') else ""
                see = f" [see: {', '.join(t['see'])}]" if t.get('see') else ""
                lines.append(f"{i}. [{t.get('status', '?')}] {t.get('thread', '')}{ref}{see}")
            out.append(format_section(f"Open Threads ({len(threads)})", '\n'.join(lines)))

    # Recent decisions (memory + project modes)
    if is_active_mode(mode):
        decs = hot.get('recent_decisions', [])
        if decs:
            lines = []
            for i, d in enumerate(decs, 1):
                see = f" [see: {', '.join(d['see'])}]" if d.get('see') else ""
                lines.append(f"{i}. {d.get('what', '?')} -> {d.get('chose', '?')} | {d.get('why', '')}{see}")
            out.append(format_section(f"Recent Decisions ({len(decs)})", '\n'.join(lines)))

    # Instance notes (memory + project modes)
    if is_active_mode(mode):
        notes = hot.get('instance_notes', {})
        if notes:
            lines = [f"From: {notes.get('from', '?')}"]
            lines.append("Remarks:")
            for r in notes.get('remarks', []):
                lines.append(f"  * {r}")
            if notes.get('open_questions'):
                lines.append("Open Questions:")
                for q in notes.get('open_questions', []):
                    lines.append(f"  ? {q}")
            out.append(format_section("Instance Notes", '\n'.join(lines)))

    # Concept map digest (project mode)
    if is_full_mode(mode):
        cmd = hot.get('concept_map_digest', {})
        if cmd:
            meta_cm = cmd.get('_meta', {})
            lines = [
                f"Total: {meta_cm.get('total_entries', '?')} entries "
                f"(last validated: {meta_cm.get('last_validated', '?')})"
            ]
            recent = cmd.get('recent_changes', [])
            if recent:
                lines.append(f"Recent changes ({len(recent)}):")
                for r in recent[:20]:
                    lines.append(f"  {r.get('id', '?')} | {r.get('key', '?')} | {r.get('status', '?')}")
                if len(recent) > 20:
                    lines.append(f"  ... and {len(recent) - 20} more")
            flagged = cmd.get('flagged', [])
            if flagged:
                lines.append(f"FLAGGED: {', '.join(flagged)}")
            out.append(format_section("Concept Map Digest", '\n'.join(lines)))

    # Convergence web digest (project mode)
    if is_full_mode(mode):
        cwd = hot.get('convergence_web_digest', {})
        if cwd:
            meta_cw = cwd.get('_meta', {})
            lines = [
                f"Total: {meta_cw.get('total_entries', '?')} entries"
            ]
            clusters = cwd.get('clusters', [])
            if clusters:
                lines.append(f"Clusters ({len(clusters)}):")
                for c in clusters:
                    lines.append(f"  * {c}")
            flagged = cwd.get('flagged', [])
            if flagged:
                lines.append(f"FLAGGED: {', '.join(flagged)}")
            else:
                lines.append("Flagged: none")
            out.append(format_section("Convergence Web Digest", '\n'.join(lines)))

    # Memory config
    mc = hot.get('memory_config', {})
    if mc:
        out.append(format_section("Memory Config", '\n'.join([
            f"Integration: {mc.get('integration', '?')}",
            f"Path: {mc.get('path', '?')}",
        ])))

    # Natural summary
    ns = hot.get('natural_summary', '')
    if ns:
        out.append(format_section("Natural Summary", ns))

    # Resolve pointers
    resolved = resolve_see_refs(hot, warm, cold)
    if resolved:
        lines = []
        for r in resolved:
            entry = r['entry']
            if entry is None:
                lines.append(f"{r['ref']} | {r['source']}")
            elif 'archived_to' in entry:
                lines.append(f"{r['ref']} | ARCHIVED to tower-{entry['archived_to']}"
                             f" | was: {entry.get('was', '?')}")
            elif 'migrated_to' in entry:
                lines.append(f"{r['ref']} | REDIRECT -> {entry['migrated_to']}")
            else:
                key = entry.get('key', entry.get('what', entry.get('thread', '?')))
                maps_to = entry.get('maps_to', '')
                suggest = entry.get('suggest', '')
                extra = []
                if maps_to:
                    extra.append(f"maps_to={maps_to}")
                if suggest:
                    extra.append(f"suggest={suggest}")
                extra_str = f" | {', '.join(extra)}" if extra else ""
                lines.append(f"{r['ref']} [{r['source']}] | {key}{extra_str}")
        out.append(format_section("Warm Pointers Resolved", '\n'.join(lines)))

    # Layer sizes
    hot_max, warm_max, cold_max = resolve_limits(args)
    hot_lines = count_json_lines(hot)
    warm_lines = count_json_lines(warm) if warm else 0
    cold_lines = count_json_lines(cold) if cold else 0

    size_lines = [
        f"Hot:  {hot_lines} lines (max {hot_max})"
        + (" *** OVER ***" if hot_lines > hot_max else ""),
        f"Warm: {warm_lines} lines (max {warm_max})"
        + (" *** OVER ***" if warm_lines > warm_max else ""),
        f"Cold: {cold_lines} lines (max {cold_max})"
        + (" *** OVER ***" if cold_lines > cold_max else ""),
    ]
    out.append(format_section("Layer Sizes", '\n'.join(size_lines)))

    print('\n'.join(out))


# ---------------------------------------------------------------------------
# Subcommand: update — merge alpha stash into sigma trunk
# ---------------------------------------------------------------------------

def cmd_update(args):
    """Merge session alpha stash (changes) into buffer layers."""
    buf_dir = Path(args.buffer_dir)
    hot_path = buf_dir / 'handoff.json'
    warm_path = buf_dir / 'handoff-warm.json'

    hot = read_json(hot_path)
    warm = read_json(warm_path)

    if not hot:
        print("Error: no hot layer found. Initialize the buffer first.", file=sys.stderr)
        sys.exit(1)

    # Read changes (alpha stash) — prefer file input over stdin (Windows compat)
    if args.input:
        changes = read_json(args.input)
    else:
        try:
            changes = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON input: {e}", file=sys.stderr)
            sys.exit(1)

    if not changes:
        print("Error: empty changes.", file=sys.stderr)
        sys.exit(1)

    mode = hot.get('buffer_mode', 'minimal')
    report = []

    # --- Hot layer updates ---

    # Session meta (always)
    if 'session_meta' in changes:
        hot['session_meta'] = changes['session_meta']
        report.append("Updated session_meta")

    # Active work (memory + project)
    if is_active_mode(mode) and 'active_work' in changes:
        hot['active_work'] = changes['active_work']
        report.append("Updated active_work")

    # New decisions -> append to recent_decisions (memory + project)
    if is_active_mode(mode) and 'new_decisions' in changes:
        if 'recent_decisions' not in hot:
            hot['recent_decisions'] = []
        for d in changes['new_decisions']:
            d.setdefault('session', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
            d.setdefault('see', [])
            hot['recent_decisions'].append(d)
        report.append(f"Added {len(changes['new_decisions'])} decisions")

    # Open threads — replace entirely (memory + project)
    if is_active_mode(mode) and 'open_threads' in changes:
        hot['open_threads'] = changes['open_threads']
        report.append(f"Set {len(changes['open_threads'])} open threads")

    # Instance notes — replace entirely (memory + project)
    if is_active_mode(mode) and 'instance_notes' in changes:
        hot['instance_notes'] = changes['instance_notes']
        report.append("Updated instance_notes")

    # Natural summary (always)
    if 'natural_summary' in changes:
        hot['natural_summary'] = changes['natural_summary']
        report.append("Updated natural_summary")

    # Orientation updates (rare, but supported)
    if 'orientation' in changes:
        hot['orientation'] = changes['orientation']
        report.append("Updated orientation")

    # --- Warm layer updates (project mode) ---

    if is_full_mode(mode) and warm:
        # Concept map changes
        if 'concept_map_changes' in changes:
            concept_map = warm.get('concept_map', {})
            all_warm_entries = collect_all_entries(warm, 'w:')
            digest_recent = hot.get('concept_map_digest', {}).get('recent_changes', [])
            digest_flagged = hot.get('concept_map_digest', {}).get('flagged', [])
            added = 0
            updated = 0

            for change in changes['concept_map_changes']:
                action = change.get('action', '')

                if action == 'add':
                    group = change.get('group', 'cross_source')
                    entry = change.get('entry', {})
                    new_id = next_id_in_entries(all_warm_entries, 'w:')
                    entry['id'] = new_id
                    if group not in concept_map:
                        concept_map[group] = []
                    concept_map[group].append(entry)
                    all_warm_entries.append(entry)
                    digest_recent.append({
                        'id': new_id,
                        'key': entry.get('key', '?'),
                        'status': 'NEW'
                    })
                    added += 1

                elif action == 'update':
                    target_id = change.get('id', '')
                    changes_to_apply = change.get('changes', {})
                    for group_name, group_entries in concept_map.items():
                        if isinstance(group_entries, list):
                            for e in group_entries:
                                if e.get('id') == target_id:
                                    e.update(changes_to_apply)
                                    digest_recent.append({
                                        'id': target_id,
                                        'key': e.get('key', '?'),
                                        'status': 'CHANGED'
                                    })
                                    updated += 1
                                    break

                elif action == 'flag':
                    flag_id = change.get('id', '')
                    if flag_id and flag_id not in digest_flagged:
                        digest_flagged.append(flag_id)

                elif action == 'promote':
                    target_id = change.get('id', '')
                    for group_name, group_entries in concept_map.items():
                        if isinstance(group_entries, list):
                            for e in group_entries:
                                if e.get('id') == target_id:
                                    if e.get('suggest'):
                                        e['equiv'] = e.pop('suggest')
                                        digest_recent.append({
                                            'id': target_id,
                                            'key': e.get('key', '?'),
                                            'status': 'PROMOTED'
                                        })
                                    break

            warm['concept_map'] = concept_map

            # Update digest
            if 'concept_map_digest' not in hot:
                hot['concept_map_digest'] = {'_meta': {}, 'recent_changes': [], 'flagged': []}
            hot['concept_map_digest']['recent_changes'] = digest_recent
            hot['concept_map_digest']['flagged'] = digest_flagged
            total = sum(len(g) for g in concept_map.values() if isinstance(g, list))
            hot['concept_map_digest']['_meta']['total_entries'] = total
            hot['concept_map_digest']['_meta']['last_validated'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            if added or updated:
                report.append(f"Concept map: {added} added, {updated} updated")

        # Convergence web changes
        if 'convergence_web_changes' in changes:
            cw = warm.get('convergence_web', {'_meta': {}, 'entries': []})
            cw_entries = cw.get('entries', [])
            cw_added = 0

            for change in changes['convergence_web_changes']:
                action = change.get('action', '')

                if action == 'add':
                    entry = change.get('entry', {})
                    new_id = next_id_in_entries(cw_entries, 'cw:')
                    entry['id'] = new_id
                    cw_entries.append(entry)
                    cw_added += 1

                elif action == 'update':
                    target_id = change.get('id', '')
                    changes_to_apply = change.get('changes', {})
                    for e in cw_entries:
                        if e.get('id') == target_id:
                            e.update(changes_to_apply)
                            break

            cw['entries'] = cw_entries
            cw['_meta']['total_entries'] = len(cw_entries)
            cw['_meta']['last_validated'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            warm['convergence_web'] = cw

            # Update hot digest
            if 'convergence_web_digest' not in hot:
                hot['convergence_web_digest'] = {'_meta': {}, 'clusters': [], 'flagged': []}
            hot['convergence_web_digest']['_meta']['total_entries'] = len(cw_entries)
            hot['convergence_web_digest']['_meta']['last_validated'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            if cw_added:
                report.append(f"Convergence web: {cw_added} added")

        # Validation log entries
        if 'validation_log_entries' in changes:
            if 'validation_log' not in warm:
                warm['validation_log'] = []
            warm['validation_log'].extend(changes['validation_log_entries'])
            report.append(f"Validation log: {len(changes['validation_log_entries'])} entries added")

    # --- Minimal mode: session summary tracking ---
    if mode == 'minimal' and 'natural_summary' in changes:
        # In minimal mode, warm layer holds session_summaries
        if not warm:
            warm = {'schema_version': 2, 'layer': 'warm', 'session_summaries': []}
        summaries = warm.get('session_summaries', [])
        summaries.append({
            'date': changes.get('session_meta', {}).get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d')),
            'commit': changes.get('session_meta', {}).get('commit', '?'),
            'summary': changes['natural_summary']
        })
        warm['session_summaries'] = summaries
        report.append("Added session summary to warm")

    # --- Increment full scan counter ---
    hot['sessions_since_full_scan'] = hot.get('sessions_since_full_scan', 0) + 1

    # --- Write ---
    write_json(hot_path, hot)
    report.append(f"Wrote hot layer ({count_json_lines(hot)} lines)")

    if warm:
        write_json(warm_path, warm)
        report.append(f"Wrote warm layer ({count_json_lines(warm)} lines)")

    print("Update complete:", file=sys.stderr)
    for r in report:
        print(f"  {r}", file=sys.stderr)

    # Output summary as JSON for the LLM to confirm
    result = {
        'status': 'ok',
        'hot_lines': count_json_lines(hot),
        'warm_lines': count_json_lines(warm) if warm else 0,
        'actions': report
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: migrate
# ---------------------------------------------------------------------------

def cmd_migrate(args):
    """Conservation enforcement — migrate entries between layers."""
    buf_dir = Path(args.buffer_dir)
    hot_max, warm_max, cold_max = resolve_limits(args)

    hot = read_json(buf_dir / 'handoff.json')
    warm = read_json(buf_dir / 'handoff-warm.json')
    cold = read_json(buf_dir / 'handoff-cold.json')

    if not hot:
        print("Error: no hot layer found.", file=sys.stderr)
        sys.exit(1)

    mode = hot.get('buffer_mode', 'minimal')
    report = []
    modified = {'hot': False, 'warm': False, 'cold': False}

    # --- Hot -> Warm migration ---
    hot_lines = count_json_lines(hot)
    if hot_lines > hot_max and is_active_mode(mode):
        # Move oldest decisions to warm decisions_archive
        decisions = hot.get('recent_decisions', [])
        if len(decisions) > 2:
            to_migrate = decisions[:-2]  # Keep last 2
            hot['recent_decisions'] = decisions[-2:]

            if 'decisions_archive' not in warm:
                warm['decisions_archive'] = []
            warm['decisions_archive'].extend(to_migrate)
            report.append(f"Hot->Warm: migrated {len(to_migrate)} decisions")
            modified['hot'] = True
            modified['warm'] = True

        # Remove resolved threads
        threads = hot.get('open_threads', [])
        resolved = [t for t in threads if t.get('status') == 'resolved']
        if resolved:
            hot['open_threads'] = [t for t in threads if t.get('status') != 'resolved']
            report.append(f"Hot: removed {len(resolved)} resolved threads")
            modified['hot'] = True

    # --- Warm -> Cold migration ---
    warm_lines = count_json_lines(warm) if warm else 0
    if warm_lines > warm_max and is_active_mode(mode):
        # Migrate oldest decisions_archive entries
        archive = warm.get('decisions_archive', [])
        if len(archive) > 5:
            to_migrate = archive[:len(archive) - 5]
            warm['decisions_archive'] = archive[len(archive) - 5:]

            if not cold:
                cold = {'schema_version': 2, 'layer': 'cold', 'archived_decisions': [],
                        'superseded_mappings': [], 'dialogue_trace': []}
            if 'archived_decisions' not in cold:
                cold['archived_decisions'] = []

            cold_entries = collect_all_entries(cold, 'c:')
            for entry in to_migrate:
                new_id = next_id_in_entries(cold_entries, 'c:')
                old_id = entry.get('id', entry.get('what', '?'))
                cold_entry = copy.deepcopy(entry)
                cold_entry['id'] = new_id
                cold_entry['migrated_from_warm'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                cold['archived_decisions'].append(cold_entry)
                cold_entries.append(cold_entry)

            report.append(f"Warm->Cold: migrated {len(to_migrate)} decisions")
            modified['warm'] = True
            modified['cold'] = True

        # Migrate oldest validation_log entries
        vlog = warm.get('validation_log', [])
        if len(vlog) > 20:
            to_migrate = vlog[:len(vlog) - 20]
            warm['validation_log'] = vlog[len(vlog) - 20:]
            # Validation log entries go to cold without redirect (low-value)
            report.append(f"Warm->Cold: trimmed {len(to_migrate)} validation_log entries")
            modified['warm'] = True

    # --- Minimal mode: compress session summaries ---
    if mode == 'minimal' and warm:
        summaries = warm.get('session_summaries', [])
        warm_lines = count_json_lines(warm)
        if warm_lines > WARM_MAX_LINES_DEFAULT and len(summaries) > 5:
            # Compress oldest 30% by merging adjacent summaries
            n_compress = max(2, len(summaries) * 30 // 100)
            to_compress = summaries[:n_compress]
            merged_summary = ' | '.join(
                f"[{s.get('date', '?')}] {s.get('summary', '')[:80]}"
                for s in to_compress
            )
            compressed = {
                'date': f"{to_compress[0].get('date', '?')}..{to_compress[-1].get('date', '?')}",
                'commit': to_compress[-1].get('commit', '?'),
                'summary': f"[compressed {n_compress} sessions] {merged_summary}"
            }
            warm['session_summaries'] = [compressed] + summaries[n_compress:]
            report.append(f"Minimal: compressed {n_compress} session summaries")
            modified['warm'] = True

    # --- Cold overflow detection ---
    cold_lines = count_json_lines(cold) if cold else 0
    if cold_lines > cold_max:
        report.append(f"WARNING: Cold layer at {cold_lines} lines (max {cold_max}). "
                      f"Run 'archive' subcommand to create tower file.")

    # --- Write modified layers ---
    if modified['hot'] or args.dry_run:
        if not args.dry_run:
            write_json(buf_dir / 'handoff.json', hot)
    if modified['warm'] or args.dry_run:
        if not args.dry_run:
            write_json(buf_dir / 'handoff-warm.json', warm)
    if modified['cold'] or args.dry_run:
        if not args.dry_run:
            write_json(buf_dir / 'handoff-cold.json', cold)

    # Report
    if not report:
        report.append("All layers within bounds. No migration needed.")

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Migration report:", file=sys.stderr)
    for r in report:
        print(f"  {r}", file=sys.stderr)

    result = {
        'status': 'ok',
        'hot_lines': count_json_lines(hot),
        'warm_lines': count_json_lines(warm) if warm else 0,
        'cold_lines': cold_lines,
        'actions': report,
        'dry_run': args.dry_run
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: validate
# ---------------------------------------------------------------------------

def cmd_validate(args):
    """Check layers against size and schema constraints."""
    buf_dir = Path(args.buffer_dir)
    hot_max, warm_max, cold_max = resolve_limits(args)

    hot = read_json(buf_dir / 'handoff.json')
    warm = read_json(buf_dir / 'handoff-warm.json')
    cold = read_json(buf_dir / 'handoff-cold.json')

    issues = []
    info = []

    if not hot:
        issues.append("CRITICAL: No hot layer (handoff.json) found")
        print(json.dumps({'status': 'error', 'issues': issues, 'info': info}))
        sys.exit(1)

    mode = hot.get('buffer_mode', 'unknown')
    info.append(f"Buffer mode: {mode}")
    info.append(f"Schema version: {hot.get('schema_version', 'missing')}")

    # Schema version
    if hot.get('schema_version', 0) < SCHEMA_VERSION:
        issues.append(f"Schema version {hot.get('schema_version')} < {SCHEMA_VERSION}. Migration needed.")
    if hot.get('schema_version', 0) > SCHEMA_VERSION:
        print(f"buffer_manager: handoff.json schema_version {hot.get('schema_version')} > {SCHEMA_VERSION} — some features may not work",
              file=sys.stderr)

    # Size checks
    hot_lines = count_json_lines(hot)
    warm_lines = count_json_lines(warm) if warm else 0
    cold_lines = count_json_lines(cold) if cold else 0

    info.append(f"Hot: {hot_lines}/{hot_max} lines")
    info.append(f"Warm: {warm_lines}/{warm_max} lines")
    info.append(f"Cold: {cold_lines}/{cold_max} lines")

    if hot_lines > hot_max:
        issues.append(f"Hot layer over limit: {hot_lines} > {hot_max}")
    if warm_lines > warm_max:
        issues.append(f"Warm layer over limit: {warm_lines} > {warm_max}")
    if cold_lines > cold_max:
        issues.append(f"Cold layer over limit: {cold_lines} > {cold_max}")

    # Required fields
    required_hot = ['session_meta', 'natural_summary', 'memory_config']
    if is_active_mode(mode):
        required_hot.extend(['active_work', 'open_threads', 'recent_decisions', 'instance_notes'])
    if is_full_mode(mode):
        required_hot.extend(['concept_map_digest', 'convergence_web_digest'])

    for field in required_hot:
        if field not in hot:
            issues.append(f"Missing required hot field: {field}")

    # Pointer integrity (project mode)
    all_layer_ids = set()
    broken_refs = []
    if is_full_mode(mode) and warm:
        all_warm_ids = {e.get('id') for e in collect_all_entries(warm, 'w:') if e.get('id')}
        cw_ids = {e.get('id') for e in warm.get('convergence_web', {}).get('entries', []) if e.get('id')}
        all_layer_ids = all_warm_ids | cw_ids

        # Check hot see-refs
        for d in hot.get('recent_decisions', []):
            for ref in d.get('see', []):
                if ref not in all_layer_ids:
                    broken_refs.append(ref)
        for t in hot.get('open_threads', []):
            for ref in t.get('see', []):
                if ref not in all_layer_ids:
                    broken_refs.append(ref)

        if broken_refs:
            issues.append(f"Broken see-refs: {', '.join(broken_refs)}")

    # Full scan threshold
    sfs = hot.get('sessions_since_full_scan', 0)
    threshold = hot.get('full_scan_threshold', 5)
    if sfs >= threshold:
        issues.append(f"Full scan due: {sfs} sessions since last scan (threshold: {threshold})")

    # Alpha bin status
    alpha_idx = read_alpha_index(buf_dir)
    alpha_summary = {}
    if alpha_idx:
        alpha_summary = alpha_idx.get('summary', {})
        info.append(f"Alpha: {alpha_summary.get('total_framework', 0)} fw, "
                    f"{alpha_summary.get('total_cross_source', 0)} cs, "
                    f"{alpha_summary.get('total_convergence_web', 0)} cw "
                    f"across {alpha_summary.get('total_sources', 0)} sources")

        # Check alpha_ref consistency
        if hot.get('alpha_ref') and not (buf_dir / 'alpha' / 'index.json').exists():
            issues.append("Hot layer has alpha_ref but alpha/index.json missing")

        # Pointer integrity: check see-refs against alpha too
        if is_full_mode(mode) and broken_refs:
            all_alpha_ids = alpha_all_ids(alpha_idx)
            still_broken = [r for r in broken_refs if r not in all_alpha_ids]
            if len(still_broken) < len(broken_refs):
                # Some refs resolved via alpha — update the issue
                issues = [i for i in issues if not i.startswith('Broken see-refs')]
                if still_broken:
                    issues.append(f"Broken see-refs: {', '.join(still_broken)}")
    else:
        info.append("Alpha: not present")

    result = {
        'status': 'ok' if not issues else 'issues_found',
        'issues': issues,
        'info': info,
        'layer_sizes': {
            'hot': hot_lines,
            'warm': warm_lines,
            'cold': cold_lines,
        },
        'alpha_summary': alpha_summary
    }
    print(json.dumps(result, indent=2))

    if issues:
        print(f"\n{len(issues)} issue(s) found:", file=sys.stderr)
        for i in issues:
            print(f"  ! {i}", file=sys.stderr)
    else:
        print("All checks passed.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Subcommand: sync — MEMORY.md status + project registry
# ---------------------------------------------------------------------------

def cmd_sync(args):
    """Sync MEMORY.md status + global project registry."""
    buf_dir = Path(args.buffer_dir)
    hot = read_json(buf_dir / 'handoff.json')

    if not hot:
        print("Error: no hot layer found.", file=sys.stderr)
        sys.exit(1)

    report = []

    # --- MEMORY.md sync ---
    mc = hot.get('memory_config', {})
    integration = mc.get('integration', 'none')
    memory_path = args.memory_path or mc.get('path', '')

    if integration != 'none' and memory_path and os.path.exists(memory_path):
        try:
            content = Path(memory_path).read_text(encoding='utf-8')
            lines = content.split('\n')
            new_lines = []
            in_status = False
            status_updated = False

            # Build status line
            aw = hot.get('active_work', {})
            status_text = (
                f"**Status**: {aw.get('current_phase', 'Unknown')}. "
                f"Next: {aw.get('next_action', 'TBD')}."
            )

            for line in lines:
                if line.strip().startswith('## Status'):
                    in_status = True
                    new_lines.append(line)
                    continue

                if in_status:
                    if line.strip().startswith('##'):
                        # Next section — insert status before it
                        new_lines.append(status_text)
                        new_lines.append('')
                        in_status = False
                        new_lines.append(line)
                        status_updated = True
                    elif line.strip().startswith('**Status**'):
                        new_lines.append(status_text)
                        status_updated = True
                        in_status = False
                    else:
                        # Skip old status content
                        continue
                else:
                    new_lines.append(line)

            # Handle case where ## Status is last section
            if in_status and not status_updated:
                new_lines.append(status_text)
                new_lines.append('')
                status_updated = True

            # If no ## Status section found, add one before ## Buffer Integration
            if not status_updated:
                final_lines = []
                inserted = False
                for line in new_lines:
                    if line.strip().startswith('## Buffer Integration') and not inserted:
                        final_lines.append('## Status')
                        final_lines.append(status_text)
                        final_lines.append('')
                        inserted = True
                    final_lines.append(line)
                if not inserted:
                    final_lines.append('')
                    final_lines.append('## Status')
                    final_lines.append(status_text)
                new_lines = final_lines

            Path(memory_path).write_text('\n'.join(new_lines), encoding='utf-8')
            report.append(f"MEMORY.md status updated: {status_text[:60]}...")
        except OSError as e:
            report.append(f"Warning: MEMORY.md sync failed: {e}")
    elif integration == 'none':
        report.append("MEMORY.md sync skipped (integration=none)")
    else:
        report.append(f"MEMORY.md not found at {memory_path}")

    # --- Global project registry ---
    registry_path = args.registry_path or os.path.expanduser('~/.claude/buffer/projects.json')
    registry = read_json(registry_path)
    if not registry:
        registry = {'schema_version': 1, 'projects': {}}

    # Determine project name
    project_name = args.project_name
    if not project_name:
        # Infer from buffer directory
        buf_abs = Path(buf_dir).resolve()
        project_name = buf_abs.parent.parent.name  # .claude/buffer/ -> parent.parent = repo root

    # Determine scope from buffer_mode
    buffer_mode = hot.get('buffer_mode', 'minimal')
    scope = resolve_scope(buffer_mode)

    ori = hot.get('orientation', {})
    registry['projects'][project_name] = {
        'buffer_path': str(Path(buf_dir).resolve()),
        'scope': scope,
        'last_handoff': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'project_context': ori.get('core_insight', '')[:120],
        'remote_backup': False
    }

    Path(registry_path).parent.mkdir(parents=True, exist_ok=True)
    write_json(registry_path, registry)
    report.append(f"Registry updated: {project_name} (scope={scope})")

    print("Sync complete:", file=sys.stderr)
    for r in report:
        print(f"  {r}", file=sys.stderr)

    print(json.dumps({'status': 'ok', 'actions': report}, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: next-id
# ---------------------------------------------------------------------------

def cmd_next_id(args):
    """Get the next available ID for a layer.

    Scans both warm layer AND alpha bin to find the true max, preventing
    ID collisions after alpha migration.
    """
    buf_dir = Path(args.buffer_dir)
    layer_name = args.layer
    alpha_idx = read_alpha_index(buf_dir)

    if layer_name == 'cold':
        cold = read_json(buf_dir / 'handoff-cold.json')
        entries = collect_all_entries(cold, 'c:')
        print(next_id_in_entries(entries, 'c:'))
        return

    # warm and convergence share the same pattern
    prefix = 'w:' if layer_name == 'warm' else 'cw:'
    warm = read_json(buf_dir / 'handoff-warm.json')
    if layer_name == 'warm':
        entries = collect_all_entries(warm, 'w:')
    else:
        entries = warm.get('convergence_web', {}).get('entries', [])

    layer_max = 0
    pattern = re.compile(rf'^{re.escape(prefix)}(\d+)$')
    for e in entries:
        m = pattern.match(e.get('id', ''))
        if m:
            layer_max = max(layer_max, int(m.group(1)))
    alpha_max = alpha_max_id(alpha_idx, prefix) if alpha_idx else 0
    # Safety: also check disk to prevent stale-index collisions
    alpha_dir = buf_dir / 'alpha'
    if alpha_dir.is_dir():
        disk_max_w, disk_max_cw = _alpha_disk_max_ids(alpha_dir)
        disk_max = disk_max_w if prefix == 'w:' else disk_max_cw
        alpha_max = max(alpha_max, disk_max)
    print(f"{prefix}{max(layer_max, alpha_max) + 1}")


# ---------------------------------------------------------------------------
# Subcommand: archive
# ---------------------------------------------------------------------------

def cmd_archive(args):
    """Cold->tower archival: compute dependency map and create tower file."""
    buf_dir = Path(args.buffer_dir)
    cold = read_json(buf_dir / 'handoff-cold.json')

    if not cold:
        print("No cold layer found.", file=sys.stderr)
        sys.exit(1)

    cold_lines = count_json_lines(cold)
    _, _, cold_max = resolve_limits(args)
    if cold_lines <= cold_max and not args.force:
        print(f"Cold layer at {cold_lines} lines (max {cold_max}). "
              f"No archival needed. Use --force to override.", file=sys.stderr)
        sys.exit(0)

    # Compute dependency map
    all_entries = []
    for key in ['archived_decisions', 'superseded_mappings', 'dialogue_trace']:
        for entry in cold.get(key, []):
            entry_id = entry.get('id', '')
            if entry_id:
                all_entries.append({
                    'id': entry_id,
                    'section': key,
                    'refs': [],  # entries that reference this one
                    'depth': 0,
                    'was': entry.get('what', entry.get('key', entry.get('thread', '?')))[:60]
                })

    # Build reference graph
    all_ids = {e['id'] for e in all_entries}
    cold_text = json.dumps(cold)
    for entry in all_entries:
        for other in all_entries:
            if other['id'] != entry['id'] and entry['id'] in str(cold.get(other['section'], [])):
                entry['refs'].append(other['id'])
                entry['depth'] += 1

    # Sort: depth-0 entries are safe to archive
    all_entries.sort(key=lambda e: e['depth'])

    # Output dependency map
    result = {
        'cold_lines': cold_lines,
        'total_entries': len(all_entries),
        'entries': [
            {
                'id': e['id'],
                'section': e['section'],
                'depth': e['depth'],
                'refs': e['refs'],
                'was': e['was'],
                'safe_to_archive': e['depth'] == 0
            }
            for e in all_entries
        ]
    }

    if args.entry_ids:
        # Archive specific entries
        ids_to_archive = set(args.entry_ids)

        # Find next tower number
        existing_towers = list(buf_dir.glob('handoff-tower-*.json'))
        tower_num = len(existing_towers) + 1
        tower_name = f"handoff-tower-{tower_num:03d}-{date.today()}.json"

        tower_entries = []
        for key in ['archived_decisions', 'superseded_mappings', 'dialogue_trace']:
            remaining = []
            for entry in cold.get(key, []):
                if entry.get('id', '') in ids_to_archive:
                    tower_entries.append(entry)
                    # Leave tombstone
                    remaining.append({
                        'id': entry.get('id'),
                        'archived_to': f"tower-{tower_num:03d}",
                        'was': entry.get('what', entry.get('key', '?'))[:60],
                        'session_archived': datetime.now(timezone.utc).strftime('%Y-%m-%d')
                    })
                else:
                    remaining.append(entry)
            cold[key] = remaining

        tower = {
            'schema_version': 2,
            'layer': 'tower',
            'tower_number': tower_num,
            'created': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'entries': tower_entries
        }

        write_json(buf_dir / tower_name, tower)
        write_json(buf_dir / 'handoff-cold.json', cold)

        result['archived'] = {
            'tower_file': tower_name,
            'entries_archived': len(tower_entries),
            'cold_lines_after': count_json_lines(cold)
        }
        print(f"Archived {len(tower_entries)} entries to {tower_name}", file=sys.stderr)
    else:
        print("Dependency map generated. Pass --entry-ids to archive specific entries.",
              file=sys.stderr)

    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: handoff — full pipeline: update + migrate + sync
#
# Accepts a changes file (alpha stash) via --input, then runs the complete
# sigma trunk pipeline in a single invocation.
# ---------------------------------------------------------------------------

def cmd_handoff(args):
    """Full handoff pipeline: update -> migrate -> sync.

    Accepts a changes file (alpha stash, same schema as 'update'), then runs
    the complete pipeline in a single invocation. This replaces calling update,
    migrate, and sync separately — saving 3 tool calls and ~50% of handoff
    tokens.

    The alpha stash schema:
    {
      "session_meta": { "date", "commit", "branch", "files_modified", "tests" },
      "active_work": { "current_phase", "completed_this_session", "in_progress", "blocked_by", "next_action" },
      "new_decisions": [ { "what", "chose", "why" } ],
      "open_threads": [ { "thread", "status", "ref?" } ],
      "instance_notes": { "from", "to", "remarks": [], "open_questions": [] },
      "natural_summary": "...",
      "concept_map_changes": [ { "action": "add|update|flag|promote", ... } ],
      "convergence_web_changes": [ { "action": "add|update", ... } ],
      "validation_log_entries": [ { "check", "status", "detail" } ]
    }
    """
    import types

    buf_dir = args.buffer_dir
    hot_max, warm_max, cold_max = resolve_limits(args)
    pipeline_report = []

    # --- Phase 1: Update (merge alpha stash into sigma trunk) ---
    update_args = types.SimpleNamespace(
        buffer_dir=buf_dir,
        input=args.input,
    )
    try:
        cmd_update(update_args)
        pipeline_report.append("update: OK")
    except SystemExit as e:
        if e.code and e.code != 0:
            pipeline_report.append(f"update: FAILED (exit {e.code})")
            result = {'status': 'error', 'phase': 'update', 'pipeline': pipeline_report}
            print(json.dumps(result, indent=2))
            sys.exit(1)

    # --- Phase 2: Migrate (conservation enforcement) ---
    migrate_args = types.SimpleNamespace(
        buffer_dir=buf_dir,
        warm_max=warm_max,
        hot_max=hot_max,
        cold_max=cold_max,
        dry_run=False,
    )
    try:
        cmd_migrate(migrate_args)
        pipeline_report.append("migrate: OK")
    except SystemExit as e:
        if e.code and e.code != 0:
            pipeline_report.append(f"migrate: FAILED (exit {e.code})")

    # --- Phase 3: Sync (MEMORY.md + project registry) ---
    sync_args = types.SimpleNamespace(
        buffer_dir=buf_dir,
        memory_path=args.memory_path,
        registry_path=args.registry_path,
        project_name=args.project_name,
    )
    try:
        cmd_sync(sync_args)
        pipeline_report.append("sync: OK")
    except SystemExit as e:
        if e.code and e.code != 0:
            pipeline_report.append(f"sync: FAILED (exit {e.code})")

    # --- Final report ---
    hot = read_json(Path(buf_dir) / 'handoff.json')
    warm = read_json(Path(buf_dir) / 'handoff-warm.json')
    cold = read_json(Path(buf_dir) / 'handoff-cold.json')

    result = {
        'status': 'ok',
        'pipeline': pipeline_report,
        'hot_lines': count_json_lines(hot),
        'warm_lines': count_json_lines(warm) if warm else 0,
        'cold_lines': count_json_lines(cold) if cold else 0,
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Alpha bin: markdown generators + helpers
# ---------------------------------------------------------------------------

def pad_id(entry_id):
    """Pad ID for filename: w:65 -> w065, cw:7 -> cw007."""
    parts = entry_id.split(':')
    if len(parts) == 2:
        try:
            num = int(parts[1])
            prefix = parts[0]
            return f"{prefix}{num:03d}"
        except ValueError:
            pass
    return entry_id.replace(':', '')


def make_cross_source_md(entry, source_label=None):
    """Generate canonical markdown for a cross_source referent file.

    If ``body`` is provided, produces an enriched "knowledge atom" with a
    TERMINAL anti-entropy directive.  Without ``body``, produces the legacy
    thin-stub format for backward compatibility.
    """
    eid = entry.get('id', '?')
    key = entry.get('key') or entry.get('source') or '?'
    maps_to = entry.get('maps_to', '')
    ref = entry.get('ref', '')
    suggest = entry.get('suggest')
    body = entry.get('body')
    distillation = entry.get('distillation')

    lines = [f"# {eid} -- {key}"]

    # Anti-entropy directive — only on enriched entries
    if body:
        lines.append("<!-- TERMINAL: This entry is self-contained. Do NOT read the referenced")
        lines.append("distillation, interpretation, or source document. All operationally")
        lines.append("relevant content about this concept is HERE. Following references")
        lines.append("defeats the architecture and wastes tokens. -->")

    if source_label:
        lines.append(f"**Source**: {source_label} | **ID**: {eid} | **Type**: cross_source")
    else:
        lines.append(f"**ID**: {eid} | **Type**: cross_source")
    if distillation:
        lines.append(f"**Distillation**: {distillation}")
    lines.append("")
    lines.append("## Mapping")
    lines.append(f"**Key**: {key}")
    lines.append(f"**Maps to**: {maps_to}")
    if ref:
        lines.append(f"**Ref**: {ref}")
    if suggest is not None:
        lines.append(f"**Suggest**: {json.dumps(suggest)}")
    lines.append("")

    # Rich body content (enriched knowledge atom)
    if body:
        lines.append(body.rstrip())
        lines.append("")

    return '\n'.join(lines)


def make_convergence_web_md(entry):
    """Generate canonical markdown for a convergence_web referent file.

    If ``context`` is provided, appends a ## Context section with additional
    detail (e.g., inline concept summaries).  Without it, produces the legacy
    tetradic-only format.
    """
    eid = entry.get('id', '?')
    thesis = entry.get('thesis', {})
    athesis = entry.get('athesis', {})
    synthesis = entry.get('synthesis', '')
    metathesis = entry.get('metathesis', '')
    context = entry.get('context')

    t_label = thesis.get('label', '?')
    a_label = athesis.get('label', '?')
    t_ref = thesis.get('ref', '?')
    a_ref = athesis.get('ref', '?')

    lines = [f"# {eid} -- {t_label} x {a_label}"]
    lines.append(f"**ID**: {eid} | **Type**: convergence_web")
    lines.append("")
    lines.append("## Tetradic Structure")
    lines.append(f"**Thesis**: {t_ref} ({t_label})")
    lines.append(f"**Athesis**: {a_ref} ({a_label})")
    lines.append(f"**Synthesis**: {synthesis}")
    lines.append(f"**Metathesis**: {metathesis}")
    lines.append("")

    if context:
        lines.append("## Context")
        lines.append(context.rstrip())
        lines.append("")

    return '\n'.join(lines)


def _parse_concept_key(concept_key):
    """Parse concept_key into (concept_name, source_prefix) for index updates."""
    if not concept_key or concept_key == '?':
        return None, None
    if ':' in concept_key:
        parts = concept_key.split(':', 1)
        prefix = parts[0].strip()
        name = parts[1].strip().lower()
        source_prefix = prefix if prefix and not prefix.startswith('_') else None
        return name or None, source_prefix
    return concept_key.strip().lower() or None, None


def alpha_update_index(index, new_id, entry_type, source_folder, concept_key,
                       filename, extra_fields=None):
    """Update all index structures for a new alpha entry.

    Handles: entries, sources, concept_index, source_index, summary counts.
    extra_fields: optional dict merged into the entry (convergence_tag, origin, etc.)
    """
    # entries
    entry = {
        "source": source_folder,
        "file": filename,
        "concept": concept_key,
        "type": entry_type
    }
    if extra_fields:
        entry.update(extra_fields)
    index.setdefault('entries', {})[new_id] = entry

    # sources
    sources = index.setdefault('sources', {})
    if source_folder not in sources:
        sources[source_folder] = {
            "folder": source_folder,
            "cross_source_ids": [],
            "convergence_web_ids": [],
            "entry_count": 0
        }
    src = sources[source_folder]
    id_list_key = 'convergence_web_ids' if entry_type == 'convergence_web' else 'cross_source_ids'
    if new_id not in src.get(id_list_key, []):
        src.setdefault(id_list_key, []).append(new_id)
    src['entry_count'] = len(src.get('cross_source_ids', [])) + len(src.get('convergence_web_ids', []))

    # concept_index + source_index
    concept_name, source_prefix = _parse_concept_key(concept_key)
    if concept_name:
        index.setdefault('concept_index', {}).setdefault(concept_name, []).append(new_id)
    if source_prefix:
        index.setdefault('source_index', {}).setdefault(source_prefix, []).append(new_id)

    # summary counts
    summary = index.setdefault('summary', {
        'total_cross_source': 0, 'total_convergence_web': 0,
        'total_framework': 0, 'total_sources': 0
    })
    if entry_type == 'convergence_web':
        summary['total_convergence_web'] = summary.get('total_convergence_web', 0) + 1
    else:
        summary['total_cross_source'] = summary.get('total_cross_source', 0) + 1
    summary['total_sources'] = len(sources)


def alpha_remove_from_index(index, entry_id):
    """Remove an entry from all index structures.

    Returns the removed entry info dict, or None if not found.
    """
    entries = index.get('entries', {})
    entry_info = entries.pop(entry_id, None)
    if not entry_info:
        return None

    source_folder = entry_info.get('source', '')
    entry_type = entry_info.get('type', 'cross_source')
    concept_key = entry_info.get('concept', '')

    # sources
    src = index.get('sources', {}).get(source_folder)
    if src:
        id_list_key = 'convergence_web_ids' if entry_type == 'convergence_web' else 'cross_source_ids'
        ids = src.get(id_list_key, [])
        if entry_id in ids:
            ids.remove(entry_id)
        src['entry_count'] = len(src.get('cross_source_ids', [])) + len(src.get('convergence_web_ids', []))
        # Remove empty source folders from index
        if src['entry_count'] == 0:
            index['sources'].pop(source_folder, None)

    # concept_index + source_index
    concept_name, source_prefix = _parse_concept_key(concept_key)
    if concept_name:
        clist = index.get('concept_index', {}).get(concept_name, [])
        if entry_id in clist:
            clist.remove(entry_id)
        if not clist:
            index.get('concept_index', {}).pop(concept_name, None)
    if source_prefix:
        slist = index.get('source_index', {}).get(source_prefix, [])
        if entry_id in slist:
            slist.remove(entry_id)
        if not slist:
            index.get('source_index', {}).pop(source_prefix, None)

    # summary counts
    summary = index.get('summary', {})
    if entry_type == 'convergence_web':
        summary['total_convergence_web'] = max(0, summary.get('total_convergence_web', 0) - 1)
    else:
        summary['total_cross_source'] = max(0, summary.get('total_cross_source', 0) - 1)
    summary['total_sources'] = len(index.get('sources', {}))

    return entry_info


# ---------------------------------------------------------------------------
# Alpha bin: path + read helpers
# ---------------------------------------------------------------------------

def alpha_index_path(buf_dir):
    """Return path to alpha/index.json if it exists, else None."""
    p = Path(buf_dir) / 'alpha' / 'index.json'
    return p if p.exists() else None


def read_alpha_index(buf_dir):
    """Read alpha index.json. Returns empty dict if alpha doesn't exist."""
    p = alpha_index_path(buf_dir)
    if not p:
        return {}
    return read_json(p)


def alpha_max_id(index, prefix):
    """Find the max numeric ID in the alpha index for a given prefix (w: or cw:).

    Scans BOTH the entries dict AND the sources dict to prevent
    stale-index collisions (the entries dict may be incomplete after
    an external rebuild — see 2026-03-18 incident report).
    """
    max_n = 0
    pattern = re.compile(rf'^{re.escape(prefix)}(\d+)$')
    # Source 1: entries dict (canonical per-entry registry)
    for eid in index.get('entries', {}):
        m = pattern.match(eid)
        if m:
            max_n = max(max_n, int(m.group(1)))
    # Source 2: sources dict (per-directory ID lists — may contain IDs
    # not yet in entries if the index was rebuilt incompletely)
    id_key = 'cross_source_ids' if prefix == 'w:' else 'convergence_web_ids'
    for src_data in index.get('sources', {}).values():
        for sid in src_data.get(id_key, []):
            m = pattern.match(sid)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n


def _alpha_disk_max_ids(alpha_dir):
    """Scan .md file headers on disk to find the true max w: and cw: IDs.

    This is a safety net against stale index.json — if the index was
    rebuilt incompletely, the entries dict may report a lower max than
    what actually exists on disk. Returns (max_w, max_cw).
    """
    max_w = 0
    max_cw = 0
    w_pattern = re.compile(r'^#\s+w:(\d+)')
    cw_pattern = re.compile(r'^#\s+cw:(\d+)')
    for root, dirs, files in os.walk(alpha_dir):
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = Path(root) / fname
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    header = f.readline()
            except Exception:
                continue
            m = w_pattern.match(header)
            if m:
                max_w = max(max_w, int(m.group(1)))
                continue
            m = cw_pattern.match(header)
            if m:
                max_cw = max(max_cw, int(m.group(1)))
    return max_w, max_cw


def alpha_all_ids(index):
    """Return set of all entry IDs in the alpha index."""
    return set(index.get('entries', {}).keys())


# ---------------------------------------------------------------------------
# Subcommand: alpha-read
# ---------------------------------------------------------------------------

def cmd_alpha_read(args):
    """Read alpha/index.json and output summary.

    Outputs JSON with summary stats, source list, and optional entry details.
    Used by /buffer:on to show alpha availability without loading all referents.
    """
    buf_dir = Path(args.buffer_dir)
    index = read_alpha_index(buf_dir)

    if not index:
        result = {
            'status': 'absent',
            'message': 'No alpha bin found. Reference memory not yet separated from warm layer.'
        }
        print(json.dumps(result, indent=2))
        return

    summary = index.get('summary', {})
    sources = index.get('sources', {})

    result = {
        'status': 'ok',
        'summary': summary,
        'sources': {
            name: {
                'folder': info.get('folder', name),
                'entry_count': info.get('entry_count', 0),
                'framework': info.get('framework', False),
            }
            for name, info in sources.items()
        },
        'schema_version': index.get('schema_version', '?'),
        'last_updated': index.get('last_updated', '?'),
    }

    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: alpha-query
# ---------------------------------------------------------------------------

def _find_distilled_dir(buf_dir):
    """Locate the project's distilled directory from the buffer dir.

    Derives project root from buf_dir (.claude/buffer/ → project root),
    then checks common distillation directory patterns.
    Returns Path or None.
    """
    project_root = buf_dir.parent.parent  # .claude/buffer/ → .claude/ → root
    for candidate in ['docs/references/distilled', 'docs/distilled', 'distilled']:
        d = project_root / candidate
        if d.is_dir():
            return d
    return None


def _extract_marker_content(distilled_dir, distillation_file, marker_key):
    """Extract content between CONCEPT markers from a distillation file.

    Returns extracted text or None if file/marker not found.
    """
    fpath = distilled_dir / distillation_file
    if not fpath.is_file():
        return None
    try:
        lines = fpath.read_text(encoding='utf-8').splitlines(keepends=True)
    except OSError:
        return None

    open_tag = f'<!-- CONCEPT:{marker_key} -->'
    close_tag = f'<!-- /CONCEPT:{marker_key} -->'
    capturing = False
    captured = []

    for line in lines:
        stripped = line.strip()
        if stripped == open_tag:
            capturing = True
            continue
        if stripped == close_tag:
            capturing = False
            continue
        if capturing:
            captured.append(line)

    return ''.join(captured) if captured else None


def cmd_alpha_query(args):
    """Query alpha bin for specific referents.

    Supports three query modes:
      --id w:218        → Retrieve single entry by ID
      --source sartre   → List all entries from a source (case-insensitive prefix match)
      --concept total   → Search concept_index for matching terms

    When entries have 'distillation' and 'marker' fields, retrieves content
    via marker extraction from distillation files (script-based retrieval).
    Falls back to reading alpha .md files when markers are absent or fail.
    """
    buf_dir = Path(args.buffer_dir)
    alpha_dir = buf_dir / 'alpha'
    index = read_alpha_index(buf_dir)

    if not index:
        print(json.dumps({'status': 'absent', 'message': 'No alpha bin found.'}))
        return

    entries = index.get('entries', {})
    results = []

    if args.id:
        # Direct ID lookup — batch by distillation file for efficiency
        distilled_dir = _find_distilled_dir(buf_dir)

        # Group entries by distillation file for batch extraction
        by_distillation = {}  # distillation_file → [(qid, marker_key)]
        fallback_ids = []     # IDs without marker fields

        for qid in args.id:
            if qid not in entries:
                results.append({'id': qid, 'status': 'not_found'})
                continue
            info = entries[qid]
            dist_file = info.get('distillation')
            marker = info.get('marker')
            if distilled_dir and dist_file and marker:
                by_distillation.setdefault(dist_file, []).append((qid, marker))
            else:
                fallback_ids.append(qid)

        # Batch marker extraction: one file read per distillation
        marker_cache = {}  # (dist_file, marker) → content
        for dist_file, id_markers in by_distillation.items():
            fpath = distilled_dir / dist_file
            if not fpath.is_file():
                # File missing — fall back to .md for all entries
                fallback_ids.extend(qid for qid, _ in id_markers)
                continue
            try:
                lines = fpath.read_text(encoding='utf-8').splitlines(keepends=True)
            except OSError:
                fallback_ids.extend(qid for qid, _ in id_markers)
                continue

            # Extract all needed markers from this file in a single pass
            needed_markers = {m for _, m in id_markers}
            open_tags = {f'<!-- CONCEPT:{m} -->': m for m in needed_markers}
            close_tags = {f'<!-- /CONCEPT:{m} -->': m for m in needed_markers}
            current_marker = None
            captured = {}  # marker → [lines]

            for line in lines:
                stripped = line.strip()
                if stripped in open_tags:
                    current_marker = open_tags[stripped]
                    captured.setdefault(current_marker, [])
                    continue
                if stripped in close_tags:
                    current_marker = None
                    continue
                if current_marker is not None:
                    captured[current_marker].append(line)

            for qid, marker in id_markers:
                content = ''.join(captured.get(marker, []))
                if content:
                    marker_cache[(dist_file, marker)] = content
                else:
                    fallback_ids.append(qid)

        # Build results: marker-retrieved entries
        for dist_file, id_markers in by_distillation.items():
            for qid, marker in id_markers:
                if qid in [r['id'] for r in results]:
                    continue  # Already added (not_found)
                content = marker_cache.get((dist_file, marker))
                if content:
                    info = entries[qid]
                    results.append({
                        'id': qid,
                        'source': info.get('source', '?'),
                        'concept': info.get('concept', '?'),
                        'file': info['file'],
                        'content': content,
                        'retrieval': 'marker'
                    })

        # Fallback: read .md files for entries without markers
        for qid in fallback_ids:
            if qid in [r['id'] for r in results]:
                continue
            info = entries[qid]
            fpath = alpha_dir / info['file'].replace('/', os.sep)
            content = ''
            if fpath.exists():
                try:
                    content = fpath.read_text(encoding='utf-8')
                except OSError:
                    content = '[read error]'
            results.append({
                'id': qid,
                'source': info.get('source', '?'),
                'concept': info.get('concept', '?'),
                'file': info['file'],
                'content': content,
                'retrieval': 'file'
            })

    elif args.source:
        # Source prefix search (case-insensitive)
        query = args.source.lower()
        # Search source_index first
        si = index.get('source_index', {})
        matched_ids = set()
        for src_key, ids in si.items():
            if src_key.lower().startswith(query) or query in src_key.lower():
                matched_ids.update(ids)
        # Also check folder names
        for eid, info in entries.items():
            if query in info.get('source', '').lower():
                matched_ids.add(eid)

        for eid in sorted(matched_ids, key=lambda x: (x.split(':')[0], int(x.split(':')[1]) if x.split(':')[1].isdigit() else 0)):
            info = entries.get(eid, {})
            results.append({
                'id': eid,
                'source': info.get('source', '?'),
                'concept': info.get('concept', '?'),
                'file': info.get('file', '?')
            })

    elif args.concept:
        # Concept search (case-insensitive, partial match)
        query = args.concept.lower()
        ci = index.get('concept_index', {})
        matched_ids = set()
        for concept_key, ids in ci.items():
            if query in concept_key:
                matched_ids.update(ids)

        for eid in sorted(matched_ids, key=lambda x: (x.split(':')[0], int(x.split(':')[1]) if x.split(':')[1].isdigit() else 0)):
            info = entries.get(eid, {})
            results.append({
                'id': eid,
                'source': info.get('source', '?'),
                'concept': info.get('concept', '?'),
                'file': info.get('file', '?')
            })

    output = {
        'status': 'ok',
        'count': len(results),
        'results': results
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Subcommand: alpha-validate
# ---------------------------------------------------------------------------

def cmd_alpha_validate(args):
    """Validate alpha bin integrity: index vs files on disk.

    Checks:
    1. Every index entry has a corresponding file on disk
    2. Every .md file on disk has a corresponding index entry
    3. No duplicate IDs
    4. Schema consistency (all entries have required fields)
    """
    buf_dir = Path(args.buffer_dir)
    alpha_dir = buf_dir / 'alpha'
    index = read_alpha_index(buf_dir)

    if not index:
        print(json.dumps({'status': 'absent', 'message': 'No alpha bin found.'}))
        return

    issues = []
    info = []
    entries = index.get('entries', {})

    # Check 1: Index entries -> files on disk
    missing_files = []
    for eid, entry_info in entries.items():
        fpath = alpha_dir / entry_info['file'].replace('/', os.sep)
        if not fpath.exists():
            missing_files.append(eid)
    if missing_files:
        issues.append(f"Index entries with missing files: {len(missing_files)}")
        for eid in missing_files[:10]:
            issues.append(f"  Missing: {eid} -> {entries[eid]['file']}")

    # Check 2: Files on disk -> index entries
    indexed_files = {e['file'] for e in entries.values()}
    orphan_files = []
    for root, dirs, files in os.walk(alpha_dir):
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(alpha_dir)).replace(os.sep, '/')
            if rel not in indexed_files:
                # Framework files are indexed by group, not by individual entry
                # Check if it's a framework group file
                if rel.startswith('_framework/'):
                    group_name = fname[:-3]
                    # Verify group is in sources
                    fw_sources = index.get('sources', {}).get('_framework', {})
                    if group_name in fw_sources.get('groups', []):
                        continue  # Expected framework file
                orphan_files.append(rel)
    if orphan_files:
        issues.append(f"Orphan files (on disk but not in index): {len(orphan_files)}")
        for f in orphan_files[:10]:
            issues.append(f"  Orphan: {f}")

    # Check 3: Schema consistency
    missing_fields = 0
    for eid, entry_info in entries.items():
        if not entry_info.get('source'):
            missing_fields += 1
            issues.append(f"  {eid}: missing 'source' field")
        if not entry_info.get('file'):
            missing_fields += 1
            issues.append(f"  {eid}: missing 'file' field")
    if missing_fields:
        issues.insert(0, f"Schema issues: {missing_fields} entries with missing fields")

    # Check 4: Distillation file references
    distilled_dir = _find_distilled_dir(buf_dir)
    if distilled_dir:
        stale_refs = []
        for eid, entry_info in entries.items():
            dist_file = entry_info.get('distillation')
            if dist_file and not (distilled_dir / dist_file).is_file():
                stale_refs.append(eid)
        if stale_refs:
            issues.append(f"Stale distillation references: {len(stale_refs)}")
            for eid in stale_refs[:10]:
                issues.append(f"  Stale: {eid} -> {entries[eid]['distillation']}")

    # Summary
    summary = index.get('summary', {})
    info.append(f"Framework entries: {summary.get('total_framework', 0)}")
    info.append(f"Cross-source entries: {summary.get('total_cross_source', 0)}")
    info.append(f"Convergence web entries: {summary.get('total_convergence_web', 0)}")
    info.append(f"Source folders: {summary.get('total_sources', 0)}")
    info.append(f"Schema version: {index.get('schema_version', '?')}")

    result = {
        'status': 'ok' if not issues else 'issues_found',
        'issues': issues,
        'info': info,
        'summary': summary
    }
    print(json.dumps(result, indent=2))

    if issues:
        print(f"\n{len(issues)} issue(s) found:", file=sys.stderr)
        for i in issues:
            print(f"  ! {i}", file=sys.stderr)
    else:
        print("Alpha bin integrity check passed.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Backfill: convergence_tag + origin for existing entries
# ---------------------------------------------------------------------------

def backfill_convergence_tags(buf_dir, index):
    """Scan cw: .md files and backfill convergence_tag + origin into index.

    Parses **Synthesis**: [tag] lines from .md files.
    Sets origin based on source folder heuristic.
    Returns count of entries updated.
    """
    alpha_dir = buf_dir / 'alpha'
    entries = index.get('entries', {})
    updated = 0

    for eid, einfo in entries.items():
        changed = False

        # Backfill convergence_tag for cw: entries
        if eid.startswith('cw:') and 'convergence_tag' not in einfo:
            md_path = alpha_dir / einfo.get('file', '')
            if md_path.exists():
                try:
                    text = md_path.read_text(encoding='utf-8')
                    for line in text.splitlines():
                        if line.startswith('**Synthesis**:'):
                            tag_match = re.match(
                                r'\*\*Synthesis\*\*:\s*\[(\w+)\]', line)
                            if tag_match:
                                einfo['convergence_tag'] = tag_match.group(1)
                                changed = True
                            break
                except OSError:
                    pass

        # Backfill origin for all entries
        if 'origin' not in einfo:
            source = einfo.get('source', '')
            if source in ('_framework', 'unificity'):
                einfo['origin'] = 'session'
            else:
                einfo['origin'] = 'distill'
            changed = True

        if changed:
            updated += 1

    return updated


def _read_sigma_hits(buf_dir):
    """Parse .sigma_hits log into per-concept temporal data."""
    hits_path = buf_dir / '.sigma_hits'
    if not hits_path.exists():
        return {}
    temporal = {}
    try:
        with open(hits_path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                date_str = parts[0]
                for cid in parts[1:]:
                    if cid.startswith('w:'):
                        if cid not in temporal:
                            temporal[cid] = {
                                'ref_count': 0,
                                'first_ref': date_str,
                                'last_ref': date_str,
                            }
                        temporal[cid]['ref_count'] += 1
                        temporal[cid]['last_ref'] = date_str
    except OSError:
        pass
    return temporal


def _read_sigma_errors(buf_dir):
    """Parse .sigma_errors JSONL into prediction error summary.

    Returns dict with gap_keywords (keyword -> count) and false_pos_count.
    """
    errors_path = buf_dir / '.sigma_errors'
    if not errors_path.exists():
        return {'gap_keywords': {}, 'false_pos_count': 0, 'total_errors': 0}

    gap_keywords = {}
    false_pos_count = 0
    total = 0
    try:
        with open(errors_path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                if entry.get('type') == 'gap':
                    for kw in entry.get('keywords', []):
                        gap_keywords[kw] = gap_keywords.get(kw, 0) + 1
                elif entry.get('type') == 'false_pos':
                    false_pos_count += 1
    except OSError:
        pass

    return {
        'gap_keywords': gap_keywords,
        'false_pos_count': false_pos_count,
        'total_errors': total,
    }


def compute_phase_state(buf_dir, index, temporal_data, error_data):
    """Compute buffer phase state vector for trajectory tracking.

    The buffer is a dynamical system with observable state variables:
      - hot_usage: hot layer line count / max
      - alpha_density: w: entries / (w: + unresolved)
      - W_ratio: wholeness energy (coherence)
      - W_prime: wholeness gradient (learning rate)
      - hit_rate: sigma hits / total messages (engagement)
      - error_rate: prediction errors / total (blind spots)
      - cluster_count: structural complexity

    Tracking this vector over sessions reveals trajectories, attractors,
    and bifurcation candidates (Kirsanov Neural Dynamics).
    """
    entries = index.get('entries', {})
    w_count = sum(1 for e in entries if e.startswith('w:'))
    cw_count = sum(1 for e in entries if e.startswith('cw:'))
    wholeness = index.get('wholeness', {})
    clusters = index.get('clusters', [])

    # Read sigma scores for W'
    scores_path = buf_dir / '.sigma_scores'
    sigma_scores = {}
    if scores_path.exists():
        try:
            with open(scores_path, 'r', encoding='utf-8-sig') as f:
                sigma_scores = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Read tick counter for hit rate computation
    ticks_path = buf_dir / '.sigma_ticks'
    total_ticks = 0
    try:
        if ticks_path.exists():
            with open(ticks_path, 'r') as f:
                total_ticks = int(f.read().strip() or '0')
    except (ValueError, OSError):
        pass

    total_hits = sum(t.get('ref_count', 0) for t in temporal_data.values())
    total_errors = error_data.get('total_errors', 0)

    return {
        'w_entries': w_count,
        'cw_entries': cw_count,
        'W': wholeness.get('W', 0),
        'W_ratio': wholeness.get('W_ratio', 0.0),
        'W_prime': sigma_scores.get('__W_prime', 0),
        'active_concepts': wholeness.get('active_count', 0),
        'cluster_count': len(clusters),
        'total_hits': total_hits,
        'total_errors': total_errors,
        'total_ticks': total_ticks,
        'hit_rate': round(total_hits / max(total_ticks, 1), 4),
        'error_rate': round(total_errors / max(total_ticks, 1), 4),
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
    }


def record_phase_trajectory(buf_dir, state):
    """Append phase state to .buffer_trajectory (JSONL).

    Each line is a dated snapshot of the buffer's dynamical state.
    Deduplicates by date — only one entry per day.
    """
    traj_path = buf_dir / '.buffer_trajectory'

    # Check if today already recorded
    today = state.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    existing_lines = []
    try:
        if traj_path.exists():
            with open(traj_path, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get('date') == today:
                            continue  # replace today's entry
                    except json.JSONDecodeError:
                        pass
                    existing_lines.append(line)
    except OSError:
        pass

    existing_lines.append(json.dumps(state))

    try:
        with open(traj_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(existing_lines) + '\n')
    except OSError:
        pass


def _read_phase_trajectory(buf_dir, last_n=10):
    """Read recent phase trajectory entries."""
    traj_path = buf_dir / '.buffer_trajectory'
    if not traj_path.exists():
        return []

    entries = []
    try:
        with open(traj_path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass

    return entries[-last_n:]


def _read_coactivation(buf_dir):
    """Read .sigma_coactivation resonator data.

    Returns dict of 'id_a|id_b' -> count (co-firing frequency).
    """
    coact_path = buf_dir / '.sigma_coactivation'
    if not coact_path.exists():
        return {}
    try:
        with open(coact_path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Subcommand: alpha-reinforce
# ---------------------------------------------------------------------------

def _parse_cw_concept(concept_str):
    """Parse a cw: concept field into (thesis_key, athesis_key).

    Format: 'Source:concept_a x Source:concept_b'
    Returns (concept_a_lower, concept_b_lower) with source prefixes stripped.
    Returns (None, None) if unparseable.
    """
    parts = concept_str.split(' x ')
    if len(parts) != 2:
        return None, None
    keys = []
    for part in parts:
        part = part.strip()
        if ':' in part:
            part = part.split(':', 1)[1]
        keys.append(part.lower())
    return keys[0], keys[1]


def _resolve_concept_to_wids(concept_key, concept_index, entries):
    """Resolve a concept name (lowercase) to w: IDs.

    Tries: exact concept_index match, case-insensitive concept_index scan,
    normalized match (underscores/hyphens/slashes), then substring match
    against w: entries' concept fields.
    """
    if concept_key in concept_index:
        return concept_index[concept_key]
    # Case-insensitive exact match
    for idx_key, wids in concept_index.items():
        if idx_key == '?':
            continue
        if concept_key == idx_key.lower():
            return wids
    # Normalized match: collapse separators for near-misses
    def _normalize(s):
        return s.lower().replace('-', '_').replace('/', '_').replace('+', '_').replace(' ', '_')
    norm_key = _normalize(concept_key)
    for idx_key, wids in concept_index.items():
        if idx_key == '?':
            continue
        if norm_key == _normalize(idx_key):
            return wids
    # Direct match against w: entry concept fields
    results = []
    for eid, einfo in entries.items():
        if not eid.startswith('w:'):
            continue
        econcept = einfo.get('concept', '')
        econcept_name = econcept.split(':', 1)[1].lower() if ':' in econcept else econcept.lower()
        if concept_key == econcept_name or norm_key == _normalize(econcept_name):
            results.append(eid)
    if results:
        return results
    # Substring containment: last resort for partial matches
    for eid, einfo in entries.items():
        if not eid.startswith('w:'):
            continue
        econcept = einfo.get('concept', '')
        econcept_name = econcept.split(':', 1)[1].lower() if ':' in econcept else econcept.lower()
        enorm = _normalize(econcept_name)
        if len(norm_key) >= 5 and (norm_key in enorm or enorm in norm_key):
            results.append(eid)
    return results


def build_cw_graph(entries, concept_index):
    """Build adjacency graph from convergence_web entries.

    Returns:
        cw_edges: {cw_id: {'thesis': w_id, 'athesis': w_id}}
        w_to_cw: {w_id: set(cw_ids)}
        unresolved: [cw_ids with unparseable concepts]
    """
    cw_edges = {}
    w_to_cw = {}
    unresolved = []
    for eid, einfo in entries.items():
        if not eid.startswith('cw:'):
            continue
        if einfo.get('type') != 'convergence_web':
            continue
        concept_str = einfo.get('concept', '')
        thesis_key, athesis_key = _parse_cw_concept(concept_str)
        if thesis_key is None or athesis_key is None:
            unresolved.append(eid)
            continue
        thesis_wids = _resolve_concept_to_wids(thesis_key, concept_index, entries)
        athesis_wids = _resolve_concept_to_wids(athesis_key, concept_index, entries)
        if not thesis_wids or not athesis_wids:
            unresolved.append(eid)
            continue
        t_wid = thesis_wids[0]
        a_wid = athesis_wids[0]
        cw_edges[eid] = {'thesis': t_wid, 'athesis': a_wid}
        w_to_cw.setdefault(t_wid, set()).add(eid)
        w_to_cw.setdefault(a_wid, set()).add(eid)
    return cw_edges, w_to_cw, unresolved


def compute_reinforcement(entries, concept_index, sources_data,
                          temporal_data=None):
    """Compute reinforcement degree, prime status, and temporal metrics.

    TAP score components: degree (adjacency), source_diversity, is_prime,
    plus temporal feedback from sigma_hits (ref_count, last_ref, trend).

    Returns:
        reinforcement: {w_id: {'degree': int, 'source_diversity': int,
                        'is_prime': bool, 'ref_count': int, ...}}
        cw_edges: resolved graph from build_cw_graph
        unresolved: list of unresolvable cw: IDs
    """
    cw_edges, w_to_cw, unresolved = build_cw_graph(entries, concept_index)
    reinforcement = {}
    nonzero_degrees = []
    for eid in entries:
        if not eid.startswith('w:'):
            continue
        cw_set = w_to_cw.get(eid, set())
        degree = len(cw_set)
        linked_sources = set()
        for cw_id in cw_set:
            edge = cw_edges.get(cw_id, {})
            other_wid = edge.get('thesis') if edge.get('athesis') == eid else edge.get('athesis')
            if other_wid and other_wid in entries:
                linked_sources.add(entries[other_wid].get('source', ''))
        rdata = {
            'degree': degree,
            'source_diversity': len(linked_sources),
            'is_prime': False,
        }
        # Temporal augmentation (bidirectional sigma→alpha feedback)
        if temporal_data:
            t = temporal_data.get(eid, {})
            rdata['ref_count'] = t.get('ref_count', 0)
            rdata['last_ref'] = t.get('last_ref', None)
            rdata['trend'] = t.get('trend', 'stable')
        else:
            rdata['ref_count'] = 0
            rdata['last_ref'] = None
            rdata['trend'] = 'unknown'
        reinforcement[eid] = rdata
        if degree > 0:
            nonzero_degrees.append(degree)
    # Prime threshold: median of nonzero degrees + source diversity >= 2
    if nonzero_degrees:
        sorted_deg = sorted(nonzero_degrees)
        prime_threshold = sorted_deg[len(sorted_deg) // 2]
    else:
        prime_threshold = 1
    for eid, rdata in reinforcement.items():
        if rdata['degree'] >= prime_threshold and rdata['source_diversity'] >= 2:
            rdata['is_prime'] = True
    return reinforcement, cw_edges, unresolved


def compute_wholeness(cw_edges, active_set):
    """Compute wholeness W — coherence of the active concept field.

    W = count of convergence web edges where both endpoints are active.
    Derived from Hopfield energy: E = -1/2 * sum(w_ij * s_i * s_j)
    (Alexander's Wholeness as computational measure of system coherence.)

    Args:
        cw_edges: {cw_id: {'thesis': w_id, 'athesis': w_id}}
        active_set: set of w: IDs considered active (from sigma_hits)

    Returns:
        dict with W, W_potential, W_ratio, active_count
    """
    if not cw_edges:
        return {'W': 0, 'W_potential': 0, 'W_ratio': 0.0, 'active_count': 0}

    w_active = sum(
        1 for edge in cw_edges.values()
        if edge['thesis'] in active_set and edge['athesis'] in active_set
    )
    w_potential = len(cw_edges)
    return {
        'W': w_active,
        'W_potential': w_potential,
        'W_ratio': round(w_active / w_potential, 4) if w_potential > 0 else 0.0,
        'active_count': len(active_set),
    }


def build_adjacency_cache(cw_edges, entries):
    """Build compact adjacency list + concept names from cw_graph.

    Written to .cw_adjacency for sigma hook to use in spreading activation
    and incremental wholeness updates without loading full index.json.
    """
    adj = {}
    involved = set()
    for edge in cw_edges.values():
        t, a = edge['thesis'], edge['athesis']
        adj.setdefault(t, [])
        adj.setdefault(a, [])
        if a not in adj[t]:
            adj[t].append(a)
        if t not in adj[a]:
            adj[a].append(t)
        involved.add(t)
        involved.add(a)

    concepts = {}
    for wid in involved:
        einfo = entries.get(wid, {})
        concept = einfo.get('concept', '?')
        if ':' in concept:
            concept = concept.split(':', 1)[1]
        concepts[wid] = concept

    return adj, concepts


def cmd_alpha_reinforce(args):
    """Compute reinforcement scores and cw_graph, write to index.json."""
    buf_dir = Path(args.buffer_dir)
    index = read_alpha_index(buf_dir)
    if not index:
        print(json.dumps({'status': 'error', 'message': 'No alpha bin found'}))
        return

    # Auto-backfill convergence_tag + origin if any entries lack them
    entries = index.get('entries', {})
    needs_backfill = any(
        ('origin' not in e) or (eid.startswith('cw:') and 'convergence_tag' not in e)
        for eid, e in entries.items()
    )
    if needs_backfill:
        backfill_count = backfill_convergence_tags(buf_dir, index)
        if backfill_count > 0:
            print(f"Backfilled {backfill_count} entries (convergence_tag + origin)",
                  file=sys.stderr)

    concept_index = index.get('concept_index', {})
    sources_data = index.get('sources', {})

    # Read temporal data from sigma hits (bidirectional feedback)
    temporal_data = _read_sigma_hits(buf_dir)

    reinforcement, cw_edges, unresolved = compute_reinforcement(
        entries, concept_index, sources_data, temporal_data)
    primes = [eid for eid, r in reinforcement.items() if r['is_prime']]
    max_degree = max((r['degree'] for r in reinforcement.values()), default=0)
    result_summary = {
        'total_scored': len(reinforcement),
        'cw_edges_resolved': len(cw_edges),
        'unresolved_cw': len(unresolved),
        'primes_identified': len(primes),
        'max_reinforcement_degree': max_degree,
    }
    if unresolved:
        result_summary['unresolved_ids'] = unresolved[:10]
    if args.dry_run:
        top = sorted(reinforcement.items(),
                     key=lambda x: x[1]['degree'], reverse=True)[:20]
        result_summary['top_20'] = [
            {'id': eid, **rdata,
             'concept': entries.get(eid, {}).get('concept', '?')}
            for eid, rdata in top
        ]
        print(json.dumps(result_summary, indent=2))
        return
    index['reinforcement'] = reinforcement
    index['cw_graph'] = cw_edges
    index['reinforcement_computed'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Wholeness computation (Alexander-Hopfield energy)
    active_set = set(temporal_data.keys()) if temporal_data else set()
    wholeness = compute_wholeness(cw_edges, active_set)
    index['wholeness'] = wholeness

    idx_path = alpha_index_path(buf_dir)
    write_json(idx_path, index)

    # Adjacency cache for sigma hook (spreading activation + incremental W)
    adj, adj_concepts = build_adjacency_cache(cw_edges, entries)
    write_json(str(buf_dir / '.cw_adjacency'), {
        'adjacency': adj,
        'concepts': adj_concepts,
        'edge_count': len(cw_edges),
        'computed': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
    })

    # Phase portrait: record trajectory snapshot at batch checkpoint
    error_data = _read_sigma_errors(buf_dir)
    phase_state = compute_phase_state(buf_dir, index, temporal_data, error_data)
    record_phase_trajectory(buf_dir, phase_state)

    result_summary['status'] = 'ok'
    result_summary['wholeness'] = wholeness
    result_summary['phase_state'] = phase_state
    result_summary['message'] = (
        f"Wrote reinforcement ({len(reinforcement)} entries) + "
        f"cw_graph ({len(cw_edges)} edges) + wholeness (W={wholeness['W']}) "
        f"to index.json. Adjacency cache: {len(adj)} concepts. "
        f"Phase trajectory updated."
    )
    print(json.dumps(result_summary, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: alpha-clusters
# ---------------------------------------------------------------------------

def compute_clusters(cw_edges, reinforcement_data, entries):
    """Compute connected components from cw: adjacency via BFS.

    Returns list of cluster dicts + w_to_cluster mapping.
    """
    # Build undirected adjacency list from cw edges
    # Wall edges are anti-edges (inhibitory) — do NOT connect
    adj = {}
    for cw_id, edge in cw_edges.items():
        tag = entries.get(cw_id, {}).get('convergence_tag', '')
        if tag == 'wall':
            continue  # Wall edges inhibit — must not conflate
        t, a = edge['thesis'], edge['athesis']
        adj.setdefault(t, set()).add(a)
        adj.setdefault(a, set()).add(t)

    visited = set()
    clusters = []

    for start_node in sorted(adj.keys()):
        if start_node in visited:
            continue
        # BFS
        component = set()
        queue = [start_node]
        while queue:
            node = queue.pop(0)
            if node in component:
                continue
            component.add(node)
            visited.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in component:
                    queue.append(neighbor)

        members = sorted(component)

        # Internal edges: cw edges where BOTH endpoints are in this component
        internal_edges = []
        bridge_edges = []
        for cw_id, edge in cw_edges.items():
            t_in = edge['thesis'] in component
            a_in = edge['athesis'] in component
            if t_in and a_in:
                internal_edges.append(cw_id)
            elif t_in or a_in:
                bridge_edges.append(cw_id)

        # Internal density: actual edges / possible edges
        n = len(members)
        possible = n * (n - 1) / 2 if n > 1 else 1
        internal_density = round(len(internal_edges) / possible, 3)

        # Hubs: members with reinforcement >= cluster median
        member_degrees = [
            reinforcement_data.get(m, {}).get('degree', 0) for m in members
        ]
        if member_degrees:
            sorted_md = sorted(member_degrees)
            cluster_median = sorted_md[len(sorted_md) // 2]
        else:
            cluster_median = 0

        hubs = [
            m for m in members
            if reinforcement_data.get(m, {}).get('degree', 0) >= max(cluster_median, 1)
        ]

        # Derive name from top hub concepts
        hub_concepts = []
        for h in hubs[:2]:
            c = entries.get(h, {}).get('concept', h)
            if ':' in c:
                c = c.split(':', 1)[1]
            hub_concepts.append(c.lower().replace(' ', '_')[:25])
        name = '-'.join(hub_concepts) if hub_concepts else f'cluster_{len(clusters)}'

        clusters.append({
            'id': len(clusters),
            'name': name,
            'members': members,
            'hubs': sorted(hubs),
            'cw_edges': sorted(internal_edges),
            'internal_density': internal_density,
            'bridge_count': len(bridge_edges),
            'size': n,
        })

    # w_to_cluster mapping
    w_to_cluster = {}
    for cluster in clusters:
        for m in cluster['members']:
            w_to_cluster[m] = cluster['id']

    return clusters, w_to_cluster


def cmd_alpha_clusters(args):
    """Compute cluster analysis from convergence_web adjacency."""
    buf_dir = Path(args.buffer_dir)
    index = read_alpha_index(buf_dir)
    if not index:
        print(json.dumps({'status': 'error', 'message': 'No alpha bin found'}))
        return

    # Requires reinforcement data (run alpha-reinforce first)
    cw_edges = index.get('cw_graph', {})
    reinforcement = index.get('reinforcement', {})
    if not cw_edges:
        print(json.dumps({
            'status': 'error',
            'message': 'No cw_graph found. Run alpha-reinforce first.'
        }))
        return

    entries = index.get('entries', {})
    clusters, w_to_cluster = compute_clusters(cw_edges, reinforcement, entries)

    result_summary = {
        'total_clusters': len(clusters),
        'largest_cluster': max((c['size'] for c in clusters), default=0),
        'isolates': len([eid for eid in entries
                         if eid.startswith('w:') and eid not in w_to_cluster]),
        'cluster_names': [c['name'] for c in clusters],
    }

    if args.dry_run:
        result_summary['clusters'] = clusters
        print(json.dumps(result_summary, indent=2))
        return

    index['clusters'] = clusters
    index['w_to_cluster'] = w_to_cluster
    index['clusters_computed'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    idx_path = alpha_index_path(buf_dir)
    write_json(idx_path, index)
    result_summary['status'] = 'ok'
    result_summary['message'] = f'Wrote {len(clusters)} clusters to index.json'
    print(json.dumps(result_summary, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: alpha-neighborhood
# ---------------------------------------------------------------------------

def traverse_neighborhood(start_id, cw_edges, entries, reinforcement_data,
                          max_hops=2):
    """BFS traversal from a w: or cw: ID through convergence_web edges.

    Returns subgraph with distance and reinforcement annotations.
    Weights by walk distance: score = degree / (1 + distance).
    """
    # If start_id is a cw: entry, expand to its thesis + athesis
    start_nodes = set()
    if start_id.startswith('cw:') and start_id in cw_edges:
        edge = cw_edges[start_id]
        start_nodes.add(edge['thesis'])
        start_nodes.add(edge['athesis'])
    elif start_id.startswith('w:'):
        start_nodes.add(start_id)
    else:
        return {'error': f'Unknown ID format: {start_id}'}

    # Build undirected adjacency with cw edge labels
    adj = {}  # w_id -> [(neighbor_w_id, cw_id), ...]
    for cw_id, edge in cw_edges.items():
        t, a = edge['thesis'], edge['athesis']
        adj.setdefault(t, []).append((a, cw_id))
        adj.setdefault(a, []).append((t, cw_id))

    # BFS with distance tracking
    nodes = {}
    edges_out = []
    queue = [(n, 0) for n in start_nodes]
    visited = set()

    for n in start_nodes:
        rdata = reinforcement_data.get(n, {})
        concept = entries.get(n, {}).get('concept', '?')
        nodes[n] = {
            'distance': 0,
            'reinforcement': rdata.get('degree', 0),
            'is_prime': rdata.get('is_prime', False),
            'concept': concept,
            'weighted_score': round(rdata.get('degree', 0) / 1.0, 2),
        }
        visited.add(n)

    while queue:
        current, dist = queue.pop(0)
        if dist >= max_hops:
            continue
        for neighbor, cw_id in adj.get(current, []):
            tag = entries.get(cw_id, {}).get('convergence_tag', '')
            is_wall = (tag == 'wall')
            edges_out.append({
                'cw': cw_id, 'from': current, 'to': neighbor,
                'hop': dist + 1, 'wall': is_wall
            })
            if is_wall:
                continue  # Wall edges are boundaries — do NOT traverse through
            if neighbor not in visited:
                visited.add(neighbor)
                rdata = reinforcement_data.get(neighbor, {})
                concept = entries.get(neighbor, {}).get('concept', '?')
                degree = rdata.get('degree', 0)
                nodes[neighbor] = {
                    'distance': dist + 1,
                    'reinforcement': degree,
                    'is_prime': rdata.get('is_prime', False),
                    'concept': concept,
                    'weighted_score': round(degree / (1 + dist + 1), 2),
                }
                queue.append((neighbor, dist + 1))

    return {
        'center': start_id,
        'nodes': nodes,
        'edges': edges_out,
        'total_nodes': len(nodes),
        'total_edges': len(edges_out),
    }


def cmd_alpha_neighborhood(args):
    """Traverse convergence_web neighborhood from a given ID."""
    buf_dir = Path(args.buffer_dir)
    index = read_alpha_index(buf_dir)
    if not index:
        print(json.dumps({'status': 'error', 'message': 'No alpha bin found'}))
        return
    cw_edges = index.get('cw_graph', {})
    reinforcement = index.get('reinforcement', {})
    if not cw_edges:
        print(json.dumps({
            'status': 'error',
            'message': 'No cw_graph found. Run alpha-reinforce first.'
        }))
        return
    entries = index.get('entries', {})
    result = traverse_neighborhood(
        args.id, cw_edges, entries, reinforcement, max_hops=args.hops)
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: alpha-health
# ---------------------------------------------------------------------------

def cmd_alpha_health(args):
    """Generate alpha bin health diagnostics report."""
    buf_dir = Path(args.buffer_dir)
    index = read_alpha_index(buf_dir)
    if not index:
        print("Alpha bin not found.")
        return

    entries = index.get('entries', {})
    reinforcement = index.get('reinforcement', {})
    cw_edges = index.get('cw_graph', {})
    clusters = index.get('clusters', [])

    w_count = sum(1 for e in entries if e.startswith('w:'))
    cw_count = sum(1 for e in entries if e.startswith('cw:'))
    possible_pairs = w_count * (w_count - 1) / 2 if w_count > 1 else 1
    youn_ratio = round(cw_count / possible_pairs, 6) if possible_pairs > 0 else 0

    # Type diversity: parse [type_tag] from cw concept fields or cw .md files
    type_counts = {}
    for cw_id in cw_edges:
        einfo = entries.get(cw_id, {})
        concept = einfo.get('concept', '')
        # Type tags are stored in cw .md files, not index — approximate from source
        source = einfo.get('source', 'unknown')
        type_counts[source] = type_counts.get(source, 0) + 1

    # Prime report
    primes = sorted(
        [(eid, r) for eid, r in reinforcement.items() if r.get('is_prime')],
        key=lambda x: x[1]['degree'], reverse=True
    )

    # Temporal data from sigma hits (for staleness + promotion)
    temporal_data = _read_sigma_hits(buf_dir)
    referenced = set(temporal_data.keys())

    stale = [eid for eid in reinforcement
             if eid not in referenced and reinforcement[eid]['degree'] > 0]

    # Wall count
    wall_count = sum(1 for eid, e in entries.items()
                     if eid.startswith('cw:') and e.get('convergence_tag') == 'wall')

    # Polyvocal provenance
    distill_count = sum(1 for e in entries.values() if e.get('origin') == 'distill')
    session_count = sum(1 for e in entries.values() if e.get('origin') == 'session')
    untagged_count = sum(1 for e in entries.values() if 'origin' not in e)

    # TAP distribution
    tap_active = [(eid, r.get('degree', 0)) for eid, r in reinforcement.items()
                  if r.get('degree', 0) > 0]
    zero_tap = w_count - len(tap_active)

    # Temporal feedback summary
    temporal_active = sum(1 for r in reinforcement.values()
                          if r.get('ref_count', 0) > 0)

    # Output report
    lines = [
        "=" * 60,
        "ALPHA BIN HEALTH REPORT",
        "=" * 60,
        "",
        f"Total w: entries:  {w_count}",
        f"Total cw: entries: {cw_count}",
        f"CW graph edges:    {len(cw_edges)}",
        f"Wall edges:        {wall_count}",
        f"Clusters:          {len(clusters)}",
        "",
        f"Bin Youn ratio:    {youn_ratio} (actual_cw / possible_pairs)",
        f"  ({cw_count} / {int(possible_pairs)})",
        "",
        f"Provenance:        {distill_count} distilled (diachronic), "
        f"{session_count} session (synchronic)"
        + (f", {untagged_count} untagged" if untagged_count else ""),
        "",
        f"TAP distribution:  {len(tap_active)} adjacent (finite), "
        f"{zero_tap} unadjacent (infinite possibility)",
        f"Temporal feedback: {temporal_active} concepts with sigma hits",
    ]

    # Wholeness (Alexander-Hopfield energy)
    wholeness = index.get('wholeness', {})
    if wholeness:
        lines.extend([
            "",
            f"Wholeness (W):     {wholeness.get('W', 0)} active-active edges "
            f"/ {wholeness.get('W_potential', 0)} total "
            f"(ratio: {wholeness.get('W_ratio', 0.0):.4f})",
            f"  Active concepts: {wholeness.get('active_count', 0)}",
        ])

    lines.extend([
        "",
        "--- PRIMES (top 20 by reinforcement degree) ---",
    ])
    for eid, rdata in primes[:20]:
        concept = entries.get(eid, {}).get('concept', '?')
        lines.append(
            f"  {eid:8s} deg={rdata['degree']:2d}  "
            f"div={rdata['source_diversity']:2d}  {concept}"
        )

    if clusters:
        lines.append("")
        lines.append("--- CLUSTERS ---")
        for c in clusters:
            lines.append(
                f"  #{c['id']:2d} {c['name'][:35]:35s}  "
                f"size={c['size']:3d}  density={c['internal_density']:.2f}  "
                f"bridges={c['bridge_count']}"
            )

    if stale:
        lines.append("")
        lines.append(f"--- STALE CONCEPTS ({len(stale)} never referenced by sigma hook) ---")
        for eid in stale[:10]:
            concept = entries.get(eid, {}).get('concept', '?')
            lines.append(f"  {eid:8s} {concept}")
        if len(stale) > 10:
            lines.append(f"  ... and {len(stale) - 10} more")

    # Promotion candidates (anopressive channel — upward flow)
    promotion_candidates = [
        (eid, tdata) for eid, tdata in temporal_data.items()
        if tdata.get('ref_count', 0) >= 3
    ]
    if promotion_candidates:
        promotion_candidates.sort(key=lambda x: x[1]['ref_count'], reverse=True)
        lines.append("")
        lines.append(
            f"--- PROMOTION CANDIDATES ({len(promotion_candidates)} "
            f"concepts with 3+ sigma hits) ---"
        )
        for eid, tdata in promotion_candidates[:10]:
            concept = entries.get(eid, {}).get('concept', '?')
            lines.append(
                f"  {eid:8s} refs={tdata['ref_count']:3d}  "
                f"last={tdata.get('last_ref', '?')}  {concept}"
            )
        if len(promotion_candidates) > 10:
            lines.append(f"  ... and {len(promotion_candidates) - 10} more")

    # Co-activation resonance (Kirsanov resonator dynamics)
    coact = _read_coactivation(buf_dir)
    if coact:
        top_pairs = sorted(coact.items(), key=lambda x: x[1], reverse=True)
        lines.append("")
        lines.append(
            f"--- RESONANCE PAIRS ({len(coact)} co-activation pairs) ---"
        )
        for pair_key, count in top_pairs[:8]:
            ids = pair_key.split('|')
            c1 = entries.get(ids[0], {}).get('concept', '?') if len(ids) > 0 else '?'
            c2 = entries.get(ids[1], {}).get('concept', '?') if len(ids) > 1 else '?'
            if ':' in c1:
                c1 = c1.split(':', 1)[1]
            if ':' in c2:
                c2 = c2.split(':', 1)[1]
            lines.append(f"  {count:3d}x  {c1} <-> {c2}")
        if len(top_pairs) > 8:
            lines.append(f"  ... and {len(top_pairs) - 8} more")

    # Phase portrait trajectory (Kirsanov Neural Dynamics)
    trajectory = _read_phase_trajectory(buf_dir, last_n=5)
    if trajectory:
        lines.append("")
        lines.append(f"--- PHASE PORTRAIT (last {len(trajectory)} snapshots) ---")
        wp_label = "W'"
        lines.append(
            f"  {'Date':12s} {'W':>4s} {'W_r':>6s} {wp_label:>5s} "
            f"{'Hits':>5s} {'Err':>4s} {'Cl':>3s} {'Active':>6s}"
        )
        for snap in trajectory:
            lines.append(
                f"  {snap.get('date', '?'):12s} "
                f"{snap.get('W', 0):4d} "
                f"{snap.get('W_ratio', 0):6.4f} "
                f"{snap.get('W_prime', 0):5.2f} "
                f"{snap.get('total_hits', 0):5d} "
                f"{snap.get('total_errors', 0):4d} "
                f"{snap.get('cluster_count', 0):3d} "
                f"{snap.get('active_concepts', 0):6d}"
            )

    # Prediction errors (Kirsanov predictive coding)
    error_data = _read_sigma_errors(buf_dir)
    if error_data['total_errors'] > 0:
        lines.append("")
        lines.append(
            f"--- PREDICTION ERRORS ({error_data['total_errors']} total, "
            f"{error_data['false_pos_count']} false positives) ---"
        )
        # Top gap keywords — concepts the user discusses but alpha doesn't have
        gap_kws = error_data['gap_keywords']
        if gap_kws:
            top_gaps = sorted(gap_kws.items(), key=lambda x: x[1], reverse=True)
            lines.append("  Gap keywords (user discusses, alpha lacks):")
            for kw, count in top_gaps[:10]:
                lines.append(f"    {kw:25s} x{count}")
            if len(top_gaps) > 10:
                lines.append(f"    ... and {len(top_gaps) - 10} more")

    lines.append("")
    lines.append("=" * 60)
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Subcommand: alpha-grid-build (thin wrapper for grid_builder.py)
# ---------------------------------------------------------------------------

def cmd_alpha_grid_build(args):
    """Build the mesological relevance grid (delegates to grid_builder.py)."""
    import subprocess
    script_dir = Path(__file__).resolve().parent
    grid_script = script_dir / 'grid_builder.py'
    if not grid_script.exists():
        print(json.dumps({'status': 'error', 'message': 'grid_builder.py not found'}))
        sys.exit(1)
    cmd = [sys.executable, str(grid_script),
           '--buffer-dir', str(args.buffer_dir)]
    if getattr(args, 'dry_run', False):
        cmd.append('--dry-run')
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Subcommand: alpha-resolve (resolution bin for unresolved concepts)
# ---------------------------------------------------------------------------

def cmd_alpha_resolve(args):
    """Check for unresolved concept entries and present resolution candidates.

    Scans alpha index for entries with concept='?' and extracts suggested
    concept names from their .md file content (Maps to / Maps-to fields).
    Outputs a JSON summary of candidates for user review.
    """
    buf_dir = Path(args.buffer_dir)
    index = read_alpha_index(buf_dir)
    if not index:
        print(json.dumps({'status': 'error', 'message': 'No alpha bin found'}))
        return

    entries = index.get('entries', {})
    alpha_dir = buf_dir / 'alpha'
    queue = []

    for eid, einfo in entries.items():
        if einfo.get('concept', '') not in ('?', ''):
            continue
        suggestion = None
        md_path = alpha_dir / einfo.get('file', '')
        if md_path.exists():
            try:
                text = md_path.read_text(encoding='utf-8')
                for line in text.splitlines():
                    if line.startswith('**Maps to**:') or line.startswith('**Maps-to**:'):
                        suggestion = line.split(':', 1)[1].strip()[:80]
                        break
            except OSError:
                pass
        status = 'awaits_design' if einfo.get('source', '') == '_forward-notes' else 'ready'
        queue.append({
            'id': eid,
            'source': einfo.get('source', '?'),
            'file': einfo.get('file', '?'),
            'suggestion': suggestion,
            'status': status,
        })

    if getattr(args, 'auto', False) and queue:
        resolved = 0
        for item in queue:
            if item['suggestion'] and item['status'] == 'ready':
                # Apply suggestion as concept name
                concept_name = item['suggestion'].split(',')[0].strip().replace(' ', '_')[:60]
                entries[item['id']]['concept'] = concept_name
                resolved += 1
        if resolved > 0:
            idx_path = alpha_index_path(buf_dir)
            write_json(idx_path, index)
        print(json.dumps({
            'status': 'ok',
            'total_unresolved': len(queue),
            'auto_resolved': resolved,
            'remaining': len(queue) - resolved,
        }, indent=2))
        return

    # Write queue to resolution file for reference
    queue_path = buf_dir / '.resolution_queue'
    with open(queue_path, 'w', encoding='utf-8') as f:
        for item in queue:
            f.write(f"{item['id']}  {item['source']}  "
                    f"{item['suggestion'] or '(none)'}  "
                    f"{item['status']}\n")

    result = {
        'status': 'ok',
        'total_unresolved': len(queue),
        'ready': sum(1 for q in queue if q['status'] == 'ready'),
        'awaits_design': sum(1 for q in queue if q['status'] == 'awaits_design'),
        'candidates': queue,
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: alpha-write
# ---------------------------------------------------------------------------

def cmd_alpha_write(args):
    """Write one or more entries to the alpha bin.

    Reads JSON from stdin (single object or array of objects).
    For each entry: assigns next available ID, writes canonical .md file,
    updates alpha/index.json atomically.

    Entry types:
      cross_source:    requires type, source_folder, key, maps_to
      convergence_web: requires type, source_folder, thesis, athesis, synthesis, metathesis

    Optional fields: ref, suggest (cross_source), id override via --id flag.
    """
    buf_dir = Path(args.buffer_dir)
    alpha_dir = buf_dir / 'alpha'
    index_path = alpha_dir / 'index.json'
    dry_run = getattr(args, 'dry_run', False)

    # Read alpha index (must exist)
    if not index_path.exists():
        print(json.dumps({
            "status": "error",
            "message": "Alpha bin not found. Run migration first."
        }))
        sys.exit(1)

    index = read_json(index_path)

    # Read entries from file (--input) or stdin
    if getattr(args, 'input', None):
        raw = Path(args.input).read_text(encoding='utf-8').strip()
    else:
        raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin."}))
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {e}"}))
        sys.exit(1)

    entries = data if isinstance(data, list) else [data]
    if not entries:
        print(json.dumps({"status": "error", "message": "Empty entry list."}))
        sys.exit(1)

    # Track next IDs from current index state
    next_w = alpha_max_id(index, 'w:') + 1
    next_cw = alpha_max_id(index, 'cw:') + 1

    # Safety: also scan .md files on disk for max IDs.
    # Prevents collisions when index is stale after external rebuild.
    disk_max_w, disk_max_cw = _alpha_disk_max_ids(alpha_dir)
    next_w = max(next_w, disk_max_w + 1)
    next_cw = max(next_cw, disk_max_cw + 1)

    # Also check warm layer for max IDs to prevent collisions
    warm = read_json(buf_dir / 'handoff-warm.json')
    for e in collect_all_entries(warm, 'w:'):
        m = re.match(r'^w:(\d+)$', e.get('id', ''))
        if m:
            next_w = max(next_w, int(m.group(1)) + 1)
    for e in warm.get('convergence_web', {}).get('entries', []):
        m = re.match(r'^cw:(\d+)$', e.get('id', ''))
        if m:
            next_cw = max(next_cw, int(m.group(1)) + 1)

    results = []
    errors = []

    for i, entry in enumerate(entries):
        entry_type = entry.get('type', '')
        source_folder = entry.get('source_folder', '')

        if not source_folder:
            errors.append(f"Entry {i}: missing 'source_folder'")
            continue

        if entry_type == 'cross_source':
            key = entry.get('key', '')
            if not key:
                errors.append(f"Entry {i}: cross_source requires 'key'")
                continue

            # Assign ID
            if args.id_override and i == 0:
                new_id = args.id_override
            else:
                new_id = f"w:{next_w}"
                next_w += 1

            # Build entry for md generator
            md_entry = {
                'id': new_id,
                'key': key,
                'maps_to': entry.get('maps_to', ''),
                'ref': entry.get('ref', ''),
                'suggest': entry.get('suggest'),
                'body': entry.get('body'),
                'distillation': entry.get('distillation'),
            }
            md_content = make_cross_source_md(md_entry, source_label=source_folder)
            concept_key = key

        elif entry_type == 'convergence_web':
            thesis = entry.get('thesis', {})
            athesis = entry.get('athesis', {})
            if not thesis.get('label') or not athesis.get('label'):
                errors.append(f"Entry {i}: convergence_web requires thesis.label and athesis.label")
                continue

            # Assign ID
            if args.id_override and i == 0:
                new_id = args.id_override
            else:
                new_id = f"cw:{next_cw}"
                next_cw += 1

            # Build entry for md generator
            md_entry = {
                'id': new_id,
                'thesis': thesis,
                'athesis': athesis,
                'synthesis': entry.get('synthesis', ''),
                'metathesis': entry.get('metathesis', ''),
                'context': entry.get('context'),
            }
            md_content = make_convergence_web_md(md_entry)
            concept_key = f"{thesis.get('label', '?')} x {athesis.get('label', '?')}"

        else:
            errors.append(f"Entry {i}: unknown type '{entry_type}'. Use: cross_source, convergence_web")
            continue

        # Compute file path
        padded = pad_id(new_id)
        filename = f"{source_folder}/{padded}.md"
        file_path = alpha_dir / source_folder / f"{padded}.md"

        if not dry_run:
            # Create source folder if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # Write .md file
            file_path.write_text(md_content, encoding='utf-8')

        # Build extra index fields
        extra = {}
        # Origin: provenance direction (diachronic distill vs synchronic session)
        extra['origin'] = entry.get('origin', 'distill')
        # Convergence tag: extract [type_tag] from synthesis for cw: entries
        if entry_type == 'convergence_web':
            synthesis = entry.get('synthesis', '')
            tag_match = re.match(r'\[(\w+)\]', synthesis)
            if tag_match:
                extra['convergence_tag'] = tag_match.group(1)

        # Update index
        alpha_update_index(index, new_id, entry_type, source_folder,
                           concept_key, filename, extra_fields=extra)

        results.append({
            "id": new_id,
            "file": filename,
            "source_folder": source_folder,
            "type": entry_type
        })

    # Update last_updated timestamp
    index['last_updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Write updated index
    if not dry_run and results:
        write_json(index_path, index)

    output = {
        "status": "ok" if not errors else "partial" if results else "error",
        "entries_written": results,
        "index_updated": bool(results) and not dry_run,
        "dry_run": dry_run,
    }
    if errors:
        output["errors"] = errors
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: alpha-enrich
# ---------------------------------------------------------------------------


def _split_alpha_md(content):
    """Split alpha .md content into header (through Mapping/Tetradic) and body.

    Returns ``(header, old_body)`` where *header* includes everything through
    the ``## Mapping`` or ``## Tetradic Structure`` section (including its
    field lines), and *old_body* is whatever came after that section.
    """
    lines = content.split('\n')
    mapping_start = None
    body_start = None

    for i, line in enumerate(lines):
        if line.startswith('## Mapping') or line.startswith('## Tetradic Structure'):
            mapping_start = i
        elif mapping_start is not None and line.startswith('## ') and i > mapping_start:
            # First heading AFTER the Mapping/Tetradic section
            body_start = i
            break

    if body_start is not None:
        header = '\n'.join(lines[:body_start]).rstrip()
        old_body = '\n'.join(lines[body_start:])
        return header, old_body

    # No heading after Mapping — find end of field lines (last **Bold**: line)
    if mapping_start is not None:
        last_field = mapping_start
        for i in range(mapping_start + 1, len(lines)):
            if lines[i].startswith('**') and '**:' in lines[i]:
                last_field = i
            elif lines[i].strip() == '':
                continue
            elif not lines[i].startswith('**'):
                # Non-field, non-blank line after mapping — body starts here
                body_start = i
                break
        if body_start is None:
            body_start = last_field + 1

        header = '\n'.join(lines[:body_start]).rstrip()
        old_body = '\n'.join(lines[body_start:]).strip()
        return header, old_body

    # No mapping section found — return everything as header
    return content.rstrip(), ''


def _inject_terminal_comment(header):
    """Ensure a TERMINAL anti-entropy comment exists in the header.

    Inserts it after the ``# heading`` line if not already present.
    """
    if 'TERMINAL:' in header:
        return header  # Already present

    lines = header.split('\n')
    terminal = (
        "<!-- TERMINAL: This entry is self-contained. Do NOT read the referenced\n"
        "distillation, interpretation, or source document. All operationally\n"
        "relevant content about this concept is HERE. Following references\n"
        "defeats the architecture and wastes tokens. -->"
    )
    # Insert after the first line (the # heading)
    if lines:
        return lines[0] + '\n' + terminal + '\n' + '\n'.join(lines[1:])
    return terminal + '\n' + header


def cmd_alpha_enrich(args):
    """Enrich existing alpha entries with rich body content.

    Reads JSON array of {id, body} objects from stdin.  For each entry:
    looks up id in index.json, reads the existing .md file, preserves the
    header (through Mapping/Tetradic section), and replaces the body with
    the new rich content.  Injects a TERMINAL anti-entropy directive.

    Does NOT modify index.json — IDs, source folders, concept names stay
    the same.  Only .md file content changes.
    """
    buf_dir = Path(args.buffer_dir)
    alpha_dir = buf_dir / 'alpha'
    index_path = alpha_dir / 'index.json'
    dry_run = getattr(args, 'dry_run', False)

    if not index_path.exists():
        print(json.dumps({
            "status": "error",
            "message": "Alpha bin not found."
        }))
        sys.exit(1)

    index = read_json(index_path)

    # Read enrichment entries from stdin or --input file
    if getattr(args, 'input', None):
        raw = Path(args.input).read_text(encoding='utf-8').strip()
    else:
        raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin."}))
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {e}"}))
        sys.exit(1)

    entries = data if isinstance(data, list) else [data]
    if not entries:
        print(json.dumps({"status": "error", "message": "Empty entry list."}))
        sys.exit(1)

    enriched = []
    skipped = []
    errors = []

    for i, entry in enumerate(entries):
        entry_id = entry.get('id', '')
        body = entry.get('body', '')

        if not entry_id:
            errors.append(f"Entry {i}: missing 'id'")
            continue
        if not body:
            skipped.append({"id": entry_id, "reason": "empty body"})
            continue

        # Look up in index
        idx_entry = index.get('entries', {}).get(entry_id)
        if not idx_entry:
            errors.append(f"Entry {i}: id '{entry_id}' not found in index")
            continue

        file_rel = idx_entry.get('file', '')
        file_path = alpha_dir / file_rel

        if not file_path.exists():
            errors.append(f"Entry {i}: file not found: {file_rel}")
            continue

        # Read existing .md content
        existing = file_path.read_text(encoding='utf-8')

        # Split into header + old body
        header, _old_body = _split_alpha_md(existing)

        # Inject TERMINAL comment into header
        header = _inject_terminal_comment(header)

        # Assemble enriched file
        new_content = header + '\n\n' + body.rstrip() + '\n'

        if not dry_run:
            file_path.write_text(new_content, encoding='utf-8')

        enriched.append({
            "id": entry_id,
            "file": file_rel,
            "body_lines": len(body.strip().split('\n')),
        })

    output = {
        "status": "ok" if not errors else "partial" if enriched else "error",
        "enriched": len(enriched),
        "skipped": len(skipped),
        "dry_run": dry_run,
    }
    if enriched:
        output["entries"] = enriched
    if skipped:
        output["skipped_entries"] = skipped
    if errors:
        output["errors"] = errors
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: alpha-delete
# ---------------------------------------------------------------------------

def cmd_alpha_delete(args):
    """Delete one or more entries from the alpha bin.

    Removes .md files from disk and updates alpha/index.json.
    Used during consolidation (merging absorbed entries).
    """
    buf_dir = Path(args.buffer_dir)
    alpha_dir = buf_dir / 'alpha'
    index_path = alpha_dir / 'index.json'

    if not index_path.exists():
        print(json.dumps({
            "status": "error",
            "message": "Alpha bin not found."
        }))
        sys.exit(1)

    index = read_json(index_path)
    ids_to_delete = args.id or []

    if not ids_to_delete:
        print(json.dumps({"status": "error", "message": "No --id specified."}))
        sys.exit(1)

    deleted = []
    not_found = []
    file_errors = []

    for eid in ids_to_delete:
        entry_info = index.get('entries', {}).get(eid)
        if not entry_info:
            not_found.append(eid)
            continue

        # Delete file from disk
        file_rel = entry_info.get('file', '')
        file_path = alpha_dir / file_rel
        if file_path.exists():
            try:
                file_path.unlink()
                # Remove empty parent directory
                parent = file_path.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError as e:
                file_errors.append(f"{eid}: could not delete {file_rel}: {e}")
                continue

        # Remove from index
        alpha_remove_from_index(index, eid)
        deleted.append(eid)

    # Write updated index
    if deleted:
        index['last_updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        write_json(index_path, index)

    output = {
        "status": "ok" if not (not_found or file_errors) else "partial",
        "deleted": deleted,
        "not_found": not_found,
        "index_updated": bool(deleted)
    }
    if file_errors:
        output["file_errors"] = file_errors
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Beta bin commands (narrative microbin)
# ---------------------------------------------------------------------------

BETA_SOFT_CAP = 100
BETA_HARD_CAP = 200
BETA_DEFAULT_THRESHOLD = 0.6
BETA_THRESHOLD_MIN = 0.4
BETA_THRESHOLD_MAX = 0.8


def _beta_path(buf_dir):
    """Return Path to beta/narrative.jsonl, creating beta/ dir if needed."""
    beta_dir = Path(buf_dir) / 'beta'
    beta_dir.mkdir(parents=True, exist_ok=True)
    return beta_dir / 'narrative.jsonl'


def _beta_read_entries(buf_dir):
    """Read all beta entries from JSONL file. Returns list of dicts."""
    p = Path(buf_dir) / 'beta' / 'narrative.jsonl'
    if not p.is_file():
        return []
    entries = []
    for line in p.read_text(encoding='utf-8').strip().split('\n'):
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _beta_write_entries(buf_dir, entries):
    """Rewrite beta JSONL file with given entries."""
    p = _beta_path(buf_dir)
    with open(p, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')


def _beta_get_threshold(buf_dir):
    """Read promotion threshold from hot layer beta_config, default 0.6."""
    hot_path = Path(buf_dir) / 'handoff.json'
    if hot_path.is_file():
        try:
            hot = json.loads(hot_path.read_text(encoding='utf-8'))
            return hot.get('beta_config', {}).get('threshold', BETA_DEFAULT_THRESHOLD)
        except (json.JSONDecodeError, IOError):
            pass
    return BETA_DEFAULT_THRESHOLD


def _beta_set_threshold(buf_dir, threshold):
    """Write promotion threshold to hot layer beta_config."""
    hot_path = Path(buf_dir) / 'handoff.json'
    if hot_path.is_file():
        try:
            hot = json.loads(hot_path.read_text(encoding='utf-8'))
            if 'beta_config' not in hot:
                hot['beta_config'] = {}
            hot['beta_config']['threshold'] = round(threshold, 2)
            with open(hot_path, 'w', encoding='utf-8') as f:
                json.dump(hot, f, indent=2, ensure_ascii=False)
                f.write('\n')
        except (json.JSONDecodeError, IOError):
            pass


def cmd_beta_append(args):
    """Append a narrative entry to beta/narrative.jsonl."""
    buf_dir = args.buffer_dir
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin"}))
        sys.exit(1)
    try:
        entry = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {exc}"}))
        sys.exit(1)

    entry['ts'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    entry.setdefault('promoted', False)
    entry.setdefault('r', 0.2)
    entry.setdefault('tags', [])
    entry.setdefault('tick', 'manual')

    p = _beta_path(buf_dir)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    print(json.dumps({
        "status": "ok",
        "message": f"Appended beta entry (r={entry['r']:.2f})",
        "ts": entry['ts']
    }))


def cmd_beta_read(args):
    """Read beta entries with optional filters."""
    entries = _beta_read_entries(args.buffer_dir)
    min_r = getattr(args, 'min_r', 0.0) or 0.0
    limit = getattr(args, 'limit', 0) or 0
    since = getattr(args, 'since', None)

    filtered = []
    for e in entries:
        if e.get('r', 0) < min_r:
            continue
        if since and e.get('ts', '') < since:
            continue
        filtered.append(e)

    if limit > 0:
        filtered = filtered[-limit:]

    print(json.dumps({
        "status": "ok",
        "total": len(entries),
        "filtered": len(filtered),
        "entries": filtered
    }, indent=2, ensure_ascii=False))


def cmd_beta_promote(args):
    """Mark entries above threshold as promoted. Adaptive threshold."""
    buf_dir = args.buffer_dir
    entries = _beta_read_entries(buf_dir)
    threshold = _beta_get_threshold(buf_dir)

    promoted = []
    for e in entries:
        if e.get('r', 0) >= threshold and not e.get('promoted', False):
            e['promoted'] = True
            promoted.append(e)

    # Adaptive threshold adjustment
    promoted_count = len(promoted)
    new_threshold = threshold
    if promoted_count > 10:
        new_threshold = min(threshold + 0.05, BETA_THRESHOLD_MAX)
    elif promoted_count == 0:
        new_threshold = max(threshold - 0.05, BETA_THRESHOLD_MIN)

    if new_threshold != threshold:
        _beta_set_threshold(buf_dir, new_threshold)

    _beta_write_entries(buf_dir, entries)

    print(json.dumps({
        "status": "ok",
        "promoted_count": promoted_count,
        "threshold_used": round(threshold, 2),
        "threshold_new": round(new_threshold, 2),
        "promoted": promoted
    }, indent=2, ensure_ascii=False))


def cmd_beta_purge(args):
    """Remove promoted + low-relevance old entries."""
    buf_dir = args.buffer_dir
    max_age = getattr(args, 'max_age', 3) or 3
    entries = _beta_read_entries(buf_dir)

    if not entries:
        print(json.dumps({"status": "ok", "purged": 0, "remaining": 0}))
        return

    # Compute cutoff: entries from sessions older than max_age handoffs
    # Use date-based heuristic: if we assume ~1 session/day, max_age sessions
    # = max_age days. More robust: count distinct dates in entries.
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age)).isoformat(timespec='seconds')

    surviving = []
    purged = 0
    for e in entries:
        ts = e.get('ts', '')
        is_old = ts < cutoff if ts else True
        is_promoted = e.get('promoted', False)
        is_low_r = e.get('r', 0) < 0.3

        if is_old and (is_promoted or is_low_r):
            purged += 1
        else:
            surviving.append(e)

    # Hard cap enforcement
    if len(surviving) > BETA_HARD_CAP:
        # Sort by relevance, purge lowest
        surviving.sort(key=lambda x: x.get('r', 0))
        excess = len(surviving) - BETA_SOFT_CAP
        purged += excess
        surviving = surviving[excess:]

    _beta_write_entries(buf_dir, surviving)

    print(json.dumps({
        "status": "ok",
        "purged": purged,
        "remaining": len(surviving)
    }))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Session buffer manager — sigma trunk operations for hot/warm/cold layers'
    )
    subparsers = parser.add_subparsers(dest='command', help='Subcommand')

    # Shared parent parsers to avoid repeating common arguments
    buf_parent = argparse.ArgumentParser(add_help=False)
    buf_parent.add_argument('--buffer-dir', required=True, help='Path to buffer directory')

    limits_parent = argparse.ArgumentParser(add_help=False)
    limits_parent.add_argument('--warm-max', type=int, default=None, help='Warm layer max lines')
    limits_parent.add_argument('--hot-max', type=int, default=None, help='Hot layer max lines')
    limits_parent.add_argument('--cold-max', type=int, default=None, help='Cold layer max lines')

    # --- read ---
    p_read = subparsers.add_parser('read', parents=[buf_parent, limits_parent],
        help='Reconstruct context from buffer layers')
    p_read.set_defaults(func=cmd_read)

    # --- update ---
    p_update = subparsers.add_parser('update', parents=[buf_parent],
        help='Merge alpha stash (session changes) into buffer layers')
    p_update.add_argument('--input', default=None,
        help='Path to alpha stash JSON file (default: stdin)')
    p_update.set_defaults(func=cmd_update)

    # --- migrate ---
    p_migrate = subparsers.add_parser('migrate', parents=[buf_parent, limits_parent],
        help='Conservation enforcement')
    p_migrate.add_argument('--dry-run', action='store_true', help='Report without writing')
    p_migrate.set_defaults(func=cmd_migrate)

    # --- validate ---
    p_validate = subparsers.add_parser('validate', parents=[buf_parent, limits_parent],
        help='Check layers against constraints')
    p_validate.set_defaults(func=cmd_validate)

    # --- sync ---
    p_sync = subparsers.add_parser('sync', parents=[buf_parent],
        help='Sync MEMORY.md + project registry')
    p_sync.add_argument('--memory-path', default=None, help='Path to MEMORY.md')
    p_sync.add_argument('--registry-path', default=None, help='Path to projects.json')
    p_sync.add_argument('--project-name', default=None, help='Project name for registry')
    p_sync.set_defaults(func=cmd_sync)

    # --- next-id ---
    p_nextid = subparsers.add_parser('next-id', parents=[buf_parent],
        help='Get next available ID')
    p_nextid.add_argument('--layer', required=True, choices=['warm', 'cold', 'convergence'],
                          help='Layer to get ID for')
    p_nextid.set_defaults(func=cmd_next_id)

    # --- handoff (full pipeline) ---
    p_handoff = subparsers.add_parser('handoff', parents=[buf_parent, limits_parent],
        help='Full pipeline: update + migrate + sync in one call (preferred)')
    p_handoff.add_argument('--input', default=None,
        help='Path to alpha stash JSON file (default: stdin)')
    p_handoff.add_argument('--memory-path', default=None, help='Path to MEMORY.md')
    p_handoff.add_argument('--registry-path', default=None, help='Path to projects.json')
    p_handoff.add_argument('--project-name', default=None, help='Project name for registry')
    p_handoff.set_defaults(func=cmd_handoff)

    # --- archive ---
    p_archive = subparsers.add_parser('archive', parents=[buf_parent, limits_parent],
        help='Cold->tower archival')
    p_archive.add_argument('--force', action='store_true', help='Force even if under limit')
    p_archive.add_argument('--entry-ids', nargs='*', default=None,
                           help='Specific entry IDs to archive (e.g., c:7 c:12)')
    p_archive.set_defaults(func=cmd_archive)

    # --- alpha-read ---
    p_alpha_read = subparsers.add_parser('alpha-read', parents=[buf_parent],
        help='Read alpha bin summary (reference memory index)')
    p_alpha_read.set_defaults(func=cmd_alpha_read)

    # --- alpha-query ---
    p_alpha_query = subparsers.add_parser('alpha-query', parents=[buf_parent],
        help='Query alpha bin for referents by ID, source, or concept')
    p_alpha_query.add_argument('--id', nargs='+', default=None,
                               help='Retrieve entries by ID (e.g., w:218 cw:83)')
    p_alpha_query.add_argument('--source', default=None,
                               help='Search by source name (case-insensitive prefix match)')
    p_alpha_query.add_argument('--concept', default=None,
                               help='Search by concept name (case-insensitive partial match)')
    p_alpha_query.set_defaults(func=cmd_alpha_query)

    # --- alpha-write ---
    p_alpha_write = subparsers.add_parser('alpha-write', parents=[buf_parent],
        help='Write entries to alpha bin (reads JSON from stdin)')
    p_alpha_write.add_argument('--dry-run', action='store_true',
                               help='Validate and show what would be written without writing')
    p_alpha_write.add_argument('--id', dest='id_override', default=None,
                               help='Override auto-assigned ID (for first entry only)')
    p_alpha_write.add_argument('--input',
                               help='Read JSON from file instead of stdin')
    p_alpha_write.set_defaults(func=cmd_alpha_write)

    # --- alpha-enrich ---
    p_alpha_enrich = subparsers.add_parser('alpha-enrich', parents=[buf_parent],
        help='Enrich existing alpha entries with rich body content (reads JSON from stdin)')
    p_alpha_enrich.add_argument('--dry-run', action='store_true',
                                help='Show what would be enriched without writing')
    p_alpha_enrich.add_argument('--input',
                                help='Read JSON from file instead of stdin')
    p_alpha_enrich.set_defaults(func=cmd_alpha_enrich)

    # --- alpha-delete ---
    p_alpha_del = subparsers.add_parser('alpha-delete', parents=[buf_parent],
        help='Delete entries from alpha bin (removes files + updates index)')
    p_alpha_del.add_argument('--id', nargs='+', required=True,
                             help='Entry IDs to delete (e.g., w:218 cw:83)')
    p_alpha_del.set_defaults(func=cmd_alpha_delete)

    # --- alpha-validate ---
    p_alpha_val = subparsers.add_parser('alpha-validate', parents=[buf_parent],
        help='Validate alpha bin integrity (index vs files on disk)')
    p_alpha_val.set_defaults(func=cmd_alpha_validate)

    # --- alpha-reinforce ---
    p_alpha_reinforce = subparsers.add_parser('alpha-reinforce', parents=[buf_parent],
        help='Compute reinforcement scores and cw_graph from convergence_web')
    p_alpha_reinforce.add_argument('--dry-run', action='store_true',
                                    help='Show results without writing to index.json')
    p_alpha_reinforce.set_defaults(func=cmd_alpha_reinforce)

    # --- alpha-clusters ---
    p_alpha_clusters = subparsers.add_parser('alpha-clusters', parents=[buf_parent],
        help='Compute cluster analysis from convergence_web adjacency (requires alpha-reinforce)')
    p_alpha_clusters.add_argument('--dry-run', action='store_true',
                                   help='Show results without writing to index.json')
    p_alpha_clusters.set_defaults(func=cmd_alpha_clusters)

    # --- alpha-neighborhood ---
    p_alpha_nbr = subparsers.add_parser('alpha-neighborhood', parents=[buf_parent],
        help='Traverse convergence_web neighborhood from a given ID')
    p_alpha_nbr.add_argument('--id', required=True,
                              help='Starting w: or cw: ID (e.g., w:125)')
    p_alpha_nbr.add_argument('--hops', type=int, default=2,
                              help='Max traversal hops (default: 2)')
    p_alpha_nbr.set_defaults(func=cmd_alpha_neighborhood)

    # --- alpha-health ---
    p_alpha_health = subparsers.add_parser('alpha-health', parents=[buf_parent],
        help='Generate alpha bin health diagnostics report')
    p_alpha_health.set_defaults(func=cmd_alpha_health)

    # --- alpha-grid-build ---
    p_alpha_grid = subparsers.add_parser('alpha-grid-build', parents=[buf_parent],
        help='Build mesological relevance grid (pre-computed alpha*sigma scores)')
    p_alpha_grid.add_argument('--dry-run', action='store_true',
                               help='Print grid to stdout without writing file')
    p_alpha_grid.set_defaults(func=cmd_alpha_grid_build)

    # --- alpha-resolve ---
    p_alpha_resolve = subparsers.add_parser('alpha-resolve', parents=[buf_parent],
        help='Check for unresolved concept entries and present resolution candidates')
    p_alpha_resolve.add_argument('--auto', action='store_true',
                                  help='Auto-apply suggested concept names for ready entries')
    p_alpha_resolve.set_defaults(func=cmd_alpha_resolve)

    # --- beta-append ---
    p_beta_append = subparsers.add_parser('beta-append', parents=[buf_parent],
        help='Append narrative entry to beta bin (stdin JSON)')
    p_beta_append.set_defaults(func=cmd_beta_append)

    # --- beta-read ---
    p_beta_read = subparsers.add_parser('beta-read', parents=[buf_parent],
        help='Read beta bin entries with optional filters')
    p_beta_read.add_argument('--min-r', type=float, default=0.0,
                              help='Minimum relevance score (default: 0.0)')
    p_beta_read.add_argument('--limit', type=int, default=0,
                              help='Max entries to return (0=all, default: 0)')
    p_beta_read.add_argument('--since', default=None,
                              help='Only entries after this ISO date (e.g., 2026-03-10)')
    p_beta_read.set_defaults(func=cmd_beta_read)

    # --- beta-promote ---
    p_beta_promote = subparsers.add_parser('beta-promote', parents=[buf_parent],
        help='Mark entries above threshold as promoted (adaptive threshold)')
    p_beta_promote.set_defaults(func=cmd_beta_promote)

    # --- beta-purge ---
    p_beta_purge = subparsers.add_parser('beta-purge', parents=[buf_parent],
        help='Remove promoted + low-relevance old entries from beta bin')
    p_beta_purge.add_argument('--max-age', type=int, default=3,
                               help='Max age in days for purging old entries (default: 3)')
    p_beta_purge.set_defaults(func=cmd_beta_purge)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
