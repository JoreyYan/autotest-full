from __future__ import annotations

from abc import ABC, abstractmethod


class BaseInstrument(ABC):
    IDN_SIGNATURE = ""

    @abstractmethod
    def connect(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def connected(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def idn(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def load_config(self, config_id: int) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def run_test(self) -> tuple[bool, str]:
        raise NotImplementedError
