from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Mapping, Sequence, Union

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM failures."""


class LLMConfigurationError(LLMError):
    """Raised when required configuration is missing."""


class LLMProviderNotSupported(LLMError):
    """Raised when the requested provider is not implemented."""


class LLMRequestError(LLMError):
    """Raised when the provider returns an error response."""

    def __init__(self, message: str, status_code: int | None = None, payload: object | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    content: str
    raw: Mapping[str, object]


MessageInput = Union[ChatMessage, Mapping[str, str]]


class LLMClient:
    """Simple LLM-agnostic chat client with OpenAI as the default provider."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ):
        self.provider = (provider or getattr(settings, "LLM_PROVIDER", "openai")).lower()
        self.model = model or getattr(settings, "OPENAI_DEFAULT_MODEL", "gpt-4o")
        self.timeout = timeout or int(getattr(settings, "LLM_TIMEOUT", 30))
        self._api_key = api_key or getattr(settings, "OPENAI_API_KEY", None)
        self._api_base = getattr(settings, "OPENAI_API_BASE", "https://api.openai.com/v1")

    def chat(self, messages: Sequence[MessageInput], **options) -> LLMResponse:
        normalized = self._normalize_messages(messages)
        if self.provider == "openai":
            return self._chat_openai(normalized, **options)
        raise LLMProviderNotSupported(f"LLM provider '{self.provider}' is not supported yet.")

    def _normalize_messages(self, messages: Sequence[MessageInput]) -> List[dict[str, str]]:
        if not messages:
            raise ValueError("At least one chat message is required.")

        normalized: List[dict[str, str]] = []
        for message in messages:
            if isinstance(message, ChatMessage):
                normalized.append(message.as_dict())
                continue

            role = str(message.get("role")).strip()  # type: ignore[arg-type]
            content = str(message.get("content")).strip()  # type: ignore[arg-type]
            if not role or not content:
                raise ValueError("Each message must include non-empty 'role' and 'content'.")
            normalized.append({"role": role, "content": content})
        return normalized

    def _chat_openai(self, messages: Sequence[Mapping[str, str]], **options) -> LLMResponse:
        api_key = options.pop("api_key", None) or self._api_key
        if not api_key:
            raise LLMConfigurationError("OpenAI API key is not configured.")

        model = options.pop("model", None) or self.model
        payload: dict[str, object] = {"model": model, "messages": list(messages)}

        temperature = options.pop("temperature", 0.2)
        if temperature is not None:
            payload["temperature"] = temperature

        max_tokens = options.pop("max_tokens", 256)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if options:
            payload.update(options)

        endpoint = f"{self._api_base.rstrip('/')}/chat/completions"
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LLMRequestError("Unable to reach the OpenAI API.") from exc

        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            logger.warning("OpenAI chat error %s: %s", response.status_code, detail)
            raise LLMRequestError("OpenAI chat request failed.", response.status_code, detail)

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMRequestError("OpenAI response could not be decoded as JSON.") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMRequestError("OpenAI response did not contain any choices.", payload=data) from exc

        return LLMResponse(content=content.strip(), raw=data)


def get_llm_client(**kwargs) -> LLMClient:
    """Convenience helper for callers that prefer a factory."""
    return LLMClient(**kwargs)
