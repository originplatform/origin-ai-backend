"""Central Orchestrator Agent for ORIGIN AI."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field
from app.agents.base import BaseAgent
from app.agents.registry import AGENT_REGISTRY, normalize_agent_id
from app.core.logging import get_logger
from app.graphs.state import OriginState, PlanStep
from app.services.llm_service import llm_service
from app.tools.registry import tool_registry

logger = get_logger("origin.agents.orchestrator")


class PlanStepSchema(BaseModel):
    step_number: int
    agent_name: str = Field(
        description=(
            "Canonical registered agent ID: research, document, file_manager, communication, "
            "browser, shopping_booking, or verification."
        )
    )
    action: str
    tool_id: Optional[str] = None
    input_params: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[int] = Field(default_factory=list)


class OrchestratorPlanOutput(BaseModel):
    intent: str
    objective: str
    selected_agents: List[str] = Field(
        description="Canonical registered agent IDs used by the execution plan."
    )
    selected_tools: List[str]
    steps: List[PlanStepSchema]
    planning_warnings: List[str] = Field(default_factory=list)


DOCUMENT_FORMAT_TO_TOOL = {
    "pdf": "create_pdf",
    "docx": "create_docx",
    "txt": "create_txt",
    "xlsx": "create_excel",
}


def detect_execution_requirements(command: str) -> Dict[str, Any]:
    """Derive research and output requirements from the user's command and registered tools."""
    normalized = command.casefold()
    registered_tools = {
        tool_id for tool_id in DOCUMENT_FORMAT_TO_TOOL.values()
        if tool_registry.is_registered(tool_id)
    }
    formats: List[str] = []
    aliases = {
        "pdf": r"\bpdf\b|\.pdf\b",
        "docx": r"\bdocx\b|\.docx\b|\bword(?:\s+document|\s+file)?\b",
        "txt": r"\btxt\b|\.txt\b|\btext\s+file\b|\bplain\s+text\b",
        "xlsx": r"\bxlsx\b|\.xlsx\b|\bexcel\b|\bspreadsheet\b",
    }
    for file_format, pattern in aliases.items():
        if DOCUMENT_FORMAT_TO_TOOL[file_format] in registered_tools and re.search(pattern, normalized):
            formats.append(file_format)
    formats.sort(
        key=lambda file_format: re.search(aliases[file_format], normalized).start()
    )

    explicitly_researches = bool(
        re.search(
            r"\b(research|investigate|study|latest|current|up-to-date|recent developments|"
            r"reliable web sources|web sources|source-backed|evidence-based)\b",
            normalized,
        )
    )
    research_required = explicitly_researches
    conversion_required = False
    source_filename = ""
    conversion_match = re.search(r"\b(?:convert|transform)\b", command, flags=re.IGNORECASE)
    if conversion_match:
        conversion_parts = re.split(
            r"\b(?:to|into)\b",
            command[conversion_match.end():],
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        if len(conversion_parts) == 2:
            source_match = re.search(
                r"([\w.-]+(?:[\\/][\w .-]+)*\.(?:docx|pdf|txt|md|csv|json|xlsx))",
                conversion_parts[0],
                flags=re.IGNORECASE,
            )
            target_formats = [
                file_format
                for file_format, pattern in aliases.items()
                if re.search(pattern, conversion_parts[1].casefold())
            ]
            target_formats.sort(
                key=lambda file_format: re.search(
                    aliases[file_format],
                    conversion_parts[1].casefold(),
                ).start()
            )
            if source_match and target_formats:
                conversion_required = True
                source_filename = source_match.group(1).strip()
                formats = target_formats
    return {
        "formats": formats,
        "research_required": research_required,
        "conversion_required": conversion_required,
        "source_filename": source_filename,
        "required_tools": [
            *(
                ["web_search"] if research_required and tool_registry.is_registered("web_search") else []
            ),
            *(
                ["read_document"]
                if conversion_required and tool_registry.is_registered("read_document")
                else []
            ),
            *(DOCUMENT_FORMAT_TO_TOOL[file_format] for file_format in formats),
        ],
    }


def _is_email_read_request(command: str) -> bool:
    normalized = command.casefold()
    asks_about_sender = bool(
        re.search(r"\bwhat\s+did\s+[a-z0-9._+-]+\s+say\b", normalized)
    )
    return bool(
        not re.search(r"\b(?:draft|compose|send)\b", normalized)
        and (
            asks_about_sender
            or (
                re.search(r"\b(?:email|emails|mail|mails|inbox|unread)\b", normalized)
                and re.search(
                    r"\b(?:check|show|find|search|read|summarize|summary|latest|unread|"
                    r"received|from|what\s+(?:did|emails?))\b",
                    normalized,
                )
            )
        )
    )


class OrchestratorAgent(BaseAgent):
    """Central decision-making agent that plans, routes, and delegates tasks."""

    name = "Orchestrator Agent"
    description = "Deconstructs natural-language commands into structured agentic plans, selecting approved agents and tools."
    system_prompt = (
        "You are the Lead Orchestrator for ORIGIN AI. "
        "Your task is to analyze user requests, determine intent and concrete objectives, "
        "and generate a step-by-step execution plan selecting only from registered agents and approved tools."
    )
    allowed_tools = []

    def _generate_deterministic_plan(self, user_command: str) -> OrchestratorPlanOutput:
        """Build a requirement-driven plan for recoverable research and document requests."""
        cmd_lower = user_command.lower()
        requirements = detect_execution_requirements(user_command)
        if (
            requirements["research_required"] or requirements["formats"]
        ) and not _is_email_read_request(user_command):
            return self._build_required_plan(user_command, requirements)

        if _is_email_read_request(user_command):
            if "today" in cmd_lower and re.search(r"\breceiv(?:e|ed)\b", cmd_lower):
                operation = "search"
                day_start = datetime.now(timezone.utc).replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                day_end = day_start + timedelta(days=1)
                query = (
                    f"after:{int(day_start.timestamp())} "
                    f"before:{int(day_end.timestamp())}"
                )
            elif "unread" in cmd_lower:
                operation = "unread"
                query = None
            elif (
                any(word in cmd_lower for word in ("find", "search", " from "))
                or "what did" in cmd_lower
            ):
                operation = "search"
                if "what did" in cmd_lower:
                    sender_match = re.search(
                        r"\bwhat did\s+([A-Za-z0-9._+-]+(?:\s+[A-Za-z0-9._+-]+){0,2})\s+say\b",
                        user_command,
                        flags=re.IGNORECASE,
                    )
                else:
                    sender_match = re.search(
                        r"\bfrom\s+([A-Za-z0-9._+-]+(?:\s+[A-Za-z0-9._+-]+){0,2})",
                        user_command,
                        flags=re.IGNORECASE,
                    )
                query = (
                    f"from:{sender_match.group(1).strip()}"
                    if sender_match
                    else user_command
                )
            else:
                operation = "inbox"
                query = None

            params: Dict[str, Any] = {
                "operation": operation,
                "max_results": 10,
            }
            if "summar" in cmd_lower:
                params["summarize"] = True
            if query:
                params["query"] = query
            return OrchestratorPlanOutput(
                intent="Read-only Gmail retrieval",
                objective="Retrieve actual Gmail messages for the authenticated owner.",
                selected_agents=["communication", "verification"],
                selected_tools=["gmail_read"],
                steps=[
                    PlanStepSchema(
                        step_number=1,
                        agent_name="communication",
                        action=f"Read Gmail messages using the {operation} operation",
                        tool_id="gmail_read",
                        input_params=params,
                    ),
                    PlanStepSchema(
                        step_number=2,
                        agent_name="verification",
                        action="Verify that the Gmail read returned provider data.",
                        dependencies=[1],
                    ),
                ],
            )

        # Case 2: File search & email drafting
        elif (
            re.search(r"\b(?:draft|compose|prepare|send)\b", cmd_lower)
            and re.search(r"\b(?:email|mail)\b", cmd_lower)
        ):
            target_query = "report"
            if "find" in cmd_lower and "in my workspace" in cmd_lower:
                part = cmd_lower.split("find", 1)[1].split("in my workspace", 1)[0].strip()
                if part:
                    target_query = part

            steps = [
                PlanStepSchema(
                    step_number=1,
                    agent_name="file_manager",
                    action=f"Locate file matching '{target_query}' in workspace",
                    tool_id="search_workspace_files",
                    input_params={"query": target_query},
                    dependencies=[],
                ),
                PlanStepSchema(
                    step_number=2,
                    agent_name="communication",
                    action="Prepare email draft attaching the located file",
                    tool_id="draft_email",
                    input_params={
                        "to_email": "recipient@example.com",
                        "subject": f"Project Report: {target_query.title()}",
                        "body": "Please find attached the requested report.",
                        "attachments": [],
                    },
                    dependencies=[1],
                ),
                PlanStepSchema(
                    step_number=3,
                    agent_name="verification",
                    action="Verify email draft and attachments readiness",
                    tool_id=None,
                    input_params={},
                    dependencies=[1, 2],
                ),
            ]

            return OrchestratorPlanOutput(
                intent="Workspace file discovery and email draft preparation",
                objective=f"Locate '{target_query}' in authorized workspace, prepare verified draft with attachment, and preserve safety gate for external sending.",
                selected_agents=["file_manager", "communication", "verification"],
                selected_tools=["search_workspace_files", "draft_email"],
                steps=steps,
            )

        # Case 3: Generic fallback
        steps = [
            PlanStepSchema(
                step_number=1,
                agent_name="research",
                action=f"Analyze and process instruction: {user_command}",
                tool_id="web_search",
                input_params={"query": user_command, "max_results": 3},
                dependencies=[],
            ),
            PlanStepSchema(
                step_number=2,
                agent_name="document",
                action="Summarize execution in workspace text document",
                tool_id="create_txt",
                input_params={"filename": "task_summary.txt", "content": f"Task execution record for: {user_command}"},
                dependencies=[1],
            ),
            PlanStepSchema(
                step_number=3,
                agent_name="verification",
                action="Confirm task completion and output validation",
                tool_id=None,
                input_params={},
                dependencies=[1, 2],
            ),
        ]

        return OrchestratorPlanOutput(
            intent="Process user instruction and persist execution summary",
            objective=f"Execute command: '{user_command}'",
            selected_agents=["research", "document", "verification"],
            selected_tools=["web_search", "create_txt"],
            steps=steps,
        )

    @staticmethod
    def _build_required_plan(
        user_command: str,
        requirements: Dict[str, Any],
    ) -> OrchestratorPlanOutput:
        """Build the research, document, and verification steps required by the command."""
        requirements = {
            "research_required": False,
            "formats": [],
            "conversion_required": False,
            "source_filename": "",
            **requirements,
        }
        steps: List[PlanStepSchema] = []
        selected_tools: List[str] = []
        research_step_number: Optional[int] = None
        if requirements["research_required"]:
            research_tool = "web_search"
            if not tool_registry.is_registered(research_tool):
                raise ValueError("Research was requested, but the registered web_search tool is unavailable.")
            research_step_number = len(steps) + 1
            steps.append(
                PlanStepSchema(
                    step_number=research_step_number,
                    agent_name="research",
                    action=f"Research the requested topic: {user_command}",
                    tool_id=research_tool,
                    input_params={"query": user_command},
                )
            )
            selected_tools.append(research_tool)

        source_step_number: Optional[int] = None
        if requirements["conversion_required"]:
            if not tool_registry.is_registered("read_document"):
                raise ValueError("File conversion requires the registered 'read_document' tool.")
            source_step_number = len(steps) + 1
            steps.append(
                PlanStepSchema(
                    step_number=source_step_number,
                    agent_name="file_manager",
                    action=f"Read source file '{requirements['source_filename']}' for conversion",
                    tool_id="read_document",
                    input_params={"filename_or_path": requirements["source_filename"]},
                    dependencies=[research_step_number] if research_step_number else [],
                )
            )
            selected_tools.append("read_document")

        title_topic = re.sub(r"\s+", " ", user_command).strip().rstrip(".!?")
        filename_topic = re.sub(r"[^a-z0-9]+", "_", title_topic.casefold()).strip("_")[:48]
        for file_format in requirements["formats"]:
            tool_id = DOCUMENT_FORMAT_TO_TOOL[file_format]
            tool = tool_registry.get_tool(tool_id)
            if tool is None:
                raise ValueError(
                    f"Requested {file_format.upper()} output requires unregistered tool '{tool_id}'."
                )
            params: Dict[str, Any] = {
                "filename": f"{filename_topic or 'report'}.{file_format}",
            }
            if file_format == "pdf":
                params.update({"title": title_topic, "sections": [], "author": "ORIGIN AI"})
            elif file_format == "docx":
                params.update({"title": title_topic, "sections": [], "subtitle": "ORIGIN AI Research Report"})
            elif file_format == "txt":
                params["content"] = ""
            elif file_format == "xlsx":
                params.update({"headers": ["Section", "Research"], "rows": []})
            steps.append(
                PlanStepSchema(
                    step_number=len(steps) + 1,
                    agent_name="document",
                    action=(
                        f"Convert source content to {file_format.upper()}"
                        if requirements["conversion_required"]
                        else f"Create requested {file_format.upper()} output"
                    ),
                    tool_id=tool_id,
                    input_params=params,
                    dependencies=[
                        dependency
                        for dependency in (research_step_number, source_step_number)
                        if dependency
                    ],
                )
            )
            selected_tools.append(tool_id)

        if requirements["research_required"] or requirements["formats"]:
            steps.append(
                PlanStepSchema(
                    step_number=len(steps) + 1,
                    agent_name="verification",
                    action="Verify requested research and output requirements",
                    dependencies=[step.step_number for step in steps],
                )
            )
        return OrchestratorPlanOutput(
            intent=(
                "Research and generate requested documents"
                if requirements["formats"] and requirements["research_required"]
                else "Generate requested documents"
                if requirements["formats"]
                else "Research requested topic"
            ),
            objective=f"Complete the requested research and deliverables: {user_command}",
            selected_agents=list(dict.fromkeys(step.agent_name for step in steps)),
            selected_tools=selected_tools,
            steps=steps,
        )

    @staticmethod
    def _validate_and_repair_plan(
        command: str,
        plan: OrchestratorPlanOutput,
    ) -> OrchestratorPlanOutput:
        """Repair missing requested research/document steps and validate tool and dependency integrity."""
        requirements = detect_execution_requirements(command)
        steps = list(plan.steps)
        for selected_agent in plan.selected_agents:
            normalize_agent_id(selected_agent)
        for selected_tool in plan.selected_tools:
            if not tool_registry.is_registered(selected_tool):
                raise ValueError(f"Execution plan references unregistered tool '{selected_tool}'.")
        for step in steps:
            try:
                step.agent_name = normalize_agent_id(step.agent_name)
            except ValueError as exc:
                raise ValueError(
                    f"Execution plan contains unknown agent '{step.agent_name}'."
                ) from exc
            if step.tool_id and not tool_registry.is_registered(step.tool_id):
                raise ValueError(f"Execution plan references unregistered tool '{step.tool_id}'.")
        if requirements["formats"]:
            required_agents = {"document", "verification"}
            if requirements["research_required"]:
                required_agents.add("research")
            if requirements["conversion_required"]:
                required_agents.add("file_manager")
            requested_document_tools = {
                DOCUMENT_FORMAT_TO_TOOL[file_format]
                for file_format in requirements["formats"]
            }
            retained_steps = []
            seen_required_steps = set()
            for step in steps:
                relevant = step.agent_name in required_agents
                if step.agent_name == "document":
                    relevant = step.tool_id in requested_document_tools
                elif step.agent_name == "research":
                    relevant = step.tool_id == "web_search"
                elif step.agent_name == "file_manager":
                    relevant = (
                        requirements["conversion_required"]
                        and step.tool_id == "read_document"
                    )
                if not relevant:
                    continue
                key = (
                    (step.agent_name, None)
                    if step.agent_name == "verification"
                    else (step.agent_name, step.tool_id)
                )
                if key in seen_required_steps:
                    continue
                seen_required_steps.add(key)
                retained_steps.append(step)
            removed_step_ids = {
                step.step_number for step in steps if step not in retained_steps
            }
            if removed_step_ids:
                logger.warning(
                    "Removed non-required execution steps from document plan: %s",
                    sorted(removed_step_ids),
                )
                plan.planning_warnings.append(
                    "Removed plan steps not required for the requested document workflow."
                )
                for step in retained_steps:
                    step.dependencies = [
                        dependency
                        for dependency in step.dependencies
                        if dependency not in removed_step_ids
                    ]
                steps = retained_steps
        if not requirements["research_required"]:
            steps = [
                step for step in steps
                if step.agent_name != "research" and step.tool_id != "web_search"
            ]
            removed_step_ids = {
                step.step_number for step in plan.steps if step not in steps
            }
            if removed_step_ids:
                for step in steps:
                    step.dependencies = [
                        dependency for dependency in step.dependencies
                        if dependency not in removed_step_ids
                    ]
        if not steps and not (
            requirements["research_required"] or requirements["formats"]
        ):
            raise ValueError("Orchestrator returned an empty execution plan.")

        step_ids = [step.step_number for step in steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("Execution plan contains duplicate step numbers.")
        known_step_ids = set(step_ids)
        for step in steps:
            if step.agent_name not in AGENT_REGISTRY:
                raise ValueError(f"Execution plan contains unknown agent '{step.agent_name}'.")
            if (
                step.agent_name == "verification"
                and step.tool_id == "read_document"
                and not requirements["conversion_required"]
            ):
                step.tool_id = None
                step.input_params = {}
            if (
                step.tool_id in DOCUMENT_FORMAT_TO_TOOL.values()
                and step.tool_id in requirements["required_tools"]
            ):
                step.agent_name = "document"
            elif step.tool_id == "web_search" and requirements["research_required"]:
                step.agent_name = "research"
            elif step.tool_id == "read_document" and requirements["conversion_required"]:
                step.agent_name = "file_manager"
            if step.tool_id:
                if not tool_registry.is_registered(step.tool_id):
                    raise ValueError(f"Execution plan references unregistered tool '{step.tool_id}'.")
                if step.tool_id not in AGENT_REGISTRY[step.agent_name].allowed_tools:
                    raise ValueError(
                        f"Agent '{step.agent_name}' is not allowed to use tool '{step.tool_id}'."
                    )
            missing_dependencies = set(step.dependencies) - known_step_ids
            if missing_dependencies or step.step_number in step.dependencies:
                raise ValueError(
                    f"Step {step.step_number} has invalid dependencies: "
                    f"{sorted(missing_dependencies or {step.step_number})}."
                )

        if requirements["research_required"]:
            research_steps = [step for step in steps if step.agent_name == "research"]
            if not research_steps:
                next_id = max(step_ids, default=0) + 1
                research_steps = [
                    PlanStepSchema(
                        step_number=next_id,
                        agent_name="research",
                        action=f"Research the requested topic: {command}",
                        tool_id="web_search",
                        input_params={"query": command},
                    )
                ]
                steps.extend(research_steps)
                step_ids.append(next_id)
            research_tool = next(
                (step for step in research_steps if step.tool_id == "web_search"),
                research_steps[0],
            )
            if not tool_registry.is_registered("web_search"):
                raise ValueError("Research cannot be repaired because 'web_search' is not registered.")
            if research_tool.tool_id != "web_search":
                research_tool.tool_id = "web_search"
            research_tool.dependencies = []

        source_step: Optional[PlanStepSchema] = None
        if requirements["conversion_required"]:
            if not tool_registry.is_registered("read_document"):
                raise ValueError("File conversion cannot be repaired without 'read_document'.")
            source_step = next(
                (step for step in steps if step.tool_id == "read_document"),
                None,
            )
            if source_step is None:
                next_id = max((step.step_number for step in steps), default=0) + 1
                source_step = PlanStepSchema(
                    step_number=next_id,
                    agent_name="file_manager",
                    action=f"Read source file '{requirements['source_filename']}' for conversion",
                    tool_id="read_document",
                    input_params={"filename_or_path": requirements["source_filename"]},
                )
                steps.append(source_step)
            source_step.agent_name = "file_manager"
            source_step.input_params["filename_or_path"] = requirements["source_filename"]
            research_step = next(
                (step for step in steps if requirements["research_required"] and step.agent_name == "research"),
                None,
            )
            source_step.dependencies = [research_step.step_number] if research_step else []

        for file_format in requirements["formats"]:
            tool_id = DOCUMENT_FORMAT_TO_TOOL[file_format]
            if not tool_registry.is_registered(tool_id):
                raise ValueError(
                    f"Requested {file_format.upper()} output requires unregistered tool '{tool_id}'."
                )
            existing = next((step for step in steps if step.tool_id == tool_id), None)
            if existing is None:
                next_id = max((step.step_number for step in steps), default=0) + 1
                repaired = OrchestratorAgent._build_required_plan(
                    command,
                    {"research_required": False, "formats": [file_format]},
                ).steps[0]
                repaired.step_number = next_id
                existing = repaired
                steps.append(existing)
                logger.warning(
                    "Repaired incomplete plan: inserted registered tool '%s' for requested %s output",
                    tool_id,
                    file_format.upper(),
                )
            existing.agent_name = "document"
            existing.dependencies = []
            research_step = next(
                (
                    step for step in steps
                    if requirements["research_required"] and step.agent_name == "research"
                ),
                None,
            )
            if research_step:
                existing.dependencies = list(
                    dict.fromkeys([*existing.dependencies, research_step.step_number])
                )
            if source_step:
                existing.dependencies = list(
                    dict.fromkeys([*existing.dependencies, source_step.step_number])
                )

        if requirements["research_required"] or requirements["formats"]:
            verification_steps = [
                step for step in steps if step.agent_name == "verification"
            ]
            if not verification_steps:
                next_id = max((step.step_number for step in steps), default=0) + 1
                verification_steps = [
                    PlanStepSchema(
                        step_number=next_id,
                        agent_name="verification",
                        action="Verify research findings and requested outputs",
                    )
                ]
                steps.extend(verification_steps)

            if requirements["formats"]:
                research = [step for step in steps if step.agent_name == "research"]
                source_reads = [
                    step for step in steps
                    if requirements["conversion_required"] and step.tool_id == "read_document"
                ]
                other = [
                    step for step in steps
                    if step.agent_name not in {
                        "research",
                        "document",
                        "verification",
                    } and step not in source_reads
                ]
                documents = [step for step in steps if step.agent_name == "document"]
                verifications = [step for step in steps if step.agent_name == "verification"]
                steps = [*research, *source_reads, *other, *documents, *verifications]
            elif requirements["research_required"]:
                research = [step for step in steps if step.agent_name == "research"]
                verifications = [step for step in steps if step.agent_name == "verification"]
                other = [
                    step for step in steps
                    if step.agent_name not in {"research", "verification"}
                ]
                steps = [*research, *other, *verifications]

            old_to_new = {step.step_number: index for index, step in enumerate(steps, start=1)}
            for index, step in enumerate(steps, start=1):
                invalid = set(step.dependencies) - set(old_to_new)
                if invalid:
                    raise ValueError(
                        f"Step {step.step_number} depends on unknown steps: {sorted(invalid)}."
                    )
                step.dependencies = list(
                    dict.fromkeys(old_to_new[dependency] for dependency in step.dependencies)
                )
                step.step_number = index

            research_numbers = [
                step.step_number for step in steps if step.agent_name == "research"
            ]
            if research_numbers:
                for step in steps:
                    if step.agent_name == "document":
                        step.dependencies = list(dict.fromkeys([*step.dependencies, research_numbers[0]]))
            verification_numbers = [
                step.step_number for step in steps if step.agent_name == "verification"
            ]
            for step in steps:
                if step.step_number in verification_numbers:
                    step.dependencies = [
                        previous.step_number
                        for previous in steps
                        if previous.step_number < step.step_number
                    ]

        positions = {step.step_number: index for index, step in enumerate(steps)}
        for step in steps:
            for dependency in step.dependencies:
                if dependency not in positions or positions[dependency] >= positions[step.step_number]:
                    raise ValueError(
                        f"Step {step.step_number} dependency {dependency} does not execute first."
                    )

        actual_tools = {step.tool_id for step in steps if step.tool_id}
        missing_tools = set(requirements["required_tools"]) - actual_tools
        if missing_tools:
            raise ValueError(
                "Execution plan repair did not include required registered tools: "
                + ", ".join(sorted(missing_tools))
            )
        if requirements["formats"] and requirements["research_required"]:
            ordered_agents = [step.agent_name for step in steps]
            if not (
                ordered_agents.index("research")
                < ordered_agents.index("document")
                < ordered_agents.index("verification")
            ):
                raise ValueError("Research-document plan must order Research, Document, then Verification.")

        plan.steps = steps
        plan.selected_agents = list(dict.fromkeys(step.agent_name for step in steps))
        plan.selected_tools = list(dict.fromkeys(step.tool_id for step in steps if step.tool_id))
        return plan

    async def create_plan(self, user_command: str) -> OrchestratorPlanOutput:
        """Generate an LLM plan, then repair requirements deterministically when possible."""
        if _is_email_read_request(user_command):
            return self._generate_deterministic_plan(user_command)
        requirements = detect_execution_requirements(user_command)
        prompt = (
            f"User Command: {user_command}\n"
            "Generate an execution plan with intent, objective, selected agents, selected tools, and sequential steps. "
            "Use only canonical agent IDs: research, document, file_manager, communication, browser, "
            "shopping_booking, verification. For research reports, run research before document, include "
            "every requested output format, pass research results through shared state, and finish with verification.\n"
            f"Detected requirements: {requirements}\n"
            f"Registered tools: {tool_registry.list_tools()}\n"
            "The `agent_name` and `selected_agents` fields must use canonical IDs, never class or display names.\n"
        )
        warnings: List[str] = []
        try:
            plan = await llm_service.generate_structured(
                prompt=prompt,
                response_model=OrchestratorPlanOutput,
                system_prompt=self.system_prompt,
            )
        except Exception as exc:
            logger.exception("LLM planning failed; attempting requirement-based recovery")
            if not (requirements["research_required"] or requirements["formats"]):
                raise RuntimeError(f"LLM planning failed: {exc}") from exc
            warnings.append(f"LLM planning failed; recovered from user requirements: {exc}")
            try:
                plan = self._build_required_plan(user_command, requirements)
            except Exception as recovery_exc:
                logger.exception("Requirement-based plan recovery failed")
                raise RuntimeError(
                    f"LLM planning failed: {exc}; requirement-based recovery failed: {recovery_exc}"
                ) from exc

        plan.planning_warnings.extend(warnings)
        try:
            plan = self._validate_and_repair_plan(user_command, plan)
        except Exception as exc:
            logger.exception("Orchestrator plan validation or repair failed")
            original_error = plan.planning_warnings
            message = (
                f"Plan validation/repair failed: {exc}; "
                + ("; ".join(original_error) if original_error else "LLM plan was returned successfully.")
            )
            raise ValueError(message) from exc
        return plan

    async def process(self, state: OriginState, context: Optional[Dict[str, Any]] = None) -> OriginState:
        """Orchestrator node execution: understands intent and populates plan."""
        logger.info(f"Orchestrator planning task '{state.task_id}': {state.user_command}")
        plan_output = await self.create_plan(state.user_command)

        state.intent = plan_output.intent
        state.objective = plan_output.objective
        state.planning_warnings = plan_output.planning_warnings
        state.selected_agents = plan_output.selected_agents
        state.selected_tools = plan_output.selected_tools
        state.execution_plan = [
            PlanStep(
                step_number=s.step_number,
                agent_name=s.agent_name,
                action=s.action,
                tool_id=s.tool_id,
                input_params=s.input_params,
                dependencies=s.dependencies,
                status="PENDING",
            )
            for s in plan_output.steps
        ]
        state.current_step_index = 0
        state.status = "PLANNING"
        return state


orchestrator_agent = OrchestratorAgent()
