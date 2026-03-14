"""Shared fixtures for memory-tools test suite."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add plugin/scripts to sys.path so we can import the modules
SCRIPTS_DIR = Path(__file__).parent.parent / 'plugin' / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Add schemas/ to sys.path for shared normalize/validate imports
SCHEMAS_DIR = Path(__file__).parent.parent / 'schemas'
if str(SCHEMAS_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEMAS_DIR))

FIXTURES_DIR = Path(__file__).parent / 'fixtures'


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file by name."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))


@pytest.fixture
def hot_minimal():
    """Minimal hot layer (lite mode)."""
    return load_fixture('hot_minimal.json')


@pytest.fixture
def hot_full():
    """Full mode hot layer with digests."""
    return load_fixture('hot_full.json')


@pytest.fixture
def warm_full():
    """Warm layer with concept_map, convergence_web, decisions_archive."""
    return load_fixture('warm_full.json')


@pytest.fixture
def cold_full():
    """Cold layer with archived decisions, superseded mappings, dialogue trace."""
    return load_fixture('cold_full.json')


@pytest.fixture
def alpha_index():
    """Sample alpha bin index."""
    return load_fixture('alpha_index.json')


@pytest.fixture
def buffer_dir(tmp_path, hot_minimal):
    """Create a minimal buffer directory with hot layer only."""
    buf = tmp_path / '.claude' / 'buffer'
    buf.mkdir(parents=True)
    (buf / 'handoff.json').write_text(
        json.dumps(hot_minimal, indent=2, ensure_ascii=False), encoding='utf-8')
    return buf


@pytest.fixture
def full_buffer_dir(tmp_path, hot_full, warm_full, cold_full, alpha_index):
    """Create a complete buffer directory with all layers + alpha bin."""
    buf = tmp_path / '.claude' / 'buffer'
    buf.mkdir(parents=True)

    # Write all layers
    (buf / 'handoff.json').write_text(
        json.dumps(hot_full, indent=2, ensure_ascii=False), encoding='utf-8')
    (buf / 'handoff-warm.json').write_text(
        json.dumps(warm_full, indent=2, ensure_ascii=False), encoding='utf-8')
    (buf / 'handoff-cold.json').write_text(
        json.dumps(cold_full, indent=2, ensure_ascii=False), encoding='utf-8')

    # Write alpha bin
    alpha_dir = buf / 'alpha'
    alpha_dir.mkdir()
    (alpha_dir / 'index.json').write_text(
        json.dumps(alpha_index, indent=2, ensure_ascii=False), encoding='utf-8')

    # Create sample alpha .md files
    sartre_dir = alpha_dir / 'sartre-early'
    sartre_dir.mkdir()
    (sartre_dir / 'w044.md').write_text(
        '# w:44 -- Sartre:totalization\n**ID**: w:44 | **Type**: cross_source\n',
        encoding='utf-8')
    (sartre_dir / 'w045.md').write_text(
        '# w:45 -- Sartre:praxis\n**ID**: w:45 | **Type**: cross_source\n',
        encoding='utf-8')
    (sartre_dir / 'cw001.md').write_text(
        '# cw:1 -- totalization x praxis\n**ID**: cw:1 | **Type**: convergence_web\n',
        encoding='utf-8')

    return buf


@pytest.fixture
def minimal_args(buffer_dir):
    """SimpleNamespace mimicking argparse for minimal buffer."""
    return SimpleNamespace(
        buffer_dir=str(buffer_dir),
        hot_max=None,
        warm_max=None,
        cold_max=None,
    )


@pytest.fixture
def full_args(full_buffer_dir):
    """SimpleNamespace mimicking argparse for full buffer."""
    return SimpleNamespace(
        buffer_dir=str(full_buffer_dir),
        hot_max=None,
        warm_max=None,
        cold_max=None,
    )


@pytest.fixture
def buffer_dir_with_directives(buffer_dir):
    """Buffer directory with a compact-directives.md file."""
    directives = buffer_dir / 'compact-directives.md'
    directives.write_text(
        "# Compaction Directives\n\n"
        "## On Disk\n"
        "- Sigma trunk: .claude/buffer/handoff.json\n"
        "- Alpha bin: .claude/buffer/alpha/\n\n"
        "## Active Threads\n"
        "- Layer 1 implementation (compact_hook.py)\n"
        "- PostCompact hook wiring (hooks.json)\n\n"
        "## Already Persisted\n"
        "- Session state saved in handoff.json\n\n"
        "## Session Vocabulary\n"
        "- placenta: living connective tissue between plugin and LLM\n"
        "- headroom: remaining context capacity before compaction\n",
        encoding='utf-8'
    )
    return buffer_dir
