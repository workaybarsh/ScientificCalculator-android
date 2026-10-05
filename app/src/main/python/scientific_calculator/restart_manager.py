"""Platform-safe app restart command construction."""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable


def restart_application(launch: Callable[..., object] = subprocess.Popen) -> None:
    """Start a new instance, leaving the current PyInstaller parent intact.

    Replacing a Windows one-file executable with ``os.execv`` breaks the
    bootloader's parent/child handshake. Launch first, then let ``App`` close
    the old Tk process normally.
    """
    executable = sys.executable
    argv = [executable, *sys.argv[1:]] if getattr(sys, "frozen", False) else [executable, *sys.argv]
    launch(argv, close_fds=True)
