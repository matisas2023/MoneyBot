import argparse
import signal
from threading import Event

from .config import load_config
from .logger import setup_logger


shutdown_event = Event()


def _install_signal_handlers(logger, runner):
    def handle_shutdown(_signum, _frame):
        if shutdown_event.is_set():
            return
        shutdown_event.set()
        logger.info("Stopping bot...")
        runner.stop()
        logger.info("Shutdown complete.")

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PocketOption CLI bot")
    parser.add_argument("--config", required=True, help="Path to .yaml/.yml/.json config")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    config = load_config(args.config)
    logger = setup_logger(config.logging.level, config.logging.file)

    from .runner import BotRunner

    runner = BotRunner(config=config, logger=logger)
    _install_signal_handlers(logger, runner)

    try:
        runner.run()
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
        runner.stop()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
