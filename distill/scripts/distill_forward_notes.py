#!/usr/bin/env python3
"""distill_forward_notes.py — Forward note health, clustering, consolidation, and templates.

Scans forward_notes.json for related clusters, superseded notes, and
consolidation candidates. Cross-references descriptions against alpha
concept_index for semantic similarity.

Commands:
  health       — Cluster analysis, supersession detection, orphan scan
  consolidate  — Merge specified notes into one (user-reviewed)
  check-new    — Similarity check for new candidates
  template     — Output ready-to-fill template with current registry state

Usage:
    python distill_forward_notes.py template --notes forward_notes.json
    python distill_forward_notes.py health --notes forward_notes.json [--alpha-dir ...]
    python distill_forward_notes.py consolidate --notes forward_notes.json --merge 5.72 5.79 --into 5.72
    python distill_forward_notes.py check-new --notes forward_notes.json --description "..."

Dependencies: Python 3.10+ (stdlib only)
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from datetime import date, datetime
import time

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Tokenization + similarity
# ---------------------------------------------------------------------------

STOPWORDS = frozenset({
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'this',
    'that', 'with', 'from', 'have', 'been', 'will', 'would', 'could', 'should',
    'about', 'their', 'there', 'these', 'those', 'then', 'than', 'them', 'they',
    'some', 'into', 'also', 'just', 'like', 'make', 'does', 'each', 'both',
    'same', 'other', 'only', 'well', 'over', 'such', 'very', 'more', 'most',
    'between', 'through', 'during', 'before', 'after',
})


def tokenize(text):
    """Extract meaningful tokens from text."""
    if not text:
        return set()
    # Lowercase, extract word-like tokens
    tokens = set(re.findall(r'[a-z][a-z_]{2,}', text.lower()))
    return tokens - STOPWORDS


def jaccard(set_a, set_b):
    """Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def concept_overlap(tokens_a, tokens_b, concept_index):
    """Compute concept-aware overlap using alpha concept_index.

    Two token sets that both match the same alpha concept are related
    even if they share no literal words.
    """
    if not concept_index:
        return 0.0

    concepts_a = set()
    concepts_b = set()

    for concept_key in concept_index:
        if concept_key == '?':
            continue
        concept_lower = concept_key.lower()
        concept_tokens = set(re.findall(r'[a-z][a-z_]{2,}', concept_lower))

        if tokens_a & concept_tokens:
            concepts_a.add(concept_key)
        if tokens_b & concept_tokens:
            concepts_b.add(concept_key)

    shared = concepts_a & concepts_b
    total = concepts_a | concepts_b
    return len(shared) / len(total) if total else 0.0


def compute_similarity(desc_a, desc_b, concept_index=None):
    """Combined similarity: Jaccard + concept overlap."""
    tokens_a = tokenize(desc_a)
    tokens_b = tokenize(desc_b)

    j = jaccard(tokens_a, tokens_b)
    c = concept_overlap(tokens_a, tokens_b, concept_index) if concept_index else 0.0

    # Weighted combination: direct word overlap + concept-mediated overlap
    return 0.6 * j + 0.4 * c


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def find_clusters(notes, concept_index=None, threshold=0.2):
    """Find clusters of related forward notes.

    Uses single-linkage clustering: if any pair within a cluster exceeds
    the similarity threshold, they're in the same cluster.

    Returns list of clusters: [{notes: [note_ids], similarity: float}]
    """
    note_ids = list(notes.keys())
    if len(note_ids) < 2:
        return []

    # Precompute pairwise similarities
    pairs = []
    for i in range(len(note_ids)):
        for j in range(i + 1, len(note_ids)):
            id_a, id_b = note_ids[i], note_ids[j]
            desc_a = notes[id_a].get('description', '')
            desc_b = notes[id_b].get('description', '')
            sim = compute_similarity(desc_a, desc_b, concept_index)
            if sim >= threshold:
                pairs.append((id_a, id_b, sim))

    if not pairs:
        return []

    # Single-linkage clustering via union-find
    parent = {nid: nid for nid in note_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for id_a, id_b, _ in pairs:
        union(id_a, id_b)

    # Collect clusters
    clusters_map = {}
    for nid in note_ids:
        root = find(nid)
        if root not in clusters_map:
            clusters_map[root] = []
        clusters_map[root].append(nid)

    # Filter to clusters with 2+ members
    clusters = []
    for members in clusters_map.values():
        if len(members) < 2:
            continue
        # Compute max pairwise similarity within cluster
        max_sim = 0
        for id_a, id_b, sim in pairs:
            if id_a in members and id_b in members:
                max_sim = max(max_sim, sim)
        clusters.append({
            'notes': sorted(members),
            'max_similarity': round(max_sim, 3),
        })

    clusters.sort(key=lambda c: c['max_similarity'], reverse=True)
    return clusters


# ---------------------------------------------------------------------------
# Supersession detection
# ---------------------------------------------------------------------------

def detect_superseded(notes):
    """Detect notes that self-identify as redundant or superseded.

    Patterns:
    - "no new forward note needed" → likely superseded
    - Status already 'implemented' or 'superseded'
    - Description references another note number
    """
    candidates = []
    for note_id, note in notes.items():
        desc = note.get('description', '').lower()
        status = note.get('status', '')

        if status in ('implemented', 'superseded'):
            candidates.append({
                'note': note_id,
                'reason': f'status already {status}',
            })
            continue

        # Self-identified redundancy
        if 'no new forward note needed' in desc:
            candidates.append({
                'note': note_id,
                'reason': 'self-identifies as redundant',
            })
        elif 'already cover' in desc:
            candidates.append({
                'note': note_id,
                'reason': 'references existing coverage',
            })

        # References another forward note
        refs = re.findall(r'§5\.(\d+)', desc)
        other_refs = [r for r in refs if r != note_id.replace('5.', '')]
        if other_refs:
            candidates.append({
                'note': note_id,
                'reason': f'references §5.{", §5.".join(other_refs)}',
            })

    return candidates


# ---------------------------------------------------------------------------
# Source grouping
# ---------------------------------------------------------------------------

def group_by_source(notes):
    """Group notes by source for density analysis."""
    groups = {}
    for note_id, note in notes.items():
        source = note.get('source', 'unknown')
        if source not in groups:
            groups[source] = []
        groups[source].append(note_id)
    return groups


# ---------------------------------------------------------------------------
# Health command
# ---------------------------------------------------------------------------

def cmd_health(args):
    """Run forward note health analysis."""
    notes_path = Path(args.notes)
    if not notes_path.exists():
        print(json.dumps({'status': 'error', 'message': f'Not found: {notes_path}'}))
        return

    with open(notes_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)

    notes = registry.get('notes', {})
    next_number = registry.get('next_number', 0)

    if not notes:
        print(json.dumps({'status': 'ok', 'message': 'No forward notes to analyze.'}))
        return

    # Load alpha concept_index if available
    concept_index = None
    if args.alpha_dir:
        alpha_dir = Path(args.alpha_dir)
        index_path = alpha_dir / 'index.json'
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    alpha_index = json.load(f)
                concept_index = alpha_index.get('concept_index', {})
            except (json.JSONDecodeError, OSError):
                pass

    # Status counts
    status_counts = {}
    for note in notes.values():
        s = note.get('status', 'unknown')
        status_counts[s] = status_counts.get(s, 0) + 1

    # Cluster analysis
    clusters = find_clusters(notes, concept_index, threshold=0.2)

    # Supersession detection
    superseded = detect_superseded(notes)

    # Source density
    source_groups = group_by_source(notes)

    # Output report
    lines = [
        "=" * 60,
        "FORWARD NOTE HEALTH REPORT",
        "=" * 60,
        "",
        f"Total notes:       {len(notes)}",
        f"Next number:       §5.{next_number}",
        f"Status:            {', '.join(f'{v} {k}' for k, v in sorted(status_counts.items()))}",
        "",
    ]

    # Source density
    lines.append("--- SOURCES ---")
    for source, note_ids in sorted(source_groups.items(),
                                     key=lambda x: len(x[1]), reverse=True):
        lines.append(f"  {len(note_ids):2d}  {source}")

    # Clusters
    if clusters:
        lines.append("")
        lines.append(f"--- CONSOLIDATION CLUSTERS ({len(clusters)} found) ---")
        for i, cluster in enumerate(clusters):
            lines.append(
                f"  Cluster {i+1} (similarity: {cluster['max_similarity']:.3f}):"
            )
            for nid in cluster['notes']:
                desc = notes[nid].get('description', '')[:80]
                source = notes[nid].get('source', '?')[:30]
                lines.append(f"    §{nid:8s}  [{source}]")
                lines.append(f"           {desc}")
    else:
        lines.append("")
        lines.append("--- No consolidation clusters detected ---")

    # Supersession candidates
    if superseded:
        lines.append("")
        lines.append(f"--- SUPERSESSION CANDIDATES ({len(superseded)}) ---")
        for s in superseded:
            desc = notes[s['note']].get('description', '')[:60]
            lines.append(f"  §{s['note']:8s}  {s['reason']}")
            lines.append(f"           {desc}")

    lines.append("")
    lines.append("=" * 60)
    print("\n".join(lines))

    # JSON output for programmatic consumption
    if args.json_output:
        result = {
            'total_notes': len(notes),
            'next_number': next_number,
            'status_counts': status_counts,
            'clusters': clusters,
            'superseded': superseded,
            'source_density': {s: len(ids) for s, ids in source_groups.items()},
        }
        print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Consolidate command
# ---------------------------------------------------------------------------

def cmd_consolidate(args):
    """Merge specified forward notes into one."""
    notes_path = Path(args.notes)
    if not notes_path.exists():
        print(json.dumps({'status': 'error', 'message': f'Not found: {notes_path}'}))
        return

    with open(notes_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)

    notes = registry.get('notes', {})

    # Validate inputs
    merge_ids = args.merge
    into_id = args.into

    for mid in merge_ids:
        if mid not in notes:
            print(json.dumps({
                'status': 'error',
                'message': f'Note §5.{mid} not found in registry',
            }))
            return

    if into_id not in merge_ids:
        print(json.dumps({
            'status': 'error',
            'message': f'Target §5.{into_id} must be one of the merge notes',
        }))
        return

    absorbed = [mid for mid in merge_ids if mid != into_id]

    # Build merged description
    if args.description:
        merged_desc = args.description
    else:
        # Concatenate descriptions with source attribution
        parts = []
        for mid in sorted(merge_ids):
            source = notes[mid].get('source', '?')
            desc = notes[mid].get('description', '')
            parts.append(f"[{source}] {desc}")
        merged_desc = ' | '.join(parts)

    # Collect all sources
    sources = list(set(notes[mid].get('source', '') for mid in merge_ids))

    if args.dry_run:
        print(json.dumps({
            'status': 'dry_run',
            'action': 'consolidate',
            'surviving': f'§5.{into_id}',
            'absorbed': [f'§5.{a}' for a in absorbed],
            'merged_description': merged_desc,
            'sources': sources,
        }, indent=2))
        return

    # Execute merge
    # Update surviving note
    notes[into_id]['description'] = merged_desc
    notes[into_id]['date'] = str(date.today())
    if len(sources) > 1:
        notes[into_id]['source'] = ', '.join(sorted(sources))

    # Mark absorbed notes
    for aid in absorbed:
        notes[aid]['status'] = 'merged_into'
        notes[aid]['merged_into'] = into_id
        notes[aid]['merged_date'] = str(date.today())

    # Write back
    registry['notes'] = notes
    with open(notes_path, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2)

    print(json.dumps({
        'status': 'ok',
        'action': 'consolidated',
        'surviving': f'§5.{into_id}',
        'absorbed': [f'§5.{a}' for a in absorbed],
        'total_notes': len(notes),
        'active_notes': sum(1 for n in notes.values()
                            if n.get('status') not in ('merged_into', 'superseded', 'implemented')),
    }, indent=2))


# ---------------------------------------------------------------------------
# Similarity check (for integrate step)
# ---------------------------------------------------------------------------

def cmd_check_new(args):
    """Check a new forward note candidate against existing notes.

    Used by the integrate step after writing new candidates —
    flags potential consolidation targets for user review.

    Returns JSON with matches above threshold.
    """
    notes_path = Path(args.notes)
    if not notes_path.exists():
        print(json.dumps({'matches': []}))
        return

    with open(notes_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)

    notes = registry.get('notes', {})
    new_desc = args.description
    new_tokens = tokenize(new_desc)
    threshold = args.threshold or 0.2

    # Load alpha concept_index if available
    concept_index = None
    if args.alpha_dir:
        alpha_dir = Path(args.alpha_dir)
        index_path = alpha_dir / 'index.json'
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    alpha_index = json.load(f)
                concept_index = alpha_index.get('concept_index', {})
            except (json.JSONDecodeError, OSError):
                pass

    matches = []
    for note_id, note in notes.items():
        if note.get('status') in ('merged_into', 'superseded'):
            continue
        existing_desc = note.get('description', '')
        sim = compute_similarity(new_desc, existing_desc, concept_index)
        if sim >= threshold:
            matches.append({
                'note': f'§5.{note_id}',
                'source': note.get('source', '?'),
                'description': existing_desc[:100],
                'similarity': round(sim, 3),
            })

    matches.sort(key=lambda m: m['similarity'], reverse=True)
    print(json.dumps({'matches': matches[:5]}, indent=2))


# ---------------------------------------------------------------------------
# Template command
# ---------------------------------------------------------------------------

MARKER_TTL_SECONDS = 7200  # 2 hours


def touch_marker(notes_path: Path):
    """Write .fn_queried marker next to forward_notes.json (timestamp-based TTL)."""
    marker = notes_path.parent / '.fn_queried'
    marker.write_text(str(time.time()), encoding='utf-8')


def marker_is_valid(notes_path: Path) -> bool:
    """Check if .fn_queried marker exists and is within TTL."""
    marker = notes_path.parent / '.fn_queried'
    if not marker.exists():
        return False
    try:
        ts = float(marker.read_text(encoding='utf-8').strip())
        return (time.time() - ts) < MARKER_TTL_SECONDS
    except (ValueError, OSError):
        return False


def cmd_template(args):
    """Output a ready-to-fill forward note template with current registry state."""
    notes_path = Path(args.notes)
    if not notes_path.exists():
        print(f"Registry not found: {notes_path}")
        print(f"To create: start at next_number: 70 (§5.1–§5.69 reserved)")
        return

    with open(notes_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)

    notes = registry.get('notes', {})
    next_num = registry.get('next_number', 70)

    # Status breakdown
    by_status = {}
    for nid, note in notes.items():
        s = note.get('status', 'unknown')
        by_status.setdefault(s, []).append(nid)

    # Output
    today = date.today().isoformat()
    print(f"next_number: {next_num}  |  total: {len(notes)}")
    for status, ids in sorted(by_status.items()):
        print(f"  {status}: {len(ids)}  [{', '.join(sorted(ids)[-5:])}{'...' if len(ids) > 5 else ''}]")

    print()
    print("Template entry:")
    template = {
        f"5.{next_num}": {
            "source": "FILL: Source_Label",
            "description": "FILL: one-line description",
            "status": "candidate",
            "date": today,
        }
    }
    print(json.dumps(template, indent=2))
    print()
    print(f"After adding → run: distill_forward_notes.py check-new --notes {args.notes} --description \"...\"")

    # Touch marker so the write guard knows we've consulted the registry
    touch_marker(notes_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Forward note health, clustering, and consolidation')
    subparsers = parser.add_subparsers(dest='command')

    # health
    health_parser = subparsers.add_parser('health', help='Cluster analysis + health check')
    health_parser.add_argument('--notes', required=True, help='Path to forward_notes.json')
    health_parser.add_argument('--alpha-dir', default=None,
                                help='Path to alpha directory for concept overlap')
    health_parser.add_argument('--json', dest='json_output', action='store_true',
                                help='Also output JSON summary')

    # consolidate
    cons_parser = subparsers.add_parser('consolidate', help='Merge related notes')
    cons_parser.add_argument('--notes', required=True, help='Path to forward_notes.json')
    cons_parser.add_argument('--merge', nargs='+', required=True,
                              help='Note IDs to merge (e.g., 5.72 5.79)')
    cons_parser.add_argument('--into', required=True,
                              help='Note ID that survives (must be in --merge list)')
    cons_parser.add_argument('--description', default=None,
                              help='Override merged description')
    cons_parser.add_argument('--dry-run', action='store_true')

    # check-new (for integrate step)
    check_parser = subparsers.add_parser('check-new',
                                          help='Check new candidate against existing')
    check_parser.add_argument('--notes', required=True, help='Path to forward_notes.json')
    check_parser.add_argument('--description', required=True,
                               help='Description of the new candidate')
    check_parser.add_argument('--alpha-dir', default=None)
    check_parser.add_argument('--threshold', type=float, default=0.2)

    # template (ready-to-fill template + registry state)
    tmpl_parser = subparsers.add_parser('template',
                                         help='Output template with current registry state')
    tmpl_parser.add_argument('--notes', required=True, help='Path to forward_notes.json')

    args = parser.parse_args()

    commands = {
        'health': cmd_health,
        'consolidate': cmd_consolidate,
        'check-new': cmd_check_new,
        'template': cmd_template,
    }
    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
