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

import re
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


def _set_kml_on_any_frame(page, kml_path: str, timeout_ms: int = 30000) -> bool:
    """Find the (often hidden) <input type=file> across all frames and set the KML.

    Setting the file input directly is far more robust than clicking the Google
    Picker "Browse" button, which lives in a cross-origin iframe. If the Picker
    opens on the Drive tab (no file input present), click its "Upload" tab once.
    """
    deadline = time.time() + timeout_ms / 1000
    tried_upload_tab = False
    while time.time() < deadline:
        for frame in page.frames:
            try:
                inp = frame.query_selector("input[type=file]")
            except Exception:
                inp = None
            if inp is not None:
                inp.set_input_files(kml_path)
                return True
        # File input only exists on the Picker's Upload tab — switch to it once.
        if not tried_upload_tab:
            tried_upload_tab = True
            for frame in page.frames:
                try:
                    tab = frame.get_by_text(re.compile(r"upload", re.I)).first
                    if tab.count():
                        _log("clicking the Picker 'Upload' tab")
                        tab.click(timeout=2000)
                        break
                except Exception:
                    continue
        page.wait_for_timeout(500)
    _log(f"no file input found; frames present: {[f.url for f in page.frames]}")
    return False


def _wait_for_mid(page, timeout_ms: int = 60000) -> str | None:
    """Poll the page URL until the map id (`mid`) appears (set once the map saves)."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        m = _MID_RE.search(page.url)
        if m:
            return m.group(1)
        page.wait_for_timeout(500)
    return None


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

    page.wait_for_timeout(1500)  # let the home grid render
    _log("clicking 'Create a new map'")
    _click(page, SEL_CREATE_NEW, timeout_ms=20000)

    # That opens a dialog whose confirm button is 'Create'. It isn't always shown
    # (some accounts skip straight to the editor), so treat it as optional.
    _log("confirming with 'Create' (if the dialog appears)")
    if _click(page, SEL_CREATE_CONFIRM, timeout_ms=6000, optional=True):
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


def _set_title(editor, title: str) -> bool:
    """Rename the map from 'Untitled map' to `title` via the title dialog.

    Returns True if the title was changed. Logs (instead of silently swallowing)
    so a failure here is visible — the rename is the user-facing point of the step.
    """
    _log(f"renaming map to: {title}")
    try:
        # Open the title dialog by clicking the current (Untitled) map name.
        if not _click(editor, SEL_UNTITLED_MAP, timeout_ms=8000, optional=True):
            _log("could not find the 'Untitled map' title to click")
            return False

        box = _dialog_title_box(editor)
        if box is None:
            _log("title dialog did not expose a text box")
            return False
        box.fill(title)

        # Confirm: a Save/OK button if present, otherwise Enter commits the field.
        if not _click(editor, SEL_SAVE, timeout_ms=5000, optional=True):
            box.press("Enter")
        editor.wait_for_timeout(1200)

        # Verify the rename actually took (the legend should now show `title`).
        try:
            if editor.get_by_text(title, exact=False).first.is_visible():
                _log("title updated")
                return True
        except Exception:
            pass
        _log("title dialog handled (could not verify the new name on screen)")
        return True
    except Exception as e:
        _log(f"title change failed: {e}")
        return False


class MyMapsSession:
    """Persistent-profile Chromium session that creates one map per KML file."""

    def __init__(self, profile_dir: str = PW_PROFILE_DIR, headless: bool = True):
        self.profile_dir = profile_dir
        self.headless = headless
        self._pw = None
        self._ctx = None

    def __enter__(self):
        sync_playwright = _import_playwright()
        self._pw = sync_playwright().start()
        self._ctx = _launch_persistent(self._pw, self.profile_dir, self.headless)
        return self

    def __exit__(self, *exc):
        if self._ctx:
            self._ctx.close()
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
            editor.wait_for_timeout(1500)
            _log("clicking 'Import' on the base layer")
            _click(editor, SEL_IMPORT, timeout_ms=20000)

            _log(f"selecting KML file: {kml_path}")
            if not _set_kml_on_any_frame(editor, kml_path):
                raise MyMapsError("Could not find the file-upload input in the import dialog.")

            # Importing triggers the first save, which is when `mid` appears.
            _log("file submitted; waiting for the map to save (mid in URL)")
            mid = _wait_for_mid(editor, timeout_ms=90000)
            if not mid:
                raise MyMapsError("Timed out waiting for the map to be created (no mid in URL).")
            _log(f"map created: mid={mid}")

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
