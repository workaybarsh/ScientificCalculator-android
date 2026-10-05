"""Calculator settings owned by the engine domain, not the UI."""

from __future__ import annotations

from dataclasses import dataclass

LEGACY_CONSTANTS_DATASET_LABEL = "Legacy CODATA 2010 (compatibility)"


@dataclass
class CalculatorSettings:
    angle_unit: str = "RAD"
    input_output: str = "MathI/MathO"
    number_format: str = "Fix"
    number_digits: int = 3
    engineer_symbol: bool = False
    complex_format: str = "a+bi"
    statistics_freq: bool = False
    spreadsheet_auto_calc: bool = True
    spreadsheet_show_cell: str = "Formula"
    equation_complex: bool = True
    table_two_functions: bool = False
    decimal_mark: str = "Dot"
    digit_separator: bool = False
    multiline_font: str = "Normal"
    constant_dataset: str = LEGACY_CONSTANTS_DATASET_LABEL
