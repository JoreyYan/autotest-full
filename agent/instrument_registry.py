from __future__ import annotations

from .base_instrument import BaseInstrument
from .lcr_2836_instrument import LCR2836Instrument
from .uc2910_instrument import UC2910Instrument
from .uce_instrument import UCEInstrument


INSTRUMENT_DRIVERS: dict[str, type[BaseInstrument]] = {
    "uce": UCEInstrument,
    "lcr_2836": LCR2836Instrument,
    "uc2910": UC2910Instrument,
}

# Fixture runner consumes the UC286x CSV-style payload;
# uc2910 driver converts its binary packet to the same format.
FIXTURE_TEST_DRIVERS = {"uce", "uc2910"}


def get_instrument_driver(driver_name: str) -> type[BaseInstrument] | None:
    return INSTRUMENT_DRIVERS.get(driver_name)
