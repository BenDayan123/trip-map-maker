"""Share a My Maps map with specific people via the Google Drive API.

A My Maps map is a Drive file (mimeType ``application/vnd.google-apps.map``), so
once the browser step (`mymaps.py`) gives us the map's id (`mid`), the Drive
``permissions.create`` endpoint grants people access — far more reliable than
driving the share dialog in the UI.

Auth is the standard installed-app OAuth flow: a `credentials.json` OAuth client
(downloaded from Google Cloud Console) plus a cached `token.json`. Full ``drive``
scope is required because the map was created in the browser, not by this app.
"""

import os

from .config import (
    DRIVE_CREDENTIALS_FILE as _CRED,
    DRIVE_ROLE_ALIASES,
    DRIVE_SCOPES,
    DRIVE_TOKEN_FILE,
    MYMAPS_MAP_MIME,
)
from .errors import PipelineError


class DriveShareError(PipelineError):
    """Drive sharing failed (auth, missing credentials, API error)."""


def _import_google():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:  # pragma: no cover - dependency hint
        raise DriveShareError(
            "Google Drive libraries missing. Run: pip install -r requirements.txt"
        ) from e
    return Request, Credentials, InstalledAppFlow, build


def get_drive_service(
    credentials_path: str = _CRED,
    token_path: str = DRIVE_TOKEN_FILE,
):
    """Build an authenticated Drive v3 service, running the OAuth consent if needed."""
    Request, Credentials, InstalledAppFlow, build = _import_google()

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, DRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise DriveShareError(
                    f"Drive OAuth client '{credentials_path}' not found. Create an "
                    "OAuth 2.0 Desktop client in Google Cloud Console, enable the "
                    "Drive API, and download it as credentials.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def normalize_role(role: str) -> str:
    """Map a friendly role (viewer/editor/...) to a Drive permission role."""
    key = (role or "reader").strip().lower()
    if key not in DRIVE_ROLE_ALIASES:
        raise DriveShareError(
            f"Unknown share role '{role}'. Use one of: "
            f"{', '.join(sorted(set(DRIVE_ROLE_ALIASES)))}."
        )
    return DRIVE_ROLE_ALIASES[key]


def _resolve_file_id(service, mid: str, title: str | None) -> str:
    """Confirm `mid` is a reachable Drive map; fall back to a title search."""
    try:
        service.files().get(fileId=mid, fields="id").execute()
        return mid
    except Exception:
        pass
    if title:
        q = (
            f"mimeType='{MYMAPS_MAP_MIME}' and name='{title}' and trashed=false"
        )
        resp = service.files().list(
            q=q, orderBy="modifiedTime desc", pageSize=1, fields="files(id)"
        ).execute()
        files = resp.get("files", [])
        if files:
            return files[0]["id"]
    raise DriveShareError(
        f"Could not locate the map in Drive (mid={mid}, title={title!r})."
    )


def share_map(
    mid: str,
    emails: list[str],
    role: str = "reader",
    *,
    title: str | None = None,
    credentials_path: str = _CRED,
    token_path: str = DRIVE_TOKEN_FILE,
    service=None,
    notify: bool = True,
) -> list[str]:
    """Grant `emails` access to the map `mid` at `role`. Returns emails shared with.

    `service` may be passed to reuse one Drive client across many maps.
    """
    if not emails:
        return []
    drive_role = normalize_role(role)
    service = service or get_drive_service(credentials_path, token_path)
    file_id = _resolve_file_id(service, mid, title)

    shared: list[str] = []
    for email in emails:
        email = email.strip()
        if not email:
            continue
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": drive_role, "emailAddress": email},
                sendNotificationEmail=notify,
                fields="id",
            ).execute()
            shared.append(email)
        except Exception as e:
            raise DriveShareError(f"Failed to share map with {email}: {e}") from e
    return shared
