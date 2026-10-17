"""Mathematical Entropy, Tabu, and Limit-Cycle Supervisor for HyperAgent."""

import hashlib
import json
import math
from typing import Any


class MathematicalSupervisor:
    """Supervises the fast System 1 POMDP agent using information theory and graph cycle detection.

    - Computes normalized Shannon Entropy H_norm(e) over candidate element probability distributions.
    - Tracks top-2 dominance margin Delta p = p_(1) - p_(2).
    - Maintains a Tabu set T(phi(s)) to penalize zero-state transitions (action repeated with no DOM change).
    - Detects Period-1 and Period-2 limit cycles (ping-ponging between states).
    """

    def __init__(self, conf_threshold: float = 0.48, entropy_ceiling: float = 0.68):
        self.conf_threshold = conf_threshold
        self.entropy_ceiling = entropy_ceiling
        self.action_history: list[tuple[str, str]] = []  # [(operation, target_label), ...]
        self.state_hashes: list[str] = []
        # Tabu map: state_hash -> set of target_labels or action signatures that caused zero-transition or loop
        self.tabu_targets_by_state: dict[str, set[str]] = {}
        self.tabu_count: int = 0

    @staticmethod
    def compute_state_hash(url: str, elements: list[dict[str, Any]]) -> str:
        """Structural fingerprint of current state."""
        sig = json.dumps({"url": url, "elements": [
            {k: el.get(k) for k in ("node", "role", "label", "value", "checked", "selected", "expanded", "operations")}
            for el in elements
        ]}, sort_keys=True)
        return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def compute_distribution_metrics(probabilities: dict[str, float]) -> tuple[float, float]:
        """Calculates normalized Shannon Entropy and Top-2 Dominance Margin.

        H_norm = - (1 / ln N) * sum(p_i * ln(p_i + eps))
        Delta p = p_(1) - p_(2)
        """
        probs = sorted(probabilities.values(), reverse=True)
        n = len(probabilities)
        if n <= 1:
            return 0.0, 1.0 if n == 1 else 0.0
        raw_entropy = -sum(p * math.log(p + 1e-12) for p in probs)
        norm_entropy = raw_entropy / math.log(n)
        norm_entropy = max(0.0, min(1.0, norm_entropy))
        margin = probs[0] - probs[1]
        return round(norm_entropy, 3), round(margin, 3)

    def filter_tabu_elements(
        self, state_hash: str, elements: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Strips elements in the current state that are masked in the Tabu set."""
        tabu = self.tabu_targets_by_state.get(state_hash, set())
        if not tabu:
            return elements
        filtered = [
            el for el in elements
            if el.get("label", el.get("name", "")) not in tabu
            and str(el.get("index", "")) not in tabu
        ]
        return filtered

    def record_outcome(self, state_hash: str, operation: str, target_label: str, page_changed: bool) -> None:
        """Records whether the last executed action modified page state. Adds to Tabu if no-op."""
        if not page_changed and operation not in {"WAIT", "SCROLL_UP", "SCROLL_DOWN"}:
            if state_hash not in self.tabu_targets_by_state:
                self.tabu_targets_by_state[state_hash] = set()
            if target_label not in self.tabu_targets_by_state[state_hash]:
                self.tabu_targets_by_state[state_hash].add(target_label)
                self.tabu_count += 1

    def adjudicate(
        self,
        state_hash: str,
        operation: str,
        target_label: str,
        target_probs: dict[str, float],
        goal_satisfied_noul: float = 0.0,
        irreversible_risk_noul: float = 0.0,
        last_step_changed_page: bool = True,
    ) -> tuple[str, str, dict[str, float]]:
        """Adjudicates the next proposed action.

        Returns: (decision_code, reason, metrics_dict)
        decision_code:
          - 'COMPLETE_AND_EXTRACT'  (Stop loop, synthesize Claude table)
          - 'PAUSE_FOR_HUMAN_RISK'  (Irreversible mutation gate)
          - 'ESCALATE_CLAUDE_SYS2'  (Cycle detected or high entropy)
          - 'EXECUTE_SYS1'          (Normal fast-path execution)
        """
        entropy_norm, margin = self.compute_distribution_metrics(target_probs)
        top_conf = max(target_probs.values()) if target_probs else 0.0
        metrics = {
            "entropy": entropy_norm if target_probs else None,
            "margin": margin if target_probs else None,
            "confidence": top_conf if target_probs else None,
            "goal_satisfied_noul": goal_satisfied_noul,
            "irreversible_risk_noul": irreversible_risk_noul,
        }

        # Risk gate takes priority over completion proposals.
        if irreversible_risk_noul >= 0.85:
            return (
                "PAUSE_FOR_HUMAN_RISK",
                (
                    f"High-stakes mutation detected ({operation} -> {target_label}, "
                    f"risk={irreversible_risk_noul:.2f}). Operator approval required."
                ),
                metrics,
            )

        # Completion is a proposal; the server must independently verify fresh evidence.
        if operation == "DONE" or goal_satisfied_noul >= 0.80:
            return (
                "COMPLETE_AND_EXTRACT",
                (
                    f"Completion proposed (noul={goal_satisfied_noul:.2f}, op={operation}). "
                    "Checking the final outcome independently."
                ),
                metrics,
            )

        # Limit-cycle detection (period 1 and 2).
        candidate_pair = (operation, target_label)
        temp_hist = self.action_history + [candidate_pair]

        # Period-1: repeated identical action in same state without page change
        if len(temp_hist) >= 2 and temp_hist[-1] == temp_hist[-2] and not last_step_changed_page:
            self.tabu_targets_by_state.setdefault(state_hash, set()).add(target_label)
            self.tabu_count = sum(map(len, self.tabu_targets_by_state.values()))
            return (
                "ESCALATE_CLAUDE_SYS2",
                f"Period-1 loop detected: repeated {operation} on '{target_label}' with no state progression.",
                metrics,
            )

        # Period-2: alternating actions returning to the same observed states.
        if len(temp_hist) >= 4:
            if (
                temp_hist[-1] == temp_hist[-3]
                and temp_hist[-2] == temp_hist[-4]
                and temp_hist[-1] != temp_hist[-2]
                and len(self.state_hashes) >= 3
                and state_hash == self.state_hashes[-2]
                and self.state_hashes[-1] == self.state_hashes[-3]
            ):
                self.tabu_targets_by_state.setdefault(state_hash, set()).update(
                    {temp_hist[-1][1], temp_hist[-2][1]}
                )
                self.tabu_count = sum(map(len, self.tabu_targets_by_state.values()))
                return (
                    "ESCALATE_CLAUDE_SYS2",
                    (
                        f"Period-2 limit cycle detected ({temp_hist[-2][1]} <-> {temp_hist[-1][1]}). "
                        "Escalating to System 2."
                    ),
                    metrics,
                )

        # 5. Shannon Entropy & Confidence Gate
        if target_probs and (top_conf < self.conf_threshold or entropy_norm > self.entropy_ceiling):
            return (
                "ESCALATE_CLAUDE_SYS2",
                (
                    f"High uncertainty policy distribution (conf={top_conf:.2f}, "
                    f"H_norm={entropy_norm:.2f}, margin={margin:.2f}). Escalating to System 2."
                ),
                metrics,
            )

        # Fast lane approved
        self.action_history.append(candidate_pair)
        self.state_hashes.append(state_hash)
        return ("EXECUTE_SYS1", "Policy decision cleared for execution.", metrics)
