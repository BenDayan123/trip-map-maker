"""Self-check for the import/rename helpers.

Run it with `python gmap_planner/test_mymaps_helpers.py` (it lives in the package
because /tests is gitignored).

Covers the two things that made publishing flaky: which element is clicked to
open the rename dialog (a wrong guess leaves the map named after the KML file),
and the import retry that has to escape a Picker dialog left open by a failed
upload.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmap_planner import mymaps
from gmap_planner.mymaps import SEL_UNTITLED_MAP, map_name_from_tab, title_click_targets


def test_map_name_from_tab():
    assert map_name_from_tab("Untitled map - Google My Maps") == "Untitled map"
    assert map_name_from_tab("1-5 - Google My Maps") == "1-5"
    assert map_name_from_tab("רונן ומאיה — Days 1-5 - Google My Maps") == "רונן ומאיה — Days 1-5"
    assert map_name_from_tab("") == ""


def test_title_click_targets():
    # A map auto-named after the KML file: that name must be the first target,
    # otherwise the rename never opens the dialog.
    targets = title_click_targets("1-5 - Google My Maps")
    assert targets[0].match("1-5")
    assert targets[-1] is SEL_UNTITLED_MAP

    # Still untitled: nothing to add, just the fallback.
    assert title_click_targets("Untitled map - Google My Maps") == [SEL_UNTITLED_MAP]
    assert title_click_targets("") == [SEL_UNTITLED_MAP]

    # Regex metacharacters in a trip name must not blow up the pattern.
    targets = title_click_targets("Trip (2026) [draft] - Google My Maps")
    assert targets[0].match("Trip (2026) [draft]")


class FakePage:
    """Editor page stand-in: the Picker dialog sticks open after the first upload."""

    def __init__(self, sticky_uploads):
        self.sticky_uploads = sticky_uploads
        self.uploads = 0
        self.escapes = 0
        self.import_clicks = 0
        self.picker_open = False
        page = self

        class Keyboard:
            def press(self, key):
                if key == "Escape":
                    page.escapes += 1
                    page.picker_open = False

        self.keyboard = Keyboard()

    def upload(self):
        self.uploads += 1
        self.picker_open = self.uploads <= self.sticky_uploads

    def wait_for_timeout(self, _ms):
        pass


def test_import_retries_past_a_stuck_dialog():
    page = FakePage(sticky_uploads=1)

    def fake_click(scope, pattern, **kw):
        page.import_clicks += 1
        return True

    def fake_set_file(scope, kml_path, timeout_ms=30000):
        page.upload()
        return True

    original = (mymaps._click, mymaps._set_kml_on_any_frame, mymaps._picker_open)
    mymaps._click, mymaps._set_kml_on_any_frame, mymaps._picker_open = (
        fake_click, fake_set_file, lambda scope: page.picker_open,
    )
    try:
        mymaps._do_import(page, "trip.kml", close_timeout_ms=100)
    finally:
        mymaps._click, mymaps._set_kml_on_any_frame, mymaps._picker_open = original

    assert page.uploads == 2, page.uploads      # retried the upload
    assert page.import_clicks == 2              # clicked Import again for the retry
    assert page.escapes >= 1                    # escaped the stuck dialog first
    assert not page.picker_open


if __name__ == "__main__":
    test_map_name_from_tab()
    test_title_click_targets()
    test_import_retries_past_a_stuck_dialog()
    print("ok")
