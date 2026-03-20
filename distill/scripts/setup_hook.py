#!/usr/bin/env python3
"""
Distill Plugin — Setup Hook (SessionStart)

Deploys managed rules file to .claude/rules/ in the project directory.
Rules files are always loaded into Claude's context and survive compaction
(re-read from disk each turn).

Timeout: 5 seconds (must be fast — blocks session start).
"""

import sys
import os
import io
import json

# Force UTF-8 on Windows
if sys.platform == 'win32' and __name__ == '__main__':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except AttributeError:
        pass


DISTILL_RULES_VERSION = "3.1.0"

DISTILL_RULES_CONTENT = """\
<!-- managed by distill plugin v{version} — do not edit manually -->
# Distill Plugin Rules

## Pipeline Usage — NON-OPTIONAL

- NEVER write distillation files (`docs/references/distilled/*.md`) without using the `distill:analyze` skill.
- NEVER write interpretation files (`docs/references/interpretations/*.md`) without using the `distill:analyze` skill.
- NEVER perform skill-defined workflows manually. If a skill exists for the operation, USE IT.

## Extraction Prohibition — Absolute

You MUST NOT extract text, images, or figures from source documents outside the `distill:extract` sub-skill pipeline. This means:
- NO direct PyMuPDF / fitz.open() / pdfplumber / pdf2image calls in Bash.
- NO ad-hoc text extraction scripts that bypass `distill_scan.py`.
- NO "quick" or "lightweight" extraction that skips figure budget gating.
- NO subagent-based extraction that circumvents the 6 mandatory checkpoints.
A PreToolUse hook enforces this structurally — ad-hoc extraction commands will be blocked.

## Redistillation Detection — All Four Checks Mandatory

Before any extraction, verify all four:
1. Check `distilled/` for existing distillation of this source.
2. Check `interpretations/` for existing interpretation.
3. Check `figures/` for existing extracted figures.
4. Query the alpha bin index for existing entries.
Do NOT skip any check. Do NOT assume files don't exist without verifying via Glob or Read.

## FULL STOP Protocol

After calling `AskUserQuestion`, your turn ENDS. Do not continue to the next step. Do not prefetch, prepare, or begin subsequent work. Do not write "while we wait" or "in the meantime." The next step begins ONLY in your next turn, AFTER the user has responded. This is a hard gate, not a courtesy pause.

## Forward Notes

Before ANY write to `forward_notes.json` → run `distill_forward_notes.py template --notes [path]` first.
- Never blindly append. Template shows `next_number` + existing entries.
- NEVER write a registry entry keyed to a number within a reserved range. Reserved ranges belong to pre-existing project content. If a distillation reveals an existing section should be cross-referenced, note it in interpretation prose as: `> Cross-ref: §[N] — [reason]`.
- New notes start at `next_number` from the registry. Increment after use.
- After adding entries → run `distill_forward_notes.py check-new` for dedup.

## Figure vs Equation Policy

- Visual content (tables, graphs, charts, diagrams, schematics) → always extract as figure files.
- Core-meaning equations (the equation IS the concept) → inline LaTeX in distillation markdown. Not a figure.
- Scaffolding equations (derivations, intermediate algebra, proof steps) → skip entirely.

## Distillation Voice & Structure

- Direct assertive register. State claims as the source states them.
- No meta-commentary ("The author argues...") — just present the content.
- Attribution via `<!-- CONCEPT:key -->` markers, not prose.
- All ## sections, concept rows, and figure subsections MUST have atom markers.
- Use inline templates from sub-skills for output formats. Do NOT read existing output files to learn the pattern — the template IS the pattern.

## Infrastructure Protection

- NEVER modify bundled scripts in the plugin's `scripts/` directory. If a script needs adaptation, copy to repo first.

## Autonomy Boundary

- FULL STOP popups (redistill detection, quality gate failures) → never skip. Always present to user.
- Uncertain about extraction route or concept mapping → ask. Do not guess.
- User review of interpretation → mandatory before integrate. No shortcuts.
""".format(version=DISTILL_RULES_VERSION)


def find_project_root(start_path):
    """Walk up from start_path looking for a .claude/ directory."""
    current = os.path.abspath(start_path)
    while True:
        candidate = os.path.join(current, '.claude')
        if os.path.isdir(candidate):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def ensure_managed_rules(project_root):
    """Deploy managed rules file to .claude/rules/ if needed.

    Idempotent: only writes if content changed or file missing.
    Fail-safe: skips silently on any error.
    """
    try:
        rules_dir = os.path.join(project_root, '.claude', 'rules')
        rules_path = os.path.join(rules_dir, 'distill-pipeline-enforcement.md')

        # Check if current content matches — skip if unchanged
        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                existing = f.read()
            if existing == DISTILL_RULES_CONTENT:
                return None
        except (FileNotFoundError, OSError):
            pass

        os.makedirs(rules_dir, exist_ok=True)
        with open(rules_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(DISTILL_RULES_CONTENT)
        return f"Deployed distill rules to .claude/rules/distill-pipeline-enforcement.md (v{DISTILL_RULES_VERSION})"
    except OSError:
        return None


def main():
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        hook_input = {}

    cwd = hook_input.get('cwd', os.getcwd())
    project_root = find_project_root(cwd)

    if not project_root:
        print('{}')
        return

    try:
        result = ensure_managed_rules(project_root)
        if result:
            print(result, file=sys.stderr)
    except Exception:
        pass

    # Always output empty JSON — don't block session start
    print('{}')


if __name__ == '__main__':
    main()
