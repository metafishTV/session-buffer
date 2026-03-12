#!/usr/bin/env python3
"""
Distill Extraction Guard — PreToolUse Hook

Detects ad-hoc PDF/document extraction in Bash commands that bypass
the distill:extract pipeline. Blocks with an actionable error message.

Detection patterns (in Bash tool_params.command):
  - import fitz / fitz.open / pymupdf
  - import pdfplumber / pdfplumber.open
  - pdf2image / convert_from_path
  - get_text / extract_text / extract_images (PyMuPDF API calls)
  - page.get_pixmap (PyMuPDF rendering)

Guard conditions:
  - Only fires on Bash tool calls
  - Only fires when .distill_active marker IS present (distillation in progress)
  - Allows extraction commands when .distill_active is NOT set (normal non-distill work)
  - Allows distill pipeline scripts (distill_scan.py, distill_extract.py, etc.)

Input (stdin): {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_params": {"command": "..."}, "cwd": "..."}
Output (stdout): {} for allow, or {"decision": "block", "reason": "..."} to block
"""

import sys
import os
import io
import json
import re

# Force UTF-8 on Windows
if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ad-hoc extraction patterns — things you'd see in raw PyMuPDF/pdfplumber usage
EXTRACTION_PATTERNS = [
    r'\bimport\s+fitz\b',
    r'\bfitz\.open\s*\(',
    r'\bimport\s+pymupdf\b',
    r'\bimport\s+pdfplumber\b',
    r'\bpdfplumber\.open\s*\(',
    r'\bconvert_from_path\s*\(',
    r'\bpdf2image\b',
    r'\.get_text\s*\(',
    r'\.extract_text\s*\(',
    r'\.extract_images\s*\(',
    r'\.get_pixmap\s*\(',
]

# Compiled once
EXTRACTION_RE = re.compile('|'.join(EXTRACTION_PATTERNS), re.IGNORECASE)

# Pipeline scripts that ARE allowed to use these APIs
PIPELINE_SCRIPTS = [
    'distill_scan.py',
    'distill_extract.py',
    'distill_figures.py',
    'distill_ocr.py',
    'distill_setup.py',
]


def find_marker(cwd: str) -> bool:
    """Check if .distill_active marker exists (distillation in progress)."""
    if not cwd:
        return False
    marker = os.path.join(cwd, '.distill_active')
    return os.path.exists(marker)


def is_pipeline_script(command: str) -> bool:
    """Check if the command invokes a known pipeline script."""
    return any(script in command for script in PIPELINE_SCRIPTS)


def check_command(command: str) -> str | None:
    """Returns a reason string if blocked, None if allowed."""
    if not command:
        return None
    if is_pipeline_script(command):
        return None
    match = EXTRACTION_RE.search(command)
    if match:
        return (
            f"Ad-hoc PDF extraction detected: `{match.group()}`\n\n"
            "This bypasses the distill:extract pipeline and will miss figures, "
            "skip quality gates, and produce incomplete distillations.\n\n"
            "Use `distill:extract` instead — it handles scanning, figure budget, "
            "route selection, crop verification, and extraction stats.\n\n"
            "If you need raw text for a non-distillation purpose, end the current "
            "distillation first (remove .distill_active marker)."
        )
    return None


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print('{}')
            return

        data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        # Can't parse input — allow (fail open)
        print('{}')
        return

    tool_name = data.get('tool_name', '')
    tool_params = data.get('tool_params', {})
    cwd = data.get('cwd', '')

    # Only check Bash commands
    if tool_name != 'Bash':
        print('{}')
        return

    # Only enforce during active distillation
    if not find_marker(cwd):
        print('{}')
        return

    command = tool_params.get('command', '')
    reason = check_command(command)

    if reason:
        result = {
            'decision': 'block',
            'reason': reason
        }
        print(json.dumps(result))
    else:
        print('{}')


if __name__ == '__main__':
    main()
