import pytest

from agents.clinic_agent.tools import BookingStore, tool_schemas


def test_book_valid() -> None:
    result = BookingStore().book_appointment("dr-rao", "2026-11-20", "10:30", "98450 12345")
    assert result["ok"] is True
    assert result["id"]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (("dr-x", "2026-11-20", "10:30", "9845012345"), "doctor"),
        (("dr-rao", "2026-11-20", "13:00", "9845012345"), "time"),
        (("dr-rao", "2026-11-20", "10:15", "9845012345"), "time"),
        (("dr-rao", "2026-11-20", "10:30", "12345"), "phone"),
        (("dr-rao", "20-11-2026", "10:30", "9845012345"), "date"),
    ],
)
def test_book_invalid(args: tuple[str, str, str, str], error: str) -> None:
    result = BookingStore().book_appointment(*args)
    assert result["ok"] is False
    assert error in result["error"]


def test_phone_formats_normalised() -> None:
    result = BookingStore().book_appointment("dr-iyer", "2026-11-20", "14:00", "+91-98450 12345")
    assert result["ok"] is True


def test_double_booking_rejected() -> None:
    store = BookingStore()
    assert store.book_appointment("dr-rao", "2026-11-20", "10:30", "9845012345")["ok"]
    second = store.book_appointment("dr-rao", "2026-11-20", "10:30", "9845012346")
    assert second["ok"] is False
    assert "time" in second["error"]


def test_available_slots() -> None:
    slots = BookingStore().available_slots("dr-rao", "2026-11-20")
    assert slots == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]


def test_available_slots_excludes_booked_and_unknown() -> None:
    store = BookingStore()
    store.book_appointment("dr-iyer", "2026-11-20", "14:30", "9845012345")
    slots = store.available_slots("dr-iyer", "2026-11-20")
    assert slots[0] == "14:00"
    assert "14:30" not in slots
    assert slots[-1] == "16:30"
    assert store.available_slots("dr-x", "2026-11-20") == []


def test_tool_schemas_names() -> None:
    names = {tool.name for tool in tool_schemas().standard_tools}
    assert names == {"book_appointment", "available_slots"}
