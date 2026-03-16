import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PocketOptionSettings:
    ssid: str
    demo: bool = True


@dataclass
class TradingSettings:
    stake: float = 1.0
    martingale: float = 2.0
    max_steps: int = 3
    pairs: list[str] | None = None
    timeframe_sec: int = 300
    candles_limit: int = 150
    check_interval_sec: int = 20
    api_retry_delay_sec: int = 10


@dataclass
class SignalSettings:
    source: str = "internal"
    channel_id: str = ""
    file_path: str = ""


@dataclass
class LoggingSettings:
    level: str = "INFO"
    file: str = "bot.log"


@dataclass
class AppConfig:
    pocketoption: PocketOptionSettings
    trading: TradingSettings
    signals: SignalSettings
    logging: LoggingSettings


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ImportError("PyYAML is required for .yaml config files. Install: pip install pyyaml") from exc

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_config(path: str) -> AppConfig:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    if cfg_path.suffix.lower() in {".yaml", ".yml"}:
        data = _load_yaml(cfg_path)
    elif cfg_path.suffix.lower() == ".json":
        data = _load_json(cfg_path)
    else:
        raise ValueError("Config must be .yaml/.yml or .json")

    return validate_config(data)


def validate_config(data: dict[str, Any]) -> AppConfig:
    po = data.get("pocketoption", {})
    tr = data.get("trading", {})
    sg = data.get("signals", {})
    lg = data.get("logging", {})

    ssid = str(po.get("ssid", "")).strip()
    if not ssid:
        raise ValueError("pocketoption.ssid is required")

    pairs = tr.get("pairs") or ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("trading.pairs must be a non-empty list")

    trading = TradingSettings(
        stake=float(tr.get("stake", 1)),
        martingale=float(tr.get("martingale", 2)),
        max_steps=int(tr.get("max_steps", 3)),
        pairs=[str(p).upper().strip() for p in pairs if str(p).strip()],
        timeframe_sec=int(tr.get("timeframe_sec", 300)),
        candles_limit=int(tr.get("candles_limit", 150)),
        check_interval_sec=int(tr.get("check_interval_sec", 20)),
        api_retry_delay_sec=int(tr.get("api_retry_delay_sec", 10)),
    )

    if trading.stake <= 0:
        raise ValueError("trading.stake must be > 0")

    return AppConfig(
        pocketoption=PocketOptionSettings(ssid=ssid, demo=bool(po.get("demo", True))),
        trading=trading,
        signals=SignalSettings(
            source=str(sg.get("source", "internal")).strip().lower(),
            channel_id=str(sg.get("channel_id", "")).strip(),
            file_path=str(sg.get("file_path", "")).strip(),
        ),
        logging=LoggingSettings(
            level=str(lg.get("level", "INFO")).upper(),
            file=str(lg.get("file", "bot.log")).strip(),
        ),
    )
