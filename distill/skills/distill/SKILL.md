---
name: distill
description: Distill source documents (PDF, image, web) with project integration. Routes to sub-skills for extraction, analysis, and integration.
---

# Source Distillation

**ENFORCEMENT RULE — applies to all sub-skills invoked below**: Any step in any sub-skill that says MANDATORY POPUP MUST use the `AskUserQuestion` tool. You MUST call `AskUserQuestion`, you MUST wait for the response, and you MUST NOT continue past that step until the user has answered. This is non-negotiable.

Distill a source document into structured reference knowledge.

## Routing

1. **Check for project config** (silent): look for `.claude/skills/distill/SKILL.md` in the project directory.

2. **If no project config exists**:
   - This is a first-time distillation for this project.
   - Invoke the `distill:differentiate` skill to run one-time setup.
   - After differentiation completes, continue to step 3.

3. **Read the project config**: `.claude/skills/distill/SKILL.md` — this has the project-specific terminology, output paths, and tooling profile.

4. **Run the pipeline** in sequence:
   a. Invoke `distill:extract` — extracts raw content from the source document
   b. Invoke `distill:analyze` — runs analytic passes and produces the distilled output
   c. Invoke `distill:integrate` — updates project indexes, buffer, and reference bin

## Fast Path

If the user provides a source path directly (e.g., `/distill docs/references/Author_Title_2024.pdf`), skip the greeting and go straight to step 3 (or step 2 if no project config).

## Arguments

The source path can be provided as an argument or the user will be asked for it during the extract step.
