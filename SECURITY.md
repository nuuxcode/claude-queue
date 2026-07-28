# Security

This project modifies the Claude Code binary on the machine of whoever installs
it, which is exactly why reports are taken seriously.

## Reporting

Found something dangerous, a way the patch could be abused, a flaw in the
install or restore path, or a privacy leak anywhere in the repo or its clips?
Open a [GitHub issue](https://github.com/nuuxcode/claude-queue/issues). If it
should not be public, use GitHub's private vulnerability reporting on this
repository instead.

## What is in scope

- The installer, launcher and patch engine under `lib/` and `bin/`
- The patched behaviour itself: anything that could make a message run in a
  way the README's guarantees say it cannot
- The published GIFs and docs leaking information they should not

## What to expect

A reply in the issue, an honest assessment, and a fix or a documented refusal.
The patch engine already refuses to write anything it cannot verify, and that
bar applies to fixes too.
