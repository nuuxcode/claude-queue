"""A lab session with agents ENABLED.

The rest of the suite passes --safe-mode, which turns off every customization
at once: hooks, MCP servers, CLAUDE.md, custom commands AND agents. The
background-agent tests need agents back and nothing else, so instead of just
dropping safe-mode this keeps the rest off by hand:

  --strict-mcp-config        no MCP server loads, because none is passed with
                             --mcp-config, so the boot stays fast and nothing
                             external is touched
  --setting-sources project  only the project's own settings load. The lab
                             workspace has none, so whatever hooks the person
                             running this has configured never fire inside the
                             test.

What comes back is agents, plus the user's own CLAUDE.md, which costs tokens
and changes nothing about queue behaviour.
"""
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(HARNESS))
from lab import Lab  # noqa: E402


class FreeLab(Lab):
    def _argv(self):
        return [self.binary,
                "--dangerously-skip-permissions",
                "--strict-mcp-config",
                "--setting-sources", "project",
                "--settings", '{"skipDangerousModePermissionPrompt":true}',
                "--session-id", self.session_id,
                "--model", self.model]
