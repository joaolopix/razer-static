#!/usr/bin/env python3
"""
razer_static.py - cross-platform entry point for the static-colour tools.

Detects the operating system and runs the matching backend, forwarding all
command-line arguments to it. Add new platforms by dropping a backend file in
this folder and registering it in BACKENDS below.

  python razer_static.py ff0000
  python razer_static.py 00ff88 --brightness 180
  python razer_static.py --list
"""
import os
import runpy
import sys

sys.dont_write_bytecode = True   # don't scatter __pycache__ folders

# platform (sys.platform) -> backend script in this folder.
BACKENDS = {
    "win32": "razer_static_win.py",
    "darwin": "razer_static_mac.py",
}


def main():
    backend = BACKENDS.get(sys.platform)
    if not backend:
        supported = ", ".join(sorted(BACKENDS)) or "none"
        sys.exit(f"No Razer backend for platform '{sys.platform}' yet "
                 f"(supported: {supported}).")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), backend)
    if not os.path.isfile(path):
        sys.exit(f"Backend '{backend}' is missing.")

    # Run the backend as if it were invoked directly; sys.argv is already correct.
    runpy.run_path(path, run_name="__main__")
    print()


if __name__ == "__main__":
    main()
