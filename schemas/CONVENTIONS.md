# Conventions

Non-machine-validatable rules for the buffer and distill plugins. These
complement the JSON Schemas in this directory. When a rule *can* be expressed
as a schema constraint, it should be — this file is for everything else.

---

## 1. Source Label Naming

Format: `Author_Title_Year_Type`

**Type** is one of:
- `Book` — monograph or edited volume
- `Paper` — journal article or conference paper
- `Recording` — lecture, interview, podcast
- `Excerpt` — chapter or section extracted from a larger work
- `Series` — multi-part lecture series or course
- `Table` — standalone data table or dataset

Examples:
- `DeLanda_AssemblageTheory_2016_Book`
- `Lizier_JIDT_2014_Paper`
- `Shannon_MathTheoryComm_1948_Paper`

## 2. Source Folder Naming

`kebab-case(source_label)` — lowercase, underscores become hyphens.

- `DeLanda_AssemblageTheory_2016_Book` → `delanda-assemblagetheory-2016-book`
- Canonical transform: `label.lower().replace('_', '-')`

## 3. Concept Key Normalization

The `normalize_key()` algorithm (canonical source: `schemas/normalize.py`):

1. Strip whitespace and lowercase
2. Remove parenthetical content: `"Wholeness (W)"` → `"wholeness"`
3. Remove special characters (keep only `a-z`, `0-9`, `_`, space)
4. Replace spaces with underscores
5. Truncate to 40 characters

Examples:
- `"Wholeness (W)"` → `wholeness`
- `"Degrees of life"` → `degrees_of_life`
- `"Cross-metathesis"` → `crossmetathesis`

Both plugins MUST import from `schemas/normalize.py`. No local copies.

## 4. ID Formatting

| Prefix | Domain | Example |
|--------|--------|---------|
| `w:` | Cross-source concept | `w:44`, `w:337` |
| `cw:` | Convergence web edge | `cw:1`, `cw:148` |
| `c:` | Cold layer entry | `c:1` |

**File padding**: 3 digits minimum (`w044.md`, `cw007.md`).

**Sequence**: Global, monotonically increasing, never reused. The next ID is
computed as `max(existing IDs) + 1`.

## 5. Convergence Web Synthesis Tags

The synthesis field in a cw: entry MUST begin with one of these tags:

| Tag | Meaning |
|-----|---------|
| `[complementarity]` | Concepts complement each other — different angles on the same phenomenon |
| `[independent_convergence]` | Concepts converge from unrelated traditions to the same conclusion |
| `[genealogy]` | Historical/intellectual lineage between concepts |
| `[elaboration]` | One concept elaborates, extends, or deepens the other |
| `[tension]` | Productive tension or disagreement between concepts |
| `[wall]` | Anti-conflation warning — concepts appear similar but are fundamentally different (inhibitory edge) |

The tag is followed by a space and a description of the shared/involutory ground.

## 6. Relationship Types

Used in manifest source entries to classify how a concept relates to the
project framework:

| Type | Criteria |
|------|----------|
| `confirms` | Concept provides independent evidence for an existing framework element |
| `extends` | Concept adds new dimensions or nuance to an existing element |
| `challenges` | Concept contradicts or complicates an existing element |
| `novel` | Concept introduces something not yet in the framework |

## 7. Distillation Voice Rules

- **Direct assertive register.** State claims as the source states them.
- **No meta-commentary.** Don't write "The author argues..." or "This section
  discusses..." — just present the content.
- **Attribution is structural, not prose-embedded.** Use `<!-- CONCEPT:key -->`
  markers and the source label, not inline citations.

## 8. Atom Marker Format

Markers delimit structural sections within distillation files:

```
<!-- SECTION:name -->
... content ...
<!-- /SECTION:name -->

<!-- CONCEPT:key -->
... concept definition and project mapping ...
<!-- /CONCEPT:key -->

<!-- FIGURE:id -->
... figure reference and interpretation ...
<!-- /FIGURE:id -->
```

- Markers use HTML comments so they're invisible in rendered markdown.
- Opening and closing tags must match exactly.
- The `key` in `CONCEPT` markers must match `normalize_key(concept_name)`.
