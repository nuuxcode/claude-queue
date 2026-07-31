"""Where these tests find their binaries and put their scratch files.

Everything here used to be an absolute path typed into each test, which meant
they only ran on the machine that wrote them. This resolves the same things
from the environment instead.

  PATCHED    the Claude Code executable the patch is installed into
  STOCK      an unpatched copy, extracted from the installer's own backup
  SCRATCH    somewhere to put logs and the stock copy

Override any of them with CLAUDE_QUEUE_TEST_PATCHED, _STOCK or _SCRATCH.
"""
import glob
import os
import shutil
import tempfile

SCRATCH = os.environ.get("CLAUDE_QUEUE_TEST_SCRATCH") or os.path.join(
    tempfile.gettempdir(), "claude-queue-tests")
os.makedirs(SCRATCH, exist_ok=True)

# The throwaway project these sessions run in. It must be a real directory
# because Claude Code writes the queue into its .claude subdirectory, and it
# must not be the repo, because a test that leaves queue files behind in the
# working copy is a test that pollutes the next run.
WORKSPACE = os.environ.get("CLAUDE_QUEUE_TEST_WORKSPACE") or os.path.join(
    SCRATCH, "workspace")
os.makedirs(WORKSPACE, exist_ok=True)


def clean_queue_files():
    """Wipe saved queues before a run.

    A leftover queue-*.json restores rows into the next session, and every
    count then measures the wrong queue. That cost one false regression report,
    so every suite here starts by calling this.
    """
    for path in glob.glob(os.path.join(WORKSPACE, ".claude", "queue-*.json")):
        os.remove(path)


def patched_binary():
    """The installed, patched executable."""
    env = os.environ.get("CLAUDE_QUEUE_TEST_PATCHED")
    if env:
        return env
    for path in (
            "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
            "/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
            os.path.expanduser(
                "~/.npm-global/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"),
    ):
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "no Claude Code executable found; set CLAUDE_QUEUE_TEST_PATCHED")


def stock_binary():
    """An unpatched copy, so a comparison has a control.

    The installer keeps the original executable it replaced, so the control
    does not need downloading. The copy is made once and reused, because it is
    about 250 MB.
    """
    env = os.environ.get("CLAUDE_QUEUE_TEST_STOCK")
    if env:
        return env
    dest = os.path.join(SCRATCH, "stock-claude.exe")
    if os.path.exists(dest):
        return dest
    backups = sorted(glob.glob(
        os.path.expanduser("~/.claude-patch/backups/*.orig")))
    if not backups:
        raise FileNotFoundError(
            "no stock backup in ~/.claude-patch/backups; "
            "set CLAUDE_QUEUE_TEST_STOCK to an unpatched Claude Code")
    shutil.copy2(backups[-1], dest)
    os.chmod(dest, 0o755)
    return dest


def scratch(name):
    return os.path.join(SCRATCH, name)
