"""Slab-based tariffs: turn a number of units into a bill.

Electricity and water in India are usually billed in slabs. Two common styles:

* telescopic: each slab's rate applies only to the units that fall inside it.
* flat_slab:  the rate of the slab your *total* lands in applies to every unit.

Check your own bill to see which one your utility uses, then edit tariffs.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TARIFFS = Path(__file__).resolve().parent.parent / "tariffs.json"
MODES = ("telescopic", "flat_slab")


@dataclass(frozen=True)
class Slab:
    upto: float | None  # upper bound of the slab; None means "no upper limit"
    rate: float  # price per unit inside this slab


@dataclass(frozen=True)
class Tariff:
    name: str
    unit_label: str
    mode: str
    slabs: tuple[Slab, ...]
    fixed_charge: float = 0.0
    tax_percent: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        if not self.slabs:
            raise ValueError("A tariff needs at least one slab.")
        if self.slabs[-1].upto is not None:
            raise ValueError("The last slab must have upto = null (no upper limit).")
        previous = 0.0
        for slab in self.slabs[:-1]:
            if slab.upto is None or slab.upto <= previous:
                raise ValueError("Slab limits must be increasing, and only the last may be null.")
            previous = slab.upto
        if any(slab.rate < 0 for slab in self.slabs):
            raise ValueError("Slab rates cannot be negative.")


@dataclass(frozen=True)
class Bill:
    units: float
    energy_charge: float
    fixed_charge: float
    tax: float
    total: float


def energy_charge(units: float, tariff: Tariff) -> float:
    """Charge for the units consumed, before fixed charge and tax."""
    if units <= 0:
        return 0.0

    if tariff.mode == "flat_slab":
        for slab in tariff.slabs:
            if slab.upto is None or units <= slab.upto:
                return units * slab.rate

    charge, lower = 0.0, 0.0
    for slab in tariff.slabs:
        upper = units if slab.upto is None else min(units, slab.upto)
        if upper > lower:
            charge += (upper - lower) * slab.rate
        if slab.upto is None or units <= slab.upto:
            break
        lower = slab.upto
    return charge


def compute_bill(units: float, tariff: Tariff) -> Bill:
    """Full bill: energy charge + fixed charge, then tax/duty on that sum."""
    energy = energy_charge(units, tariff)
    tax = (energy + tariff.fixed_charge) * tariff.tax_percent / 100.0
    total = energy + tariff.fixed_charge + tax
    return Bill(
        units=max(units, 0.0),
        energy_charge=energy,
        fixed_charge=tariff.fixed_charge,
        tax=tax,
        total=total,
    )


def tariff_from_dict(data: dict) -> Tariff:
    slabs = tuple(Slab(upto=s["upto"], rate=float(s["rate"])) for s in data["slabs"])
    return Tariff(
        name=data["name"],
        unit_label=data.get("unit_label", "units"),
        mode=data.get("mode", "telescopic"),
        slabs=slabs,
        fixed_charge=float(data.get("fixed_charge", 0.0)),
        tax_percent=float(data.get("tax_percent", 0.0)),
    )


def load_tariffs(path: str | Path = DEFAULT_TARIFFS) -> dict[str, Tariff]:
    """Load tariffs from JSON. Keys starting with '_' are treated as comments."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {key: tariff_from_dict(val) for key, val in raw.items() if not key.startswith("_")}
