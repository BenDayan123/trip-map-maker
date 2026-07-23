"""In-app self-update via GitHub Releases.

Checks the repo's latest GitHub release, compares its tag to the bundled
``__version__``, and (when the packaged app is running) downloads the matching
installer asset and launches it to update in place — no manual reinstall.

Apply strategy (deliberately simple, for a 2-user personal app):
- **Windows**: run the Inno Setup installer with ``/SILENT`` + Restart Manager
  flags. Inno closes the running app, updates the files, and relaunches it.
- **macOS**: open the downloaded ``.dmg`` so the user drags the new app over
  the old one (the app is unsigned, so a fully silent swap isn't worth the
  Gatekeeper/quarantine fight here).

Everything is best-effort: any network/parse failure returns ``None`` so a
missing internet connection can never break app startup.
"""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from . import __version__
from .config import GITHUB_REPO

_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_UA = "trip-map-maker"

@dataclass
class UpdateInfo:
    current: str
    latest: str
    notes: str
    html_url: str
    asset_name: str
    asset_url: str

    @property
    def has_update(self) -> bool:
        return _is_newer(self.latest, self.current)

    @property
    def has_asset(self) -> bool:
        """Whether the latest release actually ships an installer for this OS."""
        return bool(self.asset_url)


def current_version() -> str:
    return __version__


def _parse_ver(s: str) -> tuple:
    """'v1.2.0' -> (1, 2, 0). Non-numeric parts degrade to 0."""
    s = (s or "").strip().lstrip("vV")
    out = []
    for part in s.split("."):
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return tuple(out)


def _is_newer(latest: str, current: str) -> bool:
    a, b = _parse_ver(latest), _parse_ver(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _platform_asset(assets: list[dict]) -> dict | None:
    """Pick the release asset for this OS (Windows .exe / macOS .dmg)."""
    if sys.platform.startswith("win"):
        exts = (".exe",)
    elif sys.platform == "darwin":
        exts = (".dmg",)
    else:
        return None
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(exts):
            return a
    return None


def check_for_update(repo: str = GITHUB_REPO, timeout: int = 8) -> UpdateInfo | None:
    """Query the latest GitHub release. Returns UpdateInfo (any version) or None
    on any failure. Callers use ``.has_update`` to decide whether to act."""
    try:
        import requests

        r = requests.get(
            _API_LATEST.format(repo=repo),
            headers={"Accept": "application/vnd.github+json", "User-Agent": _UA},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        # Reachable → always return info. A missing OS asset is a *different*
        # state from "unreachable" (None), so the UI can say so honestly instead
        # of claiming you're offline. `has_asset` reports whether a download exists.
        asset = _platform_asset(data.get("assets") or []) or {}
        return UpdateInfo(
            current=current_version(),
            latest=(data.get("tag_name") or "").lstrip("vV"),
            notes=data.get("body") or "",
            html_url=data.get("html_url") or "",
            asset_name=asset.get("name") or "",
            asset_url=asset.get("browser_download_url") or "",
        )
    except Exception:
        return None


def download_asset(url: str, name: str, progress=None) -> str:
    """Stream a release asset to a temp file. Returns the local path."""
    import requests

    dest = os.path.join(tempfile.gettempdir(), name)
    with requests.get(url, stream=True, headers={"User-Agent": _UA}, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(done / total, 1.0))
    return dest


def apply_update(installer_path: str) -> None:
    """Launch the downloaded installer to update in place.

    Windows: run Inno silently; its Restart Manager closes the running app,
    updates, and relaunches it. macOS: open the .dmg for a drag-install.
    Raises RuntimeError if called outside the packaged app.
    """
    if not getattr(sys, "frozen", False):
        raise RuntimeError(
            "Self-update only runs in the packaged app. In a dev checkout, "
            "pull the new code instead."
        )
    if sys.platform.startswith("win"):
        # DETACHED so the installer outlives the app we're about to kill.
        DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            close_fds=True,
            creationflags=DETACHED,
        )
        # Inno can't overwrite files this app holds open, and Restart Manager
        # can't reliably close the pywebview host + its Streamlit child — that's
        # what left the app stuck on "Updating…". Quit the whole app ourselves so
        # the files are free; installer.iss [Run] relaunches it when done.
        # NO /T: the installer above is our child, and /T ("and any child
        # processes") would kill it along with us — that's what made the update
        # download, close the app, and then silently do nothing. /IM alone
        # already matches every copy of the exe (host + Streamlit child).
        subprocess.Popen(
            ["taskkill", "/F", "/IM", os.path.basename(sys.executable)],
            close_fds=True,
            creationflags=DETACHED,
        )
    elif sys.platform == "darwin":
        subprocess.Popen(["open", installer_path])
    else:
        raise RuntimeError(f"Unsupported platform for self-update: {sys.platform}")
