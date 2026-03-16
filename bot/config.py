from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppSection:
    name: str = "HeadlessBot"
    env: str = "production"


@dataclass(slots=True)
class LoggingSection:
    level: str = "INFO"
    file: str = "logs/bot.log"


@dataclass(slots=True)
class ClientSection:
    endpoint: str = ""
    api_key: str = ""
    api_secret: str = ""
    ssid: str = ""
    demo: bool = True
    browser: str = "edge"
    browser_headless: bool = False
    ssid_timeout: int = 240


@dataclass(slots=True)
class SignalsSection:
    source: str = "demo"
    file_path: str = ""


@dataclass(slots=True)
class EngineSection:
    enabled: bool = True
    poll_interval: float = 1.0
    stake: float = 1.0
    martingale: float = 2.0
    max_steps: int = 3
    timeframe_sec: int = 300
    candles_limit: int = 150
    pairs: list[str] | None = None


@dataclass(slots=True)
class Settings:
    app: AppSection
    logging: LoggingSection
    client: ClientSection
    signals: SignalsSection
    engine: EngineSection


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImportError("PyYAML is required for YAML configs. Install: pip install pyyaml") from exc

    with path.open("r", encoding="utf-8") as file_obj:
        return yaml.safe_load(file_obj) or {}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def load_settings(path: str) -> Settings:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    suffix = config_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        raw = _load_yaml(config_path)
    elif suffix == ".json":
        raw = _load_json(config_path)
    else:
        raise ValueError("Config must be .yaml/.yml or .json")

    return validate_settings(raw)


def validate_settings(raw: dict[str, Any]) -> Settings:
    app_raw = raw.get("app", {})
    logging_raw = raw.get("logging", {})
    client_raw = raw.get("client", {})
    signals_raw = raw.get("signals", {})
    engine_raw = raw.get("engine", {})

    pairs = engine_raw.get("pairs") or ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("engine.pairs must be a non-empty list")

    settings = Settings(
        app=AppSection(
            name=str(app_raw.get("name", "HeadlessBot")).strip() or "HeadlessBot",
            env=str(app_raw.get("env", "production")).strip() or "production",
        ),
        logging=LoggingSection(
            level=str(logging_raw.get("level", "INFO")).upper().strip() or "INFO",
            file=str(logging_raw.get("file", "logs/bot.log")).strip() or "logs/bot.log",
        ),
        client=ClientSection(
            endpoint=str(client_raw.get("endpoint", "")).strip(),
            api_key=str(client_raw.get("api_key", "")).strip(),
            api_secret=str(client_raw.get("api_secret", "")).strip(),
            ssid=str(client_raw.get("ssid", "")).strip(),
            demo=bool(client_raw.get("demo", True)),
            browser=str(client_raw.get("browser", "edge")).strip().lower() or "edge",
            browser_headless=bool(client_raw.get("browser_headless", False)),
            ssid_timeout=int(client_raw.get("ssid_timeout", 240)),
        ),
        signals=SignalsSection(
            source=str(signals_raw.get("source", "demo")).strip().lower() or "demo",
            file_path=str(signals_raw.get("file_path", "")).strip(),
        ),
        engine=EngineSection(
            enabled=bool(engine_raw.get("enabled", True)),
            poll_interval=float(engine_raw.get("poll_interval", 1.0)),
            stake=float(engine_raw.get("stake", 1.0)),
            martingale=float(engine_raw.get("martingale", 2.0)),
            max_steps=int(engine_raw.get("max_steps", 3)),
            timeframe_sec=int(engine_raw.get("timeframe_sec", 300)),
            candles_limit=int(engine_raw.get("candles_limit", 150)),
            pairs=[str(item).upper().strip() for item in pairs if str(item).strip()],
        ),
    )

    if settings.client.browser not in {"edge", "chrome"}:
        raise ValueError("client.browser must be edge or chrome")
    if settings.client.ssid_timeout <= 0:
        raise ValueError("client.ssid_timeout must be > 0")

    if settings.engine.poll_interval <= 0:
        raise ValueError("engine.poll_interval must be > 0")
    if settings.engine.stake <= 0:
        raise ValueError("engine.stake must be > 0")
    if settings.engine.martingale <= 0:
        raise ValueError("engine.martingale must be > 0")
    if settings.engine.max_steps < 0:
        raise ValueError("engine.max_steps must be >= 0")

    return settings
