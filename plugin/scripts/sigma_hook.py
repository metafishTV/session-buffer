#!/usr/bin/env python3
"""
Session Buffer — Sigma Hook (UserPromptSubmit)

Fires on every user message. Cascades through sigma layers:

  message → gates → hot layer → alpha (if needed) → silent exit

Gates (exit-early, zero token cost):
  0a. Post-compaction relay: inject buffer summary if .compact_marker present
  0b. Distill-active: skip entirely when .distill_active marker present
  0c. Grid lookup: pre-computed relevance grid (O(1) if grid exists, skip IDF)
  1. Suppress list: .sigma_suppress file lists concepts/threads to ignore
  2. Staleness gate: skip hot level when buffer already loaded this session
  3. IDF-weighted scoring: keyword weight = 1/n (n = concept matches in corpus)
  4. Scaling threshold: longer prompts need higher total weight to fire

Cascade levels:
  1. Hot layer — active_work, open_threads, decisions, why_keys
  2. Alpha — concept_index fallthrough (only when hot misses)

Output format (ultra-minimal):
  sigma hot: thread: [noted] R&B deep review.
  sigma alpha: w:62 alterity (Levinas) | w:73 rhizomatic (DG)

Scoring model:
  IDF weight per keyword = 1 / max(1, num_concepts_matched)
    "alterity" matches 1 concept  → weight 1.0
    "structure" matches 12 concepts → weight 0.08
    "review" matches 0 concepts   → weight 0.0
  Threshold = 0.8 + non-linear(num_keywords) (scales with prompt size)
    3 keywords  → threshold 1.04
    10 keywords → threshold 1.45
    25 keywords → threshold 2.20

Dynamic scalars (scale with corpus size and/or prompt length):
  - MAX_KEYWORDS:  8-25 (prompt word_count // 20)
  - MAX_INJECT:    3-5  (prompt word_count brackets)
  - SCORE_EXACT:   2-4  (corpus size brackets)
  - MIN_SCORE:     1.5-3.0 (corpus size brackets)
  - THRESHOLD:     non-linear — 0.08/kw for first 5, 0.05/kw after

Design constraints:
  - Total injection < ~100 tokens
  - Must complete in <5s
  - Each gate reduces token cost, never adds
"""

import sys
import os
import io
import json
import re

# Force UTF-8 on Windows
# Guard: only wrap when running as main script, not when imported by tests
if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Constants — static
# ---------------------------------------------------------------------------

MIN_WORD_LEN = 4           # skip short words (below this = noise)
SCORE_SUBSTRING = 1        # substring match weight (baseline)
SUBSTRING_WEIGHT = 0.25    # IDF contribution ratio for substring vs exact matches

# ---------------------------------------------------------------------------
# Dynamic scalars — functions of corpus size, prompt length, or both
# ---------------------------------------------------------------------------

def dynamic_max_keywords(word_count):
    """Scale keyword extraction with prompt size.

    Short prompts (< 50 words)  → 8 keywords  (tight focus)
    Medium prompts (50-250)     → 10-15 keywords
    Long prompts (250+)         → up to 25 keywords (need broader net)
    """
    return min(25, max(8, word_count // 20))


def dynamic_max_inject(word_count):
    """Scale injection slots with prompt size.

    Short prompts → 3 (default)
    Long prompts (200+) → up to 5
    """
    if word_count >= 200:
        return 5
    if word_count >= 100:
        return 4
    return 3


def dynamic_score_exact(corpus_size):
    """Scale exact-match multiplier with corpus size.

    Small corpus (< 50)   → 2 (fewer concepts = less precision needed)
    Medium corpus (50-300) → 3
    Large corpus (300+)    → 4 (need sharper exactness penalty)
    """
    if corpus_size >= 300:
        return 4
    if corpus_size >= 50:
        return 3
    return 2


def dynamic_min_score(corpus_size):
    """Scale minimum alpha qualification score with corpus size.

    Small corpus (< 50)   → 1.5 (lower bar, fewer false positives possible)
    Medium corpus (50-300) → 2.0
    Large corpus (300+)    → 3.0 (higher bar to cut noise)
    """
    if corpus_size >= 300:
        return 3.0
    if corpus_size >= 50:
        return 2.0
    return 1.5


# IDF threshold scaling — non-linear (steep for first 5 keywords, gentler after)
THRESHOLD_BASE = 0.8   # minimum weight for very short prompts

def confidence_threshold(num_keywords):
    """Compute minimum total IDF weight needed to fire injection.

    Non-linear scaling — first 5 keywords at 0.08 per keyword,
    keywords 6+ at 0.05 per keyword. Longer prompts need stronger
    evidence but with diminishing marginal threshold increase.

    3 keywords  → 0.8 + 0.24 = 1.04
    5 keywords  → 0.8 + 0.40 = 1.20
    10 keywords → 0.8 + 0.40 + 0.25 = 1.45
    15 keywords → 0.8 + 0.40 + 0.50 = 1.70
    25 keywords → 0.8 + 0.40 + 1.00 = 2.20
    """
    if num_keywords <= 5:
        return THRESHOLD_BASE + 0.08 * num_keywords
    return THRESHOLD_BASE + 0.08 * 5 + 0.05 * (num_keywords - 5)

# Common words to skip
STOPWORDS = frozenset({
    'this', 'that', 'what', 'which', 'where', 'when', 'with', 'from',
    'have', 'been', 'will', 'would', 'could', 'should', 'about', 'their',
    'there', 'these', 'those', 'then', 'than', 'them', 'they', 'some',
    'into', 'also', 'just', 'like', 'make', 'made', 'does', 'doing',
    'done', 'much', 'many', 'more', 'most', 'such', 'very', 'each',
    'both', 'same', 'other', 'only', 'well', 'back', 'over', 'here',
    'after', 'before', 'being', 'still', 'first', 'last', 'even',
    'want', 'need', 'know', 'think', 'look', 'find', 'give', 'tell',
    'take', 'come', 'keep', 'help', 'show', 'turn', 'work', 'call',
    'going', 'thing', 'right', 'good', 'long', 'great', 'little',
    'file', 'code', 'read', 'write', 'edit', 'commit', 'push', 'pull',
    'test', 'build', 'sure', 'okay', 'yeah', 'please', 'thanks',
    'can', 'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
})


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def find_buffer_dir(start_path):
    """Walk up from start_path looking for .claude/buffer/handoff.json."""
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
    """Read JSON file, return dict or None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_hook_input():
    """Read hook input JSON from stdin."""
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            return json.loads(stdin_data)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def emit(output):
    """Write JSON output and exit."""
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.exit(0)


def emit_empty():
    """No match — silent exit."""
    emit({})


# ---------------------------------------------------------------------------
# GATE 1: Suppress list
# ---------------------------------------------------------------------------

def load_suppress_list(buffer_dir):
    """Load .sigma_suppress file — one entry per line.

    Entries are lowercased concept names, thread fragments, or work IDs
    that should be silenced. Lines starting with # are comments.
    Returns frozenset of suppressed terms.
    """
    suppress_path = os.path.join(buffer_dir, '.sigma_suppress')
    try:
        with open(suppress_path, 'r', encoding='utf-8') as f:
            entries = set()
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    entries.add(line.lower())
            return frozenset(entries)
    except (FileNotFoundError, OSError):
        return frozenset()


def is_suppressed(text, suppress_list):
    """Check if any suppress entry appears in text."""
    if not suppress_list:
        return False
    text_lower = text.lower()
    for entry in suppress_list:
        if entry in text_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# GATE 2: Distill-active gate
# ---------------------------------------------------------------------------

def is_distill_active(buffer_dir):
    """Check if a distillation is in progress.

    Looks for .distill_active marker written by the distill skill at start,
    cleaned at end. When active, sigma injection would create entropic
    feedback — the user's prompts are already full of concept/source keywords
    from the material being distilled, so matching against alpha would
    shotgun-inject the very concepts the distill process is already reading.
    Returns True if sigma should skip entirely.
    """
    marker = os.path.join(buffer_dir, '.distill_active')
    return os.path.exists(marker)


# ---------------------------------------------------------------------------
# GATE 3: Staleness gate
# ---------------------------------------------------------------------------

def is_hot_stale(buffer_dir):
    """Check if buffer was already loaded this session (hot context is redundant).

    Looks for .buffer_loaded marker written by /buffer:on.
    If present, hot-level hints add no value — the AI already has the full hot layer.
    Returns True if hot should be skipped (buffer already loaded).
    """
    marker = os.path.join(buffer_dir, '.buffer_loaded')
    return os.path.exists(marker)


# ---------------------------------------------------------------------------
# GATE 3: IDF weighting + scaling threshold
# ---------------------------------------------------------------------------

def compute_idf_weights(keywords, concept_index):
    """Compute information weight per keyword using corpus frequency.

    Distinguishes exact concept matches (high signal) from substring
    matches (incidental, low signal):
      - Exact match:    weight contribution = 1.0 / num_exact_matches
      - Substring match: weight contribution = 0.25 / num_substring_matches

    "alterity" (1 exact match)  → weight 1.0  (specific, real concept)
    "deep"     (0 exact, 1 sub) → weight 0.25 (incidental substring)
    "review"   (0 matches)      → weight 0.0  (noise)

    Returns dict of keyword → float weight.
    """
    weights = {}

    for kw in keywords:
        exact_matches = 0
        substring_matches = 0

        for concept_key in concept_index:
            if concept_key == '?':
                continue
            concept_lower = concept_key.lower()
            if kw == concept_lower:
                exact_matches += 1
            elif kw in concept_lower or concept_lower in kw:
                substring_matches += 1

        # Exact matches dominate: the keyword IS a concept
        # Substring matches are weak: "deep" in "some_deep_concept"
        weight = 0.0
        if exact_matches > 0:
            weight += 1.0 / exact_matches
        if substring_matches > 0:
            weight += SUBSTRING_WEIGHT / substring_matches

        weights[kw] = weight

    return weights


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def extract_keywords(text, max_keywords=None):
    """Extract meaningful keywords from user message.

    max_keywords scales dynamically with prompt size if not overridden.
    Preserves underscore_joined terms (likely concept names).
    """
    if not text:
        return []

    # Compute dynamic keyword cap from word count if not overridden
    word_count = len(text.split())
    if max_keywords is None:
        max_keywords = dynamic_max_keywords(word_count)

    # Find underscore_joined terms first (high signal)
    underscore_terms = re.findall(r'[a-zA-Z]+(?:_[a-zA-Z]+)+', text)
    underscore_lower = [t.lower() for t in underscore_terms]

    # Split into words
    cleaned = text.lower()
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    words = cleaned.split()

    keywords = []
    seen = set()

    for term in underscore_lower:
        if term not in seen:
            keywords.append(term)
            seen.add(term)

    for w in words:
        if (len(w) >= MIN_WORD_LEN
                and w not in STOPWORDS
                and w not in seen
                and w.isalpha()):
            keywords.append(w)
            seen.add(w)

    return keywords[:max_keywords]


# ---------------------------------------------------------------------------
# CASCADE LEVEL 1: Hot layer matching
# ---------------------------------------------------------------------------

def word_match(keyword, text_lower):
    """Check if keyword appears as a whole word in text (not as substring of another word)."""
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text_lower))


def match_hot(keywords, hot, suppress_list, idf_weights, threshold,
              max_inject=3):
    """Match keywords against hot layer fields using IDF-weighted scoring.

    Checks: active_work, open_threads, recent_decisions, orientation.why_keys.
    Uses word-boundary matching to avoid false positives.
    Filters suppressed entries.
    Requires total IDF weight of matching keywords >= threshold.
    Returns list of (label, text) hits, max max_inject.
    """
    if not keywords or not hot:
        return []

    hits = []

    # --- active_work fields ---
    aw = hot.get('active_work', {})
    for field in ('current_phase', 'in_progress', 'next_action'):
        val = aw.get(field)
        if val and isinstance(val, str) and val != 'None':
            if is_suppressed(val, suppress_list):
                continue
            val_lower = val.lower()
            total_weight = sum(
                idf_weights.get(kw, 0.0)
                for kw in keywords
                if word_match(kw, val_lower)
            )
            if total_weight >= threshold:
                hits.append(('active', f"{field}: {val}"))

    # --- open_threads ---
    threads = hot.get('open_threads', [])
    for t in threads:
        thread_text = t.get('thread', '')
        status = t.get('status', '?')
        if thread_text:
            if is_suppressed(thread_text, suppress_list):
                continue
            thread_lower = thread_text.lower()
            total_weight = sum(
                idf_weights.get(kw, 0.0)
                for kw in keywords
                if word_match(kw, thread_lower)
            )
            if total_weight >= threshold:
                hits.append(('thread', f"[{status}] {thread_text}"))

    # --- recent_decisions ---
    decisions = hot.get('recent_decisions', [])
    for d in decisions:
        what = d.get('what', '')
        chose = d.get('chose', '')
        combined = f"{what} {chose}"
        if is_suppressed(combined, suppress_list):
            continue
        combined_lower = combined.lower()
        total_weight = sum(
            idf_weights.get(kw, 0.0)
            for kw in keywords
            if word_match(kw, combined_lower)
        )
        if total_weight >= threshold:
            hits.append(('decision', f"{what} -> {chose}"))

    # --- orientation.why_keys (source names — single keyword ok here,
    #     these are short and high-signal, exempt from threshold) ---
    why_keys = hot.get('orientation', {}).get('why_keys', [])
    matched_sources = []
    for wk in why_keys:
        if is_suppressed(wk, suppress_list):
            continue
        wk_lower = wk.lower()
        for kw in keywords:
            if kw == wk_lower or kw in wk_lower or wk_lower in kw:
                matched_sources.append(wk)
                break
    if matched_sources:
        hits.append(('source', ', '.join(matched_sources)))

    return hits[:max_inject]


def format_hot_hits(hits):
    """Format hot layer hits into minimal injection string."""
    parts = []
    for label, text in hits:
        if len(text) > 60:
            text = text[:57] + '...'
        parts.append(f"{label}: {text}")

    return 'sigma hot: ' + ' | '.join(parts)


# ---------------------------------------------------------------------------
# CASCADE LEVEL 2: Alpha concept matching (fallthrough)
# ---------------------------------------------------------------------------

def match_alpha_concepts(keywords, concept_index, suppress_list,
                          idf_weights, threshold, score_exact=3,
                          min_score=2.0, max_inject=3):
    """Match keywords against alpha concept_index keys with IDF weighting.

    For each concept, sums the IDF weight of matching keywords.
    Exact match gets the keyword's full IDF weight * score_exact multiplier.
    Substring match gets IDF weight * SCORE_SUBSTRING.
    Requires total weighted score >= min_score AND >= threshold.
    Filters suppressed concepts.
    Returns list of (concept_key, work_ids, weighted_score) sorted desc.
    """
    if not keywords or not concept_index:
        return []

    effective_threshold = max(threshold, min_score)
    scores = {}

    for concept_key, work_ids in concept_index.items():
        if concept_key == '?':
            continue
        if is_suppressed(concept_key, suppress_list):
            continue

        concept_lower = concept_key.lower()
        weighted_score = 0.0

        for kw in keywords:
            w = idf_weights.get(kw, 0.0)
            if w == 0.0:
                continue
            if kw == concept_lower:
                weighted_score += w * score_exact
            elif kw in concept_lower or concept_lower in kw:
                weighted_score += w * SCORE_SUBSTRING

        if weighted_score >= effective_threshold:
            scores[concept_key] = (work_ids, weighted_score)

    ranked = sorted(scores.items(), key=lambda x: x[1][1], reverse=True)
    return [(key, ids, sc) for key, (ids, sc) in ranked[:max_inject]]


def find_source_for_id(work_id, sources_data):
    """Find which source a work ID belongs to. Returns source name or None."""
    if not sources_data:
        return None

    for source_key, source_info in sources_data.items():
        if not isinstance(source_info, dict):
            continue
        for id_list_key in ('cross_source_ids', 'convergence_web_ids'):
            id_list = source_info.get(id_list_key, [])
            if work_id in id_list:
                return source_key
    return None


def format_alpha_hits(concept_matches, sources_data):
    """Format alpha concept matches into minimal injection string."""
    parts = []

    for concept_key, work_ids, score in concept_matches:
        wid = work_ids[0] if isinstance(work_ids, list) and work_ids else '?'
        source = find_source_for_id(wid, sources_data)
        if source:
            parts.append(f"{wid} {concept_key} ({source})")
        else:
            parts.append(f"{wid} {concept_key}")

    return 'sigma alpha: ' + ' | '.join(parts)


# ---------------------------------------------------------------------------
# Post-compaction relay
# ---------------------------------------------------------------------------

def check_compact_relay(buffer_dir, cwd):
    """If a .compact_marker exists, inject full buffer summary and consume it.

    This acts as a PostCompact proxy — the PreCompact hook writes the marker,
    and the first UserPromptSubmit after compaction picks it up here.
    Returns True if relay fired (caller should exit), False otherwise.
    """
    marker_path = os.path.join(buffer_dir, '.compact_marker')
    if not os.path.exists(marker_path):
        return False

    hot = read_json(os.path.join(buffer_dir, 'handoff.json'))
    if not hot:
        # Marker exists but hot layer gone — clean up and skip
        try:
            os.remove(marker_path)
        except OSError:
            pass
        return False

    # Import compact_hook's summary builder (same scripts/ directory)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'compact_hook', os.path.join(script_dir, 'compact_hook.py'))
        compact_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compact_mod)

        hot_max, warm_max, cold_max = compact_mod.detect_layer_limits(cwd)
        summary = compact_mod.build_compact_summary(
            hot, buffer_dir, hot_max, warm_max, cold_max)
    except Exception:
        # Fallback: minimal summary if import fails
        ns = hot.get('natural_summary', '')
        aw = hot.get('active_work', {})
        phase = aw.get('current_phase', '?')
        summary = (
            f"POST-COMPACTION RECOVERY (minimal)\n"
            f"Phase: {phase}\n"
            f"Summary: {ns}\n"
            f"Run /buffer:on for full context."
        )

    # Consume marker
    try:
        os.remove(marker_path)
    except OSError:
        pass

    emit({"suppressOutput": True, "systemMessage": summary})


# ---------------------------------------------------------------------------
# GATE 0c: Grid lookup (pre-computed relevance grid)
# ---------------------------------------------------------------------------

def try_grid_lookup(buffer_dir, keywords):
    """Try to match keywords against pre-computed relevance grid.

    Reads relevance_grid.json, matches keywords against keyword_index,
    picks best cell, returns formatted concepts. Returns None if no grid
    or no match (fall through to existing IDF scoring).
    """
    grid_path = os.path.join(buffer_dir, 'relevance_grid.json')
    if not os.path.isfile(grid_path):
        return None

    try:
        with open(grid_path, 'r', encoding='utf-8') as f:
            grid = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    keyword_index = grid.get('keyword_index', {})
    cells = grid.get('cells', {})
    if not keyword_index or not cells:
        return None

    # Score each cell by keyword hit count
    cell_scores = {}
    for kw in keywords:
        kw_lower = kw.lower()
        matching_cells = keyword_index.get(kw_lower, [])
        for cell_key in matching_cells:
            cell_scores[cell_key] = cell_scores.get(cell_key, 0) + 1

    if not cell_scores:
        return None

    # Pick best cell (highest keyword hits, prefer thread over global)
    best_cell = max(cell_scores, key=lambda k: (cell_scores[k], k != 'global'))
    cell_data = cells.get(best_cell, {})
    concepts = cell_data.get('concepts', [])
    if not concepts:
        return None

    # Format: "sigma grid: w:62 alterity (Levinas) | w:73 rhizomatic (DG)"
    parts = []
    for c in concepts[:5]:
        concept_name = c.get('concept', '?')
        if ':' in concept_name:
            source_prefix, name = concept_name.split(':', 1)
        else:
            source_prefix, name = '?', concept_name
        name_clean = name.replace('_', ' ')
        parts.append(f"{c['id']} {name_clean} ({source_prefix})")

    concept_ids = [c['id'] for c in concepts[:5]]
    injection = f"sigma grid [{best_cell}]: {' | '.join(parts)}"
    return injection, concept_ids


def record_grid_hit(buffer_dir, concept_ids):
    """Append grid hit to .sigma_hits log for temporal tracking.

    Format: one line per hit — "2026-03-09 w:62 w:125"
    Append-only; cleared at grid rebuild.
    """
    if not concept_ids:
        return
    from datetime import date
    hits_path = os.path.join(buffer_dir, '.sigma_hits')
    try:
        line = f"{date.today()} {' '.join(concept_ids)}\n"
        with open(hits_path, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main — gated cascade
# ---------------------------------------------------------------------------

def main():
    hook_input = read_hook_input()
    user_prompt = hook_input.get('user_prompt', '')
    cwd = hook_input.get('cwd', os.getcwd())

    # Quick exits
    if not user_prompt or len(user_prompt.strip()) < 8:
        emit_empty()
    if user_prompt.strip().startswith('/'):
        emit_empty()

    # Find buffer
    buffer_dir = find_buffer_dir(cwd)
    if not buffer_dir:
        emit_empty()

    # GATE 0a: Post-compaction relay — inject buffer summary if marker present
    check_compact_relay(buffer_dir, cwd)

    # GATE 0b: Distill-active — skip entirely during distillation
    if is_distill_active(buffer_dir):
        emit_empty()

    # Extract keywords (dynamic cap based on prompt size)
    keywords = extract_keywords(user_prompt)
    if not keywords:
        emit_empty()

    # GATE 0c: Grid lookup — pre-computed relevance grid (O(1) lookup)
    # If grid exists and produces a hit, emit directly (skip IDF scoring).
    # If no grid or no hit, fall through to existing behavior.
    grid_result = try_grid_lookup(buffer_dir, keywords)
    if grid_result is not None:
        injection, concept_ids = grid_result
        record_grid_hit(buffer_dir, concept_ids)
        emit({"suppressOutput": True, "systemMessage": injection})

    # GATE 1: Load suppress list (zero cost if file absent)
    suppress_list = load_suppress_list(buffer_dir)

    # Load alpha index if alpha bin exists (needed for IDF computation + Level 2 matching)
    alpha_dir = os.path.join(buffer_dir, 'alpha')
    if os.path.isdir(alpha_dir):
        alpha_idx = read_json(os.path.join(alpha_dir, 'index.json'))
        concept_index = alpha_idx.get('concept_index', {}) if alpha_idx else {}
        sources_data = alpha_idx.get('sources', {}) if alpha_idx else {}
    else:
        alpha_idx = None
        concept_index = {}
        sources_data = {}

    # Compute dynamic scalars from corpus size and prompt size
    corpus_size = len(concept_index)
    word_count = len(user_prompt.split())
    max_inject = dynamic_max_inject(word_count)
    score_exact = dynamic_score_exact(corpus_size)
    min_score = dynamic_min_score(corpus_size)

    # GATE 3: Compute IDF weights + scaling threshold
    idf_weights = compute_idf_weights(keywords, concept_index)
    threshold = confidence_threshold(len(keywords))

    # -----------------------------------------------------------------------
    # LEVEL 1: Hot layer check (cheapest — skipped if buffer already loaded)
    # -----------------------------------------------------------------------
    if not is_hot_stale(buffer_dir):
        hot = read_json(os.path.join(buffer_dir, 'handoff.json'))
        if hot:
            hot_hits = match_hot(keywords, hot, suppress_list,
                                  idf_weights, threshold,
                                  max_inject=max_inject)
            if hot_hits:
                injection = format_hot_hits(hot_hits)
                emit({"suppressOutput": True, "systemMessage": injection})

    # -----------------------------------------------------------------------
    # LEVEL 2: Alpha concept index (fallthrough — hot skipped or missed)
    # -----------------------------------------------------------------------
    if not concept_index:
        emit_empty()

    concept_matches = match_alpha_concepts(
        keywords, concept_index, suppress_list, idf_weights, threshold,
        score_exact=score_exact, min_score=min_score, max_inject=max_inject)
    if not concept_matches:
        emit_empty()

    injection = format_alpha_hits(concept_matches, sources_data)
    emit({"suppressOutput": True, "systemMessage": injection})


if __name__ == '__main__':
    main()
