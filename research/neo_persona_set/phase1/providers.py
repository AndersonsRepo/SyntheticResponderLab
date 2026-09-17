"""Text-generation backends for the persona pipeline.

Two providers, same interface, chosen with --provider:

  anthropic   calls the Claude API directly. Needs ANTHROPIC_API_KEY.
  openrouter  reuses the app's existing client. Needs OPENROUTER_API_KEY.

Both keys are read from apps/api/.env, which is where the app already keeps them. The default is
whichever key is actually present, preferring Anthropic, so the pipeline runs on whatever is
configured rather than failing on a hardcoded choice.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
API_ENV_PATH = REPO_ROOT / "apps/api/.env"
LLM_CLIENT_PATH = REPO_ROOT / "apps/api/legacy_runtime/backend/simulation/llm_client.py"

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENROUTER_MODEL = "google/gemini-2.5-flash"

_KEYS = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL")


def load_env() -> None:
    """Pull the API keys out of apps/api/.env without overwriting anything already exported."""
    if not API_ENV_PATH.exists():
        return
    for line in API_ENV_PATH.read_text().splitlines():
        for key in _KEYS:
            if line.startswith(f"{key}="):
                _, _, value = line.partition("=")
                value = value.strip()
                if value and not os.getenv(key):
                    os.environ[key] = value


def available() -> dict[str, bool]:
    load_env()
    return {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
    }


def resolve(requested: str | None) -> str:
    """Pick a provider, preferring Anthropic when both are configured."""
    have = available()
    if requested and requested != "auto":
        if not have.get(requested):
            key = "ANTHROPIC_API_KEY" if requested == "anthropic" else "OPENROUTER_API_KEY"
            raise SystemExit(f"--provider {requested} needs {key}, which is not set in {API_ENV_PATH}")
        return requested
    if have["anthropic"]:
        return "anthropic"
    if have["openrouter"]:
        return "openrouter"
    raise SystemExit(
        f"No API key configured. Set ANTHROPIC_API_KEY (preferred) or OPENROUTER_API_KEY "
        f"in {API_ENV_PATH}"
    )


def default_model(provider: str) -> str:
    return DEFAULT_ANTHROPIC_MODEL if provider == "anthropic" else DEFAULT_OPENROUTER_MODEL


class Generator:
    """Uniform text generation across both providers.

    Each call is independent; the client is created once and shared, which is safe because both
    SDKs are thread-safe and the pipeline fans out across a thread pool.
    """

    def __init__(self, provider: str, model: str | None = None):
        load_env()
        self.provider = provider
        self.model = model or default_model(provider)

        if provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        else:
            spec = importlib.util.spec_from_file_location("app_llm_client", LLM_CLIENT_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._client = module

    def generate(self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
        if self.provider == "anthropic":
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return "".join(block.text for block in response.content if block.type == "text")

        return self._client.generate_text_with_openrouter(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_name=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
