"""Internal, pure calculator-engine domain services.

The public compatibility facade remains :mod:`scientific_calculator.calculator_engine`.
Keeping these modules free of Tk and persistence dependencies makes their numerical
contracts independently testable.
"""

from .outcomes import NO_ANS_UPDATE, EngineOutcome

__all__ = ["EngineOutcome", "NO_ANS_UPDATE"]
