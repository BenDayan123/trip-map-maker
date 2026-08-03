"""Self-check for release-asset picking.

Run it with `python gmap_planner/test_updater_asset.py` (it lives in the package
because /tests is gitignored).

Covers the bug it exists for: a macOS release ships an Intel .dmg *and* a
universal one, and picking the first match handed Apple Silicon the Intel build.
"""

import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmap_planner import updater

ASSETS = [
    {"name": "TripMapMaker-macos-intel.dmg"},
    {"name": "TripMapMaker-macos-universal.dmg"},
    {"name": "TripMapMaker-Setup.exe"},
]


def pick(assets, plat, machine="arm64"):
    old = (updater.sys.platform, platform.machine)
    try:
        updater.sys.platform = plat
        platform.machine = lambda: machine
        got = updater._platform_asset(assets)
    finally:
        updater.sys.platform, platform.machine = old
    return (got or {}).get("name")


def test_apple_silicon_gets_the_universal_dmg():
    assert pick(ASSETS, "darwin", "arm64") == "TripMapMaker-macos-universal.dmg"


def test_intel_mac_gets_the_intel_dmg():
    assert pick(ASSETS, "darwin", "x86_64") == "TripMapMaker-macos-intel.dmg"


def test_falls_back_to_any_dmg():
    only = [{"name": "TripMapMaker.dmg"}]
    assert pick(only, "darwin", "arm64") == "TripMapMaker.dmg"
    assert pick(only, "darwin", "x86_64") == "TripMapMaker.dmg"


def test_windows_still_gets_the_exe():
    assert pick(ASSETS, "win32") == "TripMapMaker-Setup.exe"


def test_no_asset_for_this_os():
    assert pick([{"name": "TripMapMaker-Setup.exe"}], "darwin") is None
    assert pick([], "linux") is None


if __name__ == "__main__":
    test_apple_silicon_gets_the_universal_dmg()
    test_intel_mac_gets_the_intel_dmg()
    test_falls_back_to_any_dmg()
    test_windows_still_gets_the_exe()
    test_no_asset_for_this_os()
    print("ok")
