"""Tests for distill_glossary.py template command."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DISTILL_SCRIPTS = Path(__file__).parent.parent / 'distill' / 'scripts'
if str(DISTILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DISTILL_SCRIPTS))

from distill_glossary import cmd_template, parse_glossary


SAMPLE_SKILL_MD = """\
# Project SKILL.md

Some content here.

## Project Terminology Glossary

| Term | Definition | Source |
|------|------------|--------|
| Metathesis | Cross-agent encounter producing novel types | Levinas_TI |
| Practico-inert | Sedimented past praxis constraining future action | Sartre_CDR |
| Affordance | Environment-presented opportunity for praxis | DeLanda_AT |

## Next Section

Other stuff.
"""


def test_parses_existing_terms():
    terms = parse_glossary(SAMPLE_SKILL_MD)
    assert terms == ['Metathesis', 'Practico-inert', 'Affordance']


def test_empty_table():
    md = "## Project Terminology Glossary\n\n| Term | Definition | Source |\n|------|------------|--------|\n\n## Next\n"
    terms = parse_glossary(md)
    assert terms == []


def test_no_glossary_section():
    terms = parse_glossary("# Just a file\n\nNo glossary here.\n")
    assert terms == []


def test_template_output(tmp_path, capsys):
    skill_md = tmp_path / 'SKILL.md'
    skill_md.write_text(SAMPLE_SKILL_MD, encoding='utf-8')
    args = SimpleNamespace(skill_md=str(skill_md))
    cmd_template(args)
    out = capsys.readouterr().out
    assert 'Existing terms: 3' in out
    assert 'Metathesis' in out
    assert 'max 5' in out.lower()
