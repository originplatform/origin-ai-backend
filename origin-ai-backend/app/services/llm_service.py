"""LLM Service Module supporting Groq and Deterministic Fallback."""

import json
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel
from app.core.config import settings
from app.core.logging import get_logger, redact_sensitive_text

logger = get_logger("origin.services.llm")


class LLMService:
    """Provides resilient LLM inference with Groq and deterministic fallback."""

    def __init__(self) -> None:
        self.api_key = settings.GROQ_API_KEY
        self.primary_model = settings.GROQ_MODEL
        self.fallback_model = settings.FALLBACK_MODEL
        self._groq_client = None

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
                logger.warning(f"Failed to initialize Groq client: {exc}. Using deterministic engine.")
                self._groq_client = None
        else:
            logger.info("No GROQ_API_KEY detected. Using deterministic execution engine.")

    def is_live_llm_available(self) -> bool:
        """Checks if a live LLM integration is active."""
        return self._groq_client is not None

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generates plain text response."""
        safe_prompt = redact_sensitive_text(prompt)
        if self._groq_client:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage

                messages = []
                if system_prompt:
                    messages.append(SystemMessage(content=system_prompt))
                messages.append(HumanMessage(content=safe_prompt))

                response = await self._groq_client.ainvoke(messages)
                return str(response.content)
            except Exception as exc:
                logger.error(f"Groq invocation failed: {exc}. Using fallback logic.")

        # Fallback response
        return f"Processed query: {safe_prompt}"

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        system_prompt: Optional[str] = None,
        deterministic_fallback: Optional[Dict[str, Any]] = None,
    ) -> BaseModel:
        """Generates validated structured output matching a Pydantic model."""
        safe_prompt = redact_sensitive_text(prompt)

        if self._groq_client:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage

                structured_llm = self._groq_client.with_structured_output(response_model)
                messages = []
                if system_prompt:
                    messages.append(SystemMessage(content=system_prompt))
                messages.append(HumanMessage(content=safe_prompt))

                result = await structured_llm.ainvoke(messages)
                if isinstance(result, response_model):
                    return result
                elif isinstance(result, dict):
                    return response_model.model_validate(result)
            except Exception as exc:
                logger.warning(
                    f"Groq structured generation failed: {exc}. Falling back to deterministic engine."
                )

        # Deterministic fallback logic
        if deterministic_fallback:
            return response_model.model_validate(deterministic_fallback)

        raise ValueError(
            f"No live LLM response and no deterministic fallback provided for model {response_model.__name__}"
        )


llm_service = LLMService()

