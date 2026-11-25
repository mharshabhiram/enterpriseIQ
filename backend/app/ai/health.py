"""Startup / on-demand checks that Ollama is reachable and the configured models exist."""
import time
from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass
class OllamaStatus:
    reachable: bool
    missing_models: list[str]
    message: str


def check_ollama() -> OllamaStatus:
    settings = get_settings()
    wanted = [settings.ollama_llm_model, settings.ollama_embedding_model]
    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
        response.raise_for_status()
    except httpx.HTTPError:
        return OllamaStatus(False, wanted, f"Ollama is not reachable at {settings.ollama_base_url}.")
    installed = {m.get("name", "") for m in response.json().get("models", [])}
    installed |= {name.split(":")[0] for name in installed}
    missing = [m for m in wanted if m not in installed and f"{m}:latest" not in installed]
    if missing:
        commands = "; ".join(f"ollama pull {m}" for m in missing)
        return OllamaStatus(True, missing, f"Missing Ollama models. Run: {commands}")
    return OllamaStatus(True, [], "Ollama is ready.")


def wait_for_ollama(timeout_seconds: float = 60, interval: float = 2) -> OllamaStatus:
    """Poll until Ollama answers (the container may still be starting)."""
    deadline = time.monotonic() + timeout_seconds
    status = check_ollama()
    while not status.reachable and time.monotonic() < deadline:
        time.sleep(interval)
        status = check_ollama()
    return status
