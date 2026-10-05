"""The Tk-free composition of stateful calculator services."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_session import CalculationSession
from .calculator_engine import ScientificCalculatorEngine
from .spreadsheet import SpreadsheetModel


@dataclass(slots=True)
class ApplicationServices:
    """Runtime domain services owned by one application instance."""

    engine: ScientificCalculatorEngine
    calculation_session: CalculationSession
    spreadsheet: SpreadsheetModel

    @classmethod
    def build(
        cls,
        engine_factory=ScientificCalculatorEngine,
        session_factory=CalculationSession,
        spreadsheet_factory=SpreadsheetModel,
    ) -> ApplicationServices:
        """Build services, with injectable factories for headless callers."""

        engine = engine_factory()
        return cls(engine, session_factory(engine), spreadsheet_factory(engine))
