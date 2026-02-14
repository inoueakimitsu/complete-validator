#!/usr/bin/env bash
# Hook entry point: reads PreToolUse hook JSON from stdin,
# checks if the command is "git commit", and delegates to check_style.py if so.

set -euo pipefail

# CLAUDE_PLUGIN_ROOT is set by Claude Code when running as a plugin.
# Fall back to script-relative resolution for standalone use.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    PLUGIN_DIR="$CLAUDE_PLUGIN_ROOT"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Read stdin into variable
INPUT="$(cat)"

# Extract command from tool_input.command using python3 (avoid jq dependency)
COMMAND="$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('tool_input', {}).get('command', ''))
" 2>/dev/null || echo "")"

# Only proceed if the command starts with "git commit"
case "$COMMAND" in
    git\ commit*)
        # Delegate to Python script
        exec python3 "$PLUGIN_DIR/scripts/check_style.py" "$PLUGIN_DIR"
        ;;
    *)
        # Not a git commit — allow immediately (no output = allow)
        exit 0
        ;;
esac
