from __future__ import annotations

import argparse
import logging
import signal
from types import FrameType

from .config import load_settings
from .logger import setup_logger


def _apply_logger_warn_compat() -> None:
    if hasattr(logging.Logger, "warning") and not hasattr(logging.Logger, "warn"):
        logging.Logger.warn = logging.Logger.warning  # type: ignore[attr-defined]
    if (
        hasattr(logging, "LoggerAdapter")
        and hasattr(logging.LoggerAdapter, "warning")
        and not hasattr(logging.LoggerAdapter, "warn")
    ):
        logging.LoggerAdapter.warn = logging.LoggerAdapter.warning  # type: ignore[attr-defined]


class _SignalController:
    def __init__(self, runner, logger):
        self.runner = runner
        self.logger = logger
        self.triggered = False

    def handle(self, _signum: int, _frame: FrameType | None) -> None:
        if self.triggered:
            return
        self.triggered = True
        self.logger.info("Stopping bot...")
        self.runner.stop()
        self.logger.info("Shutdown complete.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Headless PocketOption bot")
    parser.add_argument("--config", required=True, help="Path to YAML/JSON config")
    return parser


def main() -> None:
    _apply_logger_warn_compat()
    args = _build_parser().parse_args()
    settings = load_settings(args.config)
    logger = setup_logger(settings.logging.level, settings.logging.file)

    if not settings.client.ssid:
        from .ssid_fetcher import get_ssid

        ssid = get_ssid(
            timeout=settings.client.ssid_timeout,
            browser=settings.client.browser,
            headless=settings.client.browser_headless,
            log=logger.info,
        )
        settings.client.ssid = ssid

    logger.info("[INFO] Starting bot...")

    from .runner import BotRunner

    runner = BotRunner(settings=settings, logger=logger)
    signal_controller = _SignalController(runner, logger)
    signal.signal(signal.SIGINT, signal_controller.handle)
    signal.signal(signal.SIGTERM, signal_controller.handle)

    try:
        runner.start()
    except KeyboardInterrupt:
        signal_controller.handle(signal.SIGINT, None)


if __name__ == "__main__":
    main()
