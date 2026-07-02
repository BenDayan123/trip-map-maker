"""Gemini extraction stage: file loading + itinerary extraction."""

import json
import os

from google import genai
from google.genai import types

from .config import GEMINI_MODEL
from .errors import PipelineError
from .prompt import GEMINI_EXTRACTION_PROMPT


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


def extract_itinerary(parts: list, client: genai.Client) -> dict:
    response = None
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )
        data = json.loads(response.text)
    except json.JSONDecodeError as e:
        raw = response.text if response else "<no response>"
        raise PipelineError(
            f"Gemini API (location extraction) returned invalid JSON: {e}\n"
            f"Raw response:\n{raw}"
        ) from e
    except PipelineError:
        raise
    except Exception as e:
        raise PipelineError(f"Gemini API (location extraction) request failed: {e}") from e

    if "trip_name" not in data or "days" not in data:
        raise PipelineError(
            "Gemini API (location extraction) response is missing required "
            "fields ('trip_name', 'days').\n"
            f"Raw response: {response.text}"
        )

    return data
