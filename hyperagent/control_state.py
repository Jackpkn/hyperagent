"""Grounded state checks for idempotent UI actions; never infer state from colors or labels."""

from typing import Any


def state_value(value: Any) -> bool | None:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    return None


def control_state(element: dict[str, Any]) -> tuple[str, bool | None] | None:
    for key in ("checked", "selected", "pressed"):
        if key in element:
            return key, state_value(element[key])
    return None


def can_deactivate(element: dict[str, Any]) -> bool:
    # Tabs, radio choices and list options select an alternative rather than toggling off.
    return element.get("role") not in ("tab", "radio", "menuitemradio", "option") \
        and element.get("type") != "radio"


def satisfied_action(name: str, args: dict[str, Any], element: dict[str, Any]) -> str | None:
    if name == "click":
        state = control_state(element)
        desired = args.get("desired_state")
        if state and desired is None and not can_deactivate(element):
            desired = True
        if state and type(desired) is bool and state[1] is desired:
            return f"Already {state[0]}={str(desired).lower()}; no click was needed."
    elif name == "type_text" and element.get("type") != "password" and not args.get("press_enter"):
        if not element.get("value_truncated") and "value" in element and element["value"] == args.get("text"):
            return "That field already holds this value; nothing was typed."
    elif name == "select_option":
        if not element.get("value_truncated") and "value" in element and element["value"] == args.get("option"):
            return "That option is already selected; nothing was changed."
    return None
