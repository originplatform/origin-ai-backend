"""Verification Agent Module for Grounded Outcome Validation."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.core.logging import get_logger
from app.core.security import PathSecurity
from app.graphs.state import OriginState, PlanStep

logger = get_logger("origin.agents.verifier")


class VerificationAgent(BaseAgent):
    """
    Validates physical execution artifacts and confirms task completion.
    A model-generated statement is not proof of execution.
    """

    name = "Verification Agent"
    description = "Inspects physical filesystem artifacts, validates tool outcomes, and compiles verification proof."
    system_prompt = "You are the Verification Specialist for ORIGIN AI. Ensure objective, grounded validation."
    allowed_tools = []

    async def verify_task(
        self,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Performs objective audit of all execution outputs."""
        evidence: Dict[str, Any] = {
            "verified_files": [],
            "verified_drafts": [],
            "completed_steps": 0,
            "total_steps": len(state.execution_plan),
            "all_steps_successful": True,
            "discrepancies": [],
        }

        # 1. Audit step completion
        for step in state.execution_plan:
            if step.agent_name == "Verification Agent":
                continue

            if step.status == "COMPLETED":
                evidence["completed_steps"] += 1
            else:
                evidence["all_steps_successful"] = False
                evidence["discrepancies"].append(
                    f"Step {step.step_number} ({step.action}) ended with status '{step.status}': {step.error}"
                )

        # 2. Audit generated files on disk
        doc_outputs = state.agent_outputs.get("document", [])
        if not isinstance(doc_outputs, list):
            doc_outputs = [doc_outputs] if doc_outputs else []

        for item in doc_outputs:
            if isinstance(item, dict) and "filename" in item and item.get("filename"):
                fname = item["filename"]
                try:
                    safe_p = PathSecurity.resolve_safe_path(fname, allow_create_parent=False)
                    if safe_p.is_file() and safe_p.stat().st_size > 0:
                        size = safe_p.stat().st_size
                        computed_hash = PathSecurity.compute_sha256(safe_p)
                        evidence["verified_files"].append({
                            "filename": fname,
                            "exists": True,
                            "size_bytes": size,
                            "sha256": computed_hash,
                            "verified_readable": True,
                            "file_id": item.get("file_id"),
                        })
                    else:
                        evidence["discrepancies"].append(f"Claimed file '{fname}' is missing or 0 bytes on disk.")
                        evidence["all_steps_successful"] = False
                except Exception as exc:
                    evidence["discrepancies"].append(f"Verification error checking '{fname}': {exc}")
                    evidence["all_steps_successful"] = False

        # 3. Audit communication drafts
        comm_output = state.agent_outputs.get("communication", {})
        if comm_output and isinstance(comm_output, dict):
            if "to_email" in comm_output:
                evidence["verified_drafts"].append({
                    "recipient": comm_output.get("to_email"),
                    "subject": comm_output.get("subject"),
                    "attachments_count": len(comm_output.get("attachments", [])),
                    "status": "DRAFT_READY",
                })

        return evidence

    async def execute_step(
        self,
        step: PlanStep,
        state: OriginState,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        evidence = await self.verify_task(state, context)
        return evidence

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        evidence = await self.verify_task(state, context)
        state.verification_evidence = evidence
        return state


verification_agent = VerificationAgent()

