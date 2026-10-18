"""The System 1 loop: Jev executes a delegated UI subgoal with fast typed decisions, then hands back."""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

from playwright.async_api import Error as PlaywrightError

from .browser import ActionError
from .control_state import satisfied_action
from .fast import FastError
from .tools import needs_approval

if TYPE_CHECKING:
    from .agent import Agent

FAST_MAX_ACTIONS = 15
NO_CHANGE_LIMIT = 3
OPERATION_TOOLS = {"CLICK": "click", "TYPE_TEXT": "type_text", "SELECT": "select_option",
                   "ACTIVATE": "click", "DEACTIVATE": "click", "TYPE_TEXT_ENTER": "type_text",
                   "SCROLL_DOWN": "scroll", "SCROLL_UP": "scroll"}


class FastLoopMixin:
    """Mixed into Agent. Each Jev action is a visible, approvable, interruptible step of its own."""

    async def _delegate(self: Agent, subgoal: str, parent: dict[str, Any], *,
                        max_actions: int = FAST_MAX_ACTIONS, force_approval: bool = False) -> str:
        self._fast_recovery = False
        max_actions = max(1, min(FAST_MAX_ACTIONS, int(max_actions)))
        log: list[str] = []
        recent: list[str] = []
        unchanged = 0
        last_sig = None
        for _ in range(max_actions):
            if self.stopped or self.paused:
                return self._handback(log, "the operator paused or stopped the run")
            if self.actions_taken >= self.max_steps:
                return self._handback(log, "the action budget is used up")
            self.n += 1
            step: dict[str, Any] = {"id": f"s{self.n}", "n": self.n, "status": "thinking", "system": "fast",
                                    "parent": parent["id"], "started_at": time.time()}
            await self.set_state("thinking", "Jev is choosing the next action…")
            try:
                page = await self.browser.observe(screenshot=False)
            except (ActionError, PlaywrightError) as exc:
                await self._fail_step(step, str(exc).splitlines()[0][:200])
                return self._handback(log, "the page could not be read")
            sig = hashlib.sha1(f"{page.url}\n{page.text}".encode()).hexdigest()
            unchanged = unchanged + 1 if sig == last_sig else 0
            last_sig = sig
            if unchanged >= NO_CHANGE_LIMIT:
                return self._handback(log, f"the last {NO_CHANGE_LIMIT} actions did not change the page", recovery=True)
            step["url"] = page.url
            await self.send_step(step)
            version = self.guidance_version
            try:
                d = await self.fast.decide(page, goal=self.goal, subgoal=subgoal, recent=recent,
                                           guidance=self.guidance)
            except FastError as exc:
                await self._fail_step(step, str(exc))
                return self._handback(log, f"Jev failed: {exc}", recovery=True)
            self.usage["fast_calls"] += 1
            self.usage["fast_ms_total"] += d.latency_ms
            step.update(confidence=round(d.confidence, 3), alternatives=d.alternatives, latency_ms=d.latency_ms,
                        thought={"evaluation": "", "memory": "", "next_goal": subgoal})
            if self.stopped or self.paused or self.guidance_version != version:
                why = "new guidance arrived" if self.guidance_version != version else "the run was paused"
                step.update(status="skipped", result=f"Discarded because {why}.", ended_at=time.time())
                await self.send_step(step)
                return self._handback(log, why)
            outcome = await self._fast_terminal(step, d, log)
            if outcome:
                return outcome
            result = await self._fast_act(step, d, page, subgoal, recent, force_approval=force_approval)
            if step["status"] == "skipped":
                return self._handback(log, step.get("result", "the action was skipped"))
            if step["status"] == "error":
                return self._handback(log, f"an action failed: {step.get('error')}", recovery=True)
            if step["status"] == "rejected":
                return self._handback(log, "you rejected an action")
            entry = f"{step['action']['label']} → {result}"
            log.append(entry)
            recent.append(entry)
        return self._handback(log, f"Jev used its {max_actions}-action budget; verify the outcome before continuing")

    async def _fast_terminal(self: Agent, step: dict[str, Any], d: Any, log: list[str]) -> str | None:
        pct = f"{d.confidence:.0%}"
        if d.operation == "SUBGOAL_DONE":
            step.update(status="ok", action={"name": "subgoal_done", "args": {}, "label": "Subgoal looks complete"},
                        result=f"Jev reports the subgoal is done ({pct} confident).", ended_at=time.time())
            await self.send_step(step)
            return self._handback(log, f"Jev reports the subgoal is done ({pct} confident); verify on the page")
        if d.operation == "STUCK":
            step.update(status="ok", action={"name": "stuck", "args": {}, "label": "Hand back to the planner"},
                        result="Jev can't progress here with the visible controls.", ended_at=time.time())
            await self.send_step(step)
            return self._handback(log, "Jev is stuck on this page", recovery=True)
        if d.confidence < self.fast.config.min_confidence:
            step.update(status="skipped", action={"name": "unsure", "args": {}, "label": "Not confident enough"},
                        result=f"Jev was only {pct} sure; the planner will decide instead.", ended_at=time.time())
            await self.send_step(step)
            return self._handback(log, f"Jev was unsure ({pct}) about the next action", recovery=True)
        return None

    async def _fast_act(self: Agent, step: dict[str, Any], d: Any, page: Any, subgoal: str,
                        recent: list[str], *, force_approval: bool = False) -> str:
        version = self.guidance_version
        name = OPERATION_TOOLS[d.operation]
        args: dict[str, Any] = {"irreversible": force_approval or d.irreversible >= 0.6}
        if d.operation in ("ACTIVATE", "DEACTIVATE"):
            args["desired_state"] = d.operation == "ACTIVATE"
        target_label = ""
        if d.element_id is not None:
            element = page.element(d.element_id)
            target_label = element["label"] or element["tag"]
            args["element_id"] = d.element_id
            try:
                rect = await self.browser.element_rect(d.element_id)
            except (ActionError, PlaywrightError):
                rect = None
            step["target"] = {"label": target_label, "rect": rect or element["rect"]}
        if name == "scroll":
            args["direction"] = "down" if d.operation == "SCROLL_DOWN" else "up"
        elif name == "select_option":
            args["option"] = d.option
        elif name == "type_text":
            await self.set_state("thinking", "Writing the text to type…")
            try:
                text, ms = await self.fast.write_text(goal=self.goal, subgoal=subgoal, page=page, recent=recent,
                                                      field={k: element.get(k) for k in ("label", "role", "value")})
            except FastError as exc:
                await self._fail_step(step, str(exc))
                return ""
            self.usage["text_calls"] += 1
            step["latency_ms"] = step.get("latency_ms", 0) + ms
            args.update(text=text, press_enter=d.operation == "TYPE_TEXT_ENTER")
        from .agent import _action  # local import avoids a cycle
        step.update(action=_action(name, args, target_label), status="planned")
        if self.paused or self.stopped or self.guidance_version != version:
            await self._skip_satisfied(step, "Decision discarded: stopped, paused, or new guidance arrived.")
            return ""
        if d.element_id is not None:
            satisfied = satisfied_action(name, args, element)
            if satisfied:
                await self._skip_satisfied(step, satisfied)
                return ""
        risky, reason = needs_approval(name, args, target_label, self.approval_mode)
        if risky:
            step["risk"] = {"risky": True, "reason": reason}
            if not await self._approve(step, reason):
                return ""
        await self._execute(step, name, args, decision_version=version)
        return step.get("result", "")

    def _handback(self, log: list[str], reason: str, *, recovery: bool = False) -> str:
        self._fast_recovery = recovery
        done = f"Jev took {len(log)} action{'s' if len(log) != 1 else ''}"
        detail = (": " + "; ".join(log[-8:])) if log else ""
        return f"{done}{detail}. Returned control because {reason}."
