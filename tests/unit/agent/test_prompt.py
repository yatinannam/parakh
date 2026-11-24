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
    assert "Dr. Rao" in prompt
    assert "Dr. Iyer" in prompt
    assert "Parakh Clinic" in prompt


def test_prompt_spells_doctor_in_full() -> None:
    assert (
        "Always write the word Doctor in full, in every language and script; never abbreviate "
        "it as Dr. or डॉ." in system_prompt(load_config())
    )
