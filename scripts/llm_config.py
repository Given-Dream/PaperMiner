# -*- coding: utf-8 -*-
"""LLM 接口配置、模型发现与连接测速。

该文件依据事故前 README、GUI 导入接口、环境变量清单和任务记录重建。
它兼容 DeepSeek 以及提供 ``/models``、``/chat/completions`` 的 OpenAI
兼容接口，并在保存设置时保留 ``.env`` 中不属于 PaperMiner 的其它行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any, Iterable
from urllib.parse import urlparse


DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"

SETTING_KEYS = (
    "DEEPSEEK_API_KEY",
    "LLM_PROVIDER",
    "DEEPSEEK_MODEL",
    "CUSTOM_API_BASE_URL",
    "CUSTOM_API_KEY",
    "CUSTOM_API_MODELS_JSON",
    "CUSTOM_API_MODEL",
)


@dataclass
class LLMSettings:
    provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    custom_api_base_url: str = ""
    custom_api_key: str = ""
    custom_api_models: list[str] = field(default_factory=list)
    custom_api_model: str = ""

    def __post_init__(self) -> None:
        self.provider = (self.provider or "deepseek").strip().lower()
        if self.provider not in {"deepseek", "custom"}:
            self.provider = "deepseek"
        self.deepseek_model = self.deepseek_model.strip() or DEFAULT_DEEPSEEK_MODEL
        self.custom_api_base_url = self.custom_api_base_url.strip()
        self.custom_api_models = _clean_model_ids(self.custom_api_models)
        self.custom_api_model = self.custom_api_model.strip()
        if self.custom_api_model and self.custom_api_model not in self.custom_api_models:
            self.custom_api_models.append(self.custom_api_model)

    @property
    def active_model(self) -> str:
        if self.provider == "custom":
            return self.custom_api_model or (
                self.custom_api_models[0] if self.custom_api_models else ""
            )
        return self.deepseek_model or DEFAULT_DEEPSEEK_MODEL

    @property
    def enabled_models(self) -> list[str]:
        if self.provider == "custom":
            return list(self.custom_api_models)
        return [self.deepseek_model or DEFAULT_DEEPSEEK_MODEL]


def _clean_model_ids(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        model = str(value).strip()
        if model and model not in seen:
            seen.add(model)
            result.append(model)
    return result


def _default_env_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".env"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        if key:
            values[key] = value.strip()
    return values


def _models_from_json(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return _clean_model_ids(parsed if isinstance(parsed, list) else [])


def load_llm_settings(env_path: Path | str | None = None) -> LLMSettings:
    path = Path(env_path) if env_path is not None else _default_env_path()
    values = _read_env(path)
    return LLMSettings(
        provider=values.get("LLM_PROVIDER", "deepseek"),
        deepseek_api_key=values.get("DEEPSEEK_API_KEY", ""),
        deepseek_model=values.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        custom_api_base_url=values.get("CUSTOM_API_BASE_URL", ""),
        custom_api_key=values.get("CUSTOM_API_KEY", ""),
        custom_api_models=_models_from_json(values.get("CUSTOM_API_MODELS_JSON", "")),
        custom_api_model=values.get("CUSTOM_API_MODEL", ""),
    )


def _serialize_settings(settings: LLMSettings) -> dict[str, str]:
    return {
        "DEEPSEEK_API_KEY": settings.deepseek_api_key.strip(),
        "LLM_PROVIDER": settings.provider,
        "DEEPSEEK_MODEL": settings.deepseek_model.strip() or DEFAULT_DEEPSEEK_MODEL,
        "CUSTOM_API_BASE_URL": settings.custom_api_base_url.strip(),
        "CUSTOM_API_KEY": settings.custom_api_key.strip(),
        "CUSTOM_API_MODELS_JSON": json.dumps(
            _clean_model_ids(settings.custom_api_models), ensure_ascii=False, separators=(",", ":")
        ),
        "CUSTOM_API_MODEL": settings.custom_api_model.strip(),
    }


def save_llm_settings(
    settings: LLMSettings, env_path: Path | str | None = None
) -> Path:
    path = Path(env_path) if env_path is not None else _default_env_path()
    replacements = _serialize_settings(settings)
    original_lines = (
        path.read_text(encoding="utf-8", errors="replace").splitlines()
        if path.exists()
        else []
    )
    output: list[str] = []
    written: set[str] = set()
    for line in original_lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key in replacements and not stripped.startswith("#"):
            if key not in written:
                output.append(f"{key}={replacements[key]}")
                written.add(key)
            continue
        output.append(line)
    if output and output[-1] != "":
        output.append("")
    for key in SETTING_KEYS:
        if key not in written:
            output.append(f"{key}={replacements[key]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8", newline="\n")
    return path


def normalize_api_base_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API 根地址必须是有效的 http:// 或 https:// URL")
    return url


def endpoint_url(api_base_url: str, endpoint: str) -> str:
    base = normalize_api_base_url(api_base_url)
    return f"{base}/{endpoint.strip('/')}"


def build_auth_headers(api_key: str = "") -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def discover_models(
    api_base_url: str, api_key: str = "", timeout: float = 15.0
) -> list[str]:
    import requests

    response = requests.get(
        endpoint_url(api_base_url, "models"),
        headers=build_auth_headers(api_key),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else []
    model_ids: list[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            model_ids.append(item)
        elif isinstance(item, dict):
            candidate = item.get("id") or item.get("name") or item.get("model")
            if candidate:
                model_ids.append(str(candidate))
    return sorted(_clean_model_ids(model_ids), key=str.casefold)


def test_model_speed(
    api_base_url: str,
    api_key: str,
    model: str,
    timeout: float = 45.0,
) -> dict[str, Any]:
    import requests

    started = time.perf_counter()
    try:
        response = requests.post(
            endpoint_url(api_base_url, "chat/completions"),
            headers=build_auth_headers(api_key),
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 16,
                "temperature": 0,
                "stream": False,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        elapsed = time.perf_counter() - started
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        completion_tokens = int(usage.get("completion_tokens") or 0)
        choices = payload.get("choices", []) if isinstance(payload, dict) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            content = str((choices[0].get("message") or {}).get("content") or "")
        approximate_tokens = completion_tokens or max(1, len(content) // 4)
        return {
            "ok": True,
            "model": model,
            "elapsed_seconds": elapsed,
            "completion_tokens": completion_tokens,
            "tokens_per_second": approximate_tokens / elapsed if elapsed > 0 else 0.0,
            "content_preview": content[:80],
        }
    except Exception as exc:
        return {
            "ok": False,
            "model": model,
            "elapsed_seconds": time.perf_counter() - started,
            "error": str(exc),
        }


def format_speed_result(result: dict[str, Any]) -> str:
    model = str(result.get("model") or "未知模型")
    elapsed = float(result.get("elapsed_seconds") or 0.0)
    if not result.get("ok"):
        return f"{model}: 失败（{elapsed:.2f}s）— {result.get('error', '未知错误')}"
    speed = float(result.get("tokens_per_second") or 0.0)
    return f"{model}: {elapsed:.2f}s，约 {speed:.1f} token/s"
