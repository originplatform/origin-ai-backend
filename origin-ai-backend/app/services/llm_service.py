"""LLM service backed by Groq."""

from typing import Optional, Type
from pydantic import BaseModel
from app.core.config import settings
from app.core.logging import get_logger, redact_sensitive_text

logger = get_logger("origin.services.llm")


class LLMService:
    """Provides Groq inference and surfaces provider failures to task execution."""

    def __init__(self) -> None:
        self.api_key = settings.GROQ_API_KEY
        self.primary_model = settings.GROQ_MODEL
        self._groq_client = None
        self._initialization_error: Optional[str] = None

        if self.api_key and self.api_key.strip():
            try:
                from langchain_groq import ChatGroq

                self._groq_client = ChatGroq(
                    groq_api_key=self.api_key,
                    model_name=self.primary_model,
                    temperature=0.1,
                )
                logger.info(f"Initialized Groq client with model '{self.primary_model}'")
            except Exception as exc:
                self._initialization_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Failed to initialize Groq client for model '%s'", self.primary_model)
                self._groq_client = None
        else:
            self._initialization_error = "GROQ_API_KEY is not configured."
            logger.error(self._initialization_error)

    def is_live_llm_available(self) -> bool:
        """Checks if a live LLM integration is active."""
        return self._groq_client is not None

    def _require_client(self):
        if self._groq_client is None:
            raise RuntimeError(
                f"Groq model '{self.primary_model}' is unavailable: {self._initialization_error or 'client was not initialized'}"
            )
        return self._groq_client

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generates plain text response."""
        safe_prompt = redact_sensitive_text(prompt)
        client = self._require_client()
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=safe_prompt))

        try:
            response = await client.ainvoke(messages)
            return str(response.content)
        except Exception as exc:
            logger.exception("Groq invocation failed for model '%s'", self.primary_model)
            raise RuntimeError(f"Groq invocation failed for model '{self.primary_model}': {exc}") from exc

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        system_prompt: Optional[str] = None,
    ) -> BaseModel:
        """Generates validated structured output matching a Pydantic model."""
        safe_prompt = redact_sensitive_text(prompt)
        client = self._require_client()
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=safe_prompt))

        try:
            structured_llm = client.with_structured_output(
                response_model,
                method="json_schema",
                strict=False,
            )
            result = await structured_llm.ainvoke(messages)
            if isinstance(result, response_model):
                return result
            if isinstance(result, dict):
                return response_model.model_validate(result)
            raise TypeError(
                f"Groq returned unsupported structured output type: {type(result).__name__}"
            )
        except Exception as exc:
            logger.exception(
                "Groq structured generation failed for model '%s' and schema '%s'",
                self.primary_model,
                response_model.__name__,
            )
            raise RuntimeError(
                f"Groq structured generation failed for model '{self.primary_model}' "
                f"and schema '{response_model.__name__}': {exc}"
            ) from exc


llm_service = LLMService()
