"""Recompute the WER fields of a finished report from its stored transcripts."""

from parakh.report.model import TURN_NOT_REACHED, Report
from parakh.scenario import Scenario
from parakh.score.wer import conversation_wer, loose_wer, strict_wer


def rescore_report(report: Report, scenario: Scenario) -> Report:
    """Score the stored transcripts against the scenario's current references.

    Gives the values build_report gives for the same inputs. Turns beyond the
    scenario's turn count keep their reference and scores. Nothing else changes.
    """
    any_transcript = any(t.transcript.strip() for t in report.turns)
    turns = []
    for index, turn in enumerate(report.turns):
        if index >= len(scenario.turns):
            turns.append(turn)
            continue
        ref = scenario.turns[index].reference
        scored = turn.latency_reason != TURN_NOT_REACHED and any_transcript
        turns.append(
            turn.model_copy(
                update={
                    "reference": ref,
                    "strict_wer": strict_wer(ref, turn.transcript) if scored else None,
                    "loose_wer": loose_wer(ref, turn.transcript) if scored else None,
                }
            )
        )
    wer = conversation_wer([t.reference for t in turns], [[t.transcript] for t in turns])
    metrics = report.metrics.model_copy(
        update={
            "strict_wer": wer.strict_wer,
            "loose_wer": wer.loose_wer,
            "loose_cer": wer.loose_cer,
            "wer_reason": wer.reason,
            "script_unsupported_turns": wer.script_unsupported_turns,
        }
    )
    return report.model_copy(update={"turns": turns, "metrics": metrics})
