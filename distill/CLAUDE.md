# Distill Plugin — Behavioral Directives

These load every session. They are posture, not procedure — SKILL.md files have the full steps.

## Forward Notes

Before ANY write to `forward_notes.json` → run `distill_forward_notes.py template --notes [path]` first.
- Never blindly append. Template shows `next_number` + existing entries.
- §5.1–§5.69 = design doc (bookmarked). Never assign to new candidates.
- New notes start at `next_number` from the registry. Increment after use.
- After adding entries → run `distill_forward_notes.py check-new` for dedup.

## Figure vs Equation Policy

- Visual content (tables, graphs, charts, diagrams, schematics) → always extract as figure files.
- Core-meaning equations (the equation IS the concept) → inline LaTeX in distillation markdown. Not a figure.
- Scaffolding equations (derivations, intermediate algebra, proof steps) → skip entirely.
- Equation-heavy sources: most equations are scaffolding. Extract only what carries structural meaning.

## Glossary

Before adding terms → run `distill_glossary.py template --skill-md [path]` to see existing entries.
- Max 5 new terms per distillation.
- Term must appear in interpretation's Key Concepts table.
- Check existing rows — no duplicates.
- Append to table. Never rewrite the section.

## Distillation Voice

- Direct assertive register. State claims as the source states them.
- No meta-commentary. ≠ "The author argues..." — just present the content.
- Attribution via `<!-- CONCEPT:key -->` markers, not prose.

## Autonomy Boundary

- FULL STOP popups (redistill detection, quality gate failures) → never skip. Always present to user.
- Uncertain about extraction route or concept mapping → ask. Do not guess.
- User review of interpretation → mandatory before integrate. No shortcuts.

## Section Reservation

§5.1–§5.69 are design doc forward notes (status: bookmarked).
§5.70+ are distillation candidates. Only the registry's `next_number` determines the next ID.
