"""Physical-constant catalogues offered by the calculator.

This is plain data with no SymPy dependency, so the application can read the
selectable dataset names without pulling in the calculation engine. Startup
would otherwise pay a 0.6 second import before its window appears.
"""

from __future__ import annotations

# The original calculator values remain selectable for reproducible older
# calculations.  A separate current dataset prevents a compatibility option
# from being presented as a current CODATA recommendation.
LEGACY_CONSTANTS_DATASET_LABEL = "Legacy CODATA 2010 (compatibility)"
CURRENT_CONSTANTS_DATASET_LABEL = "Current CODATA 2022"
CONSTANTS_DATASET_LABELS = (
    LEGACY_CONSTANTS_DATASET_LABEL,
    CURRENT_CONSTANTS_DATASET_LABEL,
)
# Kept as a public compatibility name for integrations that imported it.
CONSTANTS_DATASET_LABEL = LEGACY_CONSTANTS_DATASET_LABEL

LEGACY_CONSTANTS: dict[str, tuple[str, float]] = {
    "h": ("Planck constant", 6.62606957e-34),
    "hbar": ("Reduced Planck constant", 1.054571726e-34),
    "c0": ("Speed of light in vacuum", 299792458.0),
    "eps0": ("Vacuum electric permittivity", 8.854187817e-12),
    "mu0": ("Vacuum magnetic permeability", 1.2566370614e-6),
    "Z0": ("Characteristic impedance of vacuum", 376.730313461),
    "G": ("Newtonian gravitational constant", 6.67384e-11),
    "lP": ("Planck length", 1.616199e-35),
    "tP": ("Planck time", 5.39106e-44),
    "muN": ("Nuclear magneton", 5.05078353e-27),
    "muB": ("Bohr magneton", 9.27400968e-24),
    "qe": ("Elementary charge", 1.602176565e-19),
    "Phi0": ("Magnetic flux quantum", 2.067833758e-15),
    "G0": ("Conductance quantum", 7.7480917346e-5),
    "KJ": ("Josephson constant", 483597.870e9),
    "RK": ("von Klitzing constant", 25812.8074434),
    "mp": ("Proton mass", 1.672621777e-27),
    "mn": ("Neutron mass", 1.674927351e-27),
    "me": ("Electron mass", 9.10938291e-31),
    "mmu": ("Muon mass", 1.883531475e-28),
    "a0": ("Bohr radius", 5.2917721092e-11),
    "alpha": ("Fine-structure constant", 7.2973525698e-3),
    "re": ("Classical electron radius", 2.8179403267e-15),
    "lambdaC": ("Electron Compton wavelength", 2.4263102389e-12),
    "gamma_p": ("Proton gyromagnetic ratio", 2.67522128e8),
    "lambdaCp": ("Proton Compton wavelength", 1.32140985623e-15),
    "lambdaCn": ("Neutron Compton wavelength", 1.3195909068e-15),
    "Rinf": ("Rydberg constant", 10973731.568539),
    "mu_p": ("Proton magnetic moment", 1.410606743e-26),
    "mu_e": ("Electron magnetic moment", -9.2847643e-24),
    "mu_n": ("Neutron magnetic moment", -9.662365e-27),
    "mu_mu": ("Muon magnetic moment", -4.49044807e-26),
    "mtau": ("Tau particle mass", 3.16747e-27),
    "u": ("Unified atomic mass constant", 1.660538921e-27),
    "F": ("Faraday constant", 96485.3365),
    "NA": ("Avogadro constant", 6.02214129e23),
    "kB": ("Boltzmann constant", 1.3806488e-23),
    "Vm": ("Ideal-gas standard molar volume", 0.022710953),
    "R": ("Molar gas constant", 8.3144621),
    "c1": ("First radiation constant", 3.74177153e-16),
    "c2": ("Second radiation constant", 1.4387770e-2),
    "sigmaSB": ("Stefan–Boltzmann constant", 5.670373e-8),
    "g": ("Standard acceleration of gravity", 9.80665),
    "atm": ("Standard atmosphere", 101325.0),
    "RK90": ("Conventional von Klitzing constant", 25812.807),
    "KJ90": ("Conventional Josephson constant", 483597.9e9),
    "tC": ("Kelvin equivalent of 0 °C", 273.15),
}

# NIST's current table is based on the 2022 CODATA recommended values. Values
# that are exact under the SI are represented as ordinary floats because this
# list is a calculator insertion/display catalogue, not a units package.
CURRENT_CONSTANTS: dict[str, tuple[str, float]] = {
    "h": ("Planck constant", 6.62607015e-34),
    "hbar": ("Reduced Planck constant", 1.054571817e-34),
    "c0": ("Speed of light in vacuum", 299792458.0),
    "eps0": ("Vacuum electric permittivity", 8.8541878188e-12),
    "mu0": ("Vacuum magnetic permeability", 1.25663706127e-6),
    "Z0": ("Characteristic impedance of vacuum", 376.730313412),
    "G": ("Newtonian gravitational constant", 6.67430e-11),
    "lP": ("Planck length", 1.616255e-35),
    "tP": ("Planck time", 5.391247e-44),
    "muN": ("Nuclear magneton", 5.0507837393e-27),
    "muB": ("Bohr magneton", 9.2740100657e-24),
    "qe": ("Elementary charge", 1.602176634e-19),
    "Phi0": ("Magnetic flux quantum", 2.067833848e-15),
    "G0": ("Conductance quantum", 7.748091729e-5),
    "KJ": ("Josephson constant", 483597.8484e9),
    "RK": ("von Klitzing constant", 25812.80745),
    "mp": ("Proton mass", 1.67262192595e-27),
    "mn": ("Neutron mass", 1.67492750056e-27),
    "me": ("Electron mass", 9.1093837139e-31),
    "mmu": ("Muon mass", 1.883531627e-28),
    "a0": ("Bohr radius", 5.29177210544e-11),
    "alpha": ("Fine-structure constant", 7.2973525643e-3),
    "re": ("Classical electron radius", 2.8179403205e-15),
    "lambdaC": ("Electron Compton wavelength", 2.42631023538e-12),
    "gamma_p": ("Proton gyromagnetic ratio", 2.6752218708e8),
    "lambdaCp": ("Proton Compton wavelength", 1.32140985360e-15),
    "lambdaCn": ("Neutron Compton wavelength", 1.31959090382e-15),
    "Rinf": ("Rydberg constant", 10973731.568157),
    "mu_p": ("Proton magnetic moment", 1.41060679545e-26),
    "mu_e": ("Electron magnetic moment", -9.2847646917e-24),
    "mu_n": ("Neutron magnetic moment", -9.6623653e-27),
    "mu_mu": ("Muon magnetic moment", -4.49044830e-26),
    "mtau": ("Tau particle mass", 3.16754e-27),
    "u": ("Unified atomic mass constant", 1.66053906892e-27),
    "F": ("Faraday constant", 96485.33212),
    "NA": ("Avogadro constant", 6.02214076e23),
    "kB": ("Boltzmann constant", 1.380649e-23),
    "Vm": ("Ideal-gas standard molar volume", 0.02271095464),
    "R": ("Molar gas constant", 8.314462618),
    "c1": ("First radiation constant", 3.741771852e-16),
    "c2": ("Second radiation constant", 1.438776877e-2),
    "sigmaSB": ("Stefan–Boltzmann constant", 5.670374419e-8),
    "g": ("Standard acceleration of gravity", 9.80665),
    "atm": ("Standard atmosphere", 101325.0),
    "RK90": ("Conventional von Klitzing constant", 25812.807),
    "KJ90": ("Conventional Josephson constant", 483597.9e9),
    "tC": ("Kelvin equivalent of 0 °C", 273.15),
}

# ``CONSTANTS`` stays a legacy alias so third-party imports keep their former
# semantics. UI code must call ``constants_for_dataset`` for user selection.
CONSTANTS = LEGACY_CONSTANTS


def constants_for_dataset(dataset: str) -> dict[str, tuple[str, float]]:
    """Return a supported constants catalogue, falling back to legacy safely."""
    return CURRENT_CONSTANTS if dataset == CURRENT_CONSTANTS_DATASET_LABEL else LEGACY_CONSTANTS
