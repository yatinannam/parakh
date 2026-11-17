"""In-memory booking store and the LLM tool schemas that expose it."""

import re
from datetime import date as Date
from datetime import time as Time
from typing import Any

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema

# Doctor id -> (opening, closing) in minutes after midnight.
DOCTOR_HOURS: dict[str, tuple[int, int]] = {
    "dr-rao": (9 * 60, 12 * 60),
    "dr-iyer": (14 * 60, 17 * 60),
}
SLOT_MINUTES = 30


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _parse_minutes(value: str) -> int | None:
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        return None
    try:
        parsed = Time.fromisoformat(value)
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        Date.fromisoformat(value)
    except ValueError:
        return False
    return True


class BookingStore:
    def __init__(self) -> None:
        self._booked: dict[tuple[str, str, str], dict[str, str]] = {}

    def available_slots(self, doctor: str, date: str) -> list[str]:
        hours = DOCTOR_HOURS.get(doctor)
        if hours is None:
            return []
        start, end = hours
        return [
            _fmt(m)
            for m in range(start, end, SLOT_MINUTES)
            if (doctor, date, _fmt(m)) not in self._booked
        ]

    def book_appointment(self, doctor: str, date: str, time: str, phone: str) -> dict[str, Any]:
        hours = DOCTOR_HOURS.get(doctor)
        if hours is None:
            return {"ok": False, "error": "unknown doctor; use dr-rao or dr-iyer"}
        if not _valid_date(date):
            return {"ok": False, "error": "date must be YYYY-MM-DD"}
        minutes = _parse_minutes(time)
        if minutes is None or minutes % SLOT_MINUTES != 0 or not hours[0] <= minutes < hours[1]:
            return {
                "ok": False,
                "error": "time must be HH:MM on a 30-minute slot between "
                f"{_fmt(hours[0])} and {_fmt(hours[1])}",
            }
        digits = re.sub(r"[\s-]", "", phone).removeprefix("+91")
        if not re.fullmatch(r"\d{10}", digits):
            return {"ok": False, "error": "phone must be exactly 10 digits"}
        key = (doctor, date, _fmt(minutes))
        if key in self._booked:
            return {"ok": False, "error": "time slot is already booked"}
        booking_id = f"bk-{len(self._booked) + 1:03d}"
        self._booked[key] = {"id": booking_id, "phone": digits}
        return {"ok": True, "id": booking_id}


def tool_schemas() -> ToolsSchema:
    doctor = {
        "type": "string",
        "enum": sorted(DOCTOR_HOURS),
        "description": "Doctor id: dr-rao (general physician) or dr-iyer (paediatrician).",
    }
    day = {"type": "string", "description": "Date as YYYY-MM-DD."}
    return ToolsSchema(
        standard_tools=[
            FunctionSchema(
                name="available_slots",
                description="List free 30-minute slots for a doctor on a date.",
                properties={"doctor": doctor, "date": day},
                required=["doctor", "date"],
            ),
            FunctionSchema(
                name="book_appointment",
                description="Book an appointment once the caller has confirmed the details.",
                properties={
                    "doctor": doctor,
                    "date": day,
                    "time": {"type": "string", "description": "Time as HH:MM, 24-hour."},
                    "phone": {"type": "string", "description": "10-digit phone number."},
                },
                required=["doctor", "date", "time", "phone"],
            ),
        ]
    )
