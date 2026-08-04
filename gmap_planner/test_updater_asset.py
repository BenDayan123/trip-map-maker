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
    {"name": "TripMapMaker-macos-arm64.dmg"},
    {"name": "TripMapMaker-Setup.exe"},
]


def pick(assets, plat, machine="arm64"):
    # NB: `updater.sys` IS the global sys module, so this swaps sys.platform
    # process-wide for the duration of the call. Fine for a standalone script;
    # the finally restores both before anything else looks at them.
    old = (updater.sys.platform, platform.machine)
    try:
        updater.sys.platform = plat
        platform.machine = lambda: machine
        got = updater._platform_asset(assets)
    finally:
        updater.sys.platform, platform.machine = old
    return (got or {}).get("name")


def test_apple_silicon_gets_the_arm64_dmg():
    assert pick(ASSETS, "darwin", "arm64") == "TripMapMaker-macos-arm64.dmg"


def test_intel_mac_is_offered_nothing_rather_than_an_arm64_dmg():
    # Releases are Apple Silicon only; an arm64 .dmg cannot run on Intel, so the
    # UI must say "no installer for your system", not install a brick.
    assert pick(ASSETS, "darwin", "x86_64") is None


def test_older_releases_with_intel_and_universal_still_resolve():
    old = [{"name": "TripMapMaker-macos-intel.dmg"},
           {"name": "TripMapMaker-macos-universal.dmg"}]
    assert pick(old, "darwin", "x86_64") == "TripMapMaker-macos-intel.dmg"
    assert pick(old, "darwin", "arm64") == "TripMapMaker-macos-universal.dmg"


def test_falls_back_to_an_arch_less_dmg():
    only = [{"name": "TripMapMaker.dmg"}]
    assert pick(only, "darwin", "arm64") == "TripMapMaker.dmg"
    assert pick(only, "darwin", "x86_64") == "TripMapMaker.dmg"


def test_windows_still_gets_the_exe():
    assert pick(ASSETS, "win32") == "TripMapMaker-Setup.exe"


def test_no_asset_for_this_os():
    assert pick([{"name": "TripMapMaker-Setup.exe"}], "darwin") is None
    assert pick([], "linux") is None


if __name__ == "__main__":
    test_apple_silicon_gets_the_arm64_dmg()
    test_intel_mac_is_offered_nothing_rather_than_an_arm64_dmg()
    test_older_releases_with_intel_and_universal_still_resolve()
    test_falls_back_to_an_arch_less_dmg()
    test_windows_still_gets_the_exe()
    test_no_asset_for_this_os()
    print("ok")
