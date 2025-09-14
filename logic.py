# logic.py
from __future__ import annotations
import math
import pandas as pd
from dataclasses import dataclass

@dataclass
class Weights:
    enroll: float = 0.4   # weight on normalized enrollment
    frl: float    = 0.6   # weight on normalized FRL %

def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0

def compute_need_frame(sub: pd.DataFrame, w: Weights) -> pd.DataFrame:
    """sub has columns: enrollment, frl_pct (0-100) for one county"""
    sub = sub.copy()
    sum_enroll = sub["enrollment"].sum()
    sum_frl    = sub["frl_pct"].sum()
    sub["norm_enroll"] = sub["enrollment"].apply(lambda x: _safe_div(x, sum_enroll))
    sub["norm_frl"]    = sub["frl_pct"].apply(lambda x: _safe_div(x, sum_frl))
    sub["need"] = w.enroll*sub["norm_enroll"] + w.frl*sub["norm_frl"]
    return sub

def allocate(pool_amount: float, sub: pd.DataFrame, *,
             w: Weights,
             floor: float = 0.0,
             cap_fraction: float | None = None) -> pd.DataFrame:
    """
    Proportional allocation with optional per-school floor and cap (fraction of pool).
    Rounds to cents and ensures sum equals pool by distributing remainder to largest residuals.
    """
    sub = compute_need_frame(sub, w)
    total_need = sub["need"].sum()
    if total_need <= 0:
        sub["raw_alloc"] = 0.0
    else:
        sub["raw_alloc"] = pool_amount * (sub["need"] / total_need)

    # Apply floor
    if floor > 0:
        sub["raw_alloc"] = sub["raw_alloc"].apply(lambda x: max(x, floor))

    # Apply cap
    if cap_fraction is not None:
        cap_val = cap_fraction * pool_amount
        sub["raw_alloc"] = sub["raw_alloc"].apply(lambda x: min(x, cap_val))

    # Re-normalize if floors/caps changed total
    total_raw = sub["raw_alloc"].sum()
    if total_raw > 0:
        sub["raw_alloc"] = (sub["raw_alloc"] / total_raw) * pool_amount
    else:
        sub["raw_alloc"] = 0.0

    # Round to cents with largest-remainder method
    cents = (sub["raw_alloc"] * 100).round(6)
    floored = cents.apply(math.floor)
    remainder = int(round(pool_amount * 100)) - int(floored.sum())
    residuals = (cents - floored)
    order = residuals.sort_values(ascending=False).index.tolist()
    bump = set(order[:max(remainder, 0)])

    sub["allocation"] = floored / 100.0
    if remainder > 0:
        sub.loc[sub.index.isin(bump), "allocation"] += 0.01

    return sub.assign(
        need_share=(sub["need"] / sub["need"].sum() if sub["need"].sum() else 0.0)
    )

def explain_allocation(row: pd.Series, pool: float, w: Weights,
                       county_sum_enroll: int, county_sum_frl: float) -> str:
    return (
        f"{row['school']} receives ${row['allocation']:,.2f} from the ${pool:,.2f} pool.\n"
        f"Weights: enrollment {w.enroll:.2f}, FRL {w.frl:.2f}. "
        f"It has {int(row['enrollment'])} students out of {county_sum_enroll} "
        f"and FRL {row['frl_pct']:.0f}% out of a county total {county_sum_frl:.0f}%. "
        f"This yields a need share of {row['need_share']*100:.1f}%."
    )

