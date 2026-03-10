#!/usr/bin/env python3
"""Section and atom retrieval from marked distillation files.

Usage:
    python distill_retrieve.py --dir <distilled_dir> --source <Source-Label> --section core_argument
    python distill_retrieve.py --dir <distilled_dir> --source <Source-Label> --atoms key1,key2,key3
    python distill_retrieve.py --dir <distilled_dir> --source <Source-Label> --figure fig_01_p57
    python distill_retrieve.py --dir <distilled_dir> --source <Source-Label> --list-sections

Extracts marked sections from distillation files at zero token cost.
Markers are HTML comments: <!-- SECTION:name -->, <!-- CONCEPT:key -->, <!-- FIGURE:id -->

Exit codes: 0 = success, 1 = file not found, 2 = marker not found
"""

import argparse
import os
import re
import sys


def find_distillation_file(distilled_dir, source_label):
    """Find the distillation file for a source label."""
    # Try exact match first
    path = os.path.join(distilled_dir, f"{source_label}.md")
    if os.path.isfile(path):
        return path
    # Try without extension (in case label already has .md)
    if source_label.endswith(".md"):
        path = os.path.join(distilled_dir, source_label)
        if os.path.isfile(path):
            return path
    return None


def extract_markers(lines, marker_type, marker_name):
    """Extract content between <!-- TYPE:NAME --> and <!-- /TYPE:NAME --> markers."""
    open_tag = f"<!-- {marker_type}:{marker_name} -->"
    close_tag = f"<!-- /{marker_type}:{marker_name} -->"
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

    return captured


def extract_by_heading(lines, heading_name):
    """Fallback: extract content by ## heading name (for unmarked files)."""
    normalized = heading_name.lower().replace("_", " ").replace("-", " ")
    capturing = False
    captured = []
    heading_level = 0

    for line in lines:
        stripped = line.strip()
        # Check for heading match
        if stripped.startswith("## ") and not stripped.startswith("### "):
            h_text = stripped[3:].strip().lower()
            if h_text == normalized or normalized in h_text:
                capturing = True
                heading_level = 2
                captured.append(line)
                continue
            elif capturing:
                # Hit another ## heading — stop
                break
        elif stripped.startswith("# ") and not stripped.startswith("## "):
            if capturing:
                break
        if capturing:
            captured.append(line)

    return captured


def extract_concept_row(lines, concept_key):
    """Extract a concept's table row and any surrounding content by key."""
    normalized = concept_key.lower().replace("_", " ").replace("-", " ")

    # Try marker-based first
    captured = extract_markers(lines, "CONCEPT", concept_key)
    if captured:
        return captured

    # Fallback: scan Key Concepts table for matching row
    in_concepts = False
    captured = []

    for line in lines:
        stripped = line.strip()
        if "## Key Concepts" in stripped or "## key concepts" in stripped.lower():
            in_concepts = True
            continue
        if in_concepts and stripped.startswith("## "):
            break
        if in_concepts and stripped.startswith("|"):
            # Parse first column of table row
            cols = [c.strip() for c in stripped.split("|")]
            if len(cols) >= 2:
                first_col = cols[1].lower().strip()
                # Normalize for matching
                first_norm = re.sub(r'[^a-z0-9\s]', '', first_col).strip()
                if normalized in first_norm or first_norm in normalized:
                    captured.append(line)

    return captured


def list_all_markers(lines):
    """List all markers found in the file."""
    sections = []
    concepts = []
    figures = []

    for line in lines:
        stripped = line.strip()
        m = re.match(r'<!-- (SECTION|CONCEPT|FIGURE):(\S+?) -->', stripped)
        if m:
            mtype, mname = m.group(1), m.group(2)
            if mtype == "SECTION":
                sections.append(mname)
            elif mtype == "CONCEPT":
                concepts.append(mname)
            elif mtype == "FIGURE":
                figures.append(mname)

    return sections, concepts, figures


def main():
    parser = argparse.ArgumentParser(description="Retrieve marked sections from distillation files")
    parser.add_argument("--dir", required=True, help="Path to distilled/ directory")
    parser.add_argument("--source", required=True, help="Source label (filename without .md)")
    parser.add_argument("--section", default=None, help="Section name to extract (e.g., core_argument)")
    parser.add_argument("--atoms", default=None, help="Comma-separated concept keys to extract")
    parser.add_argument("--figure", default=None, help="Figure ID to extract (e.g., fig_01_p57)")
    parser.add_argument("--list-sections", action="store_true", help="List all markers in the file")
    args = parser.parse_args()

    # Find file
    fpath = find_distillation_file(args.dir, args.source)
    if fpath is None:
        print(f"ERROR: No distillation file found for '{args.source}' in '{args.dir}'", file=sys.stderr)
        sys.exit(1)

    with open(fpath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # List mode
    if args.list_sections:
        sections, concepts, figures = list_all_markers(lines)
        if not sections and not concepts and not figures:
            # Fallback: list ## headings
            headings = [l.strip()[3:].strip() for l in lines if l.strip().startswith("## ") and not l.strip().startswith("### ")]
            print("No markers found. Available ## headings:")
            for h in headings:
                print(f"  heading: {h}")
        else:
            if sections:
                print(f"Sections ({len(sections)}): {', '.join(sections)}")
            if concepts:
                print(f"Concepts ({len(concepts)}): {', '.join(concepts)}")
            if figures:
                print(f"Figures ({len(figures)}): {', '.join(figures)}")
        sys.exit(0)

    # Section extraction
    if args.section:
        captured = extract_markers(lines, "SECTION", args.section)
        if not captured:
            # Fallback to heading-based extraction
            captured = extract_by_heading(lines, args.section)
        if not captured:
            print(f"MARKER_NOT_FOUND: {args.section}", file=sys.stderr)
            sys.exit(2)
        print("".join(captured), end="")
        sys.exit(0)

    # Atom (concept) extraction — batch mode
    if args.atoms:
        keys = [k.strip() for k in args.atoms.split(",")]
        found = 0
        for key in keys:
            captured = extract_concept_row(lines, key)
            if captured:
                print(f"--- {key} ---")
                print("".join(captured), end="")
                if not "".join(captured).endswith("\n"):
                    print()
                found += 1
            else:
                print(f"--- {key} --- NOT FOUND")
        if found == 0:
            sys.exit(2)
        sys.exit(0)

    # Figure extraction
    if args.figure:
        captured = extract_markers(lines, "FIGURE", args.figure)
        if not captured:
            # Fallback: look for ### Figure with matching ID in text
            fig_pattern = re.compile(re.escape(args.figure), re.IGNORECASE)
            in_figure = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("### ") and fig_pattern.search(stripped):
                    in_figure = True
                    captured.append(line)
                    continue
                if in_figure:
                    if stripped.startswith("### ") or stripped.startswith("## "):
                        break
                    captured.append(line)
        if not captured:
            print(f"FIGURE_NOT_FOUND: {args.figure}", file=sys.stderr)
            sys.exit(2)
        print("".join(captured), end="")
        sys.exit(0)

    print("ERROR: Specify --section, --atoms, --figure, or --list-sections", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
