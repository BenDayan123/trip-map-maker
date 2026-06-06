"""Gemini extraction stage: file loading + itinerary extraction."""

import json
import os
import sys

from google import genai
from google.genai import types

from .config import GEMINI_MODEL
from .prompt import GEMINI_EXTRACTION_PROMPT


def load_file_for_gemini(file_path: str, client: genai.Client) -> tuple[list, str]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".txt":
        with open(file_path, encoding="utf-8") as f:
            text = f.read()
        return [GEMINI_EXTRACTION_PROMPT, text], "inline TXT"

    uploaded = client.files.upload(file=file_path)
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
        print(f"Error: Gemini returned invalid JSON ({e}).")
        print("Raw response:")
        print(response.text if response else "<no response>")
        sys.exit(1)
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        sys.exit(1)

    if "trip_name" not in data or "days" not in data:
        print("Error: Gemini response is missing required fields ('trip_name', 'days').")
        print("Raw response:", response.text)
        sys.exit(1)

    return data
