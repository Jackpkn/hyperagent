"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import json
import math
import os
import time

import httpx

from .questions import NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)


class InvalidPolicyResponse(ValueError):
    """Invalid policy choice; no browser mutation has been attempted."""


def post_json(url, key, body):
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue
        if response.is_error:
            raise RuntimeError(f"Model provider returned HTTP {response.status_code}; no action executed.")
        return response.json()
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise InvalidPolicyResponse("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {
                k: action[k] for k in ("node", "rect", "role", "value", "checked", "selected", "expanded", "href")
                if k in action
            }
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def choose(
    state,
    goal,
    history,
    *,
    allowed_elements=None,
    include_verifiers=False,
    stopping_predicate=None,
    whisper_notes=None,
    research_evidence=None,
):
    elements, targets, controls = action_space(state["actions"])
    if allowed_elements is not None:
        allowed_indices = {str(el["index"]) for el in allowed_elements}
        elements = [el for el in elements if el["index"] in allowed_indices]
        targets = {
            operation: {index: action for index, action in candidates.items()
                        if index.split(":")[0] in allowed_indices}
            for operation, candidates in targets.items()
        }
        targets = {operation: candidates for operation, candidates in targets.items() if candidates}
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")

    rules = NEXT_ACTION
    if whisper_notes:
        notes_str = " | ".join(whisper_notes)
        rules = f"{NEXT_ACTION}\nOperator Guidance (Whisper Constraints): {notes_str}"

    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": rules}}
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [rules, TARGET]},
        }

    if include_verifiers:
        predicate = stopping_predicate or "Every requirement is visibly satisfied on screen."
        questions["goal_satisfied"] = {
            "type": "noul",
            "instructions": f"Stopping condition: {predicate}. Do the observations establish EVERY requirement? "
                            "Prior observations may support research, but never prove a current submission succeeded.",
        }
        questions["irreversible_mutation"] = {
            "type": "noul",
            "instructions": {
                "goal": goal,
                "question": "Would the next step toward this goal risk an irreversible submission or payment? "
                            "Evaluate the current state; other question answers are not available.",
            },
        }

    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "prior_observations_untrusted": research_evidence or [],
            "completion_criteria": stopping_predicate,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    try:
        result = post_json("https://api.typesafe.ai/v1/systemone", os.environ["TYPESAFE_API_KEY"], body)
    except json.JSONDecodeError:
        raise InvalidPolicyResponse("Invalid TypeSafe JSON; no action executed.") from None
    if (not isinstance(result, dict) or not isinstance(result.get("answers"), dict)
            or not isinstance(result.get("model"), str)):
        raise InvalidPolicyResponse("Invalid TypeSafe response envelope; no action executed.")
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]

    def noul(name):
        if not include_verifiers:
            return 0.0
        answer = result["answers"].get(name, {})
        value = answer.get("noul") if isinstance(answer, dict) else None
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise InvalidPolicyResponse(f"Invalid TypeSafe {name} verifier; no action executed.")
        return value

    goal_satisfied_noul = noul("goal_satisfied")
    irreversible_risk_noul = noul("irreversible_mutation")

    target_label = ""
    if target and operation in targets and target in targets[operation]:
        target_label = targets[operation][target].get("label", "")
    elif choice:
        target_label = controls.get(operation, {}).get("label", choice)

    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "target_label": target_label,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "goal_satisfied_noul": goal_satisfied_noul,
        "irreversible_risk_noul": irreversible_risk_noul,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text(context):
    key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError("TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor.")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = {"thinking": {"type": "disabled"}} if "api.deepseek.com/" in base else {"reasoning": {"effort": "low"}}
    if os.environ.get("TEXT_MODEL_REASONING") == "none":
        reasoning = {"reasoning": {"enabled": False}}
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": TEXT_VALUE},
                {
                    "role": "user",
                    "content": json.dumps(context),
                },
            ],
        },
    )
    try:
        output = json.loads(result["choices"][0]["message"]["content"])
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }
