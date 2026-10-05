"""Mutable engine-state defaults with explicit identity semantics."""

from __future__ import annotations

import numpy as np
import sympy as sp


def default_memory() -> dict[str, sp.Expr]:
    return {name: sp.Integer(0) for name in "ABCDEFMxy"}


def reset_memory_values(memory: dict[str, sp.Expr]) -> None:
    for name in memory:
        memory[name] = sp.Integer(0)


def default_matrices() -> dict[str, np.ndarray | None]:
    """Named matrix slots, unset until ``define_matrix`` populates one."""
    return {f"Mat{name}": None for name in "ABCD"}


def default_vectors() -> dict[str, np.ndarray | None]:
    """Named vector slots, unset until ``define_vector`` populates one."""
    return {f"Vct{name}": None for name in "ABCD"}
