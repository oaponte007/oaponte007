"""PBS / PBS Pro backend, via pbsnodes.

pbsnodes has drifted slightly across OpenPBS, classic TORQUE/PBS, and PBS
Pro -- the offline/note/clear flags below (-o / -N / -c) are the common
convention across all three, but if your specific PBS Pro version differs,
override pbs_binary/pbs_offline_flag/pbs_note_flag/pbs_clear_flag in
chpc.yaml rather than patching this file. Verify against your site's
`pbsnodes --help` / `man pbsnodes` before relying on this in production --
this was written from documented behavior, not tested against a live PBS
Pro install.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import CommandRunner


class PBSBackend:
    name = "pbs"

    def __init__(
        self,
        runner: CommandRunner,
        binary: str = "pbsnodes",
        offline_flag: str = "-o",
        note_flag: str = "-N",
        clear_flag: str = "-c",
    ):
        self.runner = runner
        self.binary = binary
        self.offline_flag = offline_flag
        self.note_flag = note_flag
        self.clear_flag = clear_flag

    def drain(self, node: str, reason: str) -> bool:
        result = self.runner.run(
            [self.binary, self.offline_flag, self.note_flag, reason, node], mutating=True
        )
        return result.ok

    def resume(self, node: str) -> bool:
        result = self.runner.run([self.binary, self.clear_flag, node], mutating=True)
        return result.ok

    def is_drained(self, node: str) -> Optional[bool]:
        result = self.runner.run([self.binary, node])
        if not result.ok:
            return None
        m = re.search(r"state\s*=\s*([\w,]+)", result.stdout, re.I)
        if not m:
            return None
        state = m.group(1).lower()
        return "offline" in state or "down" in state
