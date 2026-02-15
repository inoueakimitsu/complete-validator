#!/usr/bin/env bash
# Hook entry point: reads PreToolUse hook JSON from stdin,
# checks if the command is "git commit", and delegates to check_style.py if so.

# CLAUDE_PLUGIN_ROOT is set by Claude Code when running as a plugin.
# Fall back to script-relative resolution for standalone use.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    PLUGIN_DIR="$CLAUDE_PLUGIN_ROOT"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

LOG_FILE="$PLUGIN_DIR/.complete-validator/hook_debug.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Read stdin into variable
INPUT="$(cat)"

# Extract command from tool_input.command using python3 (avoid jq dependency)
COMMAND="$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('tool_input', {}).get('command', ''))
" 2>/dev/null || echo "")"

# Check if the command contains a git commit (handles compound commands like "git add && git commit",
# "git -C <dir> commit", etc.)
IS_GIT_COMMIT="$(echo "$COMMAND" | python3 -c "
import sys, re
cmd = sys.stdin.read().strip()
# Split on shell operators (&&, ||, ;) and check each part
# Also handle \$(... ) subshells by checking the whole string
parts = re.split(r'[;&|]+', cmd)
for part in parts:
    part = part.strip()
    # Match: git [<git-options>...] commit [<args>...]
    # Git options before subcommand: -C <path>, --git-dir=<path>, -c <key>=<value>, etc.
    if re.match(r'^git\s+((-[CcA-Za-z](\s+\S+)?|--[a-z-]+(=\S+)?)\s+)*commit(\s|$)', part):
        print('yes')
        sys.exit(0)
print('no')
" 2>/dev/null || echo "no")"

case "$IS_GIT_COMMIT" in
    yes)
        # Pre-stage files if the command contains "git add" before "git commit"
        # (PreToolUse fires before the command runs, so files aren't staged yet)
        PRE_ADD_CMD="$(echo "$COMMAND" | python3 -c "
import sys, re
cmd = sys.stdin.read().strip()
parts = re.split(r'&&|\|\||;', cmd)
add_parts = []
for part in parts:
    part = part.strip()
    if re.match(r'^git\s+((-[CcA-Za-z](\s+\S+)?|--[a-z-]+(=\S+)?)\s+)*add(\s|$)', part):
        add_parts.append(part)
    elif re.match(r'^git\s+((-[CcA-Za-z](\s+\S+)?|--[a-z-]+(=\S+)?)\s+)*commit(\s|$)', part):
        break
if add_parts:
    print(' && '.join(add_parts))
" 2>/dev/null || echo "")"

        if [ -n "$PRE_ADD_CMD" ]; then
            eval "$PRE_ADD_CMD" 2>>"$LOG_FILE"
        fi

        # Delegate to Python script, capturing stderr to log file
        # Always exit 0 to prevent Claude Code from treating hook as error
        python3 "$PLUGIN_DIR/scripts/check_style.py" --staged --plugin-dir "$PLUGIN_DIR" 2>>"$LOG_FILE"
        EXIT_CODE=$?
        if [ $EXIT_CODE -ne 0 ]; then
            echo "{\"ts\": \"$(date -Iseconds)\", \"exit_code\": $EXIT_CODE}" >> "$LOG_FILE"
        fi
        exit 0
        ;;
    *)
        # Not a git commit — allow immediately (no output = allow)
        exit 0
        ;;
esac
