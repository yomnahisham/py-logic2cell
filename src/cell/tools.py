"""Run Magic, Netgen and ngspice in the dd2-layout-tools container.

The repo is mounted at the same path inside the container, and the resolved
PDK is mounted at the path the pdk link points to, so paths mean the same
thing on both sides.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = os.getenv("LAYOUT_IMAGE", "dd2-layout-tools")
ENTRY = {"magic": "magic", "netgen": "netgen", "ngspice": "ngspice"}

PDK = ROOT / "pdk"
TECH = PDK / "libs.tech/magic/sky130A.tech"
LVS_SETUP = PDK / "libs.tech/netgen/sky130A_setup.tcl"
MODELS = PDK / "libs.tech/ngspice/sky130.lib.spice"


def run(tool: str, args: list[str], cwd: Path, log: Path, stdin: str | None = None, timeout: int = 600) -> str:
    pdk_real = PDK.resolve()
    pdk_target = Path(os.readlink(PDK)) if PDK.is_symlink() else PDK
    if not pdk_target.is_absolute():
        pdk_target = PDK.parent / pdk_target
    cmd = ["docker", "run", "--rm", "-i", "--user", f"{os.getuid()}:{os.getgid()}",
           "-e", "HOME=/tmp", "-e", "OMP_NUM_THREADS=1",
           "-v", f"{ROOT}:{ROOT}", "-v", f"{pdk_real}:{pdk_target}:ro",
           "-w", str(cwd), "--entrypoint", ENTRY[tool], IMAGE, *args]
    p = subprocess.run(cmd, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(p.stdout)
    if p.returncode:
        raise RuntimeError(f"{tool} exited with {p.returncode}, see {log}")
    return p.stdout
