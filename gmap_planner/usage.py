"""Live API-usage lookup via Google Cloud Monitoring.

Reads real request counts for the Gemini and Geocoding APIs from the
`serviceruntime.googleapis.com/api/request_count` metric, scoped to a project,
and turns them into "percent of quota used" for the GUI gauges.

Needs a service account with `roles/monitoring.viewer` (the Monitoring API uses
OAuth, not an API key) and the Cloud project behind the API keys. Everything is
best-effort: any failure returns None so the GUI can degrade gracefully.

Caveats: Monitoring data lags a few minutes; `api/request_count` counts all API
requests (≈ quota consumption, not the exact per-metric quota counter); Google
quotas reset on Pacific time, so the windows are aligned to America/Los_Angeles.
"""

import datetime
import json
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import google.auth.transport.requests
from google.oauth2 import service_account

_PACIFIC = ZoneInfo("America/Los_Angeles")
_SCOPE = "https://www.googleapis.com/auth/monitoring.read"
_TIMESERIES_URL = "https://monitoring.googleapis.com/v3/projects/{project}/timeSeries"

GEOCODE_SERVICE = "geocoding-backend.googleapis.com"


def _rfc3339(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request_count(
    project: str,
    token: str,
    service: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> int:
    """Total API requests for `service` in [start, end] from Cloud Monitoring."""
    window_s = max(int((end - start).total_seconds()), 60)
    params = {
        "filter": (
            'metric.type="serviceruntime.googleapis.com/api/request_count" '
            'AND resource.type="consumed_api" '
            f'AND resource.label."service"="{service}"'
        ),
        "interval.startTime": _rfc3339(start),
        "interval.endTime": _rfc3339(end),
        "aggregation.alignmentPeriod": f"{window_s}s",
        "aggregation.perSeriesAligner": "ALIGN_SUM",
        "aggregation.crossSeriesReducer": "REDUCE_SUM",
    }
    url = _TIMESERIES_URL.format(project=project) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    total = 0.0
    for series in payload.get("timeSeries", []):
        for point in series.get("points", []):
            value = point.get("value", {})
            total += float(value.get("int64Value") or value.get("doubleValue") or 0)
    return int(total)


def _gauge(used: int, limit: int) -> dict:
    pct = 0.0 if limit <= 0 else min(max(used / limit * 100.0, 0.0), 100.0)
    return {"used": used, "limit": limit, "pct": pct}


def get_api_usage(
    *,
    project_id: str,
    sa_info: dict,
    geo_monthly_limit: int,
) -> dict | None:
    """Return {'geocode': {...}} or None on any failure.

    Geocoding usage is for the current month (Pacific, matching Google's quota
    reset window).
    """
    try:
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=[_SCOPE]
        )
        creds.refresh(google.auth.transport.requests.Request())
        token = creds.token

        now = datetime.datetime.now(tz=_PACIFIC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)

        geo_used = _request_count(project_id, token, GEOCODE_SERVICE, month_start, now)

        return {"geocode": _gauge(geo_used, geo_monthly_limit)}
    except Exception:
        return None
