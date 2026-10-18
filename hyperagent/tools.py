"""Tool schemas the model may call, human-readable labels, and the risk policy for approvals."""

from __future__ import annotations

import re
from typing import Any

REASONING = {
    "evaluation": {
        "type": "string",
        "description": "One sentence: did the previous action work? Cite what you see on the page now.",
    },
    "memory": {
        "type": "string",
        "description": "Brief running notes: what is done, what was found, what remains. Keep it under 60 words.",
    },
    "next_goal": {
        "type": "string",
        "description": "The immediate goal of THIS action in plain language for a non-technical observer.",
    },
    "message": {
        "type": "string",
        "description": "One or two short first-person sentences for the person watching, like a colleague "
                       "narrating: what you just learned and what you will do next. Plain words, no tool names.",
    },
    "plan_step": {
        "type": "integer",
        "description": "1-based number of the plan item THIS action works on. Earlier items count as done, so "
                       "send it every step instead of re-sending the whole plan.",
    },
    "plan": {
        "type": "array",
        "description": "The full updated plan (3-7 short items). Required on the first step; afterwards only when "
                       "the plan or an item's status changes.",
        "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "active", "done", "skipped"]},
            },
            "required": ["text", "status"],
        },
    },
}
REASONING_REQUIRED = ["evaluation", "memory", "next_goal", "message"]
RISK_FIELDS = {
    "irreversible": {
        "type": "boolean",
        "description": "True if this action submits, purchases, sends, books, deletes, publishes or otherwise "
                       "commits something on the user's behalf that is hard to undo.",
    },
}


def _bare(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema without descriptions: shared fields are explained once in the system prompt."""
    out = {k: v for k, v in schema.items() if k != "description"}
    if isinstance(out.get("items"), dict):
        out["items"] = _bare(out["items"])
    if isinstance(out.get("properties"), dict):
        out["properties"] = {k: _bare(v) for k, v in out["properties"].items()}
    return out


# The tool list is resent on every planner call, so the shared reasoning fields carry no descriptions here.
_SHARED = {k: _bare(v) for k, v in REASONING.items()}


def _tool(name: str, description: str, params: dict[str, Any], required: list[str], risk: bool = False) -> dict:
    # Order matters to models that fill arguments in schema order: short reasoning, then the action's own
    # parameters, then the long plan last, so a verbose plan can never crowd out the required arguments.
    reasoning = {k: v for k, v in _SHARED.items() if k != "plan"}
    properties = {**reasoning, **params, **(RISK_FIELDS if risk else {}), "plan": _SHARED["plan"]}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": REASONING_REQUIRED + required + (["irreversible"] if risk else []),
            },
        },
    }


ELEMENT = {"element_id": {"type": "integer", "description": "The [id] of an element in the CURRENT page state."}}
ROW = {"type": "object", "additionalProperties": {"type": "string"}}

TOOLS = [
    _tool("search", "Search the web (opens a search results page).",
          {"query": {"type": "string"}}, ["query"]),
    _tool("navigate", "Open a URL in the current tab.", {"url": {"type": "string"}}, ["url"]),
    _tool("click", "Click an element.", ELEMENT, ["element_id"], risk=True),
    _tool("type_text", "Replace the text of an input field, optionally pressing Enter afterwards.",
          {**ELEMENT, "text": {"type": "string"}, "press_enter": {"type": "boolean"}},
          ["element_id", "text", "press_enter"], risk=True),
    _tool("select_option", "Choose an option of a <select> dropdown by its visible label.",
          {**ELEMENT, "option": {"type": "string"}}, ["element_id", "option"]),
    _tool("press_key", "Press a keyboard key such as Enter, Escape, Tab, ArrowDown.",
          {"key": {"type": "string"}}, ["key"]),
    _tool("scroll", "Scroll the page to reveal more content.",
          {"direction": {"type": "string", "enum": ["down", "up"]},
           "pages": {"type": "number", "description": "How many screen heights, default 1."}}, ["direction"]),
    _tool("go_back", "Go back to the previous page in this tab.", {}, []),
    _tool("switch_tab", "Switch to another open tab.", {"tab_index": {"type": "integer"}}, ["tab_index"]),
    _tool("close_tab", "Close the current tab.", {}, []),
    _tool("read_page", "Read the FULL text of the current page including content below the fold and link URLs. "
          "The output is shown to you once, in the next step only, so record what you need right after.", {}, []),
    _tool("read_urls_parallel", "Open and read 2 to 4 http(s) URLs concurrently in background tabs and return their "
          "full text in a single step. Ideal when comparing multiple pages, repositories, products, or sources.",
          {"urls": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                    "description": "2 to 4 http(s) URLs to read concurrently."}},
          ["urls"]),
    _tool("extract", "Pull structured rows from the current page, or from 1-4 http(s) URLs read in parallel, and "
          "save them as findings in one step. A fast extraction model reads the page text, not you: you get a "
          "one-line summary and the rows appear in findings_saved. Prefer this over read_page + record_findings "
          "for lists, tables, search results and product details.",
          {"fields": {"type": "array", "maxItems": 12, "items": {"type": "string"},
                      "description": "Column names to fill for every item, e.g. [\"title\", \"price\"]."},
           "instruction": {"type": "string", "description": "Which items to keep, e.g. 'only books rated 4-5 "
                           "stars under £20'. Leave empty to keep every item."},
           "urls": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                    "description": "Optional http(s) URLs read from the page; empty means the current page."}},
          ["fields"]),
    _tool("record_findings", "Save structured facts you have verified on the current page. Use flat objects with "
          "consistent keys across items. Saved findings persist for the rest of the task and feed the final result.",
          {"items": {"type": "array", "items": ROW},
           "source_url": {"type": "string", "description": "URL of the page the facts were read from."}},
          ["items", "source_url"]),
    _tool("wait", "Wait for the page to finish loading or updating.",
          {"seconds": {"type": "number", "description": "1-10"}}, []),
    _tool("ask_user", "Ask the operator a question when you need information or a decision only they can give "
          "(credentials, personal details, ambiguous choices, a captcha). The task pauses until they answer.",
          {"question": {"type": "string"}}, ["question"]),
    _tool("done", "Finish the task and deliver the final result. Call when the goal is achieved, or when it cannot "
          "be achieved (success=false, explain why in issues).",
          {"success": {"type": "boolean"},
           "summary": {"type": "string", "description": "Markdown answer for the user: lead with the answer."},
           "columns": {"type": "array", "items": {"type": "string"},
                       "description": "Table columns if the result is tabular, else empty."},
           "rows": {"type": "array", "items": ROW, "description": "Table rows keyed by column name."},
           "sources": {"type": "array", "items": {"type": "object", "properties": {
               "title": {"type": "string"}, "url": {"type": "string"}}, "required": ["title", "url"]}},
           "issues": {"type": "array", "items": {"type": "string"},
                      "description": "Anything unverified, missing or uncertain."},
           "checklist": {"type": "array", "description": "One item per distinct requirement in the user's goal, "
                         "in the goal's own words (2-6 items).", "items": {"type": "object", "properties": {
               "requirement": {"type": "string"},
               "met": {"type": "boolean"},
               "evidence": {"type": "string", "description": "What on the page proves it, in a few words."},
               "step": {"type": "integer", "description": "History step number where that evidence was seen."}},
               "required": ["requirement", "met", "evidence"]}},
           "assumptions": {"type": "array", "items": {"type": "string"},
                           "description": "Interpretations you chose where the goal was ambiguous."},
           "follow_ups": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                          "description": "Up to 3 short next goals this user might plausibly want."},
           "remember": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                        "description": "Lasting preferences or facts the user stated about themselves, in their "
                                       "own words. Usually empty."}},
          ["success", "summary", "columns", "rows", "sources", "issues", "checklist"]),
]
DELEGATE = _tool(
    "delegate",
    "Hand a concrete on-page UI subgoal to Jev, the fast System 1 policy (~0.3 s per action). Jev clicks, types, "
    "selects and scrolls on the CURRENT page until it judges the subgoal done, gets stuck, or is unsure, then "
    "returns control to you with a log of what it did. Use it for multi-step form filling, menus, filters, "
    "date pickers and clicking through to a result. Jev cannot open URLs, read/extract data or ask questions.",
    {"subgoal": {"type": "string", "description": "One concrete, checkable UI subgoal with every value Jev needs, "
                 "e.g. 'Fill name Ada Lovelace, phone 555-0100, choose Large size, tick Bacon and Mushroom'."}},
    ["subgoal"],
)
TOOLS_WITH_FAST = [*TOOLS[:-1], DELEGATE, TOOLS[-1]]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS_WITH_FAST}
_REQUIRED = {t["function"]["name"]: t["function"]["parameters"]["required"] for t in TOOLS_WITH_FAST}
_REASONING_KEYS = set(REASONING) | set(RISK_FIELDS)
# Asked of the model, but a finished run is never thrown away for leaving it out.
_LENIENT_KEYS = {"checklist"}


def missing_args(name: str, args: dict[str, Any]) -> list[str]:
    """Required action parameters the model left out or left empty (reasoning fields are optional here)."""
    required = [k for k in _REQUIRED.get(name, []) if k not in _REASONING_KEYS | _LENIENT_KEYS]
    return [k for k in required if args.get(k) is None or args.get(k) == ""]

# Actions that change page state; under approval mode "always" each needs operator approval.
MUTATING = {"search", "navigate", "click", "type_text", "select_option", "press_key", "go_back", "close_tab"}
RISKY_WORDS = re.compile(
    r"\b(submit|buy|purchase|pay|order|checkout|check out|place|confirm|delete|remove|send|book|reserve|"
    r"subscribe|sign ?up|register|publish|post|transfer|apply|donate|unsubscribe|cancel (?:my )?(?:account|order))\b",
    re.I,
)


def needs_approval(name: str, args: dict[str, Any], target_label: str, mode: str) -> tuple[bool, str]:
    """Return (needs approval, plain-language reason)."""
    if mode == "never" or name not in MUTATING:
        return False, ""
    if mode == "always":
        return True, "You asked to approve every action."
    if args.get("irreversible"):
        return True, "The agent flagged this as hard to undo."
    if name == "click" and RISKY_WORDS.search(target_label or ""):
        return True, f'The button "{target_label[:60]}" looks like it commits something.'
    if name == "type_text" and args.get("press_enter") and RISKY_WORDS.search(target_label or ""):
        return True, "Pressing Enter here may submit a form."
    return False, ""


def label(name: str, args: dict[str, Any], target_label: str = "") -> str:
    """A short human sentence for the timeline."""
    target = f'"{target_label[:60]}"' if target_label else f"element [{args.get('element_id')}]"
    match name:
        case "search":
            return f'Search the web for "{args.get("query", "")}"'
        case "navigate":
            return f"Open {args.get('url', '')}"
        case "click":
            return f"Click {target}"
        case "type_text":
            text = str(args.get("text", ""))
            shown = text if len(text) <= 60 else text[:57] + "…"
            return f'Type "{shown}" into {target}' + (" and press Enter" if args.get("press_enter") else "")
        case "select_option":
            return f'Choose "{args.get("option", "")}" in {target}'
        case "press_key":
            return f"Press {args.get('key', '')}"
        case "scroll":
            return f"Scroll {args.get('direction', 'down')}"
        case "go_back":
            return "Go back"
        case "switch_tab":
            return f"Switch to tab {args.get('tab_index')}"
        case "close_tab":
            return "Close this tab"
        case "read_page":
            return "Read the whole page"
        case "read_urls_parallel":
            urls = args.get("urls") if isinstance(args.get("urls"), list) else []
            return f"Read {len(urls)} page{'s' if len(urls) != 1 else ''} in parallel"
        case "extract":
            fields = [str(f) for f in (args.get("fields") or [])][:4]
            shown = ", ".join(fields) + ("…" if len(args.get("fields") or []) > 4 else "")
            pages = len(args.get("urls") or [])
            where = f"{pages} page{'s' if pages != 1 else ''}" if pages else "this page"
            return f"Extract {shown} from {where}"
        case "record_findings":
            n = len(args.get("items") or [])
            return f"Save {n} finding{'s' if n != 1 else ''}"
        case "wait":
            return "Wait for the page"
        case "ask_user":
            return "Ask you a question"
        case "done":
            return "Deliver the result"
        case "delegate":
            return f"Hand off to Jev: {str(args.get('subgoal', ''))[:90]}"
    return name
