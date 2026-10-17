"""Tests for MathematicalSupervisor: Shannon entropy, Tabu set, and Limit-Cycle detector."""

from hyperagent.supervisor import MathematicalSupervisor


def test_entropy_and_margin_decisive():
    # Sharp distribution: p1 = 0.95, p2 = 0.05
    probs = {"1": 0.95, "2": 0.05}
    entropy, margin = MathematicalSupervisor.compute_distribution_metrics(probs)
    assert entropy < 0.35
    assert margin == 0.90


def test_entropy_and_margin_uncertain():
    # Flat distribution across 4 elements: 0.25 each
    probs = {"1": 0.25, "2": 0.25, "3": 0.25, "4": 0.25}
    entropy, margin = MathematicalSupervisor.compute_distribution_metrics(probs)
    assert entropy > 0.95
    assert margin == 0.0


def test_certain_distribution_includes_zero_probability_candidates():
    entropy, margin = MathematicalSupervisor.compute_distribution_metrics({"1": 1.0, "2": 0.0})
    assert entropy == 0
    assert margin == 1


def test_tabu_filtering():
    sup = MathematicalSupervisor()
    state_hash = "abc123"
    elements = [
        {"index": "1", "label": "Done", "role": "button"},
        {"index": "2", "label": "Open report", "role": "button"},
    ]
    # No tabu yet
    filtered = sup.filter_tabu_elements(state_hash, elements)
    assert len(filtered) == 2

    # Add Done to tabu for this state
    sup.tabu_targets_by_state[state_hash] = {"Done"}
    filtered = sup.filter_tabu_elements(state_hash, elements)
    assert len(filtered) == 1
    assert filtered[0]["label"] == "Open report"


def test_period2_cycle_adjudication():
    sup = MathematicalSupervisor()
    state_hash = "search_state"
    probs = {"1": 0.9}

    # Step 1: Click 'Open menu'
    v1, _, _ = sup.adjudicate(state_hash, "CLICK", "Open menu", probs)
    assert v1 == "EXECUTE_SYS1"

    # Step 2: Click 'Done'
    v2, _, _ = sup.adjudicate(state_hash, "CLICK", "Done", probs)
    assert v2 == "EXECUTE_SYS1"

    # Step 3: Click 'Open menu' again
    v3, _, _ = sup.adjudicate(state_hash, "CLICK", "Open menu", probs)
    assert v3 == "EXECUTE_SYS1"

    # Step 4: Click 'Done' again -> Period-2 limit cycle triggers!
    v4, reason, _ = sup.adjudicate(state_hash, "CLICK", "Done", probs)
    assert v4 == "ESCALATE_CLAUDE_SYS2"
    assert "Period-2 limit cycle" in reason
    assert "Done" in sup.tabu_targets_by_state[state_hash]
    assert "Open menu" in sup.tabu_targets_by_state[state_hash]


def test_high_irreversible_risk_pauses_for_human():
    sup = MathematicalSupervisor()
    probs = {"1": 0.95}
    v, reason, _ = sup.adjudicate(
        "checkout",
        "CLICK",
        "Confirm purchase",
        probs,
        irreversible_risk_noul=0.92,
    )
    assert v == "PAUSE_FOR_HUMAN_RISK"
    assert "Operator approval" in reason


def test_goal_satisfied_completes_and_extracts():
    sup = MathematicalSupervisor()
    probs = {"1": 0.9}
    v, reason, _ = sup.adjudicate(
        "results_page",
        "CLICK",
        "First result",
        probs,
        goal_satisfied_noul=0.88,
    )
    assert v == "COMPLETE_AND_EXTRACT"


def test_tabu_never_unmasks_everything_when_exhausted():
    sup = MathematicalSupervisor()
    sup.record_outcome("state", "CLICK", "Only button", False)
    assert sup.filter_tabu_elements("state", [{"index": "1", "label": "Only button"}]) == []


def test_state_hash_tracks_values_and_controls_after_sixty():
    sup = MathematicalSupervisor()
    first = [{"index": str(i), "label": "Field", "value": ""} for i in range(65)]
    second = [dict(el) for el in first]
    second[-1]["value"] = "updated"
    assert sup.compute_state_hash("url", first) != sup.compute_state_hash("url", second)


def test_risk_is_not_bypassed_by_completion_probability():
    verdict, _, _ = MathematicalSupervisor().adjudicate(
        "state", "CLICK", "Pay", {"1": 1.0}, goal_satisfied_noul=0.9, irreversible_risk_noul=0.95,
    )
    assert verdict == "PAUSE_FOR_HUMAN_RISK"
