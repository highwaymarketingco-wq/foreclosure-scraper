Verbatim copies of the launchd plists that were installed in ~/Library/LaunchAgents on
2026-09-21 (audit O5: the repo had no copy of them, so a lost disk meant recreating the
schedules from memory). These are the RECORD of what was running, not templates.

The templates that replace them are one directory up (deploy/mac/*.plist, with __ROOT__ and
__HOME__ placeholders); scripts/install_launchd.sh renders them and, by default, only
prints a diff against what is installed. dailycourt is included in its disabled form
(unloaded 2026-09-20 after 31 consecutive "uv: command not found" exits); it has no template.
