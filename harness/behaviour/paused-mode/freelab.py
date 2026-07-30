"""A lab session with agents ENABLED.

The normal harness passes --safe-mode, which turns off every customization at
once: hooks, MCP servers, CLAUDE.md, custom commands AND agents. Agents are the
only one we need back, so instead of dropping safe-mode alone this keeps the
rest off by hand:

  --strict-mcp-config      no MCP server is loaded, because no --mcp-config is
                           given, so the boot stays fast and nothing external
                           is touched
  --setting-sources project  only the project's own settings load. The lab
                           workspace has none, so the user's hooks never fire
                           inside the test.

What comes back is agents, plus ~/.claude/CLAUDE.md, which costs tokens and
changes nothing about queue behaviour.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/Developer/_claude-lab"))
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
