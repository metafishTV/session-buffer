#!/usr/bin/env python3
"""Backfill atom markers into existing distillation files and update alpha index.

Usage:
    python distill_backfill_markers.py --distilled-dir <path> --alpha-dir <path> [--dry-run]

Inserts <!-- SECTION:name -->, <!-- CONCEPT:key -->, and <!-- FIGURE:id --> markers
into existing distillation .md files. Updates alpha index.json with distillation
filename and marker fields for script-based retrieval.

Safe: --dry-run shows changes without writing. Never deletes alpha .md files.
"""

import argparse
import json
import os
import re
import sys


# Section heading → marker name mapping
SECTION_MAP = {
    "core argument": "core_argument",
    "key concepts": "key_concepts",
    "figures, tables & maps": "figures",
    "figures": "figures",
    "equations & formal models": "equations",
    "equations": "equations",
    "theoretical & methodological implications": "theoretical_implications",
    "theoretical implications": "theoretical_implications",
    "figure <-> concept contrast": None,  # Skip — deprecated section
    "figure ↔ concept contrast": None,
}


def normalize_concept_key(concept_name):
    """Normalize a concept name to a marker key."""
    key = concept_name.lower()
    key = re.sub(r'\([^)]*\)', '', key)  # Remove parenthetical
    key = re.sub(r'[^a-z0-9\s]', '', key)  # Strip special chars
    key = key.strip()
    key = re.sub(r'\s+', '_', key)  # Spaces to underscores
    return key[:40]


def insert_section_markers(lines):
    """Insert section markers around ## headings. Returns (new_lines, sections_found)."""
    new_lines = []
    sections_found = []
    current_section = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for ## heading (not ### or #)
        if stripped.startswith("## ") and not stripped.startswith("### "):
            heading_text = stripped[3:].strip()
            # Remove conditional markers like "← CONDITIONAL" or "← MANDATORY"
            heading_clean = re.sub(r'\s*←.*$', '', heading_text).strip().lower()

            section_name = SECTION_MAP.get(heading_clean)

            # Close previous section if open
            if current_section:
                new_lines.append(f"<!-- /SECTION:{current_section} -->\n")
                new_lines.append("\n")

            if section_name:
                sections_found.append(section_name)
                new_lines.append(f"<!-- SECTION:{section_name} -->\n")
                current_section = section_name
            else:
                current_section = None

        new_lines.append(line)
        i += 1

    # Close last section
    if current_section:
        new_lines.append(f"<!-- /SECTION:{current_section} -->\n")

    return new_lines, sections_found


def insert_concept_markers(lines):
    """Insert concept markers around Key Concepts table rows. Returns (new_lines, concepts_found)."""
    new_lines = []
    concepts_found = []
    in_key_concepts = False
    past_header_row = False
    past_separator = False

    for line in lines:
        stripped = line.strip()

        # Detect Key Concepts section
        if "<!-- SECTION:key_concepts -->" in stripped:
            in_key_concepts = True
            new_lines.append(line)
            continue
        if "<!-- /SECTION:key_concepts -->" in stripped:
            in_key_concepts = False
            past_header_row = False
            past_separator = False
            new_lines.append(line)
            continue

        if in_key_concepts and stripped.startswith("|"):
            if not past_header_row:
                # First table row is header
                past_header_row = True
                new_lines.append(line)
                continue
            if not past_separator and re.match(r'^\|[\s\-|]+\|$', stripped):
                # Separator row (|---|---|---|---|)
                past_separator = True
                new_lines.append(line)
                continue

            if past_separator:
                # Data row — extract concept from first column
                cols = [c.strip() for c in stripped.split("|")]
                if len(cols) >= 2 and cols[1]:
                    concept_name = cols[1]
                    concept_key = normalize_concept_key(concept_name)
                    if concept_key:
                        concepts_found.append((concept_key, concept_name))
                        new_lines.append(f"<!-- CONCEPT:{concept_key} -->\n")
                        new_lines.append(line)
                        new_lines.append(f"<!-- /CONCEPT:{concept_key} -->\n")
                        continue

        new_lines.append(line)

    return new_lines, concepts_found


def insert_figure_markers(lines):
    """Insert figure markers around ### Figure subsections. Returns (new_lines, figures_found)."""
    new_lines = []
    figures_found = []
    in_figures_section = False
    current_figure = None

    for line in lines:
        stripped = line.strip()

        if "<!-- SECTION:figures -->" in stripped:
            in_figures_section = True
            new_lines.append(line)
            continue
        if "<!-- /SECTION:figures -->" in stripped:
            if current_figure:
                new_lines.append(f"<!-- /FIGURE:{current_figure} -->\n")
                current_figure = None
            in_figures_section = False
            new_lines.append(line)
            continue

        if in_figures_section and stripped.startswith("### "):
            # Close previous figure
            if current_figure:
                new_lines.append(f"<!-- /FIGURE:{current_figure} -->\n")

            # Extract figure ID from heading or generate from content
            # Look for page reference in heading or image link
            fig_id = None
            # Try to find page number in heading
            page_match = re.search(r'p\.?\s*(\d+)', stripped)
            fig_num_match = re.search(r'(?:Figure|Table|Fig\.?)\s*(\d+)', stripped, re.IGNORECASE)

            if fig_num_match and page_match:
                fig_type = "tab" if "table" in stripped.lower() else "fig"
                fig_id = f"{fig_type}_{int(fig_num_match.group(1)):02d}_p{page_match.group(1)}"
            elif fig_num_match:
                fig_type = "tab" if "table" in stripped.lower() else "fig"
                fig_id = f"{fig_type}_{int(fig_num_match.group(1)):02d}"
            else:
                # Fallback: use cleaned heading text
                fig_id = normalize_concept_key(stripped[4:])[:30]

            if fig_id:
                figures_found.append(fig_id)
                current_figure = fig_id
                new_lines.append(f"<!-- FIGURE:{fig_id} -->\n")

        new_lines.append(line)

    if current_figure:
        new_lines.append(f"<!-- /FIGURE:{current_figure} -->\n")

    return new_lines, figures_found


def process_file(filepath, dry_run=False):
    """Insert all marker types into a distillation file."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Skip if already marked
    content = "".join(lines)
    if "<!-- SECTION:" in content:
        return None, "already marked"

    # Phase 1: Section markers
    lines, sections = insert_section_markers(lines)
    # Phase 2: Concept markers (needs section markers to find key_concepts)
    lines, concepts = insert_concept_markers(lines)
    # Phase 3: Figure markers (needs section markers to find figures)
    lines, figures = insert_figure_markers(lines)

    if not sections and not concepts and not figures:
        return None, "no sections found"

    if not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)

    return {
        "sections": sections,
        "concepts": [(k, n) for k, n in concepts],
        "figures": figures,
    }, "ok"


def update_alpha_index(alpha_dir, distilled_dir, file_results, dry_run=False):
    """Update alpha index.json with distillation and marker fields."""
    index_path = os.path.join(alpha_dir, "index.json")
    if not os.path.isfile(index_path):
        return 0, "no index.json"

    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    entries = index.get("entries", {})
    updated = 0

    for filename, result in file_results.items():
        if result is None:
            continue
        concepts_in_file = {k: n for k, n in result["concepts"]}

        # Match alpha entries to this distillation file
        for entry_id, entry in entries.items():
            if not entry_id.startswith("w:"):
                continue
            # Skip if already has marker
            if entry.get("marker"):
                continue

            concept = entry.get("concept", "")
            concept_norm = normalize_concept_key(concept)

            # Check if this concept matches any concept in this file
            matched_key = None
            for file_key in concepts_in_file:
                if file_key == concept_norm:
                    matched_key = file_key
                    break
                # Fuzzy: check if concept_norm is substring or vice versa
                if len(concept_norm) > 3 and (concept_norm in file_key or file_key in concept_norm):
                    matched_key = file_key
                    break

            if matched_key:
                entry["distillation"] = filename
                entry["marker"] = matched_key
                updated += 1

    if not dry_run and updated > 0:
        index["last_updated"] = str(__import__("datetime").date.today())
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    return updated, "ok"


def main():
    parser = argparse.ArgumentParser(description="Backfill atom markers into distillation files")
    parser.add_argument("--distilled-dir", required=True, help="Path to distilled/ directory")
    parser.add_argument("--alpha-dir", default=None, help="Path to alpha/ directory (for index update)")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    if not os.path.isdir(args.distilled_dir):
        print(f"ERROR: Directory not found: {args.distilled_dir}", file=sys.stderr)
        sys.exit(1)

    # Process all .md files
    md_files = sorted(
        f for f in os.listdir(args.distilled_dir)
        if f.endswith(".md") and not f.startswith("_")
    )

    file_results = {}
    total_sections = 0
    total_concepts = 0
    total_figures = 0
    skipped = 0

    for fname in md_files:
        fpath = os.path.join(args.distilled_dir, fname)
        result, status = process_file(fpath, dry_run=args.dry_run)
        if result is None:
            skipped += 1
            if status != "already marked":
                print(f"  SKIP {fname}: {status}")
            else:
                print(f"  SKIP {fname}: already marked")
            continue

        file_results[fname] = result
        ns = len(result["sections"])
        nc = len(result["concepts"])
        nf = len(result["figures"])
        total_sections += ns
        total_concepts += nc
        total_figures += nf
        print(f"  {'DRY ' if args.dry_run else ''}MARK {fname}: {ns} sections, {nc} concepts, {nf} figures")

    print(f"\nTotal: {len(file_results)} files marked, {skipped} skipped")
    print(f"  {total_sections} section markers, {total_concepts} concept markers, {total_figures} figure markers")

    # Update alpha index if provided
    if args.alpha_dir and os.path.isdir(args.alpha_dir):
        updated, status = update_alpha_index(
            args.alpha_dir, args.distilled_dir, file_results, dry_run=args.dry_run
        )
        print(f"\nAlpha index: {updated} entries updated ({status})")
    elif args.alpha_dir:
        print(f"\nAlpha index: directory not found: {args.alpha_dir}")


if __name__ == "__main__":
    main()
