"""Drive the Google My Maps editor with Playwright to create maps from KML.

My Maps has **no create/import API** (Google removed it), so the only way to turn
a KML file into a live My Maps map is to automate the editor UI. This module:

  1. launches a *persistent* Chromium profile (so the Google login survives runs),
  2. creates a new map,
  3. imports one KML file into it (= one map per KML file),
  4. names the map and returns its URL + `mid` (the Drive file id used to share it).

The UI selectors here are the fragile part — Google ships UI changes and localizes
text, so the map is always opened with `hl=en` and selectors are centralized below.
On any failure a screenshot is written next to the KML so breakage is debuggable.

First-time setup: run `python main.py --login` once (headed) and sign in by hand;
every later run reuses that profile and runs headless.
"""

import json
import os
import re
import subprocess
import sys
import time

from .config import MYMAPS_HOME_URL, PW_PROFILE_DIR
from .errors import PipelineError

# A My Maps edit URL carries the map id as `?mid=...` / `&mid=...`; that id is the
# Drive file id we hand to the sharing step.
_MID_RE = re.compile(r"[?&]mid=([^&#]+)")

# --- Centralized, tweak-here selectors (the bit Google breaks) -----------------
SEL_CREATE_NEW = re.compile(r"create a new map", re.I)
# Home flow: 'Create a new map' opens a dialog whose confirm button is 'Create'.
SEL_CREATE_CONFIRM = re.compile(r"^\s*create\s*$", re.I)
SEL_IMPORT = re.compile(r"^\s*import\s*$", re.I)
SEL_UNTITLED_MAP = re.compile(r"untitled map", re.I)
SEL_SAVE = re.compile(r"^\s*(save|ok|done)\s*$", re.I)
# Text the Picker's upload pane shows while it waits for a file — i.e. "the drag
# and drop dialog is still open".
SEL_PICKER_OPEN = re.compile(r"drag (and drop|files here)|select a file from your", re.I)
# Text shown only when signed OUT — used to detect login state.
SEL_SIGNED_OUT = re.compile(r"sign in", re.I)


class MyMapsError(PipelineError):
    """My Maps automation failed (login, UI change, import timeout, ...)."""


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: WPS433
    except ImportError as e:  # pragma: no cover - dependency hint
        raise MyMapsError(
            "Playwright is not installed. Run:\n"
            "  pip install -r requirements.txt\n"
            "  playwright install chromium"
        ) from e
    return sync_playwright


_chromium_ready = False


def ensure_chromium() -> None:
    """Fetch Playwright's Chromium binary once per process if it's missing.

    Streamlit Community Cloud installs pip deps but never runs `playwright install`,
    so the browser binary is absent at runtime. This downloads it on demand (the OS
    libraries it needs come from the repo's `packages.txt`). No-ops after the first
    call and is cheap when the binary is already present.
    """
    global _chromium_ready
    if _chromium_ready:
        return
    if getattr(sys, "frozen", False):
        # Inside a packaged exe there's no `python -m playwright` to invoke; the app
        # drives the installed Chrome/Edge channel instead (see _launch_persistent).
        _chromium_ready = True
        return
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as e:  # best-effort — the launch step reports a clear error
        _log(f"'playwright install chromium' did not complete: {e}")
    _chromium_ready = True


# Hide the two signals Google uses to block sign-in ("This browser or app may not
# be secure"): the bundled-Chromium fingerprint and the --enable-automation flag.
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_IGNORE_ARGS = ["--enable-automation"]


def _launch_persistent(pw, profile_dir: str, headless: bool):
    """Open a persistent context as the *installed* Chrome with automation flags off.

    Google refuses login inside Playwright's default bundled Chromium (it sees
    --enable-automation). Using the real Chrome/Edge channel and dropping that flag
    gets past the "browser may not be secure" block. Falls back to bundled Chromium
    if neither browser is installed (login will likely stay blocked there).
    """
    common = dict(
        user_data_dir=profile_dir,
        headless=headless,
        args=_LAUNCH_ARGS,
        ignore_default_args=_IGNORE_ARGS,
    )
    last_err = None
    for channel in ("chrome", "msedge", None):
        try:
            if channel:
                return pw.chromium.launch_persistent_context(channel=channel, **common)
            return pw.chromium.launch_persistent_context(**common)
        except Exception as e:
            last_err = e
            continue
    # Every channel failed. The usual cause is a missing browser binary.
    msg = str(last_err) or repr(last_err)
    if "Executable doesn't exist" in msg or "playwright install" in msg:
        raise MyMapsError(
            "Playwright's Chromium isn't installed in this environment. Run:\n"
            "  playwright install chromium\n\n"
            "Note: My Maps publishing drives a real browser and needs an "
            "interactive Google login, so it only works when the app runs "
            "locally — not on a hosted, headless server (e.g. Streamlit "
            "Community Cloud)."
        ) from last_err
    raise MyMapsError(f"Couldn't launch a browser for My Maps: {msg}") from last_err


def _coerce_storage_state(storage_state):
    """Normalize a storage_state (dict / JSON string / file path) to what Playwright
    wants: a dict, or None. A path is passed through as a str; JSON text is parsed."""
    if storage_state is None:
        return None
    if isinstance(storage_state, dict):
        return storage_state
    if isinstance(storage_state, str):
        s = storage_state.strip()
        if not s:
            return None
        if s.startswith("{"):
            try:
                return json.loads(s)
            except json.JSONDecodeError as e:
                raise MyMapsError(f"GOOGLE_STORAGE_STATE is not valid JSON: {e}") from e
        if os.path.exists(s):
            return s  # a file path — Playwright reads it directly
        raise MyMapsError(
            "storage_state string is neither JSON nor an existing file path."
        )
    raise MyMapsError(f"Unsupported storage_state type: {type(storage_state).__name__}")


def _launch_with_storage_state(pw, storage_state):
    """Headless throwaway context restored from a captured session (Cloud path).

    Returns (browser, context). Chrome/Edge channel first (same anti-bot posture as
    the persistent launch), falling back to bundled Chromium.
    """
    common = dict(args=_LAUNCH_ARGS, ignore_default_args=_IGNORE_ARGS)
    last_err = None
    for channel in ("chrome", "msedge", None):
        try:
            browser = pw.chromium.launch(
                headless=True, **({"channel": channel} if channel else {}), **common
            )
            ctx = browser.new_context(storage_state=storage_state)
            return browser, ctx
        except Exception as e:
            last_err = e
            continue
    msg = str(last_err) or repr(last_err)
    if "Executable doesn't exist" in msg or "playwright install" in msg:
        raise MyMapsError(
            "Playwright's Chromium isn't installed in this environment. On Streamlit "
            "Community Cloud, add the libs to packages.txt; the binary is fetched at "
            "startup by ensure_chromium()."
        ) from last_err
    raise MyMapsError(f"Couldn't launch a browser for My Maps: {msg}") from last_err


def _log(msg: str) -> None:
    """Print a step line so the upload flow is visible while it runs."""
    print(f"  [mymaps] {msg}", flush=True)


def _click(scope, pattern, *, timeout_ms: int = 15000, optional: bool = False) -> bool:
    """Click the first VISIBLE match for `pattern`, trying button → link → text.

    My Maps renders the same label as different element types in different places
    (and keeps hidden template copies), so a single get_by_text often resolves to a
    hidden node and times out. Polling several role strategies for a visible hit is
    far more robust. Returns True on click; raises (unless `optional`) on timeout.
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for getter in (
            lambda: scope.get_by_role("button", name=pattern),
            lambda: scope.get_by_role("link", name=pattern),
            lambda: scope.get_by_text(pattern),
        ):
            try:
                el = getter().first
                if el.is_visible():
                    el.click()
                    return True
            except Exception:
                continue
        scope.wait_for_timeout(300)
    if optional:
        return False
    raise MyMapsError(f"Could not find a clickable element matching {pattern.pattern!r}.")


def _picker_frames(page):
    """Frames that belong to the Google Picker (where the real upload input lives).

    Preferring these avoids setting the KML on some unrelated `input[type=file]`
    that happens to exist elsewhere on the editor page — a wrong-input pick imports
    nothing, leaving the map empty.
    """
    out = []
    for frame in page.frames:
        u = (frame.url or "").lower()
        if "picker" in u or "docs.google.com" in u or "drive.google.com" in u:
            out.append(frame)
    return out


def _set_kml_on_any_frame(page, kml_path: str, timeout_ms: int = 30000) -> bool:
    """Find the (often hidden) <input type=file> in the Picker and set the KML.

    Setting the file input directly is far more robust than clicking the Google
    Picker "Browse" button, which lives in a cross-origin iframe. If the Picker
    opens on the Drive tab (no file input present), click its "Upload" tab first.
    The Picker frames are preferred over every other frame so the file lands on the
    import input rather than an unrelated one (which would silently import nothing).
    """
    deadline = time.time() + timeout_ms / 1000
    logged_tab = False
    while time.time() < deadline:
        # Prefer the Picker's own frames; fall back to all frames only if none match.
        candidates = _picker_frames(page) or page.frames
        for frame in candidates:
            try:
                inp = frame.query_selector("input[type=file]")
            except Exception:
                inp = None
            if inp is not None:
                inp.set_input_files(kml_path)
                return True
        # No input yet — on 2nd+ imports the Picker opens on the Drive/Recent tab
        # (which now lists earlier uploads), and the file input only exists on the
        # Upload tab. Keep nudging it to Upload every loop instead of waiting once
        # for Drive's file list to load; only inside real Picker frames so we don't
        # click a stray "upload" label elsewhere on the page.
        for frame in _picker_frames(page):
            try:
                tab = frame.get_by_text(re.compile(r"^\s*upload\s*$", re.I)).first
                if tab.count() and tab.is_visible():
                    if not logged_tab:
                        _log("clicking the Picker 'Upload' tab")
                        logged_tab = True
                    tab.click(timeout=1500)
                    break
            except Exception:
                continue
        page.wait_for_timeout(250)
    _log(f"no file input found; frames present: {[f.url for f in page.frames]}")
    return False


def _picker_open(page) -> bool:
    """Is the Picker's upload dialog still on screen (waiting for a file)?"""
    for frame in _picker_frames(page):
        try:
            if frame.get_by_text(SEL_PICKER_OPEN).first.is_visible():
                return True
        except Exception:
            continue
    return False


def _dismiss_picker(page) -> None:
    """Escape out of a leftover Picker dialog.

    Anything clicked while it's open (notably 'Import' on a retry) lands on the
    modal's backdrop and does nothing — which is what leaves a run stuck staring
    at the drag-and-drop dialog.
    """
    for _ in range(3):
        if not _picker_open(page):
            return
        _log("dismissing a Picker dialog that is still open")
        try:
            page.keyboard.press("Escape")
        except Exception:
            return
        page.wait_for_timeout(700)


def _wait_for_picker_close(page, timeout_ms: int = 25000) -> bool:
    """Wait for the upload dialog to go away after the file was set."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if not _picker_open(page):
            return True
        page.wait_for_timeout(500)
    return False


def _do_import(editor, kml_path: str, attempts: int = 3, close_timeout_ms: int = 25000) -> None:
    """Click 'Import' on the current layer and set the KML file into the Picker.

    Retries the whole click → set-file → dialog-closes cycle: the upload silently
    fails often enough (and leaves the dialog sitting there) that one attempt is
    not enough. Raises MyMapsError if every attempt leaves the dialog open.
    """
    for attempt in range(1, attempts + 1):
        _dismiss_picker(editor)  # a stuck dialog would swallow the 'Import' click
        _log(f"clicking 'Import' on the base layer (attempt {attempt}/{attempts})")
        _click(editor, SEL_IMPORT, timeout_ms=20000)
        _log(f"selecting KML file: {kml_path}")
        if not _set_kml_on_any_frame(editor, kml_path):
            if attempt == attempts:
                raise MyMapsError(
                    "Could not find the file-upload input in the import dialog."
                )
            continue
        if _wait_for_picker_close(editor, close_timeout_ms):
            return
        _log("the upload dialog is still open — the file did not take")
    raise MyMapsError(
        "The My Maps import dialog stayed open after uploading the KML file."
    )


def _wait_for_mid(page, timeout_ms: int = 60000) -> str | None:
    """Poll the page URL until the map id (`mid`) appears (set once the map saves)."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        m = _MID_RE.search(page.url)
        if m:
            return m.group(1)
        page.wait_for_timeout(500)
    return None


def _first_placemark_name(kml_path: str) -> str | None:
    """First placemark name in the KML — used to confirm the import actually landed."""
    try:
        import xml.etree.ElementTree as ET

        ns = "{http://www.opengis.net/kml/2.2}"
        tree = ET.parse(kml_path)
        for pm in tree.iter(f"{ns}Placemark"):
            name_el = pm.find(f"{ns}name")
            if name_el is not None and (name_el.text or "").strip():
                return name_el.text.strip()
    except Exception:
        return None
    return None


def _wait_for_import(page, kml_path: str, timeout_ms: int = 40000) -> bool:
    """Wait until the imported features render in the editor legend.

    The import runs asynchronously after the file input is set; `mid` can appear
    (map saved) while the placemarks are still loading — or never load if the import
    silently failed. We verify by waiting for the KML's first placemark name to show
    up on the page. If we can't read a name, fall back to a short settle.
    """
    name = _first_placemark_name(kml_path)
    if not name:
        page.wait_for_timeout(3000)
        return True
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            if page.get_by_text(name, exact=False).first.is_visible():
                return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    return False


def _open_new_map(context):
    """Open My Maps home and click 'Create a new map'; return the editor page."""
    page = context.new_page()
    _log("opening My Maps home")
    page.goto(MYMAPS_HOME_URL, wait_until="load")

    # If not signed in, the home page shows a Sign-in prompt instead of the editor.
    if page.get_by_text(SEL_SIGNED_OUT).count() and not page.get_by_text(SEL_CREATE_NEW).count():
        raise MyMapsError(
            "Not signed in to Google. Run `python main.py --login` once and sign in."
        )

    page.wait_for_timeout(800)  # let the home grid render
    _log("clicking 'Create a new map'")
    _click(page, SEL_CREATE_NEW, timeout_ms=20000)

    # That opens a dialog whose confirm button is 'Create'. It isn't always shown
    # (some accounts skip straight to the editor), so treat it as optional — keep the
    # timeout short so accounts that skip it don't pay a long wait every map.
    _log("confirming with 'Create' (if the dialog appears)")
    if _click(page, SEL_CREATE_CONFIRM, timeout_ms=2500, optional=True):
        _log("dialog confirmed")

    # Now we should be redirected into the editor (URL gains '/edit').
    try:
        page.wait_for_url(re.compile(r"/maps/d/.*edit"), timeout=20000)
    except Exception:
        pass
    page.wait_for_load_state("load")
    _log(f"editor URL: {page.url}")
    if "edit" not in page.url:
        raise MyMapsError(
            f"Did not reach the map editor after creating a map (URL: {page.url})."
        )
    return page


def _dialog_title_box(editor):
    """Return the visible title text box of the 'Edit map title' dialog, or None.

    Scoped to the dialog first so we don't grab the map's place-search box by
    mistake (which is also a textbox on the page).
    """
    for loc in (
        editor.get_by_role("dialog").get_by_role("textbox"),
        editor.locator("input.navbar-form-input, .modal-dialog input[type=text]"),
        editor.get_by_role("textbox"),
    ):
        try:
            el = loc.first
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


# The browser tab is named "<map name> - Google My Maps", which is the one place
# the current map name can be read without guessing at Google's DOM.
_TAB_SUFFIX_RE = re.compile(r"\s*[-–—|]\s*Google (My )?Maps\s*$", re.I)


def map_name_from_tab(tab_title: str) -> str:
    """The map's current name, taken from the browser tab title."""
    return _TAB_SUFFIX_RE.sub("", tab_title or "").strip()


def title_click_targets(tab_title: str) -> list:
    """Patterns to click to open the title dialog, best guess first.

    Importing a KML into a fresh map makes My Maps rename it after the file, so
    'Untitled map' is frequently already gone by the time the rename runs — which
    is why some maps kept the file name. The current name from the tab title is
    the reliable target; the literal 'Untitled map' stays as a fallback.
    """
    name = map_name_from_tab(tab_title)
    targets = []
    if name and not SEL_UNTITLED_MAP.search(name):
        targets.append(re.compile(rf"^\s*{re.escape(name)}\s*$"))
    targets.append(SEL_UNTITLED_MAP)
    return targets


def _set_title(editor, title: str, attempts: int = 2) -> bool:
    """Rename the map to `title` via the title dialog.

    Returns True if the tab title confirms the rename. Logs (instead of silently
    swallowing) so a failure here is visible — the rename is the user-facing point
    of the step.
    """
    _log(f"renaming map to: {title}")
    for attempt in range(1, attempts + 1):
        try:
            if map_name_from_tab(editor.title()) == title:
                _log("title updated")
                return True

            # Open the title dialog by clicking the map's current name.
            for pattern in title_click_targets(editor.title()):
                if _click(editor, pattern, timeout_ms=6000, optional=True):
                    break
            else:
                _log(f"could not find the map title to click (attempt {attempt})")
                editor.wait_for_timeout(1500)
                continue

            box = _dialog_title_box(editor)
            if box is None:
                _log("title dialog did not expose a text box")
                editor.wait_for_timeout(1000)
                continue
            box.fill(title)

            # Confirm: a Save/OK button if present, otherwise Enter commits the field.
            if not _click(editor, SEL_SAVE, timeout_ms=5000, optional=True):
                box.press("Enter")
            editor.wait_for_timeout(1500)

            # The tab title follows the map name, so it verifies the rename exactly.
            if map_name_from_tab(editor.title()) == title:
                _log("title updated")
                return True
            _log(f"title still {editor.title()!r} after attempt {attempt}")
        except Exception as e:
            _log(f"title change failed: {e}")
    return False


class MyMapsSession:
    """Chromium session that creates one map per KML file.

    Two auth modes:
    - **local** (default): a *persistent* Chromium profile whose one-time headed
      Google login is reused on every run.
    - **seeded** (`storage_state` given): a headless throwaway context restored from
      a captured `storage_state` (cookies + localStorage). This is the only way to
      run signed-in on a headless host (e.g. Streamlit Community Cloud) where an
      interactive login is impossible. `storage_state` may be a dict, a JSON string,
      or a path to a JSON file.
    """

    def __init__(
        self,
        profile_dir: str = PW_PROFILE_DIR,
        headless: bool = True,
        storage_state=None,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.storage_state = _coerce_storage_state(storage_state)
        self._pw = None
        self._ctx = None
        self._browser = None

    def __enter__(self):
        ensure_chromium()
        sync_playwright = _import_playwright()
        self._pw = sync_playwright().start()
        if self.storage_state is not None:
            self._browser, self._ctx = _launch_with_storage_state(
                self._pw, self.storage_state
            )
        else:
            self._ctx = _launch_persistent(self._pw, self.profile_dir, self.headless)
        return self

    def __exit__(self, *exc):
        if self._ctx:
            self._ctx.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def is_logged_in(self) -> bool:
        page = self._ctx.new_page()
        try:
            page.goto(MYMAPS_HOME_URL, wait_until="load")
            page.wait_for_timeout(1500)
            return bool(page.get_by_text(SEL_CREATE_NEW).count())
        finally:
            page.close()

    def create_map_from_kml(self, kml_path: str, title: str) -> dict:
        """Create a new map, import `kml_path`, name it `title`.

        Returns ``{"title", "url", "mid"}``. Raises MyMapsError on failure
        (and writes a screenshot next to the KML for debugging).
        """
        editor = _open_new_map(self._ctx)
        try:
            # Wait for the layer panel (with its 'Import' link) to render.
            editor.wait_for_load_state("domcontentloaded")
            editor.wait_for_timeout(800)
            _do_import(editor, kml_path)

            # Importing triggers the first save, which is when `mid` appears.
            _log("file submitted; waiting for the map to save (mid in URL)")
            mid = _wait_for_mid(editor, timeout_ms=90000)
            if not mid:
                raise MyMapsError("Timed out waiting for the map to be created (no mid in URL).")
            _log(f"map created: mid={mid}")

            # The import runs asynchronously after the file is set; wait until the
            # imported placemarks actually appear before moving on, otherwise the map
            # can be saved (mid present) while still empty. If it came up empty, retry
            # the import once — a re-import into the same (already-saved) map is the
            # cheapest recovery for a dropped first attempt.
            if not _wait_for_import(editor, kml_path):
                _log("no features after import — retrying the import once")
                self._dump_screenshot(editor, kml_path.rsplit(".", 1)[0] + ".empty1.kml")
                _do_import(editor, kml_path)
                if not _wait_for_import(editor, kml_path):
                    _log("WARNING: still no imported features after retry; map may be empty")

            _log("setting the map title")
            if not _set_title(editor, title):
                _log("WARNING: map left as 'Untitled map' (title step failed)")
            _log("done")
            return {"title": title, "url": editor.url, "mid": mid}
        except MyMapsError:
            self._dump_screenshot(editor, kml_path)
            raise
        except Exception as e:
            self._dump_screenshot(editor, kml_path)
            raise MyMapsError(f"My Maps automation failed for {kml_path}: {e}") from e
        finally:
            # Close this editor tab so the next map is created in a clean context —
            # leaving prior My Maps editors (each with a live Google Picker/OAuth
            # session) open can make a later import land on the wrong map or no-op,
            # leaving those maps empty.
            try:
                editor.close()
            except Exception:
                pass

    @staticmethod
    def _dump_screenshot(page, kml_path: str) -> None:
        try:
            shot = kml_path.rsplit(".", 1)[0] + ".error.png"
            page.screenshot(path=shot, full_page=True)
        except Exception:
            pass


def login(profile_dir: str = PW_PROFILE_DIR, timeout_s: int = 300) -> None:
    """One-time headed login: open My Maps and wait for the user to sign in.

    The login is stored in the persistent profile, so later headless runs reuse it.
    """
    sync_playwright = _import_playwright()
    print(
        "Opening Google My Maps. Sign in with your Google account in the browser "
        "window. This is a one-time step; the session is saved.\n"
    )
    with sync_playwright() as pw:
        ctx = _launch_persistent(pw, profile_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(MYMAPS_HOME_URL, wait_until="load")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if page.get_by_text(SEL_CREATE_NEW).count():
                print("Login detected. Session saved — future runs are headless.")
                ctx.close()
                return
            page.wait_for_timeout(2000)
        ctx.close()
        raise MyMapsError("Timed out waiting for Google login.")


def export_session(
    profile_dir: str = PW_PROFILE_DIR,
    out_path: str = "storage_state.json",
    timeout_s: int = 300,
) -> str:
    """Headed login, then save the signed-in session to `out_path` as JSON.

    The captured `storage_state` (cookies + localStorage) can be pasted into the
    `GOOGLE_STORAGE_STATE` secret so a headless host (Streamlit Community Cloud) can
    publish while signed in — no interactive login there. Returns `out_path`.
    """
    ensure_chromium()
    sync_playwright = _import_playwright()
    print(
        "Opening Google My Maps. Sign in with your Google account in the browser "
        "window; the session will be saved once sign-in is detected.\n"
    )
    with sync_playwright() as pw:
        ctx = _launch_persistent(pw, profile_dir, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(MYMAPS_HOME_URL, wait_until="load")
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                if page.get_by_text(SEL_CREATE_NEW).count():
                    ctx.storage_state(path=out_path)
                    print(f"Session saved to {out_path}.")
                    return out_path
                page.wait_for_timeout(2000)
            raise MyMapsError("Timed out waiting for Google login.")
        finally:
            ctx.close()


def is_logged_in(profile_dir: str = PW_PROFILE_DIR) -> bool:
    """Quick headless check: is the saved profile signed in to My Maps?

    Launches the persistent profile headless, loads the My Maps home, and looks for
    the 'Create a new map' affordance (only shown when signed in). Returns False on
    any error (Playwright missing, no profile yet, ...).
    """
    try:
        sync_playwright = _import_playwright()
    except MyMapsError:
        return False
    try:
        with sync_playwright() as pw:
            ctx = _launch_persistent(pw, profile_dir, headless=True)
            try:
                page = ctx.new_page()
                page.goto(MYMAPS_HOME_URL, wait_until="load")
                page.wait_for_timeout(1500)
                return bool(page.get_by_text(SEL_CREATE_NEW).count())
            finally:
                ctx.close()
    except Exception:
        return False
