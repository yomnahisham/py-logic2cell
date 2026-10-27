"""Run Yosys 0.33 (the version the option 2 handout used) in the dd2-yosys container.

Build the image once with: docker build -t dd2-yosys docker/yosys
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = os.getenv("YOSYS_IMAGE", "dd2-yosys")


def run(args: list[str], stdin: str | None = None, timeout: int = 1800) -> str:
    """Run a command in the container, in the repo folder. Returns stdout and stderr together."""
    given = (ROOT / "given").resolve()
    mount = Path(os.path.commonpath([ROOT, given]))
    cmd = ["docker", "run", "--rm", "-i", "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
           "-v", f"{mount}:{mount}", "-w", str(ROOT), IMAGE, *args]
    p = subprocess.run(cmd, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{args[0]} exited with {p.returncode}:\n{p.stdout[-2000:]}")
    return p.stdout
