import pytest

from agents.clinic_agent.config import load_config
from agents.clinic_agent.prompt import system_prompt


def test_prompt_rules_and_date() -> None:
    prompt = system_prompt(load_config())
    assert (
        "You answer the phone, so open the call yourself: greet the caller and ask how you "
        "can help." in prompt
    )
    assert (
        "Never end the call before the caller has spoken, and end it only after the booking "
        "is confirmed or the caller says goodbye." in prompt
    )
    assert "2026-11-19" in prompt
    assert "Doctor Rao" in prompt
    assert "Doctor Iyer" in prompt
    assert "Parakh Clinic" in prompt


def test_prompt_spells_doctor_in_full() -> None:
    assert (
        "Always write the word Doctor in full, in every language and script; never abbreviate "
        "it as Dr. or डॉ." in system_prompt(load_config())
    )


def test_prompt_has_no_dr_outside_the_rule() -> None:
    from agents.clinic_agent.prompt import DOCTOR_RULE

    assert "Dr." not in system_prompt(load_config()).replace(DOCTOR_RULE, "")


@pytest.mark.parametrize(
    ("profile", "phrase"),
    [
        ("hi", "English, Hindi or Hinglish"),
        ("kn", "English, Kannada or Kannada-English"),
        ("ta", "English, Tamil or Tamil-English"),
    ],
)
def test_prompt_replies_in_profile_languages(profile: str, phrase: str) -> None:
    prompt = system_prompt(load_config(profile=profile))
    assert f"Reply in the caller's language style: {phrase}, matching" in prompt
    if profile != "hi":
        assert "Hindi" not in prompt
