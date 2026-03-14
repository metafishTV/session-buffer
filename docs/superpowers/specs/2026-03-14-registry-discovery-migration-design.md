# Registry-Primary Discovery & Buffer Migration

**Date**: 2026-03-14
**Status**: Design approved, pending implementation planning
**Scope**: Plugin discovery flow, hook buffer lookup, sigma-TAP migration

## Problem

The buffer plugin's discovery mechanism is broken when the working directory is a parent folder containing git repos as subdirectories:

1. `find_buffer_dir()` in hooks walks UP from cwd — never finds buffers in child repos
2. SKILL.md Step 0a assumes cwd is a git repo — fails when it isn't
3. Buffers can accidentally be created in non-git parent directories (as happened with `New folder/.claude/buffer/`)
4. `projects.json` (v1) lacks `repo_root`, so hooks can't match cwd to projects

The canonical buffer for sigma-TAP ended up in `New folder/.claude/buffer/` instead of `sigma-TAP-repo/.claude/buffer/` — where any normal plugin user's project buffer would live.

## Design Principle

The plugin generates project-level structures inside the user's project repos. A project's `.claude/buffer/` is owned by the project, backed by git (optional — user chooses during first-run setup), and discovered by the plugin via a global registry. The plugin does not store project data — it stores pointers to project data.

## Architecture: Two-Tier Discovery

### Tier 1: Hooks (sigma_hook, compact_hook)

Fire on every user prompt. Must complete in <5 seconds. No exploratory I/O.

**New `find_buffer_dir()` logic:**

```
1. Registry lookup (primary)
   - Read ~/.claude/buffer/projects.json
   - For each project: check if cwd starts with or equals repo_root
   - If match found AND buffer_path exists on disk → return buffer_path

2. Walk-up safety net (fallback)
   - Walk up from cwd looking for .claude/buffer/handoff.json
   - GUARD: only accept if the directory containing .claude/buffer/
     ALSO has a .git/ directory (is a git repo)
   - This prevents buffers in non-git parent dirs from being discovered

3. No match → return None (silent exit, zero output)
```

The git-repo guard on the walk-up ensures that accidental buffers in workspace parent folders are never found by hooks. Only buffers inside git repos qualify via the fallback path.

**Shared utility question**: Both `sigma_hook.py` and `compact_hook.py` have independent `find_buffer_dir()` implementations. Two options:
- Factor into a shared module (e.g., `buffer_utils.py`) imported by both
- Duplicate the logic in both files (they're standalone scripts, imports add fragility)

Recommendation: Factor into `buffer_utils.py`. The logic is identical and non-trivial enough that divergence would be a maintenance risk. Both scripts already import other modules.

### Tier 2: SKILL.md Step 0 (session startup)

Runs once per `/buffer:on`. Has time for smart discovery and user interaction.

**New Step 0 flow:**

```
Step 0a: Locate project context

1. Try `git rev-parse --show-toplevel` from cwd
   → If success: cwd is inside a git repo. Check for .claude/buffer/ there.

2. If cwd is NOT a git repo:
   → Scan immediate children (one level deep) for directories containing .git/
   → For each git-repo child, score:
     - Has .claude/buffer/handoff.json:  +1.0  (existing buffer)
     - Has .git/:                        +0.5  (is a git repo)
     - Matches a projects.json entry:    +0.3  (previously registered)
   → Sort by score descending

3. Also check projects.json for entries whose repo_root is under cwd
   → Merge with filesystem results, deduplicate

Step 0b: Check for project skill (MOVED from old 0a)
   → Now runs AFTER project selection, not before
   → Check <selected_repo>/.claude/skills/buffer/on.md
   → If exists: read and follow instead

Step 0c: Present options via AskUserQuestion
   → If exactly one result with score >= 1.0: offer as recommended
   → If multiple results with score >= 1.0: present ranked list (score descending), top entry pre-selected
   → Always include "Start new project" and "Start lite session"
   → If zero results: proceed to first-run setup (0d)

Step 0d: First-run setup (existing, minor changes)
   → Buffer is created inside the git repo's .claude/buffer/ (not cwd if cwd isn't a git repo)
   → If no git repo found at all, create in cwd (lite users without git)
   → Register in projects.json v2
```

## projects.json Schema v2

```json
{
  "schema_version": 2,
  "projects": {
    "[project-name]": {
      "repo_root": "[absolute path to git repo root]",
      "buffer_path": "[absolute path to .claude/buffer/]",
      "scope": "full | lite",
      "last_handoff": "YYYY-MM-DD",
      "project_context": "[one-sentence description]"
    }
  }
}
```

**Changes from v1:**
- `schema_version`: 1 → 2
- Added `repo_root`: the git repo root. Hooks use this for cwd matching.
- `buffer_path` is always `<repo_root>/.claude/buffer` for git-backed projects
- For lite/non-git buffers, `repo_root` equals the working directory

**v1 → v2 migration**: When reading a v1 registry, infer `repo_root` by stripping `/.claude/buffer` (or `\.claude\buffer` on Windows) from `buffer_path`. Carry through all existing fields (`scope`, `remote_backup`, `project_context`, `last_handoff`) — do not drop them. Write back as v2. Non-breaking, automatic.

**Hook matching logic**: For each project, normalize both paths with `os.path.normcase(os.path.abspath(...))` (handles Windows drive letter casing), then check if `normalized_cwd == normalized_repo_root` or `normalized_cwd.startswith(normalized_repo_root + os.sep)`. The trailing separator guard prevents false matches (e.g., `repo_root=/proj` matching `cwd=/project-2`). This handles:
- cwd IS the repo root → match (equality check)
- cwd is a subdirectory of the repo → match (startswith + sep)
- cwd is a parent of the repo → no match (correct — parent dirs don't inherit)

## SKILL.md Changes

### skills/on/SKILL.md

- Step 0a-0c: Rewritten per the discovery flow above
- Project-skill check moves from 0a to 0b (after selection)
- Step 0d: Buffer creation targets the git repo, not cwd (when they differ)
- Step 0e: Updated to write v2 schema with `repo_root`

### skills/off/SKILL.md

- At the commit/registry-update step (Step 12): replace the v1 schema example with v2:
  ```json
  {
    "schema_version": 2,
    "projects": {
      "[project-name]": {
        "repo_root": "[git rev-parse --show-toplevel output]",
        "buffer_path": "[repo_root]/.claude/buffer",
        "scope": "full | lite",
        "last_handoff": "YYYY-MM-DD",
        "project_context": "[one-sentence description]"
      }
    }
  }
  ```
- Use `git rev-parse --show-toplevel` to get the repo root dynamically
- Note: Quicksave and Targeted modes skip Step 12 — this is acceptable as pre-existing behavior

### skills/status/SKILL.md

- No functional changes needed. Status reads from wherever the buffer is.

## Script Changes

### sigma_hook.py

- Replace `find_buffer_dir()` with registry-primary + git-guarded walk-up
- Add `read_registry()` helper
- Add v1→v2 auto-upgrade on read

### compact_hook.py

- Same `find_buffer_dir()` rewrite
- Import from shared `buffer_utils.py` or duplicate

### buffer_utils.py (NEW)

Shared utilities for hook scripts. Lives in `scripts/buffer_utils.py` alongside the hook scripts.

Import mechanism: Both hooks already manipulate `sys.path` for cross-imports (compact_hook imports from sigma_hook via `importlib`). Use the same pattern: `buffer_utils.py` is imported via `importlib.util.spec_from_file_location` using `__file__`-relative path resolution. This avoids needing `sys.path` modification and works when hooks are invoked as standalone scripts by the Claude Code hook system.

Functions:
- `find_buffer_dir(cwd)` — registry-primary + git-guarded walk-up
- `read_registry()` — read and auto-upgrade projects.json (preserves all existing fields during v1→v2 upgrade)
- `is_git_repo(path)` — check for .git directory
- `match_cwd_to_project(cwd, repo_root)` — normalized path comparison with trailing-sep guard

### buffer_manager.py

- No changes needed. It takes `--buffer-dir` as an explicit argument.

## Migration: sigma-TAP (One-Time)

### Pre-conditions
- `New folder/.claude/buffer/` has current state (hot layer: "implemented, awaiting live test")
- `sigma-TAP-repo/.claude/buffer/` has stale state (hot layer: "spec complete, ready for implementation")
- Alpha directories should be identical or very close

### Steps

1. **Copy current-state files** from `New folder/.claude/buffer/` to `sigma-TAP-repo/.claude/buffer/`:
   - `handoff.json` (overwrite stale)
   - `handoff-warm.json` (overwrite stale)
   - `handoff-cold.json` (overwrite stale)
   - `briefing.md` (overwrite stale)
   - `compact-directives.md` (new, created this session)
   - `_changes.json` (if not present in target)
   - `handoff-v1-archive.json` (if not present in target)
   - Do NOT copy `.buffer_loaded` — ephemeral session marker, regenerated by next `/buffer:on`

2. **Copy entire alpha directory tree**: Copy the full `alpha/` directory (all subdirectories and `w:NNN.md`/`cw:NNN.md` referent files) from `New folder/.claude/buffer/alpha/` to `sigma-TAP-repo/.claude/buffer/alpha/`, overwriting any stale files. The index alone is useless without the referent files it points to. Use the `New folder/` copy as canonical since it's from the more recent session.

3. **Copy auxiliary files** (take newer version):
   - `.buffer_trajectory`
   - `.cw_adjacency`
   - `.resolution_queue`
   - `.sigma_hits`
   - `relevance_grid.json`

4. **Move CLAUDE.md** from `New folder/CLAUDE.md` to `sigma-TAP-repo/CLAUDE.md`. If `sigma-TAP-repo/CLAUDE.md` already exists, merge the `## Compaction Guidance` section into it rather than overwriting.

5. **Update projects.json** to v2:
   ```json
   {
     "schema_version": 2,
     "projects": {
       "sigma-TAP": {
         "repo_root": "C:/Users/user/Documents/New folder/sigma-TAP-repo",
         "buffer_path": "C:/Users/user/Documents/New folder/sigma-TAP-repo/.claude/buffer",
         "scope": "full",
         "last_handoff": "2026-03-14",
         "project_context": "sigma-TAP models PRAXIS via the L-matrix..."
       }
     }
   }
   ```

6. **Remove** `New folder/.claude/buffer/` directory entirely

7. **Remove** `New folder/CLAUDE.md`

8. **Commit** in sigma-TAP-repo with message describing the migration

### Post-migration verification
- `projects.json` points to sigma-TAP-repo
- `sigma-TAP-repo/.claude/buffer/handoff.json` has current phase
- `New folder/.claude/buffer/` does not exist
- No CLAUDE.md in `New folder/`

## Testing

### New tests needed

1. **`find_buffer_dir` with registry** — registry match returns correct path
2. **`find_buffer_dir` with git guard** — walk-up finds buffer in git repo → accepted
3. **`find_buffer_dir` git guard rejection** — walk-up finds buffer in non-git dir → rejected, returns None
4. **Registry v1→v2 migration** — reads v1, infers repo_root, writes v2
5. **cwd matching** — cwd inside repo → match; cwd is parent of repo → no match; cwd is unrelated → no match
6. **Windows path normalization** — `C:\Users` vs `c:\Users` both match; `/proj` doesn't false-match `/project-2`
7. **v1→v2 preserves extra fields** — `scope`, `remote_backup` survive the upgrade

### Existing tests to update

- Any tests that mock `find_buffer_dir` or assume walk-up-only behavior
- `test_compact_hook.py` tests that set up buffer dirs without `.git`

## Out of Scope

- Loose files in `New folder/` (sigma_tap*.py, PNGs, notebooks, TAPS.md)
- Renaming `New folder/`
- sigma-TAP simulation work
- Layer 2-5 compaction directives
- Any distill plugin changes
