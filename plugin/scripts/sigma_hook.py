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
  sigma hot: thread: [noted] API refactor review.
  sigma alpha: w:62 dependency-injection (concept-A) | w:73 event-sourcing (concept-B)

Scoring model:
  IDF weight per keyword = 1 / max(1, num_concepts_matched)
    "injection" matches 1 concept  → weight 1.0
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
import time

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
COOLDOWN_SECONDS = 30      # minimum seconds between sigma hook firings
LITE_MODES = frozenset({'lite', 'minimal'})  # buffer modes that skip advanced features

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
    """Find buffer dir via registry lookup + git-guarded walk-up.

    Delegates to buffer_utils.find_buffer_dir. See buffer_utils.py for details.
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
        utils = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(utils)
        return utils.find_buffer_dir(start_path)
    except Exception:
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
    """Read JSON file, return dict or None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def detect_buffer_mode(buffer_dir):
    """Read buffer_mode from hot layer. Returns 'lite', 'full', etc."""
    hot = read_json(os.path.join(buffer_dir, 'handoff.json'))
    if hot:
        return hot.get('buffer_mode', 'lite')
    return 'lite'


def check_cooldown(buffer_dir, cooldown_seconds=COOLDOWN_SECONDS):
    """Return True if enough time has passed since last sigma fire.

    Uses .sigma_last_fire timestamp file. Reads the stored epoch
    timestamp from file content (not mtime) for reliable cross-platform
    behavior. If missing or expired, updates and returns True (proceed).
    Otherwise returns False (skip this firing).
    """
    marker = os.path.join(buffer_dir, '.sigma_last_fire')
    now = time.time()
    try:
        with open(marker, 'r', encoding='utf-8') as f:
            last_fire = float(f.read().strip())
        if now - last_fire < cooldown_seconds:
            return False
    except (OSError, ValueError):
        pass  # file doesn't exist or corrupt — first fire
    # Write current timestamp
    try:
        with open(marker, 'w', encoding='utf-8') as f:
            f.write(str(now))
    except OSError:
        pass  # non-fatal — fire anyway
    return True


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

# ---------------------------------------------------------------------------
# Directional asymmetry constants (Mangan & Alon FFL sign-sensitivity)
# ---------------------------------------------------------------------------

ON_STEP_THRESHOLD = 0.2       # below this regime activation = on-step (new concept)
PERSISTENCE_PENALTY = 0.5     # score multiplier for on-step concepts
PULSE_MULTIPLIER = 1.5        # boost for strong first-contact
PULSE_SCORE_GATE = 1.3        # first-contact must score >= this * threshold for pulse


def match_alpha_concepts(keywords, concept_index, suppress_list,
                          idf_weights, threshold, score_exact=3,
                          min_score=2.0, max_inject=3, regime=None):
    """Match keywords against alpha concept_index keys with IDF weighting.

    For each concept, sums the IDF weight of matching keywords.
    Exact match gets the keyword's full IDF weight * score_exact multiplier.
    Substring match gets IDF weight * SCORE_SUBSTRING.
    Requires total weighted score >= min_score AND >= threshold.
    Filters suppressed concepts.

    Directional asymmetry (when regime provided):
      - First contact (activation == 0, score >= 1.3x threshold): PULSE (1.5x)
      - On-step (activation < 0.2): PERSISTENCE PENALTY (0.5x)
      - Established (activation >= 0.2): no modification
      - Off-step: handled by decay in update_regime, no code needed here

    Returns list of (concept_key, work_ids, weighted_score) sorted desc.
    """
    if not keywords or not concept_index:
        return []

    effective_threshold = max(threshold, min_score)
    scores = {}
    regime_activations = (regime or {}).get('activations', {})

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

        # Directional asymmetry: apply regime-dependent modulation
        if regime is not None and weighted_score > 0:
            activation = regime_activations.get(concept_key, 0.0)
            if activation == 0.0:
                # First contact — pulse or persistence penalty
                if weighted_score >= PULSE_SCORE_GATE * effective_threshold:
                    weighted_score *= PULSE_MULTIPLIER  # strong first contact
                else:
                    weighted_score *= PERSISTENCE_PENALTY  # weak first contact
            elif activation < ON_STEP_THRESHOLD:
                weighted_score *= PERSISTENCE_PENALTY  # on-step, not yet established

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
    Also records co-activation pairs for resonator dynamics.
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

    # Resonator: record co-activation pairs (concepts fired together)
    if len(concept_ids) >= 2:
        _record_co_activation(buffer_dir, concept_ids)


def _record_co_activation(buffer_dir, concept_ids):
    """Record co-activation pairs for resonator dynamics.

    Concepts that fire together in the same sigma hit are co-activated.
    Pair weight increments each time they co-fire — resonance builds.

    Format: JSON dict of "id_a|id_b" -> count (sorted IDs for canonical key).
    """
    coact_path = os.path.join(buffer_dir, '.sigma_coactivation')
    coact = {}
    try:
        if os.path.exists(coact_path):
            with open(coact_path, 'r', encoding='utf-8') as f:
                coact = json.load(f)
    except (json.JSONDecodeError, OSError):
        coact = {}

    # Generate pairs (sorted canonical keys)
    ids = sorted(set(concept_ids))
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            key = f"{ids[i]}|{ids[j]}"
            coact[key] = coact.get(key, 0) + 1

    try:
        with open(coact_path, 'w', encoding='utf-8') as f:
            json.dump(coact, f)
    except OSError:
        pass


def record_grid_adjustment(buffer_dir, cell_key, concept_ids, hit=True):
    """Record incremental grid adjustment for non-catastrophic learning.

    Instead of global grid rebuild replacing all context, sigma hits/misses
    accumulate as adjustments that the next grid build incorporates.

    Each adjustment is a cell confirmation (hit) or disconfirmation (miss).
    Grid builder reads these to nudge cell scores without full recompute.

    Format: JSONL — {cell, concepts, type, date}
    """
    if not concept_ids:
        return

    from datetime import date
    adj_path = os.path.join(buffer_dir, '.grid_adjustments')
    entry = json.dumps({
        'cell': cell_key,
        'concepts': concept_ids[:5],
        'type': 'confirm' if hit else 'disconfirm',
        'date': str(date.today()),
    })
    try:
        with open(adj_path, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Regime accumulator — session-level concept belief (Tafazoli task belief)
# ---------------------------------------------------------------------------

REGIME_DECAY = 0.85         # per-prompt decay (half-life ~4.3 prompts)
REGIME_BOOST = 0.3          # activation boost per matched concept

def load_regime(buffer_dir):
    """Load .sigma_regime state file. Returns default if absent."""
    regime_path = os.path.join(buffer_dir, '.sigma_regime')
    data = read_json(regime_path)
    if data and isinstance(data, dict) and 'activations' in data:
        return data
    return {
        'activations': {},
        '_entropy': 0.0,
        '_prompt_count': 0,
        '_prev_activations': {},
        '_dkl': 0.0,
        '_dkl_cumulative': 0.0,
    }


def _compute_entropy(activations):
    """Shannon entropy H = -sum(p_i * log2(p_i)) over activation distribution."""
    import math
    if not activations:
        return 0.0
    total = sum(activations.values())
    if total <= 0:
        return 0.0
    h = 0.0
    for v in activations.values():
        if v > 0:
            p = v / total
            h -= p * math.log2(p)
    return h


def _compute_dkl(current, previous):
    """KL divergence D_KL(P_current || P_previous).

    SWM becoming-rate metric. Epsilon-smoothed to handle zero entries.
    Returns float >= 0.0.
    """
    import math
    if not current:
        return 0.0
    # Union of all keys
    all_keys = set(current) | set(previous or {})
    if not all_keys:
        return 0.0
    epsilon = 1e-10
    # Normalize to distributions
    total_c = sum(current.values()) or 1.0
    total_p = sum((previous or {}).values()) or 1.0
    dkl = 0.0
    for k in all_keys:
        p = (current.get(k, 0.0) / total_c) + epsilon
        q = ((previous or {}).get(k, 0.0) / total_p) + epsilon
        dkl += p * math.log(p / q)
    return max(0.0, dkl)


def update_regime(buffer_dir, regime, matched_concept_keys, decay_rate=REGIME_DECAY):
    """Update regime accumulator: boost matched, decay all, recompute entropy + D_KL."""
    activations = regime.get('activations', {})
    prev_activations = dict(activations)  # snapshot for D_KL

    # Decay all existing activations
    for k in list(activations):
        activations[k] *= decay_rate
        if activations[k] < 0.01:
            del activations[k]

    # Boost matched concepts
    for key in matched_concept_keys:
        activations[key] = min(1.0, activations.get(key, 0.0) + REGIME_BOOST)

    regime['activations'] = activations
    regime['_prev_activations'] = prev_activations
    regime['_entropy'] = _compute_entropy(activations)
    regime['_prompt_count'] = regime.get('_prompt_count', 0) + 1
    regime['_dkl'] = _compute_dkl(activations, prev_activations)
    regime['_dkl_cumulative'] = regime.get('_dkl_cumulative', 0.0) + regime['_dkl']

    # Write back
    regime_path = os.path.join(buffer_dir, '.sigma_regime')
    try:
        with open(regime_path, 'w', encoding='utf-8') as f:
            json.dump(regime, f, indent=2)
    except OSError:
        pass

    return regime


def regime_threshold_modifier(regime):
    """Entropy-based threshold modifier.

    Low entropy (focused session) → lower threshold (0.85) — established topics fire easier.
    High entropy (exploratory) → higher threshold (1.15) — require stronger evidence.
    Medium → no modification (1.0).
    Clamped to [0.8, 1.2].
    """
    h = regime.get('_entropy', 0.0)
    if h < 1.5:
        modifier = 0.85
    elif h >= 3.0:
        modifier = 1.15
    else:
        modifier = 1.0
    return max(0.8, min(1.2, modifier))


def record_prediction_error(buffer_dir, keywords, matched_concepts, grid_hit):
    """Record prediction errors for predictive coding feedback loop.

    Two error types (Kirsanov predictive coding):
      - gap: keyword with high signal but no alpha match (alpha is missing concepts)
      - false_pos: grid predicted concept relevant but user never engaged it

    False positives are tracked per-grid-cycle — grid rebuild resets them.
    Gaps accumulate across sessions — they signal structural blind spots.

    Format: JSONL — one JSON object per line.
    """
    if not keywords:
        return

    from datetime import date
    errors_path = os.path.join(buffer_dir, '.sigma_errors')
    today = str(date.today())

    lines = []

    # Gap detection: keywords that passed IDF threshold but matched nothing
    matched_kws = set()
    for concept_key, _, _ in matched_concepts:
        concept_lower = concept_key.lower()
        for kw in keywords:
            if kw == concept_lower or kw in concept_lower or concept_lower in kw:
                matched_kws.add(kw)

    unmatched = [kw for kw in keywords if kw not in matched_kws]
    if unmatched:
        lines.append(json.dumps({
            'type': 'gap', 'date': today,
            'keywords': unmatched[:10],
        }))

    # False positive: grid fired but no concepts matched via IDF (grid overpredicted)
    if grid_hit and not matched_concepts:
        lines.append(json.dumps({
            'type': 'false_pos', 'date': today,
            'grid_concepts': grid_hit[:5],
        }))

    if lines:
        try:
            with open(errors_path, 'a', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Spreading activation (Hopfield inference through convergence web)
# ---------------------------------------------------------------------------

def compute_spread(concept_ids, adjacency, max_spread=2, coactivation=None):
    """Hopfield-style spreading activation through convergence web.

    For each activated concept, propagates to 1-hop neighbors.
    Neighbors activated by multiple source concepts rank higher
    (multi-source convergence = stronger field effect).

    Resonator weighting: if coactivation data exists, neighbors that
    have historically co-fired with active concepts get a bonus
    (temporal coherence = resonance).

    Returns list of (neighbor_id, activation_score) tuples.
    """
    if not adjacency or not concept_ids:
        return []

    activated = set(concept_ids)
    candidates = {}

    for cid in concept_ids:
        for neighbor in adjacency.get(cid, []):
            if neighbor not in activated:
                # Base: structural adjacency count
                base = candidates.get(neighbor, 0) + 1
                # Resonator bonus: temporal co-activation history
                resonance = 0
                if coactivation:
                    pair_key = '|'.join(sorted([cid, neighbor]))
                    resonance = min(coactivation.get(pair_key, 0), 10) * 0.1
                candidates[neighbor] = base + resonance

    ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
    return ranked[:max_spread]


def update_wholeness(buffer_dir, new_concept_ids, adjacency, edge_count=0):
    """Incrementally update wholeness W after new concept activation.

    delta_W = count of already-active neighbors for each new activation.
    O(degree) per concept — fast enough for sigma hook (<5ms).
    """
    if not adjacency or not new_concept_ids:
        return

    wholeness_path = os.path.join(buffer_dir, '.sigma_wholeness')
    state = read_json(wholeness_path) or {
        'W': 0, 'W_potential': 0, 'active_set': [], 'history': []
    }

    active_set = set(state.get('active_set', []))
    delta_w = 0

    for cid in new_concept_ids:
        if cid in active_set:
            continue
        for neighbor in adjacency.get(cid, []):
            if neighbor in active_set:
                delta_w += 1
        active_set.add(cid)

    state['W'] = state.get('W', 0) + delta_w
    state['active_set'] = sorted(active_set)
    state['active_count'] = len(active_set)
    if edge_count > 0:
        state['W_potential'] = edge_count
    w_potential = state.get('W_potential', 0)
    if w_potential > 0:
        state['W_ratio'] = round(state['W'] / w_potential, 4)

    from datetime import date
    state['last_updated'] = str(date.today())

    try:
        with open(wholeness_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def apply_cw_boost(scores, adj_data, effective_threshold,
                   saturation_factor=1.3, eligibility_band=0.15,
                   max_cascade=5):
    """CW-graph neighbor boost + rich-get-split splash.

    Three phases:
    1. Neighbor boost: above-threshold concepts uplift cw-neighbors by 30%
    2. Saturation check: concepts exceeding saturation_factor * threshold
    3. Splash cascade: excess redistributed to highest sub-threshold concept
       within eligibility_band of threshold. Max max_cascade iterations.

    Args:
        scores: dict of {concept_key: (work_ids, weighted_score)}
        adj_data: parsed .cw_adjacency with 'adjacency' and 'concepts' dicts
        effective_threshold: the active scoring threshold
        saturation_factor: multiplier for saturation cap (default 1.3)
        eligibility_band: fraction of threshold for splash eligibility (0.15 = 85-100%)
        max_cascade: maximum splash iterations

    Returns:
        Modified scores dict (mutated in place and returned).
    """
    if not adj_data or not scores:
        return scores

    adjacency = adj_data.get('adjacency', {})
    concepts_lookup = adj_data.get('concepts', {})
    if not adjacency:
        return scores

    # Build reverse lookup: concept_key → w_id (for adjacency, which is keyed by w_id)
    key_to_wid = {}
    for wid, cname in concepts_lookup.items():
        key_to_wid[cname] = wid

    # Phase 1: Neighbor boost (30% uplift)
    boost_targets = {}
    for concept_key, (work_ids, wscore) in list(scores.items()):
        if wscore < effective_threshold:
            continue
        wid = key_to_wid.get(concept_key)
        if not wid:
            continue
        neighbors = adjacency.get(wid, [])
        for neighbor_wid in neighbors:
            neighbor_name = concepts_lookup.get(neighbor_wid)
            if not neighbor_name or neighbor_name == concept_key:
                continue
            boost_targets[neighbor_name] = (
                boost_targets.get(neighbor_name, 0.0) + wscore * 0.3
            )

    # Apply boosts to existing scores or create new entries
    for concept_key, boost_amount in boost_targets.items():
        if concept_key in scores:
            work_ids, current = scores[concept_key]
            scores[concept_key] = (work_ids, current + boost_amount)
        # Don't create new entries — only boost concepts already in the scoring pool

    # Phase 2 & 3: Saturation cap + splash cascade
    saturation_cap = saturation_factor * effective_threshold
    eligibility_floor = effective_threshold * (1.0 - eligibility_band)

    for _ in range(max_cascade):
        # Find saturated concept with highest excess
        saturated = None
        max_excess = 0.0
        for concept_key, (work_ids, wscore) in scores.items():
            excess = wscore - saturation_cap
            if excess > max_excess:
                max_excess = excess
                saturated = concept_key

        if saturated is None:
            break

        # Find best splash target: highest-scoring sub-threshold concept in band
        best_target = None
        best_target_score = 0.0
        for concept_key, (work_ids, wscore) in scores.items():
            if concept_key == saturated:
                continue
            if eligibility_floor <= wscore < effective_threshold:
                if wscore > best_target_score:
                    best_target = concept_key
                    best_target_score = wscore

        if best_target is None:
            # No eligible target — just cap the saturated concept
            work_ids, wscore = scores[saturated]
            scores[saturated] = (work_ids, saturation_cap)
            break

        # Splash: cap saturated, boost target
        work_ids_sat, wscore_sat = scores[saturated]
        scores[saturated] = (work_ids_sat, saturation_cap)
        work_ids_tgt, wscore_tgt = scores[best_target]
        scores[best_target] = (work_ids_tgt, wscore_tgt + max_excess)

    return scores


def check_ambiguity_signal(keywords, concept_index, suppress_list,
                           idf_weights, threshold, score_exact=3):
    """Check for near-threshold concepts when no matches fired.

    Scans for the highest-scoring concept within 90-100% of threshold.
    Returns diagnostic string or None.
    ~10 tokens, only when normal injection would be empty.
    """
    if not keywords or not concept_index:
        return None

    effective_threshold = threshold
    best_key = None
    best_score = 0.0

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

        if weighted_score > best_score:
            best_score = weighted_score
            best_key = concept_key

    if best_key and best_score >= 0.9 * effective_threshold:
        return f"sigma: near {best_key} \u2014 consider /buffer-on"

    return None


def update_continuous_scores(buffer_dir, concept_ids, keywords, concept_index):
    """Update continuous scores (W') — the wholeness gradient.

    Each sigma hit nudges concept scores incrementally:
      - Hit concepts: score += delta (confirmation = energy descent)
      - Spread-activated neighbors: score += delta/2 (association boost)
      - Gap keywords (no match): no score change, but logged as prediction error

    This creates real-time learning between batch alpha-reinforce runs.
    The user's insight: this IS W' — the rate of change of wholeness.

    Scores stored in .sigma_scores as {concept_id: float}.
    Grid builder reads these as alpha score boosts.
    """
    if not concept_ids:
        return

    scores_path = os.path.join(buffer_dir, '.sigma_scores')
    scores = read_json(scores_path) or {}

    DELTA = 0.1  # learning rate per hit

    for cid in concept_ids:
        scores[cid] = scores.get(cid, 0.0) + DELTA

    # Compute W' (rate of change) from wholeness state
    wholeness_path = os.path.join(buffer_dir, '.sigma_wholeness')
    w_state = read_json(wholeness_path)
    if w_state:
        w_current = w_state.get('W', 0)
        w_prev = scores.get('__W_prev', 0)
        w_prime = w_current - w_prev
        scores['__W_prev'] = w_current
        scores['__W_prime'] = w_prime

    try:
        with open(scores_path, 'w', encoding='utf-8') as f:
            json.dump(scores, f)
    except OSError:
        pass


def apply_spread_and_wholeness(buffer_dir, concept_ids, injection):
    """Apply spreading activation and wholeness update to an injection.

    Reads .cw_adjacency cache (written by alpha-reinforce) and
    .sigma_coactivation (resonator history), computes spread neighbors
    with resonance weighting, updates incremental W.
    Returns modified injection.
    """
    adj_path = os.path.join(buffer_dir, '.cw_adjacency')
    adj_data = read_json(adj_path)
    if not adj_data or not concept_ids:
        return injection

    adjacency = adj_data.get('adjacency', {})
    concepts_lookup = adj_data.get('concepts', {})
    edge_count = adj_data.get('edge_count', 0)

    # Load co-activation data for resonator weighting
    coact_path = os.path.join(buffer_dir, '.sigma_coactivation')
    coactivation = read_json(coact_path) or {}

    # Spreading activation (with resonator weighting)
    spread = compute_spread(concept_ids, adjacency, coactivation=coactivation)
    if spread:
        spread_ids = [sid for sid, _ in spread]
        record_grid_hit(buffer_dir, spread_ids)
        spread_parts = [
            f"{sid} {concepts_lookup.get(sid, '?')}" for sid, _ in spread
        ]
        injection += ' | spread: ' + ' | '.join(spread_parts)

    # Incremental wholeness update
    update_wholeness(buffer_dir, concept_ids, adjacency, edge_count)

    return injection


# ---------------------------------------------------------------------------
# Tick counter — periodic resolution check trigger
# ---------------------------------------------------------------------------

TICK_THRESHOLD = 50  # Flag resolution_due every N messages

def _increment_tick(buffer_dir):
    """Increment per-message tick counter. Lightweight (~1ms)."""
    ticks_path = os.path.join(buffer_dir, '.sigma_ticks')
    count = 0
    try:
        if os.path.exists(ticks_path):
            with open(ticks_path, 'r') as f:
                count = int(f.read().strip() or '0')
    except (ValueError, OSError):
        pass
    count += 1
    try:
        with open(ticks_path, 'w') as f:
            f.write(str(count))
    except OSError:
        pass


def _check_resolution_due(buffer_dir):
    """Check if tick threshold reached. Returns True and resets if so."""
    ticks_path = os.path.join(buffer_dir, '.sigma_ticks')
    try:
        if os.path.exists(ticks_path):
            with open(ticks_path, 'r') as f:
                count = int(f.read().strip() or '0')
            if count >= TICK_THRESHOLD:
                with open(ticks_path, 'w') as f:
                    f.write('0')
                return True
    except (ValueError, OSError):
        pass
    return False


def _with_resolution(output, resolution_due):
    """Add resolution check flag to hook output if tick threshold reached.

    Appends a lightweight note to systemMessage when resolution is due.
    If the hook would normally exit silently (empty output), emits a
    standalone resolution notice instead. The AI can choose to act on it
    or not — purely informational.
    """
    if not resolution_due:
        return output
    if not output or output == {}:
        return {
            "suppressOutput": True,
            "systemMessage": "resolution check due — run alpha-resolve"
        }
    if 'systemMessage' in output:
        output['systemMessage'] += ' | resolution check due'
    return output


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

    # Detect buffer mode (lite skips regime, prediction error, grid, CW-boost)
    mode = detect_buffer_mode(buffer_dir)
    is_lite = mode in LITE_MODES

    # GATE -1: Cooldown — prevent rapid re-firing on idle/cycling
    if not check_cooldown(buffer_dir):
        emit_empty()

    # TICK COUNTER: Increment per-message counter for periodic resolution checks
    # Lite mode skips ticks — no consumer (resolution checks are full-mode only)
    if not is_lite:
        _increment_tick(buffer_dir)
    resolution_due = _check_resolution_due(buffer_dir) if not is_lite else False

    # GATE 0a: Post-compaction relay — inject buffer summary if marker present
    # Runs in both lite and full mode (compact marker is shared infrastructure)
    check_compact_relay(buffer_dir, cwd)

    # GATE 0b: Distill-active — skip entirely during distillation
    if is_distill_active(buffer_dir):
        emit_empty()

    # Extract keywords (dynamic cap based on prompt size)
    keywords = extract_keywords(user_prompt)
    if not keywords:
        emit(_with_resolution({}, resolution_due))

    # GATE 0c: Grid lookup — pre-computed relevance grid (O(1) lookup)
    # Lite mode skips grid entirely (no relevance grid in lite).
    # If grid exists and produces a hit, emit directly (skip IDF scoring).
    # If no grid or no hit, fall through to existing behavior.
    grid_result = None if is_lite else try_grid_lookup(buffer_dir, keywords)
    if grid_result is not None:
        injection, concept_ids = grid_result
        record_grid_hit(buffer_dir, concept_ids)
        # Incremental grid adjustment: confirm this cell hit
        # Extract cell key from injection format "sigma grid [cell_key]: ..."
        cell_match = re.search(r'sigma grid \[([^\]]+)\]', injection)
        if cell_match:
            record_grid_adjustment(buffer_dir, cell_match.group(1), concept_ids,
                                    hit=True)
        injection = apply_spread_and_wholeness(buffer_dir, concept_ids, injection)
        emit(_with_resolution(
            {"suppressOutput": True, "systemMessage": injection},
            resolution_due))

    # GATE 1: Load suppress list (zero cost if file absent)
    suppress_list = load_suppress_list(buffer_dir)

    # Load alpha index, IDF weights, regime — full mode only.
    # Lite mode uses empty defaults; exits at Level 2 before any alpha code runs.
    if not is_lite:
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

        # Load CW adjacency data (needed for boost pass after alpha matching)
        adj_path = os.path.join(buffer_dir, '.cw_adjacency')
        adj_data = read_json(adj_path)

        # GATE 3: Compute IDF weights + scaling threshold
        idf_weights = compute_idf_weights(keywords, concept_index)
        threshold = confidence_threshold(len(keywords))

        # Load regime accumulator and apply entropy-based threshold modifier
        regime = load_regime(buffer_dir)
        if regime is not None:
            threshold *= regime_threshold_modifier(regime)
    else:
        concept_index = {}
        sources_data = {}
        idf_weights = {}
        threshold = 0.0
        regime = None
        adj_data = None

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
                emit(_with_resolution(
                    {"suppressOutput": True, "systemMessage": injection},
                    resolution_due))

    # -----------------------------------------------------------------------
    # LEVEL 2: Alpha concept index (fallthrough — hot skipped or missed)
    # Lite mode: no alpha, no regime, no prediction error — exit here.
    # -----------------------------------------------------------------------
    if is_lite or not concept_index:
        if not is_lite:
            record_prediction_error(buffer_dir, keywords, [], None)
        emit(_with_resolution({}, resolution_due))

    concept_matches = match_alpha_concepts(
        keywords, concept_index, suppress_list, idf_weights, threshold,
        score_exact=score_exact, min_score=min_score, max_inject=max_inject,
        regime=regime)

    # CW-boost pass: uplift neighbors of matched concepts, splash saturation
    if concept_matches and adj_data:
        # Build scores dict for boost pass
        boost_scores = {
            key: (ids, sc) for key, ids, sc in concept_matches
        }
        # Also include near-threshold concepts for splash targets
        effective_threshold = max(threshold, min_score)
        for concept_key, work_ids in concept_index.items():
            if concept_key == '?' or concept_key in boost_scores:
                continue
            if is_suppressed(concept_key, suppress_list):
                continue
            concept_lower = concept_key.lower()
            wscore = 0.0
            for kw in keywords:
                w = idf_weights.get(kw, 0.0)
                if w == 0.0:
                    continue
                if kw == concept_lower:
                    wscore += w * score_exact
                elif kw in concept_lower or concept_lower in kw:
                    wscore += w * SCORE_SUBSTRING
            # Only include near-threshold concepts (splash candidates)
            if wscore >= effective_threshold * 0.85:
                boost_scores[concept_key] = (work_ids, wscore)

        boost_scores = apply_cw_boost(boost_scores, adj_data, effective_threshold)

        # Re-extract matches from boosted scores (re-rank, re-slice)
        ranked = sorted(boost_scores.items(), key=lambda x: x[1][1], reverse=True)
        concept_matches = [
            (key, ids, sc) for key, (ids, sc) in ranked
            if sc >= effective_threshold
        ][:max_inject]

    # Prediction error tracking (Kirsanov predictive coding)
    record_prediction_error(buffer_dir, keywords, concept_matches, None)

    # Update regime accumulator with matched concept keys
    matched_keys = [key for key, _, _ in concept_matches]
    update_regime(buffer_dir, regime, matched_keys)

    if not concept_matches:
        # Ambiguity signal: near-threshold diagnostic
        ambiguity = check_ambiguity_signal(
            keywords, concept_index, suppress_list, idf_weights,
            max(threshold, min_score), score_exact=score_exact)
        if ambiguity:
            emit(_with_resolution(
                {"suppressOutput": True, "systemMessage": ambiguity},
                resolution_due))
        emit(_with_resolution({}, resolution_due))

    injection = format_alpha_hits(concept_matches, sources_data)

    # Spreading activation through convergence web
    matched_ids = [
        ids[0] for _, ids, _ in concept_matches
        if isinstance(ids, list) and ids
    ]
    injection = apply_spread_and_wholeness(buffer_dir, matched_ids, injection)

    # Continuous score adjustment (W' — wholeness gradient)
    update_continuous_scores(buffer_dir, matched_ids, keywords, concept_index)

    emit(_with_resolution(
        {"suppressOutput": True, "systemMessage": injection},
        resolution_due))


if __name__ == '__main__':
    main()
