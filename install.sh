#!/bin/sh
# Install gemma-coder into every agent skill directory present on this machine.
# Usage: ./install.sh [--copy]   (default: symlink, so git pull updates everywhere)
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-link}"

install_into() {
    parent="$1"; target="$2/gemma-coder"
    [ -d "$parent" ] || return 0            # agent not installed on this machine
    mkdir -p "$2"
    rm -rf "$target"
    if [ "$MODE" = "--copy" ]; then
        cp -R "$SRC" "$target"
    else
        ln -s "$SRC" "$target"
    fi
    echo "installed -> $target"
}

# Claude Code
install_into "$HOME/.claude"        "$HOME/.claude/skills"
# Codex CLI (Agent Skills open standard global dir)
install_into "$HOME/.codex"         "$HOME/.agents/skills"
# Antigravity / Antigravity CLI / Gemini
install_into "$HOME/.gemini"        "$HOME/.gemini/config/skills"
# Generic open-standard location, if some other agent already created it
[ -d "$HOME/.agents/skills" ] && install_into "$HOME/.agents" "$HOME/.agents/skills"

echo "Done. Run 'python3 $SRC/scripts/setup.py' to pick your local model."
