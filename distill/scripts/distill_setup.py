#!/usr/bin/env python3
"""distill_setup.py — Automate distill skill setup (Steps 1-2, 4-4b).

Handles mechanical operations that would otherwise consume LLM tokens:
  - Tooling audit (subprocess checks for 9 specialist tools)
  - Project infrastructure scan (glob for paths, count files)
  - Project skill generation (template filling from questionnaire answers)
  - Project README generation

The LLM handles CONTENT decisions (questionnaire interpretation, user
interaction). This script handles PLUMBING (subprocess calls, path
resolution, template construction).

Subcommands:
    audit-tools     Check installed specialist tools, output tooling profile
    scan-project    Detect project infrastructure (paths, buffer, counts)
    generate-skill  Generate project SKILL.md from questionnaire answers
    generate-readme Generate project README.md from configuration

Usage:
    python distill_setup.py audit-tools
    python distill_setup.py scan-project --repo-dir /path/to/repo
    python distill_setup.py generate-skill --repo-dir /path/to/repo --input answers.json
    python distill_setup.py generate-readme --repo-dir /path/to/repo --input config.json

Dependencies: Python 3.10+ (stdlib only)
"""

import sys
import os
import io
import json
import subprocess
import argparse
from pathlib import Path
from datetime import date

# Force UTF-8 stdout/stderr on Windows (subprocess output may contain unicode)
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Subcommand: audit-tools
# ---------------------------------------------------------------------------

TOOL_CHECKS = [
    {
        'name': 'PyMuPDF',
        'category': 'Required for PDFs',
        'role': 'SCANNER + PRIMARY',
        'check': [PYTHON, '-c',
                  "import pymupdf; print(f'PyMuPDF {pymupdf.__version__}')"],
    },
    {
        'name': 'pdftotext',
        'category': 'Fallback',
        'role': 'FALLBACK — Route G only',
        'check_shell': 'pdftotext -v 2>&1 | head -1',
    },
    {
        'name': 'pdfplumber',
        'category': 'Required for PDFs',
        'role': 'table specialist',
        'check': [PYTHON, '-c',
                  "import pdfplumber; print(f'pdfplumber {pdfplumber.__version__}')"],
        'install': 'pip install pdfplumber',
        'size': '<1MB',
    },
    {
        'name': 'Pillow',
        'category': 'Required for PDFs',
        'role': 'image handling',
        'check': [PYTHON, '-c',
                  "from PIL import Image; import PIL; print(f'Pillow {PIL.__version__}')"],
    },
    {
        'name': 'Docling',
        'category': 'Highly recommended',
        'role': 'layout + OCR + complex tables',
        'check': [PYTHON, '-c',
                  "from docling.document_converter import DocumentConverter; "
                  "from importlib.metadata import version; "
                  "print(f'Docling {version(\"docling\")}')"],
        'install': 'pip install docling',
        'demand_install': True,
    },
    {
        'name': 'Marker',
        'category': 'Optional',
        'role': 'equations -> LaTeX',
        'check': [PYTHON, '-c',
                  "import marker; from importlib.metadata import version; "
                  "print(f'Marker {version(\"marker-pdf\")}')"],
        'install': 'pip install marker-pdf',
        'demand_install': True,
    },
    {
        'name': 'GROBID',
        'category': 'Optional',
        'role': 'scholarly papers (Docker)',
        'check_grobid': True,
    },
    {
        'name': 'yt-dlp',
        'category': 'Required for Recordings',
        'role': 'YouTube/platform captions + metadata + audio download',
        'check': [PYTHON, '-c',
                  "import yt_dlp; print(f'yt-dlp {yt_dlp.version.__version__}')"],
        'check_fallback_shell': 'yt-dlp --version 2>/dev/null',
        'install': 'pip install yt-dlp',
        'size': '~10MB',
        'demand_install': True,
    },
    {
        'name': 'faster-whisper',
        'category': 'Recommended for Recordings',
        'role': 'local audio/video transcription',
        'check': [PYTHON, '-c',
                  "import faster_whisper; from importlib.metadata import version; "
                  "print(f'faster-whisper {version(\"faster-whisper\")}')"],
        'install': 'pip install faster-whisper',
        'size': '<5MB install, ~150MB model',
        'demand_install': True,
    },
]


def check_tool(tool: dict) -> dict:
    """Check if a tool is installed. Returns status dict."""
    result = {
        'name': tool['name'],
        'category': tool['category'],
        'role': tool['role'],
        'status': 'not installed',
        'version': None,
    }

    # GROBID special handling
    if tool.get('check_grobid'):
        return check_grobid(result)

    # Standard Python import check
    if 'check' in tool:
        try:
            proc = subprocess.run(
                tool['check'],
                capture_output=True, text=True, timeout=15
            )
            if proc.returncode == 0 and proc.stdout.strip():
                version_str = proc.stdout.strip()
                result['status'] = f"installed: {version_str}"
                result['version'] = version_str
                return result
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Fallback shell check (e.g., yt-dlp CLI)
    if 'check_fallback_shell' in tool:
        try:
            proc = subprocess.run(
                tool['check_fallback_shell'],
                capture_output=True, text=True, timeout=10, shell=True
            )
            if proc.returncode == 0 and proc.stdout.strip():
                version_str = proc.stdout.strip()
                result['status'] = f"installed: {version_str}"
                result['version'] = version_str
                return result
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Shell check (e.g., pdftotext)
    if 'check_shell' in tool:
        try:
            proc = subprocess.run(
                tool['check_shell'],
                capture_output=True, text=True, timeout=10, shell=True
            )
            if proc.returncode == 0 and proc.stdout.strip():
                result['status'] = f"installed: {proc.stdout.strip()}"
                result['version'] = proc.stdout.strip()
                return result
            # pdftotext sometimes returns version on stderr
            if proc.stderr and 'version' in proc.stderr.lower():
                result['status'] = f"installed: {proc.stderr.strip().split(chr(10))[0]}"
                result['version'] = proc.stderr.strip().split('\n')[0]
                return result
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Mark demand-install status
    if tool.get('demand_install'):
        result['status'] = 'demand-install'
        if tool.get('install'):
            result['install_cmd'] = tool['install']
        if tool.get('size'):
            result['install_size'] = tool['size']

    return result


def check_grobid(result: dict) -> dict:
    """Check GROBID Docker status."""
    # Check running containers
    try:
        proc = subprocess.run(
            ['docker', 'ps', '-a', '--filter', 'name=grobid',
             '--format', '{{.Status}}'],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0 and proc.stdout.strip():
            status = proc.stdout.strip().split('\n')[0]
            if 'Up' in status:
                result['status'] = 'docker: running'
                result['version'] = status
                return result
            else:
                result['status'] = f'docker: container exists ({status})'
                result['version'] = status
                return result
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Check images
    try:
        proc = subprocess.run(
            ['docker', 'images', '--filter', 'reference=*grobid*',
             '--format', '{{.Repository}}:{{.Tag}}'],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0 and proc.stdout.strip():
            image = proc.stdout.strip().split('\n')[0]
            result['status'] = f'docker: image present ({image})'
            result['version'] = image
            return result
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    result['status'] = 'not available'
    return result


def cmd_audit_tools(args):
    """Run tooling audit and output profile."""
    print("Running tooling audit...", file=sys.stderr)
    results = []

    for tool in TOOL_CHECKS:
        print(f"  Checking {tool['name']}...", file=sys.stderr)
        result = check_tool(tool)
        results.append(result)

    # Categorize
    installed = [r for r in results if r['status'].startswith('installed')]
    demand = [r for r in results if r['status'] == 'demand-install']
    missing = [r for r in results
               if r['status'] in ('not installed', 'not available')]

    # Summary
    print(f"\nInstalled: {len(installed)}, Demand-install: {len(demand)}, "
          f"Missing: {len(missing)}", file=sys.stderr)

    output = {
        'tools': results,
        'summary': {
            'installed': len(installed),
            'demand_install': len(demand),
            'missing': len(missing),
        },
        'tooling_profile': {
            r['name']: r['status'] for r in results
        }
    }

    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: scan-project
# ---------------------------------------------------------------------------

def find_first_glob(repo: Path, patterns: list) -> str | None:
    """Find the first existing path matching any of the glob patterns."""
    for pattern in patterns:
        matches = list(repo.glob(pattern))
        if matches:
            return str(matches[0].relative_to(repo))
    return None


def cmd_scan_project(args):
    """Scan project infrastructure for distillation setup."""
    repo = Path(args.repo_dir).resolve()

    if not repo.exists():
        print(f"Error: repo directory not found: {repo}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {repo}...", file=sys.stderr)

    result = {
        'repo_dir': str(repo),
        'paths': {},
        'buffer': {},
        'counts': {},
        'project_context': None,
    }

    # --- Detect paths ---
    # Distillation directory
    distill_dir = find_first_glob(repo, [
        'docs/references/distilled',
        'docs/distilled',
        'distilled',
    ])
    result['paths']['distillation_dir'] = distill_dir

    # Index file
    index_file = find_first_glob(repo, [
        'docs/references/INDEX.md',
        'docs/references/index.md',
        'docs/INDEX.md',
        'docs/index.md',
        'INDEX.md',
    ])
    result['paths']['index_file'] = index_file

    # Interpretations directory
    interp_dir = find_first_glob(repo, [
        'docs/references/interpretations',
        'docs/interpretations',
        'interpretations',
    ])
    result['paths']['interpretations_dir'] = interp_dir

    # Figures directory
    if distill_dir:
        figures_dir = find_first_glob(repo, [
            f'{distill_dir}/figures',
        ])
        result['paths']['figures_dir'] = figures_dir or f"{distill_dir}/figures"

    # Raw text archive
    if distill_dir:
        raw_dir = find_first_glob(repo, [
            f'{distill_dir}/raw',
        ])
        result['paths']['raw_dir'] = raw_dir

    # --- Check buffer infrastructure ---
    buffer_dir = repo / '.claude' / 'buffer'
    if buffer_dir.exists():
        hot_path = buffer_dir / 'handoff.json'
        warm_path = buffer_dir / 'handoff-warm.json'

        if hot_path.exists():
            try:
                hot = json.loads(hot_path.read_text(encoding='utf-8'))
                result['buffer']['buffer_mode'] = hot.get('buffer_mode', 'unknown')
                mc = hot.get('memory_config', {})
                result['buffer']['memory_integration'] = mc.get('integration', 'none')
                result['buffer']['memory_path'] = mc.get('path', None)

                ori = hot.get('orientation', {})
                if ori.get('core_insight'):
                    result['project_context'] = ori['core_insight'][:200]
            except (json.JSONDecodeError, OSError):
                result['buffer']['error'] = 'Failed to read hot layer'

        if warm_path.exists():
            try:
                warm = json.loads(warm_path.read_text(encoding='utf-8'))
                # Detect map type
                has_concept_map = bool(warm.get('concept_map'))
                has_convergence_web = bool(warm.get('convergence_web'))
                has_themes = bool(warm.get('themes'))
                has_entities = bool(warm.get('entities'))

                if has_concept_map:
                    result['buffer']['detected_map_type'] = 'concept_convergence'
                    groups = [k for k, v in warm.get('concept_map', {}).items()
                              if isinstance(v, list)]
                    result['buffer']['concept_map_groups'] = groups
                    total = sum(len(v) for v in warm.get('concept_map', {}).values()
                                if isinstance(v, list))
                    result['buffer']['concept_map_entries'] = total
                    if has_convergence_web:
                        cw = warm.get('convergence_web', {})
                        result['buffer']['convergence_web_entries'] = len(cw.get('entries', []))
                elif has_themes:
                    result['buffer']['detected_map_type'] = 'thematic'
                elif has_entities:
                    result['buffer']['detected_map_type'] = 'narrative'
                else:
                    result['buffer']['detected_map_type'] = 'none'
            except (json.JSONDecodeError, OSError):
                result['buffer']['warm_error'] = 'Failed to read warm layer'
    else:
        result['buffer']['exists'] = False

    # --- Count existing distillations ---
    if distill_dir:
        distill_path = repo / distill_dir
        if distill_path.exists():
            md_files = list(distill_path.glob('*.md'))
            result['counts']['distillations'] = len(md_files)
            result['counts']['distillation_files'] = [
                f.name for f in sorted(md_files)
            ]

    if interp_dir:
        interp_path = repo / interp_dir
        if interp_path.exists():
            md_files = list(interp_path.glob('*.md'))
            result['counts']['interpretations'] = len(md_files)

    # --- Check existing project skill ---
    skill_path = repo / '.claude' / 'skills' / 'distill' / 'SKILL.md'
    result['paths']['project_skill'] = str(skill_path.relative_to(repo)) if skill_path.exists() else None
    readme_path = repo / '.claude' / 'skills' / 'distill' / 'README.md'
    result['paths']['project_readme'] = str(readme_path.relative_to(repo)) if readme_path.exists() else None

    # --- Project context from README ---
    if not result.get('project_context'):
        for readme_name in ['README.md', 'readme.md']:
            readme = repo / readme_name
            if readme.exists():
                try:
                    text = readme.read_text(encoding='utf-8')[:500]
                    # Extract first paragraph
                    paragraphs = text.split('\n\n')
                    for p in paragraphs:
                        p = p.strip()
                        if p and not p.startswith('#') and len(p) > 20:
                            result['project_context'] = p[:200]
                            break
                except OSError:
                    pass
                break

    print(f"Scan complete.", file=sys.stderr)
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: generate-skill
# ---------------------------------------------------------------------------

def cmd_generate_skill(args):
    """Generate project SKILL.md from questionnaire answers."""
    repo = Path(args.repo_dir).resolve()

    # Read configuration
    if args.input:
        config = json.loads(Path(args.input).read_text(encoding='utf-8'))
    else:
        config = json.loads(sys.stdin.read())

    # Extract config fields
    project_name = config.get('project_name', 'Project')
    project_context = config.get('project_context', '')
    map_type = config.get('map_type', 'none')
    framework_name = config.get('framework_name', '')
    distill_mode = config.get('distill_mode', 'comprehensive')
    distill_dir = config.get('distill_dir', 'docs/references/distilled')
    interp_dir = config.get('interpretations_dir', 'docs/references/interpretations')
    index_file = config.get('index_file', 'docs/references/INDEX.md')
    buffer_dir = config.get('buffer_dir', '.claude/buffer')
    memory_path = config.get('memory_path', '')
    grobid_mode = config.get('grobid_mode', False)
    custom_notes = config.get('custom_notes', '')
    tooling_profile = config.get('tooling_profile', {})

    # Description
    desc_map = {
        'concept_convergence': f"Distill source documents for {project_name} with {framework_name} concept convergence mapping.",
        'thematic': f"Distill source documents for {project_name} with {framework_name} thematic tracking.",
        'narrative': f"Distill source documents for {project_name} with {framework_name} narrative tracking.",
        'none': f"Distill source documents for {project_name}.",
        'custom': f"Distill source documents for {project_name} with {framework_name} tracking.",
    }
    description = desc_map.get(map_type, desc_map['none'])

    # Build SKILL.md
    lines = [
        '---',
        'name: distill',
        f'description: "{description}"',
        '---',
        '',
        f'# Source Distillation — {project_name}',
        '',
        f'{project_context}',
        '',
        '## Configuration',
        '',
        f'- **Project context**: {project_context}',
        f'- **Project map type**: {map_type}',
    ]

    if map_type != 'none':
        lines.append(f'- **Integration framework**: {framework_name}')

    lines.extend([
        f'- **Distillation mode**: {distill_mode}',
        f'- **Distillation directory**: {distill_dir}',
        f'- **Figures directory**: {distill_dir}/figures/',
        f'- **Raw text archive**: {distill_dir}/raw/',
    ])

    if map_type != 'none':
        lines.append(f'- **Interpretations directory**: {interp_dir}')

    lines.append(f'- **Index file**: {index_file}')

    if map_type != 'none':
        lines.append(f'- **Handoff buffer**: {buffer_dir}')
        if memory_path:
            lines.append(f'- **Memory file**: {memory_path}')

    lines.append(f'- **GROBID mode**: {"enabled" if grobid_mode else "disabled"}')

    if custom_notes:
        lines.append(f'- **Custom notes**: {custom_notes}')

    # Tooling Profile
    lines.extend([
        '',
        '## Tooling Profile',
        '',
    ])
    for tool_name, status in tooling_profile.items():
        role = next((t['role'] for t in TOOL_CHECKS if t['name'] == tool_name), '')
        role_str = f' ({role})' if role else ''
        lines.append(f'- {tool_name}: {status}{role_str}')

    # Project Terminology Glossary
    lines.extend([
        '',
        '## Project Terminology Glossary',
        '',
        '| Term | Definition | First seen in |',
        '|------|-----------|---------------|',
        '',
    ])

    # Known Issues
    lines.extend([
        '## Known Issues',
        '',
        '(Populated during distillation runs)',
        '',
    ])

    # Write file
    skill_dir = repo / '.claude' / 'skills' / 'distill'
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / 'SKILL.md'
    skill_path.write_text('\n'.join(lines), encoding='utf-8')

    print(f"Generated {skill_path}", file=sys.stderr)
    print(json.dumps({
        'status': 'ok',
        'path': str(skill_path),
        'lines': len(lines),
    }, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: generate-readme
# ---------------------------------------------------------------------------

def cmd_generate_readme(args):
    """Generate project README.md from configuration."""
    repo = Path(args.repo_dir).resolve()

    # Read configuration
    if args.input:
        config = json.loads(Path(args.input).read_text(encoding='utf-8'))
    else:
        config = json.loads(sys.stdin.read())

    project_name = config.get('project_name', 'Project')
    project_context = config.get('project_context', '')
    map_type = config.get('map_type', 'none')
    framework_name = config.get('framework_name', '')
    distill_mode = config.get('distill_mode', 'comprehensive')
    distill_dir = config.get('distill_dir', 'docs/references/distilled')
    interp_dir = config.get('interpretations_dir', 'docs/references/interpretations')
    index_file = config.get('index_file', 'docs/references/INDEX.md')
    tooling_profile = config.get('tooling_profile', {})

    lines = [
        f'# Source Distillation — {project_name}',
        '',
        project_context,
        '',
        '## Setup',
        '',
        f'- **Map type**: {map_type}',
    ]

    if framework_name:
        lines.append(f'- **Framework**: {framework_name}')

    lines.extend([
        f'- **Mode**: {distill_mode}',
        '',
        '## Tools Available',
        '',
        '| Tool | Status | Role |',
        '|------|--------|------|',
    ])

    for tool_name, status in tooling_profile.items():
        role = next((t['role'] for t in TOOL_CHECKS if t['name'] == tool_name), '')
        lines.append(f'| {tool_name} | {status} | {role} |')

    lines.extend([
        '',
        '## Output Locations',
        '',
        f'- Distillations: `{distill_dir}`',
    ])

    if map_type != 'none':
        lines.append(f'- Interpretations: `{interp_dir}`')

    lines.extend([
        f'- Figures: `{distill_dir}/figures/`',
        f'- Index: `{index_file}`',
        '',
        '## Sources Distilled',
        '',
        '(Updated after each distillation)',
        '',
        '| Source Label | Date | Route | Notes |',
        '|-------------|------|-------|-------|',
        '',
        '## Glossary',
        '',
        '(Mirrors the project skill\'s terminology glossary)',
        '',
        '## Configuration',
        '',
        'To change settings, run `/distill` and choose "Re-differentiate."',
        'To install additional specialist tools, they will be offered '
        'automatically when relevant content is detected.',
    ])

    # Write file
    readme_dir = repo / '.claude' / 'skills' / 'distill'
    readme_dir.mkdir(parents=True, exist_ok=True)
    readme_path = readme_dir / 'README.md'
    readme_path.write_text('\n'.join(lines), encoding='utf-8')

    print(f"Generated {readme_path}", file=sys.stderr)
    print(json.dumps({
        'status': 'ok',
        'path': str(readme_path),
        'lines': len(lines),
    }, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Distill skill setup — tooling audit, project scan, skill generation'
    )
    subparsers = parser.add_subparsers(dest='command', help='Subcommand')

    # --- audit-tools ---
    p_audit = subparsers.add_parser('audit-tools',
                                     help='Check installed specialist tools')
    p_audit.set_defaults(func=cmd_audit_tools)

    # --- scan-project ---
    p_scan = subparsers.add_parser('scan-project',
                                    help='Detect project infrastructure')
    p_scan.add_argument('--repo-dir', required=True,
                        help='Path to repository root')
    p_scan.set_defaults(func=cmd_scan_project)

    # --- generate-skill ---
    p_skill = subparsers.add_parser('generate-skill',
                                     help='Generate project SKILL.md')
    p_skill.add_argument('--repo-dir', required=True,
                         help='Path to repository root')
    p_skill.add_argument('--input', default=None,
                         help='Path to config JSON (default: stdin)')
    p_skill.set_defaults(func=cmd_generate_skill)

    # --- generate-readme ---
    p_readme = subparsers.add_parser('generate-readme',
                                      help='Generate project README.md')
    p_readme.add_argument('--repo-dir', required=True,
                          help='Path to repository root')
    p_readme.add_argument('--input', default=None,
                          help='Path to config JSON (default: stdin)')
    p_readme.set_defaults(func=cmd_generate_readme)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
