import logging
import sys
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


# Global compatibility for Python 3.12+ and third-party loggers expecting .warn.
logging.Logger.warn = logging.Logger.warning  # type: ignore[attr-defined]
if hasattr(logging, "LoggerAdapter") and hasattr(logging.LoggerAdapter, "warning") and not hasattr(logging.LoggerAdapter, "warn"):
    logging.LoggerAdapter.warn = logging.LoggerAdapter.warning  # type: ignore[attr-defined]


def patch_loaded_logger_classes_warn_alias() -> None:
    for module in list(sys.modules.values()):
        if module is None:
            continue
        for class_name in ("Logger", "LoggerAdapter"):
            logger_cls = getattr(module, class_name, None)
            if isinstance(logger_cls, type) and hasattr(logger_cls, "warning") and not hasattr(logger_cls, "warn"):
                try:
                    setattr(logger_cls, "warn", logger_cls.warning)
                except Exception:
                    pass


def patch_third_party_warn_compat() -> None:
    patch_loaded_logger_classes_warn_alias()
    try:
        from loguru import logger as loguru_logger  # type: ignore

        if hasattr(loguru_logger, "warning") and not hasattr(loguru_logger, "warn"):
            setattr(loguru_logger, "warn", loguru_logger.warning)
    except Exception:
        pass


def patch_logger_warn_compat(target: Any) -> None:
    if target is None:
        return

    if hasattr(target, "warning") and not hasattr(target, "warn"):
        try:
            setattr(target, "warn", target.warning)
        except Exception:
            pass

    inner = getattr(target, "logger", None)
    if inner is not None and hasattr(inner, "warning") and not hasattr(inner, "warn"):
        try:
            setattr(inner, "warn", inner.warning)
        except Exception:
            pass


def debug_logger_shape(log_obj: Any) -> str:
    return (
        "[DEBUG logger]\n"
        f"type = {type(log_obj).__name__}\n"
        f"has warn = {hasattr(log_obj, 'warn')}\n"
        f"has warning = {hasattr(log_obj, 'warning')}"
    )
