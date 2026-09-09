"""Current weather for the essentials page.

Uses Open-Meteo: free, no API key, no account, no rate-limit paperwork. That
matters for something polled all day on a desk panel.

Location is resolved once and cached. WEATHER_LAT/WEATHER_LON in config win;
otherwise it falls back to the public IP, which is worth distrusting -- it
reports wherever the ISP breaks out, which on this connection was about 160 km
from the actual desk. Either way the lookup happens once and is cached.

Open-Meteo answers for any coordinate by interpolating its forecast grid, so
asking for an exact point automatically yields the nearest available data. The
grid point that answered is reported back as grid_lat/grid_lon.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .config import STATE_DIR

log = logging.getLogger("phonedeck.weather")

LOCATION_CACHE = STATE_DIR / "location.json"
FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
    "weather_code,wind_speed_10m,is_day"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    "&forecast_days=1&timezone=auto"
)
GEO_URL = "http://ip-api.com/json/?fields=status,city,regionName,country,lat,lon"

# Weather is not a fast-moving quantity, and the panel runs all day.
REFRESH_SECONDS = 600.0
RETRY_SECONDS = 60.0

# WMO weather codes, condensed to something that fits a small panel.
WMO = {
    0: ("Clear", "☀"), 1: ("Mainly clear", "🌤"), 2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁"), 45: ("Fog", "🌫"), 48: ("Rime fog", "🌫"),
    51: ("Light drizzle", "🌦"), 53: ("Drizzle", "🌦"), 55: ("Heavy drizzle", "🌦"),
    56: ("Freezing drizzle", "🌧"), 57: ("Freezing drizzle", "🌧"),
    61: ("Light rain", "🌦"), 63: ("Rain", "🌧"), 65: ("Heavy rain", "🌧"),
    66: ("Freezing rain", "🌧"), 67: ("Freezing rain", "🌧"),
    71: ("Light snow", "🌨"), 73: ("Snow", "🌨"), 75: ("Heavy snow", "❄"),
    77: ("Snow grains", "🌨"), 80: ("Showers", "🌦"), 81: ("Showers", "🌧"),
    82: ("Violent showers", "⛈"), 85: ("Snow showers", "🌨"),
    86: ("Snow showers", "🌨"), 95: ("Thunderstorm", "⛈"),
    96: ("Thunderstorm, hail", "⛈"), 99: ("Thunderstorm, hail", "⛈"),
}


def _get_json(url: str, timeout: float = 10.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "PhoneDeck"})
    with urllib.request.urlopen(request, timeout=timeout) as fh:
        return json.load(fh)


def _cached_location() -> dict[str, Any] | None:
    try:
        return json.loads(LOCATION_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_location(found: dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LOCATION_CACHE.write_text(json.dumps(found, indent=2), encoding="utf-8")
    except OSError:
        pass


def _reverse_geocode(lat: float, lon: float) -> str | None:
    """A human name for a coordinate. Keyless, and called at most once."""
    try:
        data = _get_json(
            "https://api.bigdatacloud.net/data/reverse-geocode-client"
            f"?latitude={lat}&longitude={lon}&localityLanguage=en")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    parts = [data.get("locality"), data.get("principalSubdivision"),
             data.get("countryName")]
    return ", ".join(p for p in parts if p) or None


def resolve_location(lat: float | None, lon: float | None,
                     place: str | None = None) -> dict[str, Any] | None:
    """Where to report weather for. Configured values beat everything."""
    if lat is not None and lon is not None:
        if place:
            return {"lat": lat, "lon": lon, "place": place}

        # Reuse the cached name only if it belongs to these coordinates --
        # otherwise a changed config would keep the old town's label.
        cached = _cached_location()
        if (cached and abs(cached.get("lat", 0) - lat) < 1e-6
                and abs(cached.get("lon", 0) - lon) < 1e-6
                and cached.get("place")):
            return cached

        found = {"lat": lat, "lon": lon,
                 "place": _reverse_geocode(lat, lon) or f"{lat:.3f}, {lon:.3f}"}
        _write_location(found)
        log.info("weather location (from config): %s", found["place"])
        return found

    cached = _cached_location()
    if cached:
        return cached

    try:
        data = _get_json(GEO_URL)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        log.info("could not look up location from IP")
        return None
    if data.get("status") != "success":
        return None

    place = ", ".join(p for p in (data.get("city"), data.get("country")) if p)
    found = {"lat": data["lat"], "lon": data["lon"], "place": place or "unknown"}
    _write_location(found)
    log.info("weather location: %s (%.2f, %.2f) -- edit .state/location.json "
             "or set the coordinates in config.py to change it",
             found["place"], found["lat"], found["lon"])
    return found


class Weather:
    """Refreshes in the background so a request never waits on the network."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None
        self._lat: float | None = None
        self._lon: float | None = None
        self._place: str | None = None

    def start(self, lat: float | None = None, lon: float | None = None,
              place: str | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._lat, self._lon, self._place = lat, lon, place
        self._thread = threading.Thread(target=self._loop, name="weather",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            ok = False
            try:
                ok = self._refresh()
            except Exception:  # noqa: BLE001 - weather must never break the panel
                log.exception("weather refresh failed")
            time.sleep(REFRESH_SECONDS if ok else RETRY_SECONDS)

    def _refresh(self) -> bool:
        place = resolve_location(self._lat, self._lon, self._place)
        if place is None:
            return False

        data = _get_json(FORECAST_URL.format(lat=place["lat"], lon=place["lon"]))
        current = data.get("current") or {}
        daily = data.get("daily") or {}
        code = int(current.get("weather_code", -1))
        label, symbol = WMO.get(code, ("—", "•"))

        def first(key: str) -> Any:
            values = daily.get(key) or []
            return values[0] if values else None

        with self._lock:
            self._data = {
                "place": place.get("place"),
                "temp": current.get("temperature_2m"),
                "feels": current.get("apparent_temperature"),
                "humidity": current.get("relative_humidity_2m"),
                "wind": current.get("wind_speed_10m"),
                "is_day": bool(current.get("is_day", 1)),
                "code": code,
                "label": label,
                "symbol": symbol,
                "high": first("temperature_2m_max"),
                "low": first("temperature_2m_min"),
                "rain_chance": first("precipitation_probability_max"),
                # The grid point that actually answered, which is the nearest
                # available data rather than the exact coordinate.
                "grid_lat": data.get("latitude"),
                "grid_lon": data.get("longitude"),
                "updated": time.time(),
            }
        return True

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._data) if self._data else None


weather = Weather()
