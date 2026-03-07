#!/usr/bin/env python3
"""
Session Buffer — Buffer Manager

Mechanical operations for the session buffer (sigma trunk + alpha bin).
Handles JSON merge, ID assignment, conservation enforcement, MEMORY.md sync,
and alpha bin queries.

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
from datetime import date

# Force UTF-8 stdout/stderr on Windows (buffer data may contain unicode)
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Constants
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

    # Resolve each ref
    resolved = []
    warm_entries = collect_all_entries(warm, 'w:')
    cold_entries = collect_all_entries(cold, 'c:')
    cw_entries = warm.get('convergence_web', {}).get('entries', [])

    for ref_id in sorted(refs):
        entry = None
        source = None

        # Check warm
        for e in warm_entries:
            if e.get('id') == ref_id:
                # Check for tombstone/redirect
                if 'migrated_to' in e:
                    # Follow redirect to cold
                    cold_id = e['migrated_to']
                    for ce in cold_entries:
                        if ce.get('id') == cold_id:
                            entry = ce
                            source = f"cold (via redirect from {ref_id})"
                            break
                    if not entry:
                        entry = e
                        source = "warm (redirect — target not found in cold)"
                else:
                    entry = e
                    source = "warm"
                break

        # Check convergence web
        if not entry:
            for e in cw_entries:
                if e.get('id') == ref_id:
                    entry = e
                    source = "convergence_web"
                    break

        # Check cold
        if not entry:
            for e in cold_entries:
                if e.get('id') == ref_id:
                    if 'archived_to' in e:
                        entry = e
                        source = f"cold (archived to tower-{e['archived_to']})"
                    else:
                        entry = e
                        source = "cold"
                    break

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
    if mode in ('memory', 'project', 'unknown'):
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
    if mode in ('memory', 'project', 'unknown'):
        threads = hot.get('open_threads', [])
        if threads:
            lines = []
            for i, t in enumerate(threads, 1):
                ref = f" -> {t['ref']}" if t.get('ref') else ""
                see = f" [see: {', '.join(t['see'])}]" if t.get('see') else ""
                lines.append(f"{i}. [{t.get('status', '?')}] {t.get('thread', '')}{ref}{see}")
            out.append(format_section(f"Open Threads ({len(threads)})", '\n'.join(lines)))

    # Recent decisions (memory + project modes)
    if mode in ('memory', 'project', 'unknown'):
        decs = hot.get('recent_decisions', [])
        if decs:
            lines = []
            for i, d in enumerate(decs, 1):
                see = f" [see: {', '.join(d['see'])}]" if d.get('see') else ""
                lines.append(f"{i}. {d.get('what', '?')} -> {d.get('chose', '?')} | {d.get('why', '')}{see}")
            out.append(format_section(f"Recent Decisions ({len(decs)})", '\n'.join(lines)))

    # Instance notes (memory + project modes)
    if mode in ('memory', 'project', 'unknown'):
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
    if mode in ('project', 'unknown'):
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
    if mode in ('project', 'unknown'):
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
    warm_max = args.warm_max if hasattr(args, 'warm_max') and args.warm_max else WARM_MAX_LINES_DEFAULT
    hot_lines = count_json_lines(hot)
    warm_lines = count_json_lines(warm) if warm else 0
    cold_lines = count_json_lines(cold) if cold else 0

    size_lines = [
        f"Hot:  {hot_lines} lines (max {HOT_MAX_LINES})"
        + (" *** OVER ***" if hot_lines > HOT_MAX_LINES else ""),
        f"Warm: {warm_lines} lines (max {warm_max})"
        + (" *** OVER ***" if warm_lines > warm_max else ""),
        f"Cold: {cold_lines} lines (max {COLD_MAX_LINES})"
        + (" *** OVER ***" if cold_lines > COLD_MAX_LINES else ""),
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
    if mode in ('memory', 'project') and 'active_work' in changes:
        hot['active_work'] = changes['active_work']
        report.append("Updated active_work")

    # New decisions -> append to recent_decisions (memory + project)
    if mode in ('memory', 'project') and 'new_decisions' in changes:
        if 'recent_decisions' not in hot:
            hot['recent_decisions'] = []
        for d in changes['new_decisions']:
            d.setdefault('session', str(date.today()))
            d.setdefault('see', [])
            hot['recent_decisions'].append(d)
        report.append(f"Added {len(changes['new_decisions'])} decisions")

    # Open threads — replace entirely (memory + project)
    if mode in ('memory', 'project') and 'open_threads' in changes:
        hot['open_threads'] = changes['open_threads']
        report.append(f"Set {len(changes['open_threads'])} open threads")

    # Instance notes — replace entirely (memory + project)
    if mode in ('memory', 'project') and 'instance_notes' in changes:
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

    if mode == 'project' and warm:
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
            hot['concept_map_digest']['_meta']['last_validated'] = str(date.today())

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
            cw['_meta']['last_validated'] = str(date.today())
            warm['convergence_web'] = cw

            # Update hot digest
            if 'convergence_web_digest' not in hot:
                hot['convergence_web_digest'] = {'_meta': {}, 'clusters': [], 'flagged': []}
            hot['convergence_web_digest']['_meta']['total_entries'] = len(cw_entries)
            hot['convergence_web_digest']['_meta']['last_validated'] = str(date.today())

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
            'date': changes.get('session_meta', {}).get('date', str(date.today())),
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
    warm_max = args.warm_max or WARM_MAX_LINES_DEFAULT

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
    if hot_lines > HOT_MAX_LINES and mode in ('memory', 'project'):
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
    if warm_lines > warm_max and mode in ('memory', 'project'):
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
                cold_entry['migrated_from_warm'] = str(date.today())
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
    if cold_lines > COLD_MAX_LINES:
        report.append(f"WARNING: Cold layer at {cold_lines} lines (max {COLD_MAX_LINES}). "
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
    warm_max = args.warm_max or WARM_MAX_LINES_DEFAULT

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

    # Size checks
    hot_lines = count_json_lines(hot)
    warm_lines = count_json_lines(warm) if warm else 0
    cold_lines = count_json_lines(cold) if cold else 0

    info.append(f"Hot: {hot_lines}/{HOT_MAX_LINES} lines")
    info.append(f"Warm: {warm_lines}/{warm_max} lines")
    info.append(f"Cold: {cold_lines}/{COLD_MAX_LINES} lines")

    if hot_lines > HOT_MAX_LINES:
        issues.append(f"Hot layer over limit: {hot_lines} > {HOT_MAX_LINES}")
    if warm_lines > warm_max:
        issues.append(f"Warm layer over limit: {warm_lines} > {warm_max}")
    if cold_lines > COLD_MAX_LINES:
        issues.append(f"Cold layer over limit: {cold_lines} > {COLD_MAX_LINES}")

    # Required fields
    required_hot = ['session_meta', 'natural_summary', 'memory_config']
    if mode in ('memory', 'project'):
        required_hot.extend(['active_work', 'open_threads', 'recent_decisions', 'instance_notes'])
    if mode == 'project':
        required_hot.extend(['concept_map_digest', 'convergence_web_digest'])

    for field in required_hot:
        if field not in hot:
            issues.append(f"Missing required hot field: {field}")

    # Pointer integrity (project mode)
    all_layer_ids = set()
    broken_refs = []
    if mode == 'project' and warm:
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
        if mode == 'project' and broken_refs:
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
        'last_handoff': str(date.today()),
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

    if layer_name == 'warm':
        warm = read_json(buf_dir / 'handoff-warm.json')
        entries = collect_all_entries(warm, 'w:')
        warm_max = 0
        pattern = re.compile(r'^w:(\d+)$')
        for e in entries:
            m = pattern.match(e.get('id', ''))
            if m:
                warm_max = max(warm_max, int(m.group(1)))
        # Also check alpha for w: IDs
        alpha_w_max = alpha_max_id(alpha_idx, 'w:') if alpha_idx else 0
        final_max = max(warm_max, alpha_w_max)
        print(f"w:{final_max + 1}")
    elif layer_name == 'cold':
        cold = read_json(buf_dir / 'handoff-cold.json')
        entries = collect_all_entries(cold, 'c:')
        print(next_id_in_entries(entries, 'c:'))
    elif layer_name == 'convergence':
        warm = read_json(buf_dir / 'handoff-warm.json')
        entries = warm.get('convergence_web', {}).get('entries', [])
        warm_max = 0
        pattern = re.compile(r'^cw:(\d+)$')
        for e in entries:
            m = pattern.match(e.get('id', ''))
            if m:
                warm_max = max(warm_max, int(m.group(1)))
        # Also check alpha for cw: IDs
        alpha_cw_max = alpha_max_id(alpha_idx, 'cw:') if alpha_idx else 0
        final_max = max(warm_max, alpha_cw_max)
        print(f"cw:{final_max + 1}")
    else:
        print(f"Error: unknown layer '{layer_name}'. Use: warm, cold, convergence",
              file=sys.stderr)
        sys.exit(1)


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
    if cold_lines <= COLD_MAX_LINES and not args.force:
        print(f"Cold layer at {cold_lines} lines (max {COLD_MAX_LINES}). "
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
                        'session_archived': str(date.today())
                    })
                else:
                    remaining.append(entry)
            cold[key] = remaining

        tower = {
            'schema_version': 2,
            'layer': 'tower',
            'tower_number': tower_num,
            'created': str(date.today()),
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
    warm_max = args.warm_max or WARM_MAX_LINES_DEFAULT
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
    """Generate canonical markdown for a cross_source referent file."""
    eid = entry.get('id', '?')
    key = entry.get('key') or entry.get('source') or '?'
    maps_to = entry.get('maps_to', '')
    ref = entry.get('ref', '')
    suggest = entry.get('suggest')

    lines = [f"# {eid} -- {key}"]
    if source_label:
        lines.append(f"**Source**: {source_label} | **ID**: {eid} | **Type**: cross_source")
    else:
        lines.append(f"**ID**: {eid} | **Type**: cross_source")
    lines.append("")
    lines.append("## Mapping")
    lines.append(f"**Key**: {key}")
    lines.append(f"**Maps to**: {maps_to}")
    if ref:
        lines.append(f"**Ref**: {ref}")
    if suggest is not None:
        lines.append(f"**Suggest**: {json.dumps(suggest)}")
    lines.append("")

    return '\n'.join(lines)


def make_convergence_web_md(entry):
    """Generate canonical markdown for a convergence_web referent file."""
    eid = entry.get('id', '?')
    thesis = entry.get('thesis', {})
    athesis = entry.get('athesis', {})
    synthesis = entry.get('synthesis', '')
    metathesis = entry.get('metathesis', '')

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

    return '\n'.join(lines)


def alpha_update_index(index, new_id, entry_type, source_folder, concept_key, filename):
    """Update all index structures for a new alpha entry.

    Handles: entries, sources, concept_index, source_index, summary counts.
    """
    # entries
    index.setdefault('entries', {})[new_id] = {
        "source": source_folder,
        "file": filename,
        "concept": concept_key,
        "type": entry_type
    }

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

    # concept_index
    if concept_key and concept_key != '?':
        concept_name = concept_key.split(':')[1].strip().lower() if ':' in concept_key else concept_key.strip().lower()
        if concept_name:
            index.setdefault('concept_index', {}).setdefault(concept_name, []).append(new_id)

    # source_index
    if concept_key and ':' in concept_key:
        prefix = concept_key.split(':')[0].strip()
        if prefix and not prefix.startswith('_'):
            index.setdefault('source_index', {}).setdefault(prefix, []).append(new_id)

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

    # concept_index
    if concept_key and concept_key != '?':
        concept_name = concept_key.split(':')[1].strip().lower() if ':' in concept_key else concept_key.strip().lower()
        if concept_name:
            clist = index.get('concept_index', {}).get(concept_name, [])
            if entry_id in clist:
                clist.remove(entry_id)
            if not clist:
                index.get('concept_index', {}).pop(concept_name, None)

    # source_index
    if concept_key and ':' in concept_key:
        prefix = concept_key.split(':')[0].strip()
        if prefix and not prefix.startswith('_'):
            slist = index.get('source_index', {}).get(prefix, [])
            if entry_id in slist:
                slist.remove(entry_id)
            if not slist:
                index.get('source_index', {}).pop(prefix, None)

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
    """Find the max numeric ID in the alpha index for a given prefix (w: or cw:)."""
    max_n = 0
    pattern = re.compile(rf'^{re.escape(prefix)}(\d+)$')
    for eid in index.get('entries', {}):
        m = pattern.match(eid)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n


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

def cmd_alpha_query(args):
    """Query alpha bin for specific referents.

    Supports three query modes:
      --id w:218        → Retrieve single entry by ID
      --source sartre   → List all entries from a source (case-insensitive prefix match)
      --concept total   → Search concept_index for matching terms
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
        # Direct ID lookup
        for qid in args.id:
            if qid in entries:
                info = entries[qid]
                # Read the actual file content
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
                    'content': content
                })
            else:
                results.append({'id': qid, 'status': 'not_found'})

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

    # Read entries from stdin
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

        # Update index
        alpha_update_index(index, new_id, entry_type, source_folder, concept_key, filename)

        results.append({
            "id": new_id,
            "file": filename,
            "source_folder": source_folder,
            "type": entry_type
        })

    # Update last_updated timestamp
    index['last_updated'] = str(date.today())

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
        index['last_updated'] = str(date.today())
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
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Session buffer manager — sigma trunk operations for hot/warm/cold layers'
    )
    subparsers = parser.add_subparsers(dest='command', help='Subcommand')

    # --- read ---
    p_read = subparsers.add_parser('read', help='Reconstruct context from buffer layers')
    p_read.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_read.add_argument('--warm-max', type=int, default=None, help='Warm layer max lines')
    p_read.set_defaults(func=cmd_read)

    # --- update ---
    p_update = subparsers.add_parser('update',
        help='Merge alpha stash (session changes) into buffer layers')
    p_update.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_update.add_argument('--input', default=None,
        help='Path to alpha stash JSON file (default: stdin)')
    p_update.set_defaults(func=cmd_update)

    # --- migrate ---
    p_migrate = subparsers.add_parser('migrate', help='Conservation enforcement')
    p_migrate.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_migrate.add_argument('--warm-max', type=int, default=None, help='Warm layer max lines')
    p_migrate.add_argument('--dry-run', action='store_true', help='Report without writing')
    p_migrate.set_defaults(func=cmd_migrate)

    # --- validate ---
    p_validate = subparsers.add_parser('validate', help='Check layers against constraints')
    p_validate.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_validate.add_argument('--warm-max', type=int, default=None, help='Warm layer max lines')
    p_validate.set_defaults(func=cmd_validate)

    # --- sync ---
    p_sync = subparsers.add_parser('sync', help='Sync MEMORY.md + project registry')
    p_sync.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_sync.add_argument('--memory-path', default=None, help='Path to MEMORY.md')
    p_sync.add_argument('--registry-path', default=None, help='Path to projects.json')
    p_sync.add_argument('--project-name', default=None, help='Project name for registry')
    p_sync.set_defaults(func=cmd_sync)

    # --- next-id ---
    p_nextid = subparsers.add_parser('next-id', help='Get next available ID')
    p_nextid.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_nextid.add_argument('--layer', required=True, choices=['warm', 'cold', 'convergence'],
                          help='Layer to get ID for')
    p_nextid.set_defaults(func=cmd_next_id)

    # --- handoff (full pipeline) ---
    p_handoff = subparsers.add_parser('handoff',
        help='Full pipeline: update + migrate + sync in one call (preferred)')
    p_handoff.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_handoff.add_argument('--input', default=None,
        help='Path to alpha stash JSON file (default: stdin)')
    p_handoff.add_argument('--warm-max', type=int, default=None, help='Warm layer max lines')
    p_handoff.add_argument('--memory-path', default=None, help='Path to MEMORY.md')
    p_handoff.add_argument('--registry-path', default=None, help='Path to projects.json')
    p_handoff.add_argument('--project-name', default=None, help='Project name for registry')
    p_handoff.set_defaults(func=cmd_handoff)

    # --- archive ---
    p_archive = subparsers.add_parser('archive', help='Cold->tower archival')
    p_archive.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_archive.add_argument('--force', action='store_true', help='Force even if under limit')
    p_archive.add_argument('--entry-ids', nargs='*', default=None,
                           help='Specific entry IDs to archive (e.g., c:7 c:12)')
    p_archive.set_defaults(func=cmd_archive)

    # --- alpha-read ---
    p_alpha_read = subparsers.add_parser('alpha-read',
        help='Read alpha bin summary (reference memory index)')
    p_alpha_read.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_alpha_read.set_defaults(func=cmd_alpha_read)

    # --- alpha-query ---
    p_alpha_query = subparsers.add_parser('alpha-query',
        help='Query alpha bin for referents by ID, source, or concept')
    p_alpha_query.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_alpha_query.add_argument('--id', nargs='+', default=None,
                               help='Retrieve entries by ID (e.g., w:218 cw:83)')
    p_alpha_query.add_argument('--source', default=None,
                               help='Search by source name (case-insensitive prefix match)')
    p_alpha_query.add_argument('--concept', default=None,
                               help='Search by concept name (case-insensitive partial match)')
    p_alpha_query.set_defaults(func=cmd_alpha_query)

    # --- alpha-write ---
    p_alpha_write = subparsers.add_parser('alpha-write',
        help='Write entries to alpha bin (reads JSON from stdin)')
    p_alpha_write.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_alpha_write.add_argument('--dry-run', action='store_true',
                               help='Validate and show what would be written without writing')
    p_alpha_write.add_argument('--id', dest='id_override', default=None,
                               help='Override auto-assigned ID (for first entry only)')
    p_alpha_write.set_defaults(func=cmd_alpha_write)

    # --- alpha-delete ---
    p_alpha_del = subparsers.add_parser('alpha-delete',
        help='Delete entries from alpha bin (removes files + updates index)')
    p_alpha_del.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_alpha_del.add_argument('--id', nargs='+', required=True,
                             help='Entry IDs to delete (e.g., w:218 cw:83)')
    p_alpha_del.set_defaults(func=cmd_alpha_delete)

    # --- alpha-validate ---
    p_alpha_val = subparsers.add_parser('alpha-validate',
        help='Validate alpha bin integrity (index vs files on disk)')
    p_alpha_val.add_argument('--buffer-dir', required=True, help='Path to buffer directory')
    p_alpha_val.set_defaults(func=cmd_alpha_validate)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
