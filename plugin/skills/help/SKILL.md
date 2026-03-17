---
description: Show buffer plugin reference — available skills, current mode, and configuration options. Use when the user asks for help, guidance, or wants to know what they can do.
---

# Buffer Help

Display a mode-aware reference card. Read state silently, then present the output.

## Step 1: Detect current state

Read `.claude/buffer/buffer.config.yaml` (if it exists) to get `mode` (lite/full).
Read `.claude/buffer/handoff.json` (if it exists) to check if buffer is initialized.
Check if a git remote is configured in the current repo.

Set:
- `mode` = "full" | "lite" | "not configured"
- `has_remote` = true | false
- `initialized` = true | false

## Step 2: Present the reference card

Output the following block. Adapt sections marked with conditionals based on detected state.

```
Buffer Plugin Reference
===

Current mode: [full | lite | not configured]
Remote backup: [enabled | not configured]

SKILLS
------
/buffer:on      Reconstruct context at session start. Loads your sigma trunk
                (decisions, threads, concepts) so this instance knows what
                the last one knew.

/buffer:off     Write handoff at session end. Captures everything worth
                preserving — current phase, open threads, decisions made,
                instance observations. Three modes:
                  totalize   full handoff (default)
                  quicksave  fast checkpoint, minimal processing
                  targeted   update specific sections only

/buffer:status  Session health check. Shows context usage, buffer state,
                session depth, and active markers. Quick diagnostic.

/buffer:throw   Delegate a task to a parallel session. Packs context into
                a "football" that another instance can catch. Two weights:
                  heavy  full context + dialogue style
                  lite   task description only

/buffer:catch   Receive a thrown football. Initializes a worker session
                from the packed context, or absorbs worker results back
                into the main trunk.

/buffer:help    This reference card.
```

If `mode` is "lite", append:

```
AVAILABLE UPGRADES
------------------
You're running in lite mode. These features are available if you switch
to full mode:
  - Concept maps with cross-source linking
  - Convergence webs tracking idea evolution
  - Conservation laws (concept persistence tracking)
  - Tower archival (cold storage with retrieval)
  - Alpha bin (reference memory from distilled sources)

To upgrade: tell Claude "upgrade my buffer to full mode" — it will
migrate your existing data and enable the additional layers.
```

If `has_remote` is false, append:

```
REMOTE BACKUP
-------------
Your buffer is local-only. To add git backup:
  1. Initialize git if needed: git init
  2. Create a remote: gh repo create <name> --private
  3. Tell Claude "enable remote backup for my buffer"

Backup pushes automatically after each /buffer:off handoff.
```

If `initialized` is false, append:

```
GETTING STARTED
---------------
Your buffer isn't set up yet. Run /buffer:on to start the setup process.
It takes about a minute and walks you through choosing a mode and
optional remote backup.
```

Then always append:

```
TIPS
----
- Run /buffer:on at the start of every session
- Run /buffer:off before ending a session or when context gets heavy
- Run /buffer:status if you're unsure how much runway you have
- Use /buffer:throw + /buffer:catch to parallelize work across sessions
- The distill plugin (/distill:distill) pairs with buffer for source
  knowledge extraction — install separately if needed
```
