from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.paths import write_text
from app.runtime_modules.errors import WorkflowError
from .step_utils import step_agent_name, step_config


class ReviewActionsMixin:

    async def _run_multi_agent_review(
        self,
        run: dict[str, Any],
        step_record: dict[str, Any],
        prompt_name: str,
        artifact: str,
        *,
        allow_interaction: bool,
        agent_name: str | None,
    ) -> None:
        config = step_config(step_record)
        reviewers = config.get("reviewers") or []
        if not isinstance(reviewers, list) or not reviewers:
            await self.log(run, f"{step_record.get('key')}: multi_agent has no reviewers; falling back to current_session review")
            output = await self.run_agent_step(
                run,
                step_record["key"],
                prompt_name,
                artifact,
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            )
            decision = self._review_decision(output, config)
            if not decision["passed"]:
                raise WorkflowError(f"{step_record.get('key')}: review failed: {decision['reason']}")
            return

        output_dir = Path(run["workspace"]) / "output"
        stem = Path(artifact).stem
        suffix = Path(artifact).suffix or ".md"
        available_agents = self.agent_runner.agent_manager.available_agent_names()
        default_agent = agent_name or step_agent_name(step_record) or self.agent_runner.agent_manager.default_agent_name()
        decisions: list[dict[str, Any]] = []

        for index, reviewer in enumerate(reviewers, start=1):
            reviewer = reviewer if isinstance(reviewer, dict) else {}
            configured_agent = str(reviewer.get("provider") or reviewer.get("agent") or "").strip()
            provider = configured_agent if configured_agent in available_agents else default_agent
            profile = configured_agent if configured_agent and configured_agent not in available_agents else ""
            reviewer_prompt = str(reviewer.get("prompt") or prompt_name)
            reviewer_artifact = f"{stem}.reviewer-{index}{suffix}"
            weight = float(reviewer.get("weight") or 1)
            try:
                if profile:
                    await self.log(run, f"{step_record.get('key')}: reviewer {index} profile={profile} uses provider={provider}")
                output = await self.run_agent_step(
                    run,
                    step_record["key"],
                    reviewer_prompt,
                    reviewer_artifact,
                    allow_interaction=allow_interaction,
                    agent_name=provider,
                    fresh_session=True,
                )
                decision = self._review_decision(output, config)
                decision.update({"index": index, "agent": provider, "profile": profile, "weight": weight, "artifact": reviewer_artifact, "output": output})
            except Exception as exc:
                decision = {
                    "index": index,
                    "agent": provider,
                    "profile": profile,
                    "weight": weight,
                    "artifact": reviewer_artifact,
                    "output": "",
                    "passed": False,
                    "confidence": 0.0,
                    "reason": str(exc),
                }
                write_text(output_dir / reviewer_artifact, f"Status: FAIL\n\nReviewer execution failed:\n\n{exc}\n")
                await self.refresh_artifacts(run["id"])
            decisions.append(decision)

        aggregate = self._aggregate_review(config, decisions)
        write_text(output_dir / artifact, self._render_multi_agent_review(aggregate, decisions))
        await self.refresh_artifacts(run["id"])
        if not aggregate["passed"]:
            raise WorkflowError(f"{step_record.get('key')}: multi_agent review failed: {aggregate['reason']}")

    def _review_decision(self, output: str, config: dict[str, Any]) -> dict[str, Any]:
        text = output or ""
        json_decision = self._review_json_decision(text)
        if json_decision is not None:
            status = str(json_decision.get("status") or "").strip().upper()
            confidence = self._coerce_confidence(json_decision.get("confidence"))
            reason = str(json_decision.get("reason") or json_decision.get("summary") or status or "json review decision").strip()
            if status == "PASS":
                threshold = float(config.get("confidenceThreshold") or 0)
                effective_confidence = confidence if confidence is not None else 1.0
                if effective_confidence < threshold:
                    return {"passed": False, "confidence": effective_confidence, "reason": f"confidence {effective_confidence:.2f} < threshold {threshold:.2f}"}
                return {"passed": True, "confidence": effective_confidence, "reason": reason}
            if status in {"FAIL", "BLOCKED", "RISK"}:
                return {"passed": False, "confidence": confidence or 0.0, "reason": reason or f"json status {status}"}

        lowered = text.lower()
        pass_keywords = self._split_keywords(config.get("passKeywords") or "PASS, APPROVED")
        fail_keywords = self._split_keywords(config.get("failKeywords") or "FAIL, BLOCKED")
        confidence = self._extract_confidence(text)

        fail_hit = next((keyword for keyword in fail_keywords if keyword.lower() in lowered), "")
        pass_hit = next((keyword for keyword in pass_keywords if keyword.lower() in lowered), "")
        if fail_hit:
            return {"passed": False, "confidence": confidence or 0.0, "reason": f"matched fail keyword: {fail_hit}"}
        if pass_keywords and not pass_hit:
            return {"passed": False, "confidence": confidence or 0.0, "reason": "no pass keyword matched"}
        effective_confidence = confidence if confidence is not None else (1.0 if pass_hit else 0.75)
        threshold = float(config.get("confidenceThreshold") or 0)
        if effective_confidence < threshold:
            return {"passed": False, "confidence": effective_confidence, "reason": f"confidence {effective_confidence:.2f} < threshold {threshold:.2f}"}
        return {"passed": True, "confidence": effective_confidence, "reason": pass_hit or "passed"}

    @staticmethod
    def _review_json_decision(output: str) -> dict[str, Any] | None:
        text = (output or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _coerce_confidence(value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed > 1 and parsed <= 100:
            parsed = parsed / 100.0
        return max(0.0, min(1.0, parsed))

    def _aggregate_review(self, config: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
        aggregator = str(config.get("aggregatorFunction") or "keyword_confidence")
        if not decisions:
            return {"passed": True, "reason": "no reviewers configured", "aggregator": aggregator}
        pass_weight = sum(float(item.get("weight") or 1) for item in decisions if item.get("passed"))
        total_weight = sum(float(item.get("weight") or 1) for item in decisions) or 1
        if aggregator == "all_must_pass":
            passed = all(item.get("passed") for item in decisions)
            reason = "all reviewers passed" if passed else "at least one reviewer failed"
        elif aggregator == "majority_vote":
            passed = pass_weight > (total_weight / 2)
            reason = f"pass weight {pass_weight:g}/{total_weight:g}"
        else:
            threshold = float(config.get("confidenceThreshold") or 0)
            avg_confidence = sum(float(item.get("confidence") or 0) * float(item.get("weight") or 1) for item in decisions) / total_weight
            passed = pass_weight > 0 and avg_confidence >= threshold and not any(not item.get("passed") for item in decisions)
            reason = f"avg confidence {avg_confidence:.2f}, pass weight {pass_weight:g}/{total_weight:g}"
        return {"passed": passed, "reason": reason, "aggregator": aggregator, "pass_weight": pass_weight, "total_weight": total_weight}

    def _render_multi_agent_review(self, aggregate: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
        status = "PASS" if aggregate.get("passed") else "FAIL"
        lines = [
            f"Status: {status}",
            "",
            "## Multi-Agent Review Summary",
            f"- Aggregator: {aggregate.get('aggregator')}",
            f"- Decision: {aggregate.get('reason')}",
            "",
            "## Reviewer Results",
        ]
        for item in decisions:
            reviewer_status = "PASS" if item.get("passed") else "FAIL"
            profile = f" / profile={item.get('profile')}" if item.get("profile") else ""
            lines.extend(
                [
                    f"### Reviewer {item.get('index')} - {reviewer_status}",
                    f"- Agent: {item.get('agent')}{profile}",
                    f"- Weight: {item.get('weight')}",
                    f"- Confidence: {float(item.get('confidence') or 0):.2f}",
                    f"- Reason: {item.get('reason')}",
                    f"- Artifact: {item.get('artifact')}",
                    "",
                    "```text",
                    str(item.get("output") or "").strip()[:4000],
                    "```",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _split_keywords(self, value: str) -> list[str]:
        return [part.strip() for part in re.split(r"[,\n]", str(value or "")) if part.strip()]

    def _extract_confidence(self, text: str) -> float | None:
        match = re.search(r"\bconfidence\s*[:=]\s*(0(?:\.\d+)?|1(?:\.0+)?|\d{1,3}(?:\.\d+)?)\s*%?", text, re.I)
        if not match:
            return None
        value = float(match.group(1))
        if value > 1:
            value = value / 100
        return max(0.0, min(1.0, value))

