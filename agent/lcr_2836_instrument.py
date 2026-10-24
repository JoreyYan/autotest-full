from __future__ import annotations

import time

from .base_instrument import BaseInstrument
from .serial_conn import SerialConn


class LCR2836Instrument(BaseInstrument):
    IDN_SIGNATURE = "YouCe,UC2836A+"

    def __init__(self, port: str, baudrate: int = 115200):
        self._conn = SerialConn(port, baudrate)

    def connect(self) -> bool:
        return self._conn.connect()

    def disconnect(self):
        self._conn.disconnect()

    @property
    def connected(self) -> bool:
        return self._conn.connected

    def idn(self) -> str:
        return self.query("*IDN?")

    def load_config(self, config_id: int) -> bytes:
        # UC2836A+ does not use the UC286x file-based fixture config flow.
        # Keep this method for interface compatibility.
        return b"OK"

    def send(self, cmd: str):
        self._conn.send(cmd)

    def query(self, cmd: str, timeout: float = 2.0) -> str:
        self._conn.clear()
        self._conn.send(cmd)
        resp = self._conn.recv(timeout=timeout)
        return resp.decode("ascii", errors="replace").strip()

    def set_trigger_source(self, source: str = "BUS"):
        self.send(f"TRIG:SOUR {source}")

    def trigger(self):
        self.send("TRIG")

    def fetch(self) -> str:
        return self.query("FETC?")

    def configure_measurement(
        self,
        function_code: str | None = None,
        frequency_hz: float | None = None,
        voltage_v: float | None = None,
        aperture_mode: str | None = None,
        average_count: int | None = None,
    ):
        if function_code:
            self.send(f"FUNC:IMP {function_code}")
        if frequency_hz is not None:
            self.send(f"FREQ {frequency_hz}")
        if voltage_v is not None:
            self.send(f"VOLT {voltage_v}")
        if aperture_mode:
            mode = aperture_mode.upper()
            if mode == "MED" and average_count is not None:
                self.send(f"APER MED,{int(average_count)}")
            else:
                self.send(f"APER {mode}")
        self.set_trigger_source("BUS")

    @staticmethod
    def parse_fetch_result(raw: str) -> dict:
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) < 3:
            raise ValueError(f"unexpected fetch payload: {raw}")
        return {
            "primary": float(parts[0]),
            "secondary": float(parts[1]),
            "status": int(float(parts[2])),
            "raw": raw,
        }

    def run_test(self) -> tuple[bool, str]:
        self.set_trigger_source("BUS")
        self.trigger()
        time.sleep(0.05)
        raw = self.fetch()
        return bool(raw), raw
