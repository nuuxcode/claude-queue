#!/usr/bin/env bash
#
# Installer. Works out which patch it belongs to from the CLI next to it.
#
# Two things happen:
#   1. this repo's bin/ goes on your PATH, ahead of the real claude
#   2. the patch is turned on
#
# Step 1 matters because Claude Code updates itself, and an update replaces the
# binary and drops every patch. `/update` restarts by resolving `claude` on
# PATH and spawning it directly, not through your shell, so a shell alias is
# stepped over silently. A real file named `claude` earlier on PATH is not, and
# it re-applies every patch you have enabled before starting.
#
# Nothing here is irreversible. Turn the patch off with `<name> restore`, and
# remove the PATH line to undo step 1.

# Piped through curl there is no repository around this script. Fetch the
# latest release into a temporary directory and continue from there, with the
# terminal wired back to stdin so the confirmation question still works. The
# one-liner and the cloned path end up running exactly the same code. This
# runs before `set -u` because BASH_SOURCE is unset when bash reads stdin.
if [ ! -e "${BASH_SOURCE[0]:-}" ]; then
  set -euo pipefail
  TAG="$(curl -fsSL https://api.github.com/repos/nuuxcode/claude-queue/releases/latest 2>/dev/null \
         | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | tr -cd 'A-Za-z0-9._-')"
  REF="${TAG:-main}"
  # The copy needs a permanent home: bin/ goes on your PATH and the launcher
  # re-applies the patch after every Claude Code update. A temp directory
  # would be cleaned up and take both with it. ~/.claude-patch is where this
  # tooling already lives.
  DEST="$HOME/.claude-patch/claude-queue-$REF"
  TMP="$(mktemp -d)"
  echo "fetching claude-queue $REF into $DEST ..."
  curl -fsSL "https://github.com/nuuxcode/claude-queue/archive/$REF.tar.gz" | tar -xz -C "$TMP"
  rm -rf "$DEST"
  mkdir -p "$(dirname "$DEST")"
  mv "$TMP"/claude-queue-* "$DEST"
  rmdir "$TMP" 2>/dev/null || true
  if ( : < /dev/tty ) 2>/dev/null; then
    exec bash "$DEST/install.sh" "$@" < /dev/tty
  else
    exec bash "$DEST/install.sh" "$@"
  fi
fi

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$DIR/bin"
DRY=0; NO_PATH=0; YES=0

CLI=""
for f in "$BIN"/claude-*; do
  [ -x "$f" ] && CLI="$f" && break
done
[ -n "$CLI" ] || { echo "no patch CLI found in $BIN" >&2; exit 1; }
NAME="$(basename "$CLI")"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --no-path) NO_PATH=1 ;;
    --yes|-y)  YES=1 ;;
    -h|--help)
      cat <<EOF
usage: ./install.sh [--dry-run] [--no-path] [--yes]

  --dry-run   show what would happen, change nothing
  --no-path   patch only, do not touch your shell config
              (the patch is then lost on the next Claude Code update)
  --yes       do not ask
EOF
      exit 0 ;;
    *)
      echo "unknown option: $arg" >&2
      echo "run ./install.sh --help for usage" >&2
      exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }

say "$NAME"
say ""
say "This will:"
[ "$NO_PATH" -eq 0 ] && say "  1. put $BIN at the front of your PATH"
say "  2. turn on $NAME"
say ""
say "Undo any time with: $NAME restore"
say ""

if [ "$DRY" -eq 1 ]; then
  say "(dry run, nothing changed)"
  "$CLI" doctor || true
  exit 0
fi

if [ "$YES" -eq 0 ]; then
  if [ ! -t 0 ]; then
    say "non-interactive installation requires --yes" >&2
    exit 1
  fi
  printf 'continue? [y/N] '
  read -r reply
  case "$reply" in [yY]*) ;; *) say "cancelled"; exit 1 ;; esac
fi

chmod +x "$BIN"/claude "$CLI" 2>/dev/null || true

if [ "$NO_PATH" -eq 0 ]; then
  LINE="export PATH=\"$BIN:\$PATH\"  # $NAME"
  for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
    [ -f "$rc" ] || continue
    if grep -Eq '^export PATH=".*:\$PATH"  # claude-[A-Za-z0-9._-]+$' "$rc" 2>/dev/null; then
      say "a launcher is already on your PATH via $rc, leaving it alone"
    else
      printf '\n%s\n' "$LINE" >> "$rc"
      say "added to $rc"
    fi
  done
  say ""
  say "open a new terminal, or run:  export PATH=\"$BIN:\$PATH\""
  say ""
fi

"$CLI" install

say ""
say "Check any time with:  $NAME status"
