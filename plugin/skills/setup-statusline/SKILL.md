---
description: Configure the buffer plugin's statusline in your settings. Shows model tier, buffer state, football count, context pressure, cost, and cache ratio. Run once to enable. Use when the user wants to set up or update their statusline.
---

# Setup Statusline

Configure the buffer plugin's enhanced statusline in your Claude Code settings.

## Step 1: Read current settings

Read `~/.claude/settings.json`. Check if `statusLine` key exists.

## Step 2: Route

**If `statusLine` is not present:**

Tell the user:
> "No statusline configured. The buffer plugin ships an enhanced statusline that shows:
> - Model name + tier (full/moderate/lean)
> - Buffer mode, open threads, football count
> - Git branch with staged/modified counts
> - Context usage bar with cache ratio
> - Session cost, duration, lines changed
>
> Want me to enable it?"

Use `AskUserQuestion` and STOP. Wait for response.

**If `statusLine` exists and its command contains `CLAUDE_PLUGIN_ROOT` or the plugin scripts path:**

Tell the user: "Statusline already configured and pointing to the buffer plugin. Updating path to current version."

Update the command path to the current plugin root. Write settings. Done.

**If `statusLine` exists and points to something else:**

Tell the user:
> "You have a custom statusline configured:
> `[show current command]`
>
> The buffer plugin ships its own statusline. Options:
> 1. **Switch** to the plugin's statusline (your current script will not be deleted)
> 2. **Keep** your current statusline
>
> Which?"

Use `AskUserQuestion` and STOP.

## Step 3: Write settings (after user approval)

Resolve the plugin root from this skill's base directory: go up from `skills/setup-statusline/` to the plugin root.

The statusline script is at `<plugin_root>/scripts/statusline.py`.

Read `~/.claude/settings.json`, add or update:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"<absolute_path_to_plugin>/scripts/statusline.py\""
  }
}
```

Write the updated settings back. Preserve all other keys.

Tell the user: "Statusline configured. It will appear on your next message. If it doesn't show, restart Claude Code."
