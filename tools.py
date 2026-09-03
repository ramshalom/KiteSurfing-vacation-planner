"""
tools.py

Custom tools used by the agents, beyond the built-in SerperDevTool:

- fetch_wind_data(): a PLAIN Python function (not an LLM tool call) that
  pulls REAL 5-year historical wind data from Open-Meteo (free, no API key)
  in ONE pass per year, producing both:
    - a per-year summary (avg sustained/gust wind, kitesurfable days)
    - an hour-by-hour heatmap (09:00-18:00) of avg sustained ("min") and
      avg gust ("max") wind, for the color-coded table in the UI
  Both come from the SAME underlying hourly data, so they can never
  disagree with each other. crew.py calls this directly and attaches the
  result to each candidate - no LLM transcription step involved.
- WindHistoryTool: a thin CrewAI tool wrapper around the summary part, in
  case an agent wants to reference the data during its own reasoning.
- ImageSearchTool: pulls real destination photo URLs via Serper's image
  search endpoint (uses the same SERPER_API_KEY you already have).
"""

import os
import re
import statistics
from collections import defaultdict
from datetime import date
from typing import Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

KITESURF_MIN_KNOTS = 12  # rough threshold for "kitesurfable" wind
HEATMAP_HOURS = list(range(9, 19))  # 09:00 to 18:00 inclusive


def _geocode(location: str):
    """
    Try to resolve a place name to (lat, lon), with fallbacks for the kind
    of names a Destination Scout tends to produce (e.g. "Boracay (Bulabog
    Beach), Philippines") that the free geocoder often can't match exactly.
    Returns (None, None) if nothing works.
    """
    candidates = [location]

    # Strip parenthetical detail: "Boracay (Bulabog Beach), Philippines" -> "Boracay, Philippines"
    no_parens = re.sub(r"\s*\([^)]*\)", "", location).strip()
    if no_parens and no_parens != location:
        candidates.append(no_parens)

    # Try just the part before the first comma: "Boracay, Philippines" -> "Boracay"
    first_segment = no_parens.split(",")[0].strip()
    if first_segment and first_segment not in candidates:
        candidates.append(first_segment)

    # Try just the last segment (often the country): "Boracay, Philippines" -> "Philippines"
    last_segment = no_parens.split(",")[-1].strip()
    if last_segment and last_segment not in candidates:
        candidates.append(last_segment)

    for name in candidates:
        try:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": name, "count": 1},
                timeout=15,
            ).json()
            results = geo.get("results")
            if results:
                return results[0]["latitude"], results[0]["longitude"]
        except Exception:
            continue
    return None, None


# ---------------------------------------------------------------------------
# Wind data - plain function (source of truth, called directly from crew.py)
# ---------------------------------------------------------------------------

def fetch_wind_data(location: str, start_month_day: str, end_month_day: str) -> dict:
    """
    Returns:
      {
        "yearly": [{"year", "avg_wind_min_knots", "avg_wind_max_knots",
                     "kitesurfable_days", "total_days"}, ...],   # 5 rows, newest year first
        "heatmap": {
            "2025": {"avg_min": {"09:00": 6.7, ...}, "avg_max": {"09:00": 8.9, ...}},
            "2024": {...}, ...
        },
        "summary": "one-line overall summary text",
      }
    or {"error": str} if the lookup failed entirely.

    Definitions (per user's spec):
      - "min" series = average SUSTAINED wind speed (wind_speed_10m) at a
        given hour, averaged across the days in that year's travel window.
      - "max" series = average GUST wind speed (wind_gusts_10m) at a given
        hour, averaged the same way. Each is one measurement per hour per
        day - no sub-hourly data needed.
    """
    try:
        lat, lon = _geocode(location)
        if lat is None:
            return {"error": f"No coordinates found for '{location}'. Try a more specific place name."}

        this_year = date.today().year
        yearly = []
        heatmap = {}

        for years_back in range(1, 6):
            year = this_year - years_back
            start_date = f"{year}-{start_month_day}"
            end_date = f"{year}-{end_month_day}"
            # Each year's request gets its OWN try/except: a single slow/failed
            # request (timeout, transient 5xx, etc.) used to bubble up to the
            # outer except and throw away every other year's data too - so one
            # bad year could silently wipe out the whole candidate's 5-year
            # history. Now a failed year is just skipped, same as a year with
            # no usable data.
            try:
                resp = requests.get(
                    "https://archive-api.open-meteo.com/v1/archive",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "start_date": start_date,
                        "end_date": end_date,
                        "hourly": "wind_speed_10m,wind_gusts_10m",
                        "wind_speed_unit": "kn",
                        "timezone": "auto",
                    },
                    timeout=20,
                ).json()
            except Exception:
                continue
            hourly = resp.get("hourly", {})
            times = hourly.get("time", [])
            sustained = hourly.get("wind_speed_10m", [])
            gusts = hourly.get("wind_gusts_10m", [])

            by_hour_sustained = defaultdict(list)
            by_hour_gust = defaultdict(list)
            daily_max_sustained = defaultdict(list)

            for i, t in enumerate(times):
                s = sustained[i] if i < len(sustained) else None
                g = gusts[i] if i < len(gusts) else None
                if s is None:
                    continue
                day, hour = t[:10], int(t[11:13])
                by_hour_sustained[hour].append(s)
                daily_max_sustained[day].append(s)
                if g is not None:
                    by_hour_gust[hour].append(g)

            if not by_hour_sustained:
                continue

            # --- heatmap rows for this year (09:00-18:00 only) ---
            avg_min_by_hour = {
                f"{h:02d}:00": round(statistics.mean(by_hour_sustained[h]), 1)
                for h in HEATMAP_HOURS if by_hour_sustained.get(h)
            }
            avg_max_by_hour = {
                f"{h:02d}:00": round(statistics.mean(by_hour_gust[h]), 1)
                for h in HEATMAP_HOURS if by_hour_gust.get(h)
            }
            heatmap[str(year)] = {"avg_min": avg_min_by_hour, "avg_max": avg_max_by_hour}

            # --- per-year summary row (same underlying data, all hours) ---
            all_sustained = [v for vals in by_hour_sustained.values() for v in vals]
            all_gust = [v for vals in by_hour_gust.values() for v in vals]
            day_maxes = [max(vals) for vals in daily_max_sustained.values() if vals]
            kitesurfable_days = sum(1 for m in day_maxes if m >= KITESURF_MIN_KNOTS)

            yearly.append({
                "year": year,
                "avg_wind_min_knots": round(statistics.mean(all_sustained), 1) if all_sustained else 0.0,
                "avg_wind_max_knots": round(statistics.mean(all_gust), 1) if all_gust else 0.0,
                "kitesurfable_days": kitesurfable_days,
                "total_days": len(day_maxes),
            })

        if not yearly:
            return {"error": f"No historical wind data available for {location} in that window."}

        overall_avg_max = statistics.mean([y["avg_wind_max_knots"] for y in yearly])
        overall_pct = 100 * sum(y["kitesurfable_days"] for y in yearly) / max(sum(y["total_days"] for y in yearly), 1)
        summary = (
            f"5-year avg gust wind {overall_avg_max:.1f} kn for this window; "
            f"{overall_pct:.0f}% of days met the {KITESURF_MIN_KNOTS}kt kitesurfable threshold."
        )
        return {"yearly": yearly, "heatmap": heatmap, "summary": summary}

    except Exception as e:
        return {"error": f"Wind history lookup failed for {location}: {e}"}


# ---------------------------------------------------------------------------
# Wind history tool (thin wrapper, for agents that want to reason over it too)
# ---------------------------------------------------------------------------

class WindHistoryInput(BaseModel):
    location: str = Field(description="Place name, e.g. 'Dakhla, Morocco'")
    start_month_day: str = Field(description="Start of travel window as MM-DD, e.g. '10-05'")
    end_month_day: str = Field(description="End of travel window as MM-DD, e.g. '10-12'")


class WindHistoryTool(BaseTool):
    name: str = "wind_history_lookup"
    description: str = (
        "Look up REAL 5-year historical wind speed data for a location and "
        "a recurring date window (month-day range, e.g. Oct 5 - Oct 12 across "
        "the last 5 years). Returns each year's average sustained/gust wind "
        "speed in knots and the percentage of days that were kitesurfable "
        "(>=12 knots)."
    )
    args_schema: Type[BaseModel] = WindHistoryInput

    def _run(self, location: str, start_month_day: str, end_month_day: str) -> str:
        data = fetch_wind_data(location, start_month_day, end_month_day)
        if "error" in data:
            return data["error"]
        lines = [
            f"  {y['year']}: avg sustained {y['avg_wind_min_knots']} kn / avg gust {y['avg_wind_max_knots']} kn, "
            f"{y['kitesurfable_days']}/{y['total_days']} days kitesurfable"
            for y in data["yearly"]
        ]
        return (
            f"5-YEAR WIND HISTORY for {location} ({start_month_day} to {end_month_day}):\n"
            + "\n".join(lines) + f"\nOverall: {data['summary']}"
        )


# ---------------------------------------------------------------------------
# Image search tool
# ---------------------------------------------------------------------------

class ImageSearchInput(BaseModel):
    query: str = Field(description="What to search images for, e.g. 'Dakhla Morocco kitesurfing beach'")


class ImageSearchTool(BaseTool):
    name: str = "image_search"
    description: str = (
        "Search the web for real photos of a place. Returns up to 3 image URLs. "
        "Use this to find photos of candidate kitesurfing destinations."
    )
    args_schema: Type[BaseModel] = ImageSearchInput

    def _run(self, query: str) -> str:
        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            return "SERPER_API_KEY not set - cannot search images."
        try:
            resp = requests.post(
                "https://google.serper.dev/images",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 3},
                timeout=15,
            ).json()
            images = resp.get("images", [])[:3]
            urls = [img.get("imageUrl") for img in images if img.get("imageUrl")]
            if not urls:
                return f"No images found for '{query}'."
            return "Image URLs:\n" + "\n".join(urls)
        except Exception as e:
            return f"Image search failed for '{query}': {e}"
