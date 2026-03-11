#!/usr/bin/env python3
"""Mesological Grid Builder — pre-computed relevance grid for alpha-sigma bins.

Reads index.json (with reinforcement + clusters) and handoff.json (hot layer),
computes combined alpha*sigma scores, writes relevance_grid.json.

The grid replaces runtime O(n) keyword search with O(1) lookup:
  - sigma hook extracts keywords from user message
  - keywords map to grid cells via keyword_index
  - grid cell contains pre-ranked concepts → inject directly

Usage:
    python grid_builder.py --buffer-dir .claude/buffer [--dry-run]

Scoring architecture is PLUGGABLE: default_scoring can be swapped for
euler_scoring (or any fn with signature (degree, diversity, is_prime) -> float)
without changing surrounding code.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Scoring functions (pluggable interface)
# ---------------------------------------------------------------------------

def tap_scoring(degree, diversity, is_prime, ref_count=0, recency=0.0):
    """TAP score: adjacent possibility — per-concept structural importance.

    Higher adjacency in the convergence web = higher TAP.
    Temporal feedback from sigma_hits boosts operationally active concepts.

    Interface: (int, int, bool, int, float) -> float
    Can be swapped for any function with same signature.
    """
    base = degree * (1.0 + 0.1 * (diversity - 1)) * (1.5 if is_prime else 1.0)
    temporal_boost = 1.0 + 0.05 * min(ref_count, 20)  # cap at 2x boost
    return base * temporal_boost


# Backward compatibility alias
default_scoring = tap_scoring


# ---------------------------------------------------------------------------
# Alpha scoring
# ---------------------------------------------------------------------------

def compute_alpha_score(concept_id, reinforcement_data, scoring_fn=None):
    """Compute TAP (adjacent possibility) score for a concept.

    TAP = structural importance in the convergence web, boosted by
    temporal feedback from sigma hits (bidirectional alpha-sigma flow).

    Args:
        concept_id: w: entry ID
        reinforcement_data: {w_id: {degree, source_diversity, is_prime,
                                     ref_count, last_ref, trend}}
        scoring_fn: pluggable scoring function (default: tap_scoring)

    Returns:
        float TAP score (0.0 if concept has no reinforcement data)
    """
    if scoring_fn is None:
        scoring_fn = tap_scoring
    rdata = reinforcement_data.get(concept_id, {})
    degree = rdata.get('degree', 0)
    diversity = rdata.get('source_diversity', 0)
    is_prime = rdata.get('is_prime', False)
    ref_count = rdata.get('ref_count', 0)
    recency = 0.0  # reserved for date-based recency weighting
    if degree == 0:
        return 0.0
    return scoring_fn(degree, diversity, is_prime, ref_count, recency)


# ---------------------------------------------------------------------------
# Sigma scoring (contextual relevance)
# ---------------------------------------------------------------------------

def _tokenize(text):
    """Split text into lowercase tokens, strip short/common words."""
    if not text:
        return set()
    tokens = set(re.findall(r'[a-zA-Z_]{3,}', text.lower()))
    # Remove very common words that add noise
    stopwords = {
        'the', 'and', 'for', 'with', 'this', 'that', 'from', 'are', 'was',
        'have', 'has', 'been', 'not', 'but', 'can', 'will', 'would', 'should',
        'could', 'into', 'about', 'also', 'than', 'then', 'when', 'where',
        'which', 'their', 'there', 'these', 'those', 'they', 'what', 'how',
        'all', 'each', 'every', 'between', 'through', 'during', 'before',
        'after', 'above', 'below', 'does', 'did', 'had', 'its', 'other',
        'more', 'most', 'some', 'any', 'only', 'very', 'just', 'over',
        'such', 'may', 'might',
    }
    return tokens - stopwords


def compute_sigma_score(concept_id, entry, context_tokens, cluster_data,
                         w_to_cluster):
    """Compute contextual relevance of a concept to a sigma orientation context.

    Args:
        concept_id: w: entry ID
        entry: entry dict with concept, source, etc.
        context_tokens: set of tokens from orientation/thread text
        cluster_data: list of cluster dicts
        w_to_cluster: {w_id: cluster_id}

    Returns:
        float score based on keyword overlap + cluster proximity
    """
    # Concept name overlap
    concept_name = entry.get('concept', '')
    if ':' in concept_name:
        concept_name = concept_name.split(':', 1)[1]
    concept_tokens = _tokenize(concept_name.replace('_', ' '))
    source = entry.get('source', '')
    source_tokens = _tokenize(source.replace('-', ' ').replace('_', ' '))

    # Direct keyword overlap
    overlap = len(concept_tokens & context_tokens)
    source_overlap = len(source_tokens & context_tokens)

    score = overlap * 2.0 + source_overlap * 0.5

    # Cluster proximity bonus: if any cluster hub is in the context,
    # boost other members of that cluster
    cluster_id = w_to_cluster.get(concept_id)
    if cluster_id is not None and cluster_data:
        cluster = cluster_data[cluster_id] if cluster_id < len(cluster_data) else None
        if cluster:
            # Check if cluster name tokens overlap with context
            cluster_name_tokens = _tokenize(cluster['name'].replace('-', ' ').replace('_', ' '))
            cluster_overlap = len(cluster_name_tokens & context_tokens)
            score += cluster_overlap * 0.3

    return score


# ---------------------------------------------------------------------------
# Grid construction
# ---------------------------------------------------------------------------

def build_grid(index, hot, scoring_fn=None, top_n=5, sigma_scores=None):
    """Build the relevance grid from index + hot layer.

    For each coordinate (global, thread), score all w: entries with
    combined alpha*sigma, keep top_n per cell. sigma_scores (W') from
    continuous adjustment provide real-time boosts between reinforce runs.

    Args:
        index: alpha index.json contents (with reinforcement, clusters)
        hot: handoff.json contents (with orientation, open_threads)
        scoring_fn: pluggable alpha scoring function
        top_n: concepts to keep per cell
        sigma_scores: optional dict {concept_id: float} from .sigma_scores

    Returns:
        grid dict ready for JSON serialization
    """
    entries = index.get('entries', {})
    reinforcement = index.get('reinforcement', {})
    clusters = index.get('clusters', [])
    w_to_cluster = index.get('w_to_cluster', {})

    orientation = hot.get('orientation', {})
    open_threads = hot.get('open_threads', [])

    # Build global context tokens from orientation
    global_text_parts = [
        orientation.get('core_insight', ''),
        orientation.get('practical_warning', ''),
    ]
    why_keys = orientation.get('why_keys', {})
    for source_name, description in why_keys.items():
        global_text_parts.append(f'{source_name} {description}')
    global_tokens = _tokenize(' '.join(global_text_parts))

    # Collect all w: entries for scoring
    w_entries = {eid: einfo for eid, einfo in entries.items()
                 if eid.startswith('w:')}

    # Build cells
    cells = {}

    # W' boost function: continuous score provides real-time learning boost
    if sigma_scores is None:
        sigma_scores = {}

    def _w_prime_boost(eid, base_score):
        """Apply W' (continuous score) boost to base combined score."""
        boost = sigma_scores.get(eid, 0.0)
        if boost > 0:
            return base_score * (1.0 + min(boost, 2.0))  # cap at 3x
        return base_score

    # --- Global cell ---
    global_scores = []
    for eid, einfo in w_entries.items():
        alpha = compute_alpha_score(eid, reinforcement, scoring_fn)
        sigma = compute_sigma_score(eid, einfo, global_tokens, clusters,
                                     w_to_cluster)
        combined = alpha * sigma if sigma > 0 else alpha * 0.01
        combined = _w_prime_boost(eid, combined)
        if combined > 0:
            global_scores.append({
                'id': eid,
                'concept': einfo.get('concept', '?'),
                'source': einfo.get('source', '?'),
                'score': round(combined, 2),
                'alpha': round(alpha, 2),
                'sigma': round(sigma, 2),
            })
    global_scores.sort(key=lambda x: x['score'], reverse=True)
    global_top = global_scores[:top_n]
    tip_score = sum(c['score'] for c in global_top)
    cells['global'] = {'concepts': global_top, 'tip_score': round(tip_score, 2)}

    # --- Thread cells ---
    thread_names = []
    for thread_entry in open_threads:
        thread_text = thread_entry.get('thread', '')
        ref = thread_entry.get('ref', '')
        thread_name = thread_text[:60].strip()
        if not thread_name:
            continue
        thread_names.append(thread_name)

        thread_tokens = _tokenize(f'{thread_text} {ref}')
        # Merge with global for richer context
        combined_tokens = global_tokens | thread_tokens

        thread_scores = []
        for eid, einfo in w_entries.items():
            alpha = compute_alpha_score(eid, reinforcement, scoring_fn)
            sigma = compute_sigma_score(eid, einfo, combined_tokens, clusters,
                                         w_to_cluster)
            combined = alpha * sigma if sigma > 0 else 0
            combined = _w_prime_boost(eid, combined)
            if combined > 0:
                thread_scores.append({
                    'id': eid,
                    'concept': einfo.get('concept', '?'),
                    'source': einfo.get('source', '?'),
                    'score': round(combined, 2),
                })
        thread_scores.sort(key=lambda x: x['score'], reverse=True)
        thread_top = thread_scores[:top_n]
        tip_score = sum(c['score'] for c in thread_top)
        cell_key = f'thread:{thread_name}'
        cells[cell_key] = {'concepts': thread_top, 'tip_score': round(tip_score, 2)}

    # Build phase text from active_work
    active_work = hot.get('active_work', {})
    phase = active_work.get('phase', '')

    # W' state from continuous scores
    w_prime = sigma_scores.get('__W_prime', 0)
    w_prev = sigma_scores.get('__W_prev', 0)
    boosted_count = sum(1 for eid in w_entries if sigma_scores.get(eid, 0) > 0)

    grid = {
        'schema_version': 3,
        'computed': datetime.now().isoformat(timespec='seconds'),
        'coordinates': {
            'phase': phase,
            'threads': thread_names,
        },
        'cells': cells,
        'keyword_index': {},
        'temporal': {},
        'w_prime': {
            'W_prime': w_prime,
            'W_at_build': w_prev,
            'boosted_concepts': boosted_count,
        },
    }

    return grid


def build_keyword_index(grid, entries):
    """Build reverse map: keyword -> [cell_keys] for O(1) lookup.

    Scans concept names in each cell, tokenizes, builds reverse index.
    """
    keyword_index = {}

    for cell_key, cell_data in grid.get('cells', {}).items():
        for concept_entry in cell_data.get('concepts', []):
            concept_name = concept_entry.get('concept', '')
            if ':' in concept_name:
                concept_name = concept_name.split(':', 1)[1]
            tokens = _tokenize(concept_name.replace('_', ' '))
            source = concept_entry.get('source', '')
            source_tokens = _tokenize(source.replace('-', ' ').replace('_', ' '))
            for token in tokens | source_tokens:
                if token not in keyword_index:
                    keyword_index[token] = []
                if cell_key not in keyword_index[token]:
                    keyword_index[token].append(cell_key)

    grid['keyword_index'] = keyword_index
    return grid


# ---------------------------------------------------------------------------
# Temporal signature management
# ---------------------------------------------------------------------------

def update_temporal(grid, hits_log_path):
    """Read .sigma_hits log, compute per-concept temporal data.

    Args:
        grid: grid dict (modified in place)
        hits_log_path: Path to .sigma_hits file

    Returns:
        grid dict with updated temporal section
    """
    if not hits_log_path.exists():
        return grid

    concept_hits = {}
    try:
        with open(hits_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                date_str = parts[0]
                for concept_id in parts[1:]:
                    if concept_id.startswith('w:'):
                        if concept_id not in concept_hits:
                            concept_hits[concept_id] = {
                                'ref_count': 0, 'first_ref': date_str,
                                'last_ref': date_str,
                            }
                        concept_hits[concept_id]['ref_count'] += 1
                        concept_hits[concept_id]['last_ref'] = date_str
    except OSError:
        pass

    # Compute trend (simple: rising if recent refs > early refs)
    for cid, data in concept_hits.items():
        data['trend'] = 'stable'  # default; refined when more data accrues

    grid['temporal'] = {
        'hits_count': len(concept_hits),
        'concepts': concept_hits,
    }
    return grid


# ---------------------------------------------------------------------------
# Incremental grid adjustments (non-catastrophic learning)
# ---------------------------------------------------------------------------

def apply_incremental_adjustments(grid, adjustments_path):
    """Read .grid_adjustments and nudge cell scores incrementally.

    Each confirmation bumps matched concepts' scores up;
    each disconfirmation nudges down. This prevents catastrophic
    forgetting — accumulated sigma feedback persists across rebuilds.

    Returns grid with adjusted scores + clears the adjustments file.
    """
    if not adjustments_path.exists():
        return grid

    # Parse adjustments
    confirmations = {}  # concept_id -> confirm_count
    disconfirmations = {}
    try:
        with open(adjustments_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    adj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for cid in adj.get('concepts', []):
                    if adj.get('type') == 'confirm':
                        confirmations[cid] = confirmations.get(cid, 0) + 1
                    else:
                        disconfirmations[cid] = disconfirmations.get(cid, 0) + 1
    except OSError:
        return grid

    if not confirmations and not disconfirmations:
        return grid

    # Apply adjustments to cell scores
    adjust_rate = 0.05  # per confirmation/disconfirmation
    for cell_key, cell_data in grid.get('cells', {}).items():
        for concept_entry in cell_data.get('concepts', []):
            cid = concept_entry.get('id', '')
            confirms = confirmations.get(cid, 0)
            disconfirms = disconfirmations.get(cid, 0)
            if confirms or disconfirms:
                nudge = (confirms - disconfirms) * adjust_rate
                concept_entry['score'] = round(
                    max(0, concept_entry.get('score', 0) + nudge), 2)
                concept_entry['incremental'] = confirms - disconfirms

    # Record adjustment metadata
    grid['incremental'] = {
        'confirmations': sum(confirmations.values()),
        'disconfirmations': sum(disconfirmations.values()),
        'concepts_adjusted': len(set(confirmations) | set(disconfirmations)),
    }

    # Clear adjustments file (consumed)
    try:
        adjustments_path.unlink()
    except OSError:
        pass

    return grid


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Build mesological relevance grid')
    parser.add_argument('--buffer-dir', required=True,
                        help='Path to buffer directory (e.g., .claude/buffer)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print grid to stdout without writing file')
    args = parser.parse_args()

    buf_dir = Path(args.buffer_dir)

    # Read alpha index
    index_path = buf_dir / 'alpha' / 'index.json'
    if not index_path.exists():
        print(json.dumps({'status': 'error', 'message': 'No alpha index found'}))
        sys.exit(1)

    with open(index_path, 'r', encoding='utf-8') as f:
        index = json.load(f)

    # Check prerequisites
    if 'reinforcement' not in index:
        print(json.dumps({
            'status': 'error',
            'message': 'No reinforcement data. Run alpha-reinforce first.'
        }))
        sys.exit(1)

    # Read hot layer
    hot_path = buf_dir / 'handoff.json'
    if not hot_path.exists():
        print(json.dumps({'status': 'error', 'message': 'No handoff.json found'}))
        sys.exit(1)

    with open(hot_path, 'r', encoding='utf-8') as f:
        hot = json.load(f)

    # Read continuous scores (W' — sigma-driven incremental boosts)
    sigma_scores_path = buf_dir / '.sigma_scores'
    sigma_scores = {}
    if sigma_scores_path.exists():
        try:
            with open(sigma_scores_path, 'r', encoding='utf-8') as f:
                sigma_scores = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Build grid (with continuous score boosts)
    grid = build_grid(index, hot, scoring_fn=default_scoring,
                       sigma_scores=sigma_scores)
    entries = index.get('entries', {})
    grid = build_keyword_index(grid, entries)

    # Update temporal data
    hits_log = buf_dir / '.sigma_hits'
    grid = update_temporal(grid, hits_log)

    # Apply incremental adjustments (non-catastrophic learning)
    adj_path = buf_dir / '.grid_adjustments'
    grid = apply_incremental_adjustments(grid, adj_path)

    if args.dry_run:
        print(json.dumps(grid, indent=2))
        return

    # Write grid
    grid_path = buf_dir / 'relevance_grid.json'
    with open(grid_path, 'w', encoding='utf-8') as f:
        json.dump(grid, f, indent=2)

    total_concepts = sum(
        len(cell.get('concepts', []))
        for cell in grid['cells'].values()
    )
    total_keywords = len(grid.get('keyword_index', {}))

    print(json.dumps({
        'status': 'ok',
        'message': f'Grid written to {grid_path}',
        'cells': len(grid['cells']),
        'total_concepts': total_concepts,
        'keywords_indexed': total_keywords,
        'temporal_hits': grid.get('temporal', {}).get('hits_count', 0),
    }, indent=2))


if __name__ == '__main__':
    main()
