#!/usr/bin/env python3
"""distill_glossary.py — Glossary template and duplicate checking.

Parses the Project Terminology Glossary table from a SKILL.md file,
outputs existing terms and a ready-to-fill template row.

Usage:
    python distill_glossary.py template --skill-md path/to/SKILL.md

Dependencies: Python 3.10+ (stdlib only)
"""
from __future__ import annotations

import argparse
import io
import re
import sys

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

GLOSSARY_HEADER = re.compile(r'^#{1,3}\s+.*(?:Glossary|glossary)', re.IGNORECASE)
TABLE_ROW = re.compile(r'^\|\s*([^|]+?)\s*\|')
SEPARATOR = re.compile(r'^\|[\s\-:|]+\|')
NEXT_SECTION = re.compile(r'^#{1,3}\s+')


def parse_glossary(text: str) -> list[str]:
    """Extract term names from a markdown glossary table."""
    lines = text.splitlines()
    in_glossary = False
    past_header = False
    terms = []

    for line in lines:
        if not in_glossary:
            if GLOSSARY_HEADER.match(line):
                in_glossary = True
            continue

        if SEPARATOR.match(line):
            past_header = True
            continue

        if not past_header:
            continue

        if NEXT_SECTION.match(line):
            break

        m = TABLE_ROW.match(line)
        if m:
            term = m.group(1).strip()
            if term and term.lower() not in ('term', '---'):
                terms.append(term)

    return terms


def cmd_template(args):
    """Output glossary template with existing terms for duplicate checking."""
    try:
        with open(args.skill_md, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        print(f"Error reading {args.skill_md}: {e}")
        return

    terms = parse_glossary(text)

    print(f"Existing terms: {len(terms)}")
    if terms:
        print(f"  {', '.join(terms)}")
    print()
    print("Template row:")
    print("| TERM | 1-2 sentence operational definition as used in THIS project | Source-Label |")
    print()
    print(f"Add max 5 new. Check list above \u2014 no duplicates.")


def main():
    parser = argparse.ArgumentParser(description='Glossary template and duplicate checking')
    subparsers = parser.add_subparsers(dest='command')

    tmpl = subparsers.add_parser('template', help='Output template + existing terms')
    tmpl.add_argument('--skill-md', required=True, help='Path to SKILL.md with glossary table')

    args = parser.parse_args()
    if args.command == 'template':
        cmd_template(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
