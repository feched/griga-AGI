import json
from pathlib import Path

import pytest

from griga.evaluation.multi_turn import (
    GraphCheck,
    Scenario,
    ScenarioTurn,
    load_scenarios,
    resolve_intent,
    run_scenario,
    summarize,
)

ROOT = Path(__file__).resolve().parent.parent


def _scenario(scenario_id: str):
    return next(
        item for item in load_scenarios() if item.id == scenario_id
    )


def test_loads_five_scenarios():
    scenarios = load_scenarios()

    assert len(scenarios) == 5
    assert len({item.id for item in scenarios}) == 5
    assert all(item.description for item in scenarios)


def test_each_scenario_has_ten_to_fifteen_turns():
    for scenario in load_scenarios():
        assert 10 <= len(scenario.turns) <= 15, scenario.id


def test_intent_aliases_resolve():
    assert resolve_intent("answer") == (
        "ответить_прямо",
        "ответить_с_оговоркой",
    )
    assert resolve_intent("statement") == ("запомнить_факт",)
    assert resolve_intent("dont_know") == ("признать_незнание",)
    assert resolve_intent("запомнить_факт") == ("запомнить_факт",)

    with pytest.raises(ValueError, match="unknown intent"):
        resolve_intent("nope")


def test_loader_accepts_object_with_scenarios_key(tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "one",
                        "description": "test",
                        "turns": [{"user": "Привет"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    scenarios = load_scenarios(path)

    assert len(scenarios) == 1
    assert scenarios[0].turns[0].user == "Привет"


def test_loader_rejects_unknown_intent(tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "turns": [
                        {"user": "Привет", "expected_intent": "nope"}
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown intent"):
        load_scenarios(path)


def test_loader_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text(
        json.dumps(
            [
                {"id": "one", "turns": [{"user": "Привет"}]},
                {"id": "one", "turns": [{"user": "Пока"}]},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate"):
        load_scenarios(path)


def test_unknown_then_fact_then_answer():
    outcome = run_scenario(_scenario("scenario_3_unknown"))

    assert outcome.turns[0].intent == "признать_незнание"
    assert outcome.turns[1].intent == "запомнить_факт"
    assert outcome.turns[2].intent == "ответить_прямо"
    assert "галактика" in outcome.turns[2].response.casefold()


def test_property_question_avoids_repeating_response():
    outcome = run_scenario(_scenario("scenario_2_properties"))

    first, second = outcome.turns[4], outcome.turns[5]
    assert first.passed and second.passed
    assert first.response != second.response


def test_stale_edge_invariant_fails_after_correction():
    outcome = run_scenario(_scenario("scenario_4_correction"))

    stale = next(
        item
        for item in outcome.invariants
        if item.check.target == "синяя"
    )
    fresh = next(
        item
        for item in outcome.invariants
        if item.check.target == "зелёная"
    )

    assert not stale.passed
    assert "есть, а не должно" in stale.detail
    assert fresh.passed
    assert not outcome.ok


def test_absence_invariant_passes_on_empty_graph():
    scenario = Scenario(
        id="empty",
        description="edge must be absent",
        turns=(ScenarioTurn(user="Привет", expected_intent="greet"),),
        invariants=(
            GraphCheck(
                source="трава",
                relation="has_property",
                target="синяя",
                present=False,
            ),
        ),
    )

    outcome = run_scenario(scenario)

    assert outcome.turns[0].passed
    assert outcome.invariants[0].passed
    assert outcome.ok


def test_scenario_run_is_repeatable():
    scenario = _scenario("scenario_2_properties")

    first = [turn.response for turn in run_scenario(scenario).turns]
    second = [turn.response for turn in run_scenario(scenario).turns]

    assert first == second


def test_summary_counts_turns_and_invariants():
    outcome = run_scenario(_scenario("scenario_4_correction"))

    summary = summarize([outcome])

    assert summary["scenarios"] == 1
    assert summary["scenarios_passed"] == 0
    assert summary["turns"] == len(outcome.turns)
    assert summary["turns_passed"] == outcome.passed_turns
    assert summary["invariants"] == 2
    assert summary["invariants_failed"] == 1
