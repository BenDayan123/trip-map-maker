"""Self-check for the extraction retry.

Run it with `python gmap_planner/test_gemini_extract.py` (it lives in the package
because /tests is gitignored).

Covers the bug it exists for: a truncated/empty Gemini response used to fail the
whole run, so one bad roll of the dice meant no map.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmap_planner.errors import PipelineError
from gmap_planner.gemini import extract_itinerary

GOOD = '{"trip_name": "טיול", "days": [{"day": 1, "date": "01/06", "locations": []}]}'


class FakeClient:
    """Stands in for genai.Client: replies with the next canned response text."""

    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0
        client = self

        class Models:
            def generate_content(self, **_kw):
                client.calls += 1
                return type("R", (), {"text": client.texts.pop(0), "candidates": []})()

        self.models = Models()


def test_good_response_is_returned_without_a_retry():
    client = FakeClient(GOOD)
    assert extract_itinerary([], client)["trip_name"] == "טיול"
    assert client.calls == 1


def test_truncated_json_is_retried():
    # Truncated mid-object — what a MAX_TOKENS cut-off looks like.
    client = FakeClient('{"trip_name": "טיול", "days": [{"day": 1, "loc', GOOD)
    assert extract_itinerary([], client)["days"][0]["day"] == 1
    assert client.calls == 2


def test_empty_response_is_retried():
    client = FakeClient(None, GOOD)
    assert extract_itinerary([], client)["trip_name"] == "טיול"
    assert client.calls == 2


def test_valid_json_missing_the_required_fields_is_retried():
    client = FakeClient('{"days": []}', GOOD)
    assert extract_itinerary([], client)["trip_name"] == "טיול"
    assert client.calls == 2


class ExplodingClient:
    """generate_content itself fails — a transport/auth/quota error, not a bad body."""

    def __init__(self):
        self.calls = 0
        client = self

        class Models:
            def generate_content(self, **_kw):
                client.calls += 1
                raise RuntimeError("429 RESOURCE_EXHAUSTED")

        self.models = Models()


def test_a_failed_request_is_not_retried():
    # Retrying a quota/auth failure only doubles the wait and re-uploads the PDF.
    client = ExplodingClient()
    try:
        extract_itinerary([], client)
    except PipelineError as e:
        assert "request failed" in str(e), e
    else:
        raise AssertionError("expected PipelineError")
    assert client.calls == 1, client.calls


def test_two_bad_responses_raise_a_clean_error():
    client = FakeClient("not json", "still not json")
    try:
        extract_itinerary([], client)
    except PipelineError as e:
        assert "invalid/empty JSON" in str(e), e
        # The raw model output must never leak into the message.
        assert "not json" not in str(e), e
    else:
        raise AssertionError("expected PipelineError")
    assert client.calls == 2


if __name__ == "__main__":
    test_good_response_is_returned_without_a_retry()
    test_truncated_json_is_retried()
    test_empty_response_is_retried()
    test_valid_json_missing_the_required_fields_is_retried()
    test_a_failed_request_is_not_retried()
    test_two_bad_responses_raise_a_clean_error()
    print("ok")
