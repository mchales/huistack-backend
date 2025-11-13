from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Mapping, Sequence, Union, Optional

from django.conf import settings
from openai import OpenAI  # <- new SDK import

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


def _safe_model_dump(obj: Any) -> Mapping[str, object]:
    """
    Best-effort conversion of an OpenAI SDK object into a plain mapping
    for storage in LLMResponse.raw.
    """
    try:
        # OpenAI SDK responses are Pydantic models with model_dump()
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump()  # type: ignore[call-arg]
            if isinstance(dumped, Mapping):
                return dumped  # type: ignore[return-value]
    except Exception:  # pragma: no cover - defensive
        pass

    if isinstance(obj, Mapping):
        return obj  # type: ignore[return-value]

    # Fallback: wrap in a dict so we still satisfy the Mapping type
    return {"response": obj}  # type: ignore[return-value]


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
        # For OpenAI's Python SDK this becomes base_url
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
        """
        OpenAI implementation using the official Python SDK.

        - If `text_format` is provided, uses `client.responses.parse` for structured outputs.
        - Otherwise, uses `client.chat.completions.create` for normal chat responses.
        """
        api_key: Optional[str] = options.pop("api_key", None) or self._api_key
        if not api_key:
            raise LLMConfigurationError("OpenAI API key is not configured.")

        model = options.pop("model", None) or self.model

        # Common options
        temperature = options.pop("temperature", 0.1)
        max_tokens = options.pop("max_tokens", 1024)

        response_format = options.pop("response_format", None)
        text_format = options.pop("text_format", None)
        if text_format is not None and response_format is not None:
            raise LLMConfigurationError("Provide either 'text_format' or 'response_format', not both.")

        # Instantiate SDK client with configured base URL and timeout
        client = OpenAI(
            api_key=api_key,
            base_url=self._api_base,
            timeout=self.timeout,
        )

        # ---- Structured output path (responses.parse) ----
        if text_format is not None:
            try:
                kwargs: dict[str, Any] = {}
                if temperature is not None:
                    kwargs["temperature"] = temperature
                if max_tokens is not None:
                    # responses.* uses max_output_tokens instead of max_tokens
                    kwargs["max_output_tokens"] = max_tokens

                # Any other extra options go straight through
                if options:
                    kwargs.update(options)

                resp = client.responses.parse(
                    model=model,
                    input=list(messages),
                    text_format=text_format,
                    **kwargs,
                )
            except Exception as exc:
                logger.warning("OpenAI structured chat error: %s", exc, exc_info=True)
                raise LLMRequestError("OpenAI structured chat request failed.", payload=str(exc)) from exc

            # Prefer output_text if available; fall back gracefully
            content: str
            try:
                content = getattr(resp, "output_text")
                if not isinstance(content, str):
                    content = str(content)
            except Exception:
                # Fallback: try to dig into the underlying response
                try:
                    # This is defensive; shape may change with SDK versions
                    first_output = resp.output[0]  # type: ignore[index]
                    first_content_item = first_output.content[0]  # type: ignore[index]
                    content = getattr(first_content_item, "text", "")
                    if not isinstance(content, str):
                        content = str(content)
                except Exception:
                    content = ""

            raw = _safe_model_dump(resp)
            return LLMResponse(content=content.strip(), raw=raw)

        # ---- Plain chat path (chat.completions.create) ----
        try:
            kwargs = {}
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if response_format is not None:
                kwargs["response_format"] = response_format
            if options:
                kwargs.update(options)

            resp = client.chat.completions.create(
                model=model,
                messages=list(messages),
                **kwargs,
            )
        except Exception as exc:
            logger.warning("OpenAI chat error: %s", exc, exc_info=True)
            raise LLMRequestError("OpenAI chat request failed.", payload=str(exc)) from exc

        # Extract content from the first choice
        try:
            content = resp.choices[0].message.content or ""
        except Exception as exc:
            raise LLMRequestError("OpenAI response did not contain any choices.", payload=_safe_model_dump(resp)) from exc

        raw = _safe_model_dump(resp)
        return LLMResponse(content=content.strip(), raw=raw)


def get_llm_client(**kwargs) -> LLMClient:
    """Convenience helper for callers that prefer a factory."""
    return LLMClient(**kwargs)
