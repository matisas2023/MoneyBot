from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Signal:
    symbol: str
    direction: str  # CALL | PUT
    source: str


class SignalSource(ABC):
    @abstractmethod
    def poll(self) -> list[Signal]:
        raise NotImplementedError


class DemoSignalSource(SignalSource):
    def __init__(self, pairs: list[str]):
        self.pairs = pairs

    def poll(self) -> list[Signal]:
        symbol = random.choice(self.pairs)
        direction = random.choice(["CALL", "PUT"])
        return [Signal(symbol=symbol, direction=direction, source="demo")]


class FileSignalSource(SignalSource):
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.offset = 0

    def poll(self) -> list[Signal]:
        if not self.file_path.exists():
            return []

        signals: list[Signal] = []
        with self.file_path.open("r", encoding="utf-8") as file_obj:
            file_obj.seek(self.offset)
            for line in file_obj:
                parsed = parse_signal_line(line)
                if parsed:
                    signals.append(parsed)
            self.offset = file_obj.tell()
        return signals


def parse_signal_line(line: str) -> Signal | None:
    parts = line.strip().upper().replace("/", "").split()
    if len(parts) < 2:
        return None

    symbol, raw_direction = parts[0], parts[1]
    if raw_direction in {"BUY", "CALL", "UP"}:
        return Signal(symbol=symbol, direction="CALL", source="file")
    if raw_direction in {"SELL", "PUT", "DOWN"}:
        return Signal(symbol=symbol, direction="PUT", source="file")
    return None
