# Buffer System

Session continuity for multi-instance projects. Two operations:

- **`/buffer:on`** — Reconstruct context from previous session's handoff buffer. Run at session start.
- **`/buffer:off`** — Write structured handoff buffer for the next instance. Run at session end.

The **alpha stash** is the ephemeral session intake — computed, merged into the trunk, then gone. The **sigma trunk** is the persistent knowledge: hot (always loaded), warm (selectively loaded), cold (on-demand only).

Both operations reference the architecture defined here. Each checks for a project-level override at `<repo>/.claude/skills/buffer/` before running the global process.

---

## Sigma Trunk Architecture

Sigma trunk (hot / warm / cold) with bounded sizes and downward migration:

| Layer | File | Max Lines | Loaded At `/buffer:on` |
|-------|------|-----------|------------------------|
| **Hot** | `handoff.json` | 200 | Always |
| **Warm** | `handoff-warm.json` | 500 | Selectively (via pointers) |
| **Cold** | `handoff-cold.json` | 500 | On-demand only |
| **Tower** | `handoff-tower-NNN-YYYY-MM-DD.json` | Sealed | Never auto-read |

All files live in `.claude/buffer/`.

Content migrates downward (hot -> warm -> cold -> tower) when bounds are exceeded. `/buffer:on` reads upward selectively (hot always, warm/cold only when pointed to). The system conserves attention by never auto-loading more than ~200 lines.

### Pointer-Index System

Hot-layer entries contain `"see"` arrays pointing to warm-layer entries by stable ID:

```json
{
  "thread": "Feature design for X",
  "status": "noted",
  "see": ["w:34", "w:35"]
}
```

Warm-layer entries may contain `"see_also"` arrays pointing to cold:

```json
{
  "id": "w:34",
  "key": "some-concept",
  "maps_to": "project.mapping",
  "see_also": ["c:7"]
}
```

**Redirect tombstones:** When resolving a `"see"` pointer (e.g., `w:78`), the target entry may be a redirect tombstone rather than a full entry. This occurs when warm entries migrate to cold during conservation enforcement. If the resolved entry contains a `"migrated_to"` field, follow the redirect to the cold layer and load the target `c:N` entry instead.

**Tower boundary (hard rule):** If a chain resolves to a tombstone with `"archived_to"`, the entry lives in a sealed tower file. **NEVER silently read tower files.** Always ask the user: "Entry [id] was archived to [tower file]. Want me to retrieve it?" Tower files are sealed for a reason — they were explicitly archived with user consent. Reading them without asking violates that consent.

---

## Buffer Modes

The buffer system operates in one of two modes, chosen during first-run setup (Step 0d in `/buffer:on`). The mode determines which schema fields, layers, and processes are active.

| Mode | Purpose | Hot Layer | Warm/Cold | `/buffer:off` Steps |
|------|---------|-----------|-----------|---------------------|
| **Lite** | Active work + natural summary | `session_meta`, `natural_summary`, `memory_config`, `active_work`, `open_threads`, `recent_decisions`, `instance_notes` | Session summaries, `decisions_archive` | Subset (no concept map, no consolidation) |
| **Full** | Complete research infrastructure | Full schema | Full schema | All |

The mode is stored in the hot layer as `buffer_mode` and persists across sessions. To change modes, the user must explicitly request it.

### Lite Mode

Hot and warm layers for active work, decisions, threads, instance notes, and natural summary. No concept maps, no convergence webs, no provenance-aware consolidation. Cold layer exists but only for decisions archive overflow.

**Lite hot layer:**
```json
{
  "schema_version": 2,
  "buffer_mode": "lite",
  "scope": "lite | full",
  "remote_backup": false,

  "session_meta": {
    "date": "YYYY-MM-DD",
    "commit": "abc1234",
    "branch": "main"
  },

  "orientation": {
    "core_insight": "One sentence. What this project IS and what it DOES. No filler.",
    "practical_warning": "What the AI must NOT do. State as imperative: 'Do NOT [action].' Specific, not general."
  },

  "active_work": {
    "current_phase": "Description of current project phase",
    "completed_this_session": ["item1", "item2"],
    "in_progress": "Current work item",
    "blocked_by": null,
    "next_action": "Recommended next step"
  },

  "open_threads": [
    {
      "thread": "Description of unresolved item",
      "status": "noted",
      "see": ["w:N"]
    }
  ],

  "recent_decisions": [
    {
      "what": "What was decided",
      "chose": "What was chosen",
      "why": "Brief rationale",
      "session": "YYYY-MM-DD"
    }
  ],

  "instance_notes": {
    "from": "instance-N",
    "to": "instance-N+1",
    "remarks": "Free-form observations and warnings for the next instance.",
    "open_questions": ["Question that was never raised during the session"]
  },

  "memory_config": {
    "integration": "full | minimal | none",
    "path": "resolved path to MEMORY.md or null"
  },

  "natural_summary": "Plain-language session summary."
}
```

**Lite warm layer:**
```json
{
  "session_summaries": [
    { "id": "w:N", "date": "YYYY-MM-DD", "summary": "What happened." }
  ],
  "decisions_archive": [
    {
      "id": "w:N",
      "what": "What was decided",
      "chose": "What was chosen",
      "why": "Brief rationale",
      "session": "YYYY-MM-DD"
    }
  ]
}
```

**Lite cold layer:**
```json
{
  "archived_summaries": [
    { "id": "c:N", "date": "YYYY-MM-DD", "summary": "Compressed older summary." }
  ],
  "archived_decisions": [
    {
      "id": "c:N",
      "what": "What was decided",
      "chose": "What was chosen",
      "why": "Brief rationale",
      "session": "YYYY-MM-DD"
    }
  ]
}
```

**Lite conservation:** When warm exceeds 500 lines, compress the oldest 30% by merging adjacent summaries into combined entries ("Sessions [date]–[date]: [merged summary]"), then migrate the compressed batch to cold. When cold exceeds 500 lines, trigger tower archival as normal.

### Full Mode

The complete system. All schemas, all processes, all consolidation protocols as defined in this document. Concept maps, convergence webs, conservation, tower archival, provenance-aware consolidation.

---

## Configurable Thresholds

| Parameter | Default | Description |
|-----------|---------|-------------|
| Hot max lines | 200 | Triggers migration to warm |
| Warm max lines | 500 | Triggers migration to cold |
| Cold max lines | 500 | Triggers archival questionnaire |
| `full_scan_threshold` | 5 | Sessions before prompting full rescan + consolidation review |

---

## Provenance-Aware Consolidation Protocol

> **Mode gate: Full only.** Lite mode skips this protocol entirely.

Triggers at `full_scan_threshold` intervals during `/buffer:off`. Purpose: increase warm-layer density without losing meaning. This protocol supplements the routine warm consolidation (Step 6b of `/buffer:off`) that runs every session.

### Provenance Classification

At handoff time, the instance classifies every warm-layer entry:

- **Self-integrated**: Created or meaningfully modified by this instance during this session. The instance has full source context and high confidence in the entry's meaning.
- **Inherited**: Everything else. The instance knows these only from their descriptions. Confidence in structural nuances is lower.

### Self-Integrated Consolidation (automated)

For entries this instance created or modified this session:

1. **Vocabulary compression**: Replace multi-word descriptions with established terms from the concept_map
2. **Same-concept merge**: If two self-integrated entries describe the same structural relationship, merge (keep richer formulation, absorb unique content, leave redirect tombstone)
3. **Description tightening**: Shorten explanatory prose to referential shorthand

No user prompt needed — the instance has full context from the source material.

### Inherited Consolidation (user-supervised)

For inherited entries, the instance identifies candidates but does NOT auto-modify. Present proposals to the user:

```
These inherited entries may benefit from consolidation:

1. w:42 and w:78 describe [X] from different source angles. Merge?
   [show both entries]

2. w:55 says "[long phrase]" — already defined as "[term]" (w:12). Compress?
   [show current vs proposed]

3. w:91 unchanged 5+ sessions, never pointer-loaded. Migrate to cold?

Approve all / Skip all / Review one by one?
```

### Guard Rails

- **Maximum 7 proposals per cycle** — avoid decision fatigue
- **Quality bar**: "Does this make the warm layer more navigable or more precise?" If the answer is just "shorter," don't propose it
- Never auto-consolidate inherited entries
- Never consolidate across concept_map groups (group boundaries are structural)
- Never touch base-system entries without `NEEDS_USER_INPUT` flag
- When in doubt, don't propose — missed consolidations cost tokens, false merges lose meaning

---

## Hot Layer Schema

```json
{
  "schema_version": 2,
  "buffer_mode": "lite | full",
  "scope": "lite | full",
  "remote_backup": false,

  "session_meta": {
    "date": "YYYY-MM-DD",
    "commit": "abc1234",
    "branch": "main",
    "files_modified": ["file1.py", "file2.py"],
    "tests": "N passed, M failed"
  },

  "sessions_since_full_scan": 0,
  "full_scan_threshold": 5,

  "orientation": {
    "core_insight": "One sentence. What this project IS and what it DOES. No filler.",
    "practical_warning": "What the AI must NOT do. State as imperative: 'Do NOT [action].' Specific, not general."
  },

  "active_work": {
    "current_phase": "Description of current project phase",
    "completed_this_session": ["item1", "item2"],
    "in_progress": "Current work item",
    "blocked_by": null,
    "next_action": "Recommended next step"
  },

  "open_threads": [
    {
      "thread": "Description of unresolved item",
      "status": "noted",
      "ref": "optional/reference",
      "see": ["w:N"]
    }
  ],

  "recent_decisions": [
    {
      "what": "What was decided",
      "chose": "What was chosen",
      "why": "Brief rationale",
      "session": "YYYY-MM-DD",
      "see": ["w:N"]
    }
  ],

  "instance_notes": {
    "from": "instance-N",
    "to": "instance-N+1",
    "remarks": "Free-form observations and warnings for the next instance.",
    "open_questions": ["Question that was never raised during the session"]
  },

  "concept_map_digest": {
    "_meta": {
      "total_entries": 0,
      "last_validated": "YYYY-MM-DD"
    },
    "recent_changes": [
      { "id": "w:N", "status": "NEW", "summary": "Brief description of change" }
    ],
    "flagged": ["w:N"]
  },

  "memory_config": {
    "integration": "full | minimal | none",
    "path": "resolved path to MEMORY.md or null"
  },

  "natural_summary": "Two to three plain-language sentences summarizing the current project state, what happened this session, and what comes next."
}
```

> `concept_map_digest` is **Full only**. Lite mode omits this field entirely.

### Hot Layer Size Constraints

The hot layer is **referential, not explanatory**. If a concept needs explaining, it belongs in warm. These per-field limits keep the hot layer lean while preserving full fidelity:

| Field | Limit | Rule |
|-------|-------|------|
| `orientation.core_insight` | ≤50 words | Referential. Define the project's irreducible identity. |
| `orientation.practical_warning` | ≤30 words | One sentence. The single most important gotcha. |
| `orientation` sub-fields | ≤15 words each | Structural role of each entry, not exposition. |
| `active_work.completed_this_session` | ≤8 entries | Name the deliverable, not the process. |
| `active_work.next_action` | ≤25 words | One sentence. Concrete. |
| `open_threads` | ≤5 entries | `thread` ≤25 words. Omit empty `see` arrays. |
| `recent_decisions` | ≤4 entries | `what` ≤8 words, `chose` ≤15 words, `why` ≤10 words. `session` optional (inherits from `session_meta.date`). Omit empty `see`. |
| `instance_notes.remarks` | ≤7 entries | Each ≤20 words. Actionable warnings, not narratives. |
| `instance_notes.open_questions` | ≤5 entries | Each ≤20 words. |
| `concept_map_digest.recent_changes` | ≤15 entries | Full only. Oldest roll off when exceeded. |
| `natural_summary` | ≤3 sentences | Plain language. No jargon, no codex. |

**Enforcement**: At `/buffer:off` Step 10, check each field against these limits before writing. If any field exceeds its limit, compress in place — do not silently drop content. Use the warm concept_map as a glossary: replace multi-word explanations with established terms.

**Principle**: Hot = what the next instance needs in the first 30 seconds. Everything else lives in warm or cold.

---

## Warm Layer Schema

```json
{
  "concept_map": {
    "<group_name>": [
      {
        "id": "w:N",
        "term": "Concept name",
        "equiv": "Established equivalence or mapping",
        "suggest": null
      }
    ]
  },

  "decisions_archive": [
    {
      "id": "w:N",
      "what": "What was decided",
      "chose": "What was chosen",
      "why": "Brief rationale",
      "session": "YYYY-MM-DD"
    }
  ],

  "validation_log": [
    {
      "id": "w:N",
      "check": "What was validated",
      "status": "NEW | CHANGED | PROMOTED | CONSOLIDATED | NEEDS_USER_INPUT | PASS",
      "detail": "Description of validation result",
      "session": "YYYY-MM-DD"
    }
  ]
}
```

The concept_map uses named groups relevant to the project. Group names are user-defined via the project-level skill override, or established during the first Full-mode handoff. Each group is an array of concept entries.

Example groups: "core_concepts", "cross_references", "external_mappings"

> `concept_map` and `validation_log` are **Full only**. Lite mode uses only `decisions_archive` (and `session_summaries`).

**Cross-source entries** use `key` (format: `Source:ConceptName`) and `maps_to` instead of `term` and `equiv`. They may also include `ref` for forward note references and `see_also` for cold-layer pointers.

---

## Cold Layer Schema

```json
{
  "dialogue_trace": {
    "sessions": [
      {
        "id": "c:N",
        "session": "YYYY-MM-DD brief-description",
        "arc": "One to two sentences describing the overall shape of the conversation.",
        "key_moments": ["Specific moment where something important happened"]
      }
    ],
    "recurring_patterns": [
      "Pattern observed across multiple sessions"
    ]
  },

  "superseded_mappings": [
    {
      "id": "c:N",
      "original": "Previous mapping",
      "replaced_by": "w:N",
      "reason": "Why it was superseded",
      "session": "YYYY-MM-DD"
    }
  ],

  "archived_decisions": [
    {
      "id": "c:N",
      "what": "What was decided",
      "chose": "What was chosen",
      "why": "Brief rationale",
      "session": "YYYY-MM-DD"
    }
  ]
}
```

> `dialogue_trace` and `superseded_mappings` are **Full only**. Lite mode cold layer contains only `archived_summaries` and `archived_decisions`.

---

## ID Assignment

- Warm entries: `w:N` (e.g., `w:1`, `w:34`, `w:77`)
- Cold entries: `c:N` (e.g., `c:1`, `c:20`)
- Tower tombstones reference tower files by name: `"archived_to": "tower-001"`

Tower numbers are zero-padded to 3 digits (e.g., `001`, `002`). Determine the next number by listing existing tower files in `.claude/buffer/` and incrementing the highest.

**Rules:**
- IDs are **never reused**. If `w:34` is deleted, the next warm entry gets the next available number.
- IDs are **stable across sessions**. An entry keeps its ID for its lifetime.
- New IDs are assigned by reading the current max ID in that layer and incrementing.
- The `concept_map_digest._meta.total_entries` in hot tracks the count for quick reference (Full only).

---

## Script References

Buffer management is handled by the plugin's `scripts/buffer_manager.py`. Compaction is handled by `scripts/compact_hook.py`. Both live alongside this architecture document in the plugin directory tree.

---

## Cumulative Sections

These sections grow over time. Append new entries; never delete previous ones (migration moves them to a lower layer, it does not delete them):

- `decisions_archive` (warm) — Both modes
- `validation_log` (warm) — Full only
- `dialogue_trace.sessions` (cold) — Full only
- `dialogue_trace.recurring_patterns` (cold) — Full only
- `superseded_mappings` (cold) — Full only
- `archived_decisions` (cold) — Both modes
- `concept_map` entries (warm) — Full only; preserve all entries, only modify entries that changed

---

## Replace-Each-Session Sections

These sections are written fresh at each handoff:

- `session_meta` (hot) — current session only
- `active_work` (hot) — current state only
- `open_threads` (hot) — current statuses (resolved threads migrate to warm)
- `recent_decisions` (hot) — this session's decisions only (older ones migrate to warm archive)
- `instance_notes` (hot) — personal to the outgoing instance, replaced each time
- `natural_summary` (hot) — regenerated from current state
- `concept_map_digest` (hot) — Full only; regenerated from current warm layer state
