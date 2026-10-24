from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

from .base_instrument import BaseInstrument
from .instrument_registry import get_instrument_driver


def _normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = unit.strip()
    if not u:
        return None
    return (
        u.replace("μ", "u")
        .replace("µ", "u")
        .replace("Ω", "Ohm")
        .replace("ω", "Ohm")
    )


def _convert_si_to_display(value: float, unit: str | None) -> float:
    u = _normalize_unit(unit)
    if not u:
        return value
    scale = {
        "H": 1.0,
        "mH": 1e3,
        "uH": 1e6,
        "nH": 1e9,
        "F": 1.0,
        "mF": 1e3,
        "uF": 1e6,
        "nF": 1e9,
        "pF": 1e12,
        "Ohm": 1.0,
        "mOhm": 1e3,
        "kOhm": 1e-3,
    }
    return value * scale.get(u, 1.0)


def _judge(value: float | None, lower: float | None, upper: float | None) -> str:
    if value is None:
        return "Fail"
    if lower is not None and value < lower:
        return "Fail"
    if upper is not None and value > upper:
        return "Fail"
    return "Pass"


@dataclass
class InspectionSessionRecord:
    timestamp: str
    product_code: str
    items: list[dict]
    overall: str


class InspectionRunner:
    def __init__(self, product_json_path: str, logger=None):
        with open(product_json_path, encoding="utf-8") as f:
            self.product = json.load(f)
        self.product.setdefault("workflow_type", "incoming_inspection")
        self.product.setdefault("instrument_driver", "lcr_2836")
        self._log = logger or (lambda *args, **kwargs: None)
        self._instr: BaseInstrument | None = None
        self._ready = False
        self._step_index = 0
        self._items: list[dict] = []

    def _emit(self, message: str):
        self._log(message)

    @property
    def workflow_type(self) -> str:
        return str(self.product.get("workflow_type", "incoming_inspection"))

    @property
    def steps(self) -> list[dict]:
        return list(self.product.get("inspection_steps", []))

    def _resolve_driver(self) -> tuple[str, type[BaseInstrument]]:
        driver_name = str(self.product.get("instrument_driver", "lcr_2836")).strip().lower() or "lcr_2836"
        driver_cls = get_instrument_driver(driver_name)
        if driver_cls is None:
            raise ValueError(f"unsupported instrument driver: {driver_name}")
        return driver_name, driver_cls

    def initialize(self, port: str = None, baudrate: int = 115200) -> dict:
        status = {
            "ok": False,
            "port": port,
            "idn": "",
            "message": "",
            "workflow_type": self.workflow_type,
            "current_step_index": 0,
            "total_steps": len(self.steps),
            "next_prompt": "",
        }
        if self.workflow_type != "incoming_inspection":
            status["message"] = f"workflow_type {self.workflow_type} is not supported by inspection runner"
            self._emit(status["message"])
            return status
        if not self.steps:
            status["message"] = "inspection_steps is empty"
            self._emit(status["message"])
            return status

        try:
            driver_name, driver_cls = self._resolve_driver()
        except ValueError as exc:
            status["message"] = str(exc)
            self._emit(status["message"])
            return status

        if port is None:
            status["message"] = f"inspection runner requires explicit port for driver={driver_name}"
            self._emit(status["message"])
            return status

        self._instr = driver_cls(port, baudrate)
        self._emit(f"connecting inspection instrument on {port} @ {baudrate} bps")
        if not self._instr.connect():
            status["message"] = f"failed to connect inspection instrument on {port}"
            self._emit(status["message"])
            return status

        idn = self._instr.idn()
        status["idn"] = idn
        self._emit(f"idn = {idn}")
        self._ready = True
        self._step_index = 0
        self._items = []
        status["ok"] = True
        status["next_prompt"] = self._step_prompt(self._step_index)
        status["message"] = "inspection initialized"
        return status

    def _step_prompt(self, index: int) -> str:
        if index >= len(self.steps):
            return ""
        step = self.steps[index]
        pins = str(step.get("pins", "")).strip()
        prompt = str(step.get("prompt", "")).strip()
        if prompt:
            return prompt
        return f"请测量 {pins} 脚位"

    def status(self) -> dict:
        return {
            "ready": self._ready and self._instr is not None,
            "product_code": self.product.get("product_code"),
            "workflow_type": self.workflow_type,
            "current_step_index": self._step_index,
            "total_steps": len(self.steps),
            "next_prompt": self._step_prompt(self._step_index),
            "completed_steps": self._step_index,
        }

    def run_current_step(self) -> dict:
        if not self._ready or not self._instr:
            raise RuntimeError("inspection runner is not ready")
        if self._step_index >= len(self.steps):
            raise RuntimeError("inspection already completed")

        step = self.steps[self._step_index]
        pins = str(step.get("pins", "")).strip()
        measurements = list(step.get("measurements", []))
        if not measurements:
            raise RuntimeError(f"step {self._step_index + 1} has no measurements")

        self._emit(self._step_prompt(self._step_index))
        step_items: list[dict] = []
        step_failed = False

        for measurement in measurements:
            name = str(measurement.get("name", "")).strip() or "未命名项目"
            function_code = str(measurement.get("function_code", "")).strip().upper() or None
            frequency_hz = measurement.get("frequency_hz")
            voltage_v = measurement.get("voltage_v")
            aperture_mode = measurement.get("aperture_mode")
            average_count = measurement.get("average_count")

            if hasattr(self._instr, "configure_measurement"):
                self._instr.configure_measurement(
                    function_code=function_code,
                    frequency_hz=frequency_hz,
                    voltage_v=voltage_v,
                    aperture_mode=aperture_mode,
                    average_count=average_count,
                )

            ok, raw = self._instr.run_test()
            if not ok:
                item = {
                    "pins": pins,
                    "name": name,
                    "function_code": function_code,
                    "result": "Fail",
                    "error": "empty_fetch",
                    "raw": raw,
                }
                step_items.append(item)
                self._items.append(item)
                step_failed = True
                continue

            if not hasattr(self._instr, "parse_fetch_result"):
                raise RuntimeError("selected inspection driver does not implement parse_fetch_result")
            parsed = self._instr.parse_fetch_result(raw)

            primary_unit = _normalize_unit(measurement.get("primary_unit"))
            secondary_unit = _normalize_unit(measurement.get("secondary_unit"))
            primary_display = _convert_si_to_display(parsed["primary"], primary_unit)
            secondary_display = _convert_si_to_display(parsed["secondary"], secondary_unit)

            primary_lower = measurement.get("primary_lower")
            primary_upper = measurement.get("primary_upper")
            secondary_lower = measurement.get("secondary_lower")
            secondary_upper = measurement.get("secondary_upper")

            primary_result = _judge(primary_display, primary_lower, primary_upper)
            secondary_required = any(v is not None for v in (secondary_lower, secondary_upper))
            secondary_result = _judge(secondary_display, secondary_lower, secondary_upper) if secondary_required else "Pass"
            result = "Pass" if parsed["status"] == 0 and primary_result == "Pass" and secondary_result == "Pass" else "Fail"
            if result == "Fail":
                step_failed = True

            item = {
                "pins": pins,
                "name": name,
                "function_code": function_code,
                "primary_label": measurement.get("primary_label") or "A",
                "primary_unit": primary_unit or "",
                "primary_value": parsed["primary"],
                "primary_value_display": primary_display,
                "primary_lower": primary_lower,
                "primary_upper": primary_upper,
                "primary_result": primary_result,
                "secondary_label": measurement.get("secondary_label") or "B",
                "secondary_unit": secondary_unit or "",
                "secondary_value": parsed["secondary"],
                "secondary_value_display": secondary_display,
                "secondary_lower": secondary_lower,
                "secondary_upper": secondary_upper,
                "secondary_result": secondary_result,
                "instrument_status": parsed["status"],
                "raw": raw,
                "result": result,
            }
            step_items.append(item)
            self._items.append(item)
            self._emit(f"{pins} / {name} -> {result}")

        self._step_index += 1
        finished = self._step_index >= len(self.steps)
        overall = "FAIL" if any(item.get("result") != "Pass" for item in self._items) else "PASS"

        return {
            "ok": True,
            "step_index": self._step_index - 1,
            "pins": pins,
            "step_result": "Fail" if step_failed else "Pass",
            "items": step_items,
            "finished": finished,
            "next_prompt": "" if finished else self._step_prompt(self._step_index),
            "overall": overall if finished else "",
        }

    def build_record(self) -> InspectionSessionRecord:
        overall = "FAIL" if any(item.get("result") != "Pass" for item in self._items) else "PASS"
        return InspectionSessionRecord(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            product_code=str(self.product.get("product_code", "")),
            items=list(self._items),
            overall=overall,
        )

    def close(self):
        if self._instr:
            self._instr.disconnect()
        self._instr = None
        self._ready = False
