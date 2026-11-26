"""M11: прогон многоходовых сценариев (Context Retention).

Каждый сценарий идёт на чистом in-memory графе, PostgreSQL не нужен.

    python -m scripts.run_multi_turn
    python -m scripts.run_multi_turn --only scenario_4
    python -m scripts.run_multi_turn --json

Код возврата: 0 — все сценарии прошли (ходы и инварианты), 1 — есть провалы.
"""

from __future__ import annotations

import argparse
import json
import sys

from griga.evaluation.multi_turn import (
    ScenarioOutcome,
    load_scenarios,
    run_scenarios,
    summarize,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_multi_turn",
        description="Многоходовые сценарии v0.1: удержание контекста диалога.",
    )
    parser.add_argument(
        "--scenarios",
        default=None,
        help="путь к scenarios.json (по умолчанию eval/multi_turn/scenarios.json)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="запустить только сценарии, в id которых есть подстрока",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="напечатать отчёт в JSON вместо таблицы",
    )
    parser.add_argument(
        "--learning",
        action="store_true",
        help="включить Хебба и забывание (по умолчанию выключены)",
    )
    return parser


def _print_report(outcomes: list[ScenarioOutcome]) -> None:
    print("M11 · многоходовые сценарии (Context Retention)\n")

    for number, outcome in enumerate(outcomes, start=1):
        scenario = outcome.scenario
        status = "PASS" if outcome.ok else "FAIL"
        print(
            f"Сценарий {number}: {scenario.description}\n"
            f"  {scenario.id} · {outcome.passed_turns}/{outcome.total_turns} "
            f"ходов · {status}"
        )

        for turn in outcome.turns:
            mark = "PASS" if turn.passed else "FAIL"
            print(f"  {turn.index:>2}. [{mark}] {turn.turn.user}")
            print(f"      → {turn.response}")
            for failure in turn.failures:
                print(f"      ! {failure}")

        if outcome.invariants:
            failed = outcome.failed_invariants
            mark = "PASS" if failed == 0 else "FAIL"
            print(
                f"  граф: {len(outcome.invariants) - failed}"
                f"/{len(outcome.invariants)} инвариантов · {mark}"
            )
            for item in outcome.invariants:
                if item.passed:
                    continue
                check = item.check
                expected = "есть" if check.present else "нет"
                print(
                    f"      ! {check.source} -[{check.relation}]-> "
                    f"{check.target}: ожидалось {expected}; {item.detail}"
                )

        if not outcome.ok:
            print(f"  Итог сценария: FAIL — {outcome.first_failure()}")
        print()

    summary = summarize(outcomes)
    print(
        "Итог: "
        f"{summary['scenarios_passed']}/{summary['scenarios']} сценариев · "
        f"{summary['turns_passed']}/{summary['turns']} ходов "
        f"({summary['pass_rate']:.0%})"
    )
    if summary["invariants"]:
        print(
            "Инварианты графа: "
            f"{summary['invariants'] - summary['invariants_failed']}"
            f"/{summary['invariants']}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    scenarios = list(load_scenarios(args.scenarios))
    if args.only:
        needle = args.only.casefold()
        scenarios = [
            scenario
            for scenario in scenarios
            if needle in scenario.id.casefold()
            or needle in scenario.description.casefold()
        ]
    if not scenarios:
        print("Не найдено ни одного сценария.")
        return 1

    outcomes = list(run_scenarios(scenarios, learning=args.learning))

    if args.json:
        payload = {
            "summary": summarize(outcomes),
            "scenarios": [outcome.to_dict() for outcome in outcomes],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_report(outcomes)

    return 0 if all(outcome.ok for outcome in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
