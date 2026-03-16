from dataclasses import dataclass
from pathlib import Path


@dataclass
class TradeSignal:
    symbol: str
    direction: str  # CALL/PUT
    source: str = "internal"


def parse_signal_text(text: str) -> TradeSignal | None:
    parts = text.strip().upper().replace("/", "").split()
    if len(parts) < 2:
        return None
    symbol, direction = parts[0], parts[1]
    if direction in {"BUY", "CALL", "UP"}:
        return TradeSignal(symbol=symbol, direction="CALL", source="external")
    if direction in {"SELL", "PUT", "DOWN"}:
        return TradeSignal(symbol=symbol, direction="PUT", source="external")
    return None


class FileSignalSource:
    """Reads one signal per line from a file append log."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.offset = 0

    def poll(self) -> list[TradeSignal]:
        if not self.path.exists():
            return []

        signals: list[TradeSignal] = []
        with self.path.open("r", encoding="utf-8") as fh:
            fh.seek(self.offset)
            for line in fh:
                parsed = parse_signal_text(line)
                if parsed:
                    signals.append(parsed)
            self.offset = fh.tell()
        return signals
