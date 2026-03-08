#!/usr/bin/env python3
"""distill_backfill_alpha.py — One-time backfill: enrich thin alpha stubs with
content extracted mechanically from existing distillation + interpretation files.

Usage:
    python distill_backfill_alpha.py \
        --alpha-dir /path/to/.claude/buffer/alpha \
        --distill-dir /path/to/docs/references/distilled \
        --interp-dir /path/to/docs/references/interpretations \
        --output enrichment.json \
        [--dry-run]

The output JSON is an array of {id, body} objects suitable for piping into:
    cat enrichment.json | buffer_manager.py alpha-enrich --buffer-dir ...
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Source folder → distillation file mapping
# ---------------------------------------------------------------------------
# Hardcoded because it's stable and mechanical inference is fragile.
# Maps source folder name → list of distillation labels (filename without .md).

SOURCE_TO_DISTILLATIONS: dict[str, list[str]] = {
    'cortes-early': [
        'Cortes_etal_BiocosmologyBirth_2022_Paper',
        'Cortes_etal_BiocosmologyPerspective_2022_Paper',
        'Cortes_etal_TAPEquation_2022_Paper',
    ],
    'deguerre-early': ['deGuerre_TwoStageModel_2016_Paper'],
    'delanda-assemblage-early': ['DeLanda_AssemblageTheory_2016_Book'],
    'dg-early': ['Deleuze_Guattari_ATPCh15_1987_Chapter'],
    'easwaran-gita-early': ['Easwaran_BhagavadGita_2007_Book'],
    'easwaran-glossary-early': ['Easwaran_BhagavadGita_2007_Glossary'],
    'emery-early': [
        'Emery_Emery_ParticipativeDesign_1974_Paper',
        'Emery_M_CurrentVersionOST_2000_Paper',
        'Emery_Trist_CausalTexture_1965_Paper',
    ],
    'levinas-early': ['Levinas_TotalityInfinity_1961_Excerpt'],
    'lizier-early': [
        'Lizier_etal_InfoStorageLoopMotifs_2012_Paper',
        'Lizier_etal_SynchronizabilityMotifs_2023_Paper',
        'Lizier_SynchronizabilitySlideshow_2023_Slideshow',
    ],
    'ostsite-early': ['OpenSystemsTheory_PractitionerSite_Website'],
    'ruesch-bateson-early': ['Ruesch_Bateson_Communication_1951_Excerpt'],
    'sartre-CDR2-envelopment': ['Sartre_CritiqueDR2_1991_Envelopment'],
    'sartre-early': ['Sartre_CritiqueDR2_1991_Appendix'],
    'taalbi-early': ['Taalbi_LongRunPatterns_2025_Paper'],
    'turchin-early': [
        'Turchin_FormationLargeEmpires_2009_Paper',
        'Turchin_Gavrilets_HierarchicalSocieties_2009_Paper',
        'Turchin_SocialPressures_2013_Paper',
    ],
    'unificity': ['Unificity'],
}

# Concept key prefix → specific distillation label (for disambiguation
# when a source folder maps to multiple distillation files).
KEY_PREFIX_TO_DISTILLATION: dict[str, str] = {
    # Cortes sources
    'Cortes_etal_TAP': 'Cortes_etal_TAPEquation_2022_Paper',
    'Cortes_Birth': 'Cortes_etal_BiocosmologyBirth_2022_Paper',
    'Cortes_Perspective': 'Cortes_etal_BiocosmologyPerspective_2022_Paper',
    # Emery sources
    'Emery_Trist': 'Emery_Trist_CausalTexture_1965_Paper',
    'ET': 'Emery_Trist_CausalTexture_1965_Paper',
    'Emery_M': 'Emery_M_CurrentVersionOST_2000_Paper',
    'Emery_Emery': 'Emery_Emery_ParticipativeDesign_1974_Paper',
    # Turchin sources
    'Turchin_Gavrilets': 'Turchin_Gavrilets_HierarchicalSocieties_2009_Paper',
    # Lizier sources
    'Lizier2012': 'Lizier_etal_InfoStorageLoopMotifs_2012_Paper',
    'Lizier2023': 'Lizier_etal_SynchronizabilityMotifs_2023_Paper',
    'Lizier_Sync': 'Lizier_SynchronizabilitySlideshow_2023_Slideshow',
}

# Source folders to skip (no distillation files to parse)
SKIP_SOURCES = frozenset({
    '_framework', '_forward-notes', '_mixed-early',
    'austin-early', 'baudrillard-early', 'bohm-early',
    'fermat-early', 'feynman-early', 'fermatfeynman-early',
})


# ---------------------------------------------------------------------------
# Markdown table parser
# ---------------------------------------------------------------------------

def _strip_pipes(row: str) -> list[str]:
    """Split a markdown table row on pipes, stripping outer empties."""
    cells = row.split('|')
    if cells and cells[0].strip() == '':
        cells = cells[1:]
    if cells and cells[-1].strip() == '':
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _is_separator(row: str) -> bool:
    """Check if a row is a markdown table separator (|---|---|)."""
    stripped = row.strip()
    return bool(re.match(r'^[\|\s\-:]+$', stripped)) and '---' in stripped


def parse_table(lines: list[str]) -> list[dict]:
    """Parse a markdown table into list of dicts keyed by header names."""
    if len(lines) < 3:
        return []

    header_idx = None
    for i, line in enumerate(lines):
        if '|' in line and not _is_separator(line):
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = _strip_pipes(lines[header_idx])
    if not headers:
        return []

    sep_idx = header_idx + 1
    if sep_idx >= len(lines) or not _is_separator(lines[sep_idx]):
        return []

    rows = []
    for line in lines[sep_idx + 1:]:
        stripped = line.strip()
        if not stripped or '|' not in stripped:
            break
        if _is_separator(stripped):
            continue
        cells = _strip_pipes(stripped)
        row_dict = {}
        for j, h in enumerate(headers):
            row_dict[h] = cells[j] if j < len(cells) else ''
        rows.append(row_dict)
    return rows


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

def extract_sections(md_text: str) -> dict[str, str]:
    """Split markdown into {heading: content} by ## headings."""
    lines = md_text.split('\n')
    sections: dict[str, str] = {}
    current_key = '_header'
    current_lines: list[str] = []

    for line in lines:
        if line.startswith('## '):
            sections[current_key] = '\n'.join(current_lines).strip()
            current_key = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    sections[current_key] = '\n'.join(current_lines).strip()
    return sections


def extract_source_citation(header_text: str) -> str:
    """Extract source citation from distillation header (> Source: ...)."""
    for line in header_text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('> Source:') or stripped.startswith('**Source**:'):
            return stripped.lstrip('> ').lstrip('*').strip()
        if stripped.startswith('Source:'):
            return stripped.strip()
    return ''


# ---------------------------------------------------------------------------
# Distillation parser
# ---------------------------------------------------------------------------

def parse_distillation(filepath: Path) -> dict:
    """Parse a distillation .md into structured dict."""
    text = filepath.read_text(encoding='utf-8')
    sections = extract_sections(text)
    label = filepath.stem

    source_citation = extract_source_citation(sections.get('_header', ''))

    key_concepts = []
    kc_text = sections.get('Key Concepts', '')
    if kc_text:
        kc_lines = kc_text.split('\n')
        rows = parse_table(kc_lines)
        for row in rows:
            key_concepts.append({
                'concept': row.get('Concept', ''),
                'definition': row.get('Definition', ''),
                'significance': row.get('Significance', ''),
                'ref': row.get('Source Ref', row.get('Ref', '')),
            })

    return {
        'filename': filepath.name,
        'label': label,
        'source_citation': source_citation,
        'core_argument': sections.get('Core Argument', ''),
        'key_concepts': key_concepts,
        'sections': sections,
    }


# ---------------------------------------------------------------------------
# Interpretation parser
# ---------------------------------------------------------------------------

def parse_interpretation(filepath: Path) -> dict:
    """Parse an interpretation .md into structured dict."""
    text = filepath.read_text(encoding='utf-8')
    sections = extract_sections(text)
    label = filepath.stem

    # Parse Project Mapping table — check ALL sections for it
    project_mapping = []
    for sec_name, sec_text in sections.items():
        if '|' in sec_text and ('Concept' in sec_text):
            table_lines = sec_text.split('\n')
            rows = parse_table(table_lines)
            for row in rows:
                concept_col = (row.get('Concept (from distillation)', '') or
                               row.get('Concept', ''))
                if concept_col:
                    project_mapping.append({
                        'concept': concept_col,
                        'mapping': row.get('Project Mapping', ''),
                        'relationship': row.get('Relationship', ''),
                    })
            if project_mapping:
                break  # Found the table

    # Parse Integration Points → extract concept map entries
    integration_points = []
    ip_text = sections.get('Integration Points', '')
    if ip_text:
        blocks = re.split(r'\n(?=- \*\*)', ip_text)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            cm_match = re.search(
                r'[Cc]oncept\s+map\s+entry[*`\s]*:\s*`?([^`→\n]+?)(?:`|\s*→)',
                block
            )
            cm_key = cm_match.group(1).strip() if cm_match else ''
            integration_points.append({
                'concept_map_key': cm_key,
                'text': block,
            })

    return {
        'filename': filepath.name,
        'label': label,
        'project_significance': sections.get('Project Significance', ''),
        'project_mapping': project_mapping,
        'integration_points': integration_points,
        'open_questions': sections.get('Open Questions', ''),
    }


# ---------------------------------------------------------------------------
# Concept matching
# ---------------------------------------------------------------------------

def normalize_concept(name: str) -> str:
    """Normalize a concept name for matching."""
    s = name.strip()
    s = re.sub(r'\*+', '', s)
    s = re.sub(r'`', '', s)
    s = s.replace('_', ' ')
    # Remove parenthetical clarifications: "Assemblage (agencement)" → "Assemblage"
    s = re.sub(r'\s*\([^)]*\)', '', s)
    # Remove slashes with surrounding spaces: "A / B" → "A B"
    s = s.replace(' / ', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.lower()


def match_concept_to_table(concept_key: str,
                           table_rows: list[dict],
                           column: str = 'concept') -> Optional[dict]:
    """Match an alpha concept key to a table row.

    Tries: exact normalized, substring, word overlap.
    """
    norm_key = normalize_concept(concept_key)
    norm_key_words = set(norm_key.split())

    best_match = None
    best_score = 0.0

    for row in table_rows:
        row_concept = row.get(column, '')
        norm_row = normalize_concept(row_concept)

        if norm_key == norm_row:
            return row

        # Substring match (bidirectional)
        if norm_key in norm_row or norm_row in norm_key:
            # Score by how close the lengths are (prefer exact-length matches)
            min_len = min(len(norm_key), len(norm_row))
            max_len = max(len(norm_key), len(norm_row))
            score = min_len / max(max_len, 1)
            if score > best_score:
                best_match = row
                best_score = max(score, 0.6)
            continue

        # Word overlap match
        row_words = set(norm_row.split())
        if norm_key_words and row_words:
            overlap = norm_key_words & row_words
            # Score: overlap relative to the SMALLER set (so short keys match long rows)
            ratio = len(overlap) / min(len(norm_key_words), len(row_words))
            if ratio > 0.5 and ratio > best_score:
                best_match = row
                best_score = ratio

    return best_match if best_score >= 0.5 else None


def match_concept_to_integration(concept_key: str,
                                  integration_points: list[dict]) -> Optional[dict]:
    """Match an alpha concept key to an integration point via concept_map_key."""
    norm_key = normalize_concept(concept_key)
    for ip in integration_points:
        cm_key = ip.get('concept_map_key', '')
        if cm_key and normalize_concept(cm_key) == norm_key:
            return ip
    # Fallback: match on concept name part only
    if ':' in concept_key:
        concept_part = concept_key.split(':', 1)[1]
        norm_part = normalize_concept(concept_part)
        for ip in integration_points:
            cm_key = ip.get('concept_map_key', '')
            if ':' in cm_key:
                cm_part = cm_key.split(':', 1)[1]
                if normalize_concept(cm_part) == norm_part:
                    return ip
    return None


# ---------------------------------------------------------------------------
# Body assembly
# ---------------------------------------------------------------------------

def build_body(entry_id: str,
               concept_key: str,
               distillation: Optional[dict],
               interpretation: Optional[dict],
               related_cw: list[str],
               ref_field: str,
               maps_to: str) -> str:
    """Assemble the rich body content for an alpha entry."""
    parts = []
    concept_name = concept_key.split(':', 1)[1] if ':' in concept_key else concept_key

    # --- Definition & Significance ---
    kc_match = None
    if distillation and distillation['key_concepts']:
        kc_match = match_concept_to_table(concept_name, distillation['key_concepts'])

    if kc_match:
        defn = kc_match.get('definition', '').strip()
        if defn:
            parts.append(f"## Definition\n{defn}")
        sig = kc_match.get('significance', '').strip()
        if sig:
            parts.append(f"## Significance\n{sig}")
    else:
        if maps_to:
            parts.append(f"## Definition\n{maps_to}")
        parts.append("## Significance\n[No Key Concepts table match — "
                      "see distillation for full context]")

    # --- Project Mapping ---
    pm_match = None
    ip_match = None
    if interpretation:
        if interpretation['project_mapping']:
            pm_match = match_concept_to_table(
                concept_name, interpretation['project_mapping'])
        ip_match = match_concept_to_integration(
            concept_key, interpretation['integration_points'])

    if pm_match or ip_match:
        parts.append("## Project Mapping")
        pm_lines = []
        if pm_match:
            pm_lines.append(f"- **Maps to**: {pm_match.get('mapping', maps_to)}")
            pm_lines.append(
                f"- **Relationship**: {pm_match.get('relationship', 'unknown')}")
        else:
            pm_lines.append(f"- **Maps to**: {maps_to}")
        if ip_match:
            ip_text = ip_match.get('text', '')
            ip_text = re.sub(
                r'\n\s+- \*\*Concept map entry\*\*:.*$', '', ip_text,
                flags=re.MULTILINE)
            ip_text = re.sub(
                r'\n\s+- \*\*Candidate forward note\*\*:.*$', '', ip_text,
                flags=re.MULTILINE)
            ip_text = ip_text.strip()
            if ip_text:
                pm_lines.append(f"- **Integration**: {ip_text}")
        parts.append('\n'.join(pm_lines))
    elif maps_to:
        parts.append("## Project Mapping")
        parts.append(f"- **Maps to**: {maps_to}")
        parts.append("- **Relationship**: [no interpretation file]")

    # --- Related ---
    if related_cw:
        parts.append("## Related")
        parts.append('\n'.join(f"- {cw}" for cw in related_cw))

    # --- Source ---
    if distillation:
        citation = distillation.get('source_citation', '')
        if citation:
            parts.append(f"## Source\n{citation}")

    return '\n\n'.join(parts)


# ---------------------------------------------------------------------------
# Distillation lookup
# ---------------------------------------------------------------------------

def _is_distillation_label(ref: str) -> bool:
    """Check if a Ref field looks like a distillation label (not a §section ref)."""
    if not ref:
        return False
    # Section references start with § or are just section numbers
    first = ref.split()[0].strip(',;.')
    if first.startswith('§') or first.startswith('S5.') or first.startswith('s5.'):
        return False
    # Distillation labels contain underscores and look like Author_Title_Year_Type
    if '_' in first and any(c.isalpha() for c in first):
        return True
    return False


def find_distillations_for_entry(concept_key: str,
                                  ref_field: str,
                                  source_folder: str,
                                  distillations: dict[str, dict]
                                  ) -> list[dict]:
    """Find all candidate distillation dicts for an alpha entry.

    Strategy (in priority order):
    1. If Ref field contains a real distillation label → use it
    2. Use concept key prefix → KEY_PREFIX_TO_DISTILLATION
    3. Use source folder → SOURCE_TO_DISTILLATIONS
    """
    candidates = []

    # 1. Try Ref field
    if _is_distillation_label(ref_field):
        label = ref_field.split()[0].rstrip(',;.')
        if label in distillations:
            return [distillations[label]]
        # Try prefix match
        for dlabel, ddata in distillations.items():
            if dlabel.startswith(label) or label.startswith(dlabel):
                candidates.append(ddata)
        if candidates:
            return candidates

    # 2. Try concept key prefix disambiguation
    if ':' in concept_key:
        prefix = concept_key.split(':')[0]
        for key_prefix, dist_label in KEY_PREFIX_TO_DISTILLATION.items():
            if prefix == key_prefix or prefix.startswith(key_prefix):
                if dist_label in distillations:
                    return [distillations[dist_label]]

    # 3. Fall back to source folder mapping
    dist_labels = SOURCE_TO_DISTILLATIONS.get(source_folder, [])
    for dl in dist_labels:
        if dl in distillations:
            candidates.append(distillations[dl])

    return candidates


def find_best_distillation(concept_name: str,
                           candidates: list[dict]) -> Optional[dict]:
    """From multiple candidate distillations, find the one with best KC match."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Try matching concept to each candidate's KC table
    for cand in candidates:
        if cand['key_concepts']:
            match = match_concept_to_table(concept_name, cand['key_concepts'])
            if match:
                return cand

    # No KC match — return first candidate (still has source citation)
    return candidates[0]


def find_interpretation_for_distillation(dist_label: str,
                                          interpretations: dict[str, dict]
                                          ) -> Optional[dict]:
    """Find interpretation matching a distillation label."""
    return interpretations.get(dist_label)


def find_convergence_web_refs(entry_id: str,
                              all_entries: dict) -> list[str]:
    """Find convergence_web entries that reference this cross_source entry.

    Searches the entries dict for cw entries whose concept string contains
    this entry's concept name (indicating a cross-source convergence).
    """
    refs = []
    entry_concept = all_entries.get(entry_id, {}).get('concept', '')
    if not entry_concept:
        return refs

    for cw_id, cw_data in all_entries.items():
        if cw_data.get('type') != 'convergence_web':
            continue
        cw_concept = cw_data.get('concept', '')
        if entry_concept in cw_concept:
            refs.append(f"{cw_id} → {cw_concept}")

    return refs


def parse_alpha_md(filepath: Path) -> dict:
    """Parse an existing alpha .md file to extract Ref and Maps_to fields."""
    text = filepath.read_text(encoding='utf-8')
    ref = ''
    maps_to = ''
    key = ''
    for line in text.split('\n'):
        if line.startswith('**Ref**:') or line.startswith('**Ref**: '):
            ref = line.split(':', 1)[1].strip()
        elif line.startswith('**Maps to**:') or line.startswith('**Maps to**: '):
            maps_to = line.split(':', 1)[1].strip()
        elif line.startswith('**Key**:') or line.startswith('**Key**: '):
            key = line.split(':', 1)[1].strip()
    return {'ref': ref, 'maps_to': maps_to, 'key': key}


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_backfill(alpha_dir: Path,
                 distill_dir: Path,
                 interp_dir: Path,
                 dry_run: bool = False) -> list[dict]:
    """Main backfill: crawl distillations+interpretations, produce enrichment JSON."""

    # --- 1. Load alpha index ---
    index_path = alpha_dir / 'index.json'
    if not index_path.exists():
        print(f"ERROR: {index_path} not found", file=sys.stderr)
        return []
    with open(index_path, encoding='utf-8') as f:
        index = json.load(f)

    all_entries = index.get('entries', {})
    # --- 2. Parse all distillation files ---
    distillations: dict[str, dict] = {}
    if distill_dir.exists():
        for md_file in sorted(distill_dir.glob('*.md')):
            parsed = parse_distillation(md_file)
            distillations[parsed['label']] = parsed
    print(f"Parsed {len(distillations)} distillation files", file=sys.stderr)

    # --- 3. Parse all interpretation files ---
    interpretations: dict[str, dict] = {}
    if interp_dir.exists():
        for md_file in sorted(interp_dir.glob('*.md')):
            parsed = parse_interpretation(md_file)
            interpretations[parsed['label']] = parsed
    print(f"Parsed {len(interpretations)} interpretation files", file=sys.stderr)

    # --- 4. Process each cross_source alpha entry ---
    results = []
    skipped = 0
    no_distill = 0
    source_to_distill: dict[str, set[str]] = {}
    match_stats = {'kc_match': 0, 'kc_miss': 0, 'pm_match': 0, 'pm_miss': 0,
                   'ip_match': 0, 'ip_miss': 0}

    for entry_id, entry_data in sorted(all_entries.items()):
        if entry_data.get('type') == 'convergence_web':
            continue
        source_folder = entry_data.get('source', '')
        if source_folder in SKIP_SOURCES:
            skipped += 1
            continue
        if 'group' in entry_data:
            skipped += 1
            continue

        # Read existing .md
        rel_file = entry_data.get('file', '')
        md_path = alpha_dir / rel_file
        if not md_path.exists():
            print(f"  WARN: {md_path} not found, skipping {entry_id}",
                  file=sys.stderr)
            skipped += 1
            continue

        alpha_md = parse_alpha_md(md_path)
        ref_field = alpha_md['ref']
        maps_to = alpha_md['maps_to']
        concept_key = alpha_md['key'] or entry_data.get('concept', '')
        concept_name = (concept_key.split(':', 1)[1]
                        if ':' in concept_key else concept_key)

        # Find candidate distillations
        candidates = find_distillations_for_entry(
            concept_key, ref_field, source_folder, distillations)
        dist = find_best_distillation(concept_name, candidates)

        if not dist:
            no_distill += 1
            # Still produce minimal entry
            body = build_body(
                entry_id, concept_key, None, None,
                find_convergence_web_refs(entry_id, all_entries),
                ref_field, maps_to)
            if body.strip():
                results.append({'id': entry_id, 'body': body})
            continue

        # Track mapping
        source_to_distill.setdefault(source_folder, set()).add(dist['label'])

        # Find interpretation (try all candidate distillation labels)
        interp = None
        for cand in candidates:
            interp = find_interpretation_for_distillation(
                cand['label'], interpretations)
            if interp:
                break

        # Match stats
        kc_match = match_concept_to_table(concept_name, dist['key_concepts'])
        if kc_match:
            match_stats['kc_match'] += 1
        else:
            match_stats['kc_miss'] += 1

        pm_match = None
        if interp and interp['project_mapping']:
            pm_match = match_concept_to_table(
                concept_name, interp['project_mapping'])
        if pm_match:
            match_stats['pm_match'] += 1
        else:
            match_stats['pm_miss'] += 1

        ip_match = match_concept_to_integration(
            concept_key, interp['integration_points']) if interp else None
        if ip_match:
            match_stats['ip_match'] += 1
        else:
            match_stats['ip_miss'] += 1

        # Find convergence_web cross-references
        related_cw = find_convergence_web_refs(
            entry_id, all_entries)

        # Build the body
        body = build_body(
            entry_id, concept_key, dist, interp,
            related_cw, ref_field, maps_to)

        if body.strip():
            results.append({'id': entry_id, 'body': body})

    # --- Report ---
    print(f"\n--- Backfill Report ---", file=sys.stderr)
    total = match_stats['kc_match'] + match_stats['kc_miss'] + no_distill
    print(f"Total cross_source entries processed: {total}", file=sys.stderr)
    print(f"  Key Concepts matches: {match_stats['kc_match']}", file=sys.stderr)
    print(f"  Key Concepts misses:  {match_stats['kc_miss']}", file=sys.stderr)
    print(f"  Project Mapping matches: {match_stats['pm_match']}", file=sys.stderr)
    print(f"  Project Mapping misses:  {match_stats['pm_miss']}", file=sys.stderr)
    print(f"  Integration Point matches: {match_stats['ip_match']}", file=sys.stderr)
    print(f"  Integration Point misses:  {match_stats['ip_miss']}", file=sys.stderr)
    print(f"  No distillation found: {no_distill}", file=sys.stderr)
    print(f"  Skipped (framework/forward/misc): {skipped}", file=sys.stderr)
    print(f"  Enrichment payloads generated: {len(results)}", file=sys.stderr)
    print(f"\nSource → Distillation mapping:", file=sys.stderr)
    for src, dlabels in sorted(source_to_distill.items()):
        print(f"  {src} → {', '.join(sorted(dlabels))}", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Backfill alpha entries with rich content from distillations')
    parser.add_argument('--alpha-dir', required=True,
                        help='Path to alpha/ directory (contains index.json)')
    parser.add_argument('--distill-dir', required=True,
                        help='Path to docs/references/distilled/ directory')
    parser.add_argument('--interp-dir', required=True,
                        help='Path to docs/references/interpretations/ directory')
    parser.add_argument('--output', required=True,
                        help='Output JSON file path')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse and report without producing output')
    args = parser.parse_args()

    alpha_dir = Path(args.alpha_dir)
    distill_dir = Path(args.distill_dir)
    interp_dir = Path(args.interp_dir)
    output_path = Path(args.output)

    results = run_backfill(alpha_dir, distill_dir, interp_dir, args.dry_run)

    if not args.dry_run and results:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {len(results)} entries to {output_path}", file=sys.stderr)
    elif args.dry_run:
        print(f"\n[DRY RUN] Would write {len(results)} entries", file=sys.stderr)


if __name__ == '__main__':
    main()
