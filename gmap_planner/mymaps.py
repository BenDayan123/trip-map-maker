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
    for channel in ("chrome", "msedge", None):
        try:
            if channel:
                return pw.chromium.launch_persistent_context(channel=channel, **common)
            return pw.chromium.launch_persistent_context(**common)
        except Exception:
            continue
    # Last resort: plain bundled Chromium with defaults.
    return pw.chromium.launch_persistent_context(profile_dir, headless=headless)


def _set_kml_on_any_frame(page, kml_path: str, timeout_ms: int = 30000) -> bool:
    """Find the (often hidden) <input type=file> across all frames and set the KML.

    Setting the file input directly is far more robust than clicking the Google
    Picker "Browse" button, which lives in a cross-origin iframe.
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for frame in page.frames:
            try:
                inp = frame.query_selector("input[type=file]")
            except Exception:
                inp = None
            if inp is not None:
                inp.set_input_files(kml_path)
                return True
        page.wait_for_timeout(500)
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
    page.goto(MYMAPS_HOME_URL, wait_until="load")

    # If not signed in, the home page shows a Sign-in prompt instead of the editor.
    if page.get_by_text(SEL_SIGNED_OUT).count() and not page.get_by_text(SEL_CREATE_NEW).count():
        raise MyMapsError(
            "Not signed in to Google. Run `python main.py --login` once and sign in."
        )

    # The create action may open the editor in a new tab; handle both cases.
    try:
        with context.expect_page(timeout=4000) as new_page_info:
            page.get_by_text(SEL_CREATE_NEW).first.click()
        editor = new_page_info.value
    except Exception:
        page.get_by_text(SEL_CREATE_NEW).first.click()
        editor = page
    editor.wait_for_load_state("load")
    return editor


def _set_title(editor, title: str) -> None:
    """Rename the map from 'Untitled map' to `title` via the title dialog."""
    try:
        editor.get_by_text(SEL_UNTITLED_MAP).first.click(timeout=8000)
        # The dialog's first text input is the map title.
        box = editor.locator("input[type=text], textarea").first
        box.fill(title)
        editor.get_by_role("button", name=SEL_SAVE).first.click()
        editor.wait_for_timeout(1000)
    except Exception:
        # Title is cosmetic — never fail the whole run over it.
        pass


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
            # Open the importer on the base layer, then feed it the KML file.
            editor.get_by_text(SEL_IMPORT).first.click(timeout=15000)
            if not _set_kml_on_any_frame(editor, kml_path):
                raise MyMapsError("Could not find the file-upload input in the import dialog.")

            # Importing triggers the first save, which is when `mid` appears.
            mid = _wait_for_mid(editor, timeout_ms=90000)
            if not mid:
                raise MyMapsError("Timed out waiting for the map to be created (no mid in URL).")

            _set_title(editor, title)
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
