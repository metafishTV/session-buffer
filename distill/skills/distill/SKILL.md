---
name: distill
description: Distill source documents (PDF, image, web) with project integration. Routes to sub-skills for extraction, analysis, and integration.
---

# Source Distillation

**ENFORCEMENT RULE — applies to all sub-skills invoked below.**

Sub-skills use two interaction levels:

| Marker | When | How |
|--------|------|-----|
| **⚠ MANDATORY POPUP** | Quick binary/ternary decisions (source label, install offer, proceed/stop) | `AskUserQuestion` with 2-3 short options |
| **⚠ MANDATORY REVIEW** | Dense information the user needs to read (scan summary, interpretation review, integration results) | Print information as **plain text** first, then `AskUserQuestion` with brief decision options only. The popup is the decision; the information is the plain text above it. |

**⚠ FULL STOP protocol — applies to BOTH levels:**

After calling `AskUserQuestion`, you MUST stop generating. Do not continue to the next step. Do not prefetch, prepare, or begin any subsequent work. Do not write "while we wait" or "in the meantime." Your turn ENDS with the `AskUserQuestion` call. The next step begins ONLY in your next turn, AFTER the user has responded. This is a hard gate, not a courtesy pause. If you catch yourself writing anything after the `AskUserQuestion` call, STOP IMMEDIATELY.

Distill a source document into structured reference knowledge.

## Routing

1. **Check for project config** (silent): look for `.claude/skills/distill/SKILL.md` in the project directory.

2. **If no project config exists**:
   - This is a first-time distillation for this project.
   - Invoke the `distill:differentiate` skill to run one-time setup.
   - After differentiation completes, continue to step 3.

3. **Read the project config ONCE**: `.claude/skills/distill/SKILL.md` — this has the project-specific terminology, output paths, and tooling profile. Extract and hold in working context:
   - `project_name`, `project_map_type`, `pure_mode`
   - `distillation_dir`, `figures_dir`, `interpretations_dir`
   - `terminology_glossary` (for Pass 4 mappings)
   - `tooling_profile` (installed/demand-install/never per tool)
   - `memory_config`, `custom_schema` (if applicable)

   **Context passing**: Each sub-skill's "Read project config" step becomes a **verification check** — confirm the config values are already loaded in the conversation context from this step, rather than re-reading the file. The parent skill reads once; the sub-skills use the loaded context. This eliminates redundant file reads per distillation.

   **Template-first principle**: Sub-skills provide inline templates for all output formats (interpretation files, INDEX.md rows, alpha-write JSON, README rows, Known Issues rows). Use the inline template directly — do NOT read existing output files to learn the pattern. Only read existing files when you need to UPDATE them (e.g., adding a row to an existing INDEX.md). For creation, the template IS the pattern.

4. **Run the pipeline** in sequence, passing config context forward:
   a. Invoke `distill:extract` — extracts raw content from the source document
   b. Invoke `distill:analyze` — runs analytic passes and produces the distilled output
   c. Invoke `distill:integrate` — updates project indexes, buffer, and reference bin

## Fast Path

If the user provides a source path directly (e.g., `/distill docs/references/Author_Title_2024.pdf`), skip the greeting and go straight to step 3 (or step 2 if no project config).

## Arguments

The source path can be provided as an argument or the user will be asked for it during the extract step.
