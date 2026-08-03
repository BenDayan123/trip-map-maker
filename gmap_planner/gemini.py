"""Gemini extraction stage: file loading + itinerary extraction."""

import json
import os

from google import genai
from google.genai import types

from .config import GEMINI_MODEL
from .errors import PipelineError
from .prompt import GEMINI_EXTRACTION_PROMPT

# Structured-output schema: forces Gemini to return JSON matching the shape the
# pipeline expects, instead of best-effort JSON that occasionally comes back
# wrapped in prose/markdown or malformed. Mirrors the schema in prompt.py.
_LOCATION = types.Schema(
    type=types.Type.OBJECT,
    required=["name", "lat", "lng", "notes"],
    properties={
        "name": types.Schema(type=types.Type.STRING),
        "lat": types.Schema(type=types.Type.NUMBER),
        "lng": types.Schema(type=types.Type.NUMBER),
        "notes": types.Schema(type=types.Type.STRING),
    },
)
_DAY = types.Schema(
    type=types.Type.OBJECT,
    required=["day", "date", "locations"],
    properties={
        "day": types.Schema(type=types.Type.INTEGER),
        "date": types.Schema(type=types.Type.STRING),
        "locations": types.Schema(type=types.Type.ARRAY, items=_LOCATION),
    },
)
_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=["trip_name", "days"],
    properties={
        "trip_name": types.Schema(type=types.Type.STRING),
        "days": types.Schema(type=types.Type.ARRAY, items=_DAY),
    },
)


# A bad response is usually a one-off (truncation, a blocked/empty candidate), and
# sampling is stochastic, so one plain retry fixes most of them.
ATTEMPTS = 2
# NB: max_output_tokens is deliberately NOT set — unset means the model's own
# maximum (65536 for gemini-3.1-flash-lite, `client.models.get(...)`), and any
# value we pick here can only lower the ceiling and cause the mid-JSON truncation
# this retry exists to survive.


class _BadResponse(PipelineError):
    """The call succeeded but its body is unusable (truncated, empty, wrong shape).

    Marker for the one failure that's worth retrying: a transport/auth/quota error
    fails the same way every time, so retrying it just doubles the wait and the
    input tokens.
    """


def _finish_reason(response) -> str:
    """Best-effort finish reason (MAX_TOKENS, SAFETY, …) — the usual cause of
    malformed/empty JSON. Returned as a short tag, never the response body."""
    try:
        return str(response.candidates[0].finish_reason)
    except Exception:
        return "unknown"


def load_file_for_gemini(file_path: str, client: genai.Client) -> tuple[list, str]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".txt":
        with open(file_path, encoding="utf-8") as f:
            text = f.read()
        return [GEMINI_EXTRACTION_PROMPT, text], "inline TXT"

    try:
        uploaded = client.files.upload(file=file_path)
    except Exception as e:
        raise PipelineError(
            f"Gemini Files API failed to upload {os.path.basename(file_path)!r}: {e}"
        ) from e
    return [GEMINI_EXTRACTION_PROMPT, uploaded], "PDF via Files API"


def _extract_once(parts: list, client: genai.Client) -> dict:
    """One extraction call. Raises _BadResponse for an unusable body, PipelineError
    for a failed request."""
    response = None
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
            ),
        )
        data = json.loads(response.text)
    except (json.JSONDecodeError, TypeError) as e:
        # response_schema makes this rare; when it still happens it's usually a
        # truncated (MAX_TOKENS) or blocked (SAFETY) response, not real prose.
        # Report the cause, never the raw JSON body.
        raise _BadResponse(
            "Gemini API (location extraction) returned invalid/empty JSON "
            f"(finish_reason: {_finish_reason(response)})."
        ) from e
    except Exception as e:
        raise PipelineError(f"Gemini API (location extraction) request failed: {e}") from e

    if not isinstance(data, dict) or "trip_name" not in data or "days" not in data:
        raise _BadResponse(
            "Gemini API (location extraction) response is missing required "
            "fields ('trip_name', 'days')."
        )
    return data


def extract_itinerary(parts: list, client: genai.Client) -> dict:
    """Extract the itinerary, retrying once on an unusable response body.

    A failed *request* (bad key, quota, network) is raised on the first attempt —
    retrying it would only double the wait and re-upload the whole itinerary.
    """
    last = PipelineError("Gemini API (location extraction) was never called.")
    for attempt in range(ATTEMPTS):
        try:
            return _extract_once(parts, client)
        except _BadResponse as e:
            last = e
            if attempt + 1 < ATTEMPTS:
                print(f"  [gemini] {e} Retrying…", flush=True)
    raise last
