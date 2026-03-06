---
name: buffer
description: Session buffer dispatcher. Routes to on (reconstruct) or off (handoff).
---

# Buffer Dispatcher

This skill routes to the correct operational skill. **Do not act on buffer data without loading the operational skill first.**

## Routing

If ARGUMENTS contains "on":
→ Invoke the `session-buffer:on` skill via the Skill tool. Follow its instructions completely.

If ARGUMENTS contains "off":
→ Invoke the `session-buffer:off` skill via the Skill tool. Follow its instructions completely.

If no argument or unrecognized argument:
→ Ask the user: "Start session (`/session-buffer:on`) or save handoff (`/session-buffer:off`)?"

## Rules

- **Do NOT search for buffer files.** The operational skill tells you how.
- **Do NOT read handoff.json.** The operational skill tells you when.
- **Do NOT use MEMORY.md to locate projects.** The operational skill has routing.
- If you already know where buffer files are, that knowledge is irrelevant until the operational skill loads. Invoke the skill first.
