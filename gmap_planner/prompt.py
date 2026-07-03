GEMINI_EXTRACTION_PROMPT = """\
You are a travel data extraction assistant.
Analyze the provided travel itinerary and extract EVERY single location to visit — including landmarks, restaurants, temples, parks, shopping streets, neighborhoods, specific streets, and any other place mentioned or suggested.
Do NOT skip any location, even if it seems minor (e.g., a street to stroll, a market, a viewpoint).
Return ONLY a single valid JSON object — no markdown fences, no extra text.
Format the output STRICTLY as a valid JSON array.

Schema:
{
  "trip_name": "<short descriptive name with only the names of the people traveling (in hebrew)>",
  "days": [
    {
      "day": <integer starting at 1>,
      "date": "<DD/MM or empty string>",
      "locations": [
        {
          "name": "<Full place name, City — do NOT include country>",
          "lat": <decimal latitude>,
          "lng": <decimal longitude>,
          "notes": "<1-2 sentence description or tip in Hebrew, its can be from the attached file>"
        }
      ]
    }
  ]
}

Rules:
- Extract EVERY location mentioned or suggested for each day — err on the side of including more.
- Every location MUST have realistic lat/lng coordinates from your world knowledge (get this info from google maps, otherwise other sources).
- Date must be in DD/MM format (e.g., 15/06). If date cannot be determined, use empty string.
- Do NOT omit any day or location mentioned in the document.
- Output ONLY the JSON object. No markdown, no explanation.
"""
