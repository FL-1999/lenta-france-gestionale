from __future__ import annotations

import os

from services.gps_tracking import GPSProviderAdapter, NullGPSProviderAdapter


def get_gps_provider_adapter() -> GPSProviderAdapter:
    """Factory placeholder: wire real provider adapter here when available."""
    provider_key = (os.getenv("GPS_PROVIDER") or "").strip().lower()
    if provider_key:
        # Provider requested but no adapter wired yet.
        return NullGPSProviderAdapter()
    return NullGPSProviderAdapter()
