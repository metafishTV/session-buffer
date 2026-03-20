#!/usr/bin/env python3
"""
Session Buffer — Shared Discovery Utilities

Provides buffer directory discovery for hook scripts (sigma_hook, compact_hook).
Registry-primary lookup with git-guarded walk-up fallback.

Import via importlib (see sigma_hook.py for pattern):
    spec = importlib.util.spec_from_file_location(
        'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
"""

import os
import json


REGISTRY_PATH = os.path.join(os.path.expanduser('~'), '.claude', 'buffer', 'projects.json')


def is_git_repo(path):
    """Check if path is a git repo root (has .git/ directory)."""
    try:
        return os.path.isdir(os.path.join(path, '.git'))
    except (TypeError, OSError):
        return False


def match_cwd_to_project(cwd, repo_root):
    """Check if cwd is inside (or equal to) repo_root.

    Uses os.path.normcase for Windows case-insensitivity.
    Trailing separator guard prevents /proj matching /project-2.
    """
    norm_cwd = os.path.normcase(os.path.abspath(cwd))
    norm_root = os.path.normcase(os.path.abspath(repo_root))
    if norm_cwd == norm_root:
        return True
    return norm_cwd.startswith(norm_root + os.sep)


def _read_json(path):
    """Read JSON file, return dict or None. BOM-safe (utf-8-sig)."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _infer_repo_root(buffer_path):
    """Strip /.claude/buffer or \\.claude\\buffer suffix to get repo root."""
    normalized = buffer_path.replace('\\', '/')
    for suffix in ['/.claude/buffer/', '/.claude/buffer']:
        if normalized.endswith(suffix):
            root = normalized[:-len(suffix)]
            if '\\' in buffer_path:
                return root.replace('/', '\\')
            return root
    # Fallback: warn and return as-is (malformed path)
    import sys as _sys
    print(f"buffer_utils: could not strip .claude/buffer suffix from: {buffer_path}",
          file=_sys.stderr)
    return buffer_path


def read_registry(path=None):
    """Read projects.json, auto-upgrading v1 to v2.

    Preserves all existing fields during upgrade (scope, remote_backup, etc).
    Returns empty v2 registry if file doesn't exist or is corrupt.
    """
    if path is None:
        path = REGISTRY_PATH

    data = _read_json(path)
    if not data or not isinstance(data, dict):
        return {'schema_version': 2, 'projects': {}}

    version = data.get('schema_version', 1)
    projects = data.get('projects', {})

    if version < 2:
        for name, proj in projects.items():
            if 'repo_root' not in proj and 'buffer_path' in proj:
                proj['repo_root'] = _infer_repo_root(proj['buffer_path'])
        data['schema_version'] = 2

    if version > 2:
        import sys as _sys
        print(f"buffer_utils: projects.json schema_version {version} > 2 — some features may not work",
              file=_sys.stderr)

    return data


MODEL_TIER_PATH = os.path.join(os.path.expanduser('~'), '.claude', 'buffer', '.model_tier')

FOOTBALL_REGISTRY_PATH = os.path.join(
    os.path.expanduser('~'), '.claude', 'buffer', 'football-registry.json')


def model_tier_from_name(display_name):
    """Map a model display name to a tier.

    opus -> 'full', sonnet -> 'moderate', haiku -> 'lean', unknown -> 'full'.
    """
    if not display_name:
        return 'full'
    name_lower = display_name.lower()
    if 'opus' in name_lower:
        return 'full'
    elif 'sonnet' in name_lower:
        return 'moderate'
    elif 'haiku' in name_lower:
        return 'lean'
    return 'full'


def write_model_tier(display_name, tier, path=None):
    """Write current model+tier to state file. Called by statusline on every turn."""
    if path is None:
        path = MODEL_TIER_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'model': display_name, 'tier': tier}, f)
    except OSError:
        pass


def read_model_tier(path=None):
    """Read model+tier from state file. Returns (model_name, tier).

    Fail-safe: returns ('unknown', 'full') on any error.
    """
    if path is None:
        path = MODEL_TIER_PATH
    data = _read_json(path)
    if data and 'tier' in data:
        return (data.get('model', 'unknown'), data.get('tier', 'full'))
    return ('unknown', 'full')


def read_football_registry(path=None):
    """Read global football registry. Returns dict with 'balls' key, or empty."""
    if path is None:
        path = FOOTBALL_REGISTRY_PATH
    data = _read_json(path)
    if not data or not isinstance(data, dict):
        return {'balls': {}}
    return data


def find_buffer_dir(cwd, registry_path=None):
    """Find the buffer directory for the given working directory.

    Two-tier lookup:
    1. Registry lookup: check projects.json for a project whose repo_root
       contains cwd. If match found and buffer_path exists on disk, return it.
    2. Walk-up fallback: walk up from cwd looking for .claude/buffer/handoff.json,
       but ONLY accept if the containing directory is a git repo (.git exists).

    Returns absolute path to buffer dir, or None.
    """
    if registry_path is None:
        registry_path = REGISTRY_PATH

    # Tier 1: Registry lookup
    registry = read_registry(registry_path)
    for _name, proj in registry.get('projects', {}).items():
        repo_root = proj.get('repo_root', '')
        buffer_path = proj.get('buffer_path', '')
        # Infer repo_root from buffer_path if missing
        if not repo_root and buffer_path:
            repo_root = _infer_repo_root(buffer_path)
        if repo_root and (match_cwd_to_project(cwd, repo_root)
                          or match_cwd_to_project(repo_root, cwd)):
            if os.path.isdir(buffer_path) and os.path.isfile(
                    os.path.join(buffer_path, 'handoff.json')):
                return buffer_path

    # Tier 2: Walk-up with git guard
    current = os.path.abspath(cwd)
    while True:
        candidate = os.path.join(current, '.claude', 'buffer', 'handoff.json')
        if os.path.exists(candidate):
            if is_git_repo(current):
                return os.path.join(current, '.claude', 'buffer')
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
