"""Tool schemas the model may call, human-readable labels, and the risk policy for approvals."""

from __future__ import annotations

import re
from typing import Any

REASONING = {
    "evaluation": {
        "type": "string",
        "description": "One sentence: did the previous action or Jev subgoal actually work? Cite what you see in "
                       "<browser_state> now.",
    },
    "memory": {
        "type": "string",
        "description": "Brief running notes: what is done, what was found, what remains. Keep under 60 words.",
    },
    "think": {
        "type": "string",
        "description": "Optional deep reasoning scratchpad. OMIT on routine steps. Use ONLY when recovering from "
                       "a stuck action, comparing multiple candidates/prices, or verifying constraints before done.",
    },
    "message": {
        "type": "string",
        "description": "One or two short first-person sentences for the person watching live: what you just learned "
                       "and what you will do next. Plain words, no tool or field names.",
    },
    "plan_step": {
        "type": "integer",
        "description": "1-based number of the plan item THIS action works on. Earlier items count as done.",
    },
    "plan": {
        "type": "array",
        "description": "The full updated plan (3-7 short items). Required on step 1; afterwards ONLY when the plan "
                       "changes.",
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

# Only 3 short strings + plan_step required on every turn; 'think' and 'plan' are conditional.
REASONING_REQUIRED = ["evaluation", "memory", "message", "plan_step"]

RISK_FIELDS = {
    "irreversible": {
        "type": "boolean",
        "description": "True if this action (or delegated subgoal) submits, purchases, sends, books, deletes, "
                       "publishes, or otherwise commits something on the user's behalf that is hard to undo.",
    },
}


def _bare(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip descriptions from shared fields since they are explained once in the system prompt."""
    out = {k: v for k, v in schema.items() if k != "description"}
    if isinstance(out.get("items"), dict):
        out["items"] = _bare(out["items"])
    if isinstance(out.get("properties"), dict):
        out["properties"] = {k: _bare(v) for k, v in out["properties"].items()}
    return out


_SHARED = {k: _bare(v) for k, v in REASONING.items()}


def _tool(name: str, description: str, params: dict[str, Any], required: list[str], risk: bool = False) -> dict:
    # Schema order matters for autoregressive decoding:
    # 1. Short reasoning & optional 'think' -> 2. Action arguments -> 3. Risk flag -> 4. Optional verbose 'plan' last
    reasoning_head = {k: v for k, v in _SHARED.items() if k != "plan"}
    properties = {
        **reasoning_head,
        **params,
        **(RISK_FIELDS if risk else {}),
        "plan": _SHARED["plan"],
    }
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


ELEMENT = {"element_id": {"type": "integer", "description": "The [id] of an element in the CURRENT <browser_state>."}}
ROW = {"type": "object", "additionalProperties": {"type": "string"}}

TOOLS = [
    _tool("search", "Discover websites using a web search engine; this leaves the current page. "
          "To use a search bar on the current website, use delegate (or type_text/click).",
          {"query": {"type": "string"}}, ["query"]),
    _tool("navigate", "Open a known top-level domain or an exact URL copied from the page in the current tab.",
          {"url": {"type": "string"}}, ["url"]),
    _tool("click", "Click an element [id]. When delegate is available, prefer delegate for forms, filters, "
          "and multi-step UI flows; use click only for recovery or single isolated navigation.",
          ELEMENT, ["element_id"], risk=True),
    _tool("type_text", "Replace the text of an input field [id], optionally pressing Enter afterwards. "
          "When delegate is available, prefer delegate; use type_text only for passwords or recovery.",
          {**ELEMENT, "text": {"type": "string"}, "press_enter": {"type": "boolean"}},
          ["element_id", "text", "press_enter"], risk=True),
    _tool("select_option", "Choose an option of a <select> dropdown by its visible label.",
          {**ELEMENT, "option": {"type": "string"}}, ["element_id", "option"], risk=True),
    _tool("press_key", "Press a keyboard key such as Enter, Escape, Tab, ArrowDown.",
          {"key": {"type": "string"}}, ["key"], risk=True),
    _tool("scroll", "Scroll the page to reveal more content.",
          {"direction": {"type": "string", "enum": ["down", "up"]},
           "pages": {"type": "number", "description": "Screen heights to scroll, default 1."}}, ["direction"]),
    _tool("go_back", "Go back to the previous page in this tab.", {}, []),
    _tool("switch_tab", "Switch to another open tab.", {"tab_index": {"type": "integer"}}, ["tab_index"]),
    _tool("close_tab", "Close the current tab.", {}, []),
    _tool("read_page", "Read the FULL text of the current page including below-the-fold content and link URLs. "
          "Shown once in the next step only; record needed facts immediately after.", {}, []),
    _tool("read_urls_parallel", "Open 2 to 4 URLs in background tabs and read their full text once. Only for "
          "understanding pages whose fields you cannot name yet; to collect structured data use extract(urls=...).",
          {"urls": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                    "description": "2 to 4 http(s) URLs to read concurrently."}},
          ["urls"]),
    _tool("extract", "Pull structured rows from the current page, or from 1-8 URLs/hrefs in parallel, and "
          "save them directly to findings_saved in one step. Prefer over read_page + record_findings for "
          "lists, tables, search results, and product/listing details.",
          {"fields": {"type": "array", "maxItems": 12, "items": {"type": "string"},
                      "description": "Column names to fill for every item, e.g. [\"title\", \"price\", \"link\"]."},
           "instruction": {"type": "string", "description": "Filter rule, e.g. 'only nonstop flights under $300'. "
                           "Leave empty to keep every item."},
           "urls": {"type": "array", "maxItems": 8, "items": {"type": "string"},
                    "description": "Optional URLs or relative hrefs copied from the page; empty means current page."}},
          ["fields"]),
    _tool("record_findings", "Save structured facts verified on the current page. Use flat objects with consistent "
          "keys. Pass items=[] to mark a page checked when nothing on it qualifies.",
          {"items": {"type": "array", "items": ROW},
           "source_url": {"type": "string", "description": "URL of the page the facts were read from."}},
          ["items", "source_url"]),
    _tool("wait", "Wait for the page to finish loading or updating.",
          {"seconds": {"type": "number", "description": "1-10"}}, []),
    _tool("ask_user", "Pause and ask the operator when you need credentials, personal/payment details, "
          "a decision on ambiguous choices, or human takeover for a CAPTCHA.",
          {"question": {"type": "string"}}, ["question"]),
    _tool("done", "Finish the task and deliver the final verified result.",
          {"success": {"type": "boolean"},
           "summary": {"type": "string", "description": "Markdown answer for the user: lead with the direct answer."},
           "columns": {"type": "array", "items": {"type": "string"},
                       "description": "Table columns if the result is tabular, else []."},
           "rows": {"type": "array", "items": ROW, "description": "Table rows keyed by column name, else []."},
           "sources": {"type": "array", "items": {"type": "object", "properties": {
               "title": {"type": "string"}, "url": {"type": "string"}}, "required": ["title", "url"]}},
           "issues": {"type": "array", "items": {"type": "string"},
                      "description": "Anything unverified, missing, or uncertain."},
           "checklist": {"type": "array", "description": "2-6 distinct requirements from the user's goal.",
                         "items": {"type": "object", "properties": {
                             "requirement": {"type": "string"},
                             "met": {"type": "boolean"},
                             "evidence": {"type": "string", "description": "Brief proof from the page (no step #s)."},
                             "step": {"type": "integer", "description": "Step number where evidence was seen."}},
                             "required": ["requirement", "met", "evidence"]}},
           "assumptions": {"type": "array", "items": {"type": "string"},
                           "description": "Interpretations chosen where the goal was ambiguous."},
           "follow_ups": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                          "description": "Up to 3 short next goals this user might plausibly want."},
           "remember": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                        "description": "Lasting preferences/facts the user stated about themselves. Usually []."}},
          ["success", "summary", "columns", "rows", "sources", "issues", "checklist"]),
]

DELEGATE = _tool(
    "delegate",
    "Hand on-page UI work (forms, clicks, typing, dropdowns, date pickers, filters, sorting, scrolling, popups) "
    "to Jev, the fast UI classifier (~0.4 s/action, zero planner tokens). Batch the whole stretch of UI work up "
    "to your next extraction or decision checkpoint into ONE subgoal. Jev cannot invent text, open external URLs, "
    "extract data, or type passwords.",
    {"subgoal": {"type": "string", "description": "The target outcome, EVERY exact literal string to type or select "
                 "in quotes, settings already correct to leave untouched, and the visible stopping condition. "
                 "Exclude passwords and unrequested irreversible commits."}},
    ["subgoal"],
    risk=True,  # Jev can click buttons that submit/commit; allow planner to flag irreversible=True
)

TOOLS_WITH_FAST = [*TOOLS[:2], DELEGATE, *TOOLS[2:]]
DIRECT_UI_TOOLS = frozenset({"click", "type_text", "select_option", "scroll"})
# What the planner sees in Jev mode: no direct UI tools, so on-page work goes through delegate. The agent offers
# TOOLS_WITH_FAST again for a few recovery turns after Jev ends stuck or unsure.
TOOLS_JEV_FIRST = [t for t in TOOLS_WITH_FAST if t["function"]["name"] not in DIRECT_UI_TOOLS]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS_WITH_FAST}
_REQUIRED = {t["function"]["name"]: t["function"]["parameters"]["required"] for t in TOOLS_WITH_FAST}

_REASONING_KEYS = set(REASONING) | set(RISK_FIELDS) | {"next_goal"}
_LENIENT_KEYS = {"checklist", "columns", "rows"}
# Fields where an empty string "" is a valid deliberate argument (e.g. clearing an input or unfiltered extract)
_ALLOW_EMPTY_STR = {"text", "instruction"}


def missing_args(name: str, args: dict[str, Any]) -> list[str]:
    """Required action parameters the model left out or left empty (reasoning fields are optional here)."""
    required = [k for k in _REQUIRED.get(name, []) if k not in _REASONING_KEYS | _LENIENT_KEYS]
    return [
        k for k in required
        if args.get(k) is None or (args.get(k) == "" and k not in _ALLOW_EMPTY_STR)
    ]


# Actions that mutate browser state; includes delegate since Jev executes clicks/typing on the page.
MUTATING = {
    "search", "navigate", "click", "type_text", "select_option",
    "press_key", "go_back", "close_tab", "delegate",
}

# Tightened regex: avoids false triggers on "Order Status", "Sort by Order", "Market Place", or "Apply Filters"
RISKY_WORDS = re.compile(
    r"\b(submit|buy|purchase|pay\b|place (?:an? |the |my |your )?order|checkout|check out|confirm|"
    r"delete|remove|send|book\b|reserve|subscribe|sign ?up|register|publish|post\b|transfer|"
    r"apply now|submit application|donate|unsubscribe|cancel (?:my )?(?:account|order|booking))\b",
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
    if name == "delegate" and RISKY_WORDS.search(args.get("subgoal", "")):
        return True, "This delegated UI flow includes a step that may commit or submit something."
    if name == "click" and RISKY_WORDS.search(target_label or ""):
        return True, f'The button "{target_label[:60]}" looks like it commits something.'
    if name == "type_text" and args.get("press_enter") and RISKY_WORDS.search(target_label or ""):
        return True, "Pressing Enter here may submit a form."
    if name == "press_key" and str(args.get("key", "")).lower() == "enter" and RISKY_WORDS.search(target_label or ""):
        return True, "Pressing Enter here may submit a form."
    return False, ""


def label(name: str, args: dict[str, Any], target_label: str = "") -> str:
    """A short human sentence for the timeline."""
    el_id = args.get("element_id", "?")
    target = f'"{target_label[:60]}"' if target_label else f"element [{el_id}]"
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
