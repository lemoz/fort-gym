#!/usr/bin/env python3
"""Validate DFROOT configuration for Mac or Linux setup."""

import os
import sys
from pathlib import Path


def main() -> int:
    """Check if DFROOT points to a valid DFHack installation."""

    # Import after path is set
    from fort_gym.bench.config import DFROOT, DFHACK_RUN, dfhack_cmd

    print("=" * 70)
    print("DFROOT Validation")
    print("=" * 70)
    print(f"DFROOT: {DFROOT}")
    print(f"DFHACK_RUN: {DFHACK_RUN}")
    print()

    # Check if DFROOT exists
    if not DFROOT.exists():
        print(f"❌ DFROOT does not exist: {DFROOT}")
        print()
        print("Fix:")
        print("  export DFROOT='/path/to/your/df/installation'")
        print()
        print("Examples:")
        print("  Mac (Lazy Mac Pack):")
        print('    export DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"')
        print()
        print("  Linux/VM:")
        print('    export DFROOT="/opt/dwarf-fortress"')
        return 1

    print(f"✓ DFROOT exists")

    # Check if dfhack-run exists
    if not DFHACK_RUN.exists():
        print(f"❌ dfhack-run not found: {DFHACK_RUN}")
        print()
        print("Your DFROOT may be incorrect. Expected structure:")
        print(f"  {DFROOT}/")
        print("    ├── dfhack-run (executable)")
        print("    ├── dwarfort (or Dwarf Fortress.app on Mac)")
        print("    ├── hack/")
        print("    └── data/")
        return 1

    print(f"✓ dfhack-run exists")

    # Check if hook directory exists
    hook_dir = DFROOT / "hook"
    if not hook_dir.exists():
        print(f"⚠️  hook/ directory not found: {hook_dir}")
        print()
        print("Create it with:")
        print(f'  mkdir -p "{hook_dir}"')
        print(f'  cp -r hook/* "{hook_dir}/"')
        print()
    else:
        print(f"✓ hook/ directory exists")

        # Check for hook scripts
        expected_hooks = ["order_make.lua", "designate_rect.lua"]
        missing = [h for h in expected_hooks if not (hook_dir / h).exists()]

        if missing:
            print(f"⚠️  Missing hook scripts: {', '.join(missing)}")
            print()
            print("Copy them with:")
            print(f'  cp -r hook/* "{hook_dir}/"')
            print()
        else:
            print(f"✓ All required hook scripts present")

    # Show example command
    print()
    print("Example dfhack_cmd() output:")
    cmd = dfhack_cmd("lua", "-e", 'print("hello")')
    print(f"  {cmd}")
    print()

    # Platform-specific tips
    if sys.platform == "darwin":
        print("Mac-specific setup:")
        print("  1. Ensure DF is configured with [PRINT_MODE:TEXT] and [GRAPHICS:NO]")
        print("  2. Add to hack/init/dfhack.init:")
        print("       enable remotefortressreader")
        print("       remote stop")
        print("       remote start 127.0.0.1 5000")
        print("  3. Launch DF and load a fortress")
        print("  4. Verify listener: lsof -iTCP:5000 -sTCP:LISTEN")
        print()
        print("See MAC_SETUP.md for full instructions.")
    else:
        print("Linux setup:")
        print("  - Use systemd service for headless operation")
        print("  - See README.md deployment section")

    print()
    print("=" * 70)
    print("✓ DFROOT validation passed!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
