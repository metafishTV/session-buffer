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
