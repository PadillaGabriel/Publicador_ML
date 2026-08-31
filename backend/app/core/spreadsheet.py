from datetime import datetime
from zoneinfo import ZoneInfo


def excel_safe_value(value, timezone_name: str):
    """Convert timezone-aware datetimes into Excel-compatible local datetimes."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)
    return value
