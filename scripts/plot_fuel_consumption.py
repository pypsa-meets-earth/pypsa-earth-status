# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot modeled final energy consumption by sector, stacked by fuel."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FUEL_COLORS = {
    "electricity": "#F4C430",
    "gas": "#808080",
    "oil": "#C2185B",
    "coal": "#202020",
    "biomass": "#2CA02C",
    "hydrogen": "#17BECF",
    "heat": "#D62728",
    "unclassified": "#bbbbbb",
}


def plot_by_sector(table, output, shedding=None):
    """Plot fuel consumption and load shedding on one bar for each sector.

    Load shedding is a separate diagnostic, not final energy consumption.
    The combined visual extent must not be interpreted as a fuel total.
    """
    required = {"region", "sector", "fuel", "model_year", "consumption_twh"}
    if missing := required - set(table.columns):
        raise ValueError(f"Missing columns: {sorted(missing)}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    data = table.copy()
    # pandas 3 can return object dtype when empty tables are concatenated.
    data["consumption_twh"] = pd.to_numeric(data["consumption_twh"], errors="coerce")
    data = data.dropna(subset=["consumption_twh"])
    for column in ("sector", "fuel"):
        data[column] = (
            data[column].fillna("unclassified").astype(str).replace("", "unclassified")
        )

    active_shed = pd.DataFrame()
    if shedding is not None and not shedding.empty:
        active_shed = shedding.copy()
        active_shed["unserved_twh"] = pd.to_numeric(
            active_shed["unserved_twh"], errors="coerce"
        ).fillna(0.0)
        active_shed = active_shed.loc[active_shed["unserved_twh"].gt(0.001)].copy()

    if (data.empty or data["consumption_twh"].abs().sum() == 0) and active_shed.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(
            0.5,
            0.5,
            "No fuel consumption or load shedding available",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    regions = set(data["region"].dropna().astype(str))
    if not active_shed.empty:
        regions.update(active_shed["region"].dropna().astype(str))
    multi_region = len(regions) > 1

    data["label"] = data["sector"].str.replace("_", " ").str.title()
    if multi_region:
        data["label"] = data["region"].astype(str) + " / " + data["label"]

    if data.empty:
        pivot = pd.DataFrame(index=pd.Index([], name="label"))
    else:
        pivot = data.pivot_table(
            index="label",
            columns="fuel",
            values="consumption_twh",
            aggfunc="sum",
            fill_value=0.0,
        )

    shedding_by_label = pd.Series(dtype=float)
    if not active_shed.empty:
        active_shed["sector"] = (
            active_shed["sector"]
            .fillna("unclassified")
            .astype(str)
            .replace("", "unclassified")
        )
        active_shed["label"] = active_shed["sector"].str.replace("_", " ").str.title()
        if multi_region:
            active_shed["label"] = (
                active_shed["region"].astype(str) + " / " + active_shed["label"]
            )
        shedding_by_label = active_shed.groupby("label")["unserved_twh"].sum()
        pivot = pivot.reindex(
            pivot.index.union(shedding_by_label.index), fill_value=0.0
        )

    shedding_values = shedding_by_label.reindex(pivot.index, fill_value=0.0)
    # Sort using visual extent, while keeping fuel and shedding totals separate.
    visual_extent = pivot.sum(axis=1) + shedding_values
    pivot = pivot.loc[visual_extent.sort_values().index]
    # Keep Unclassified directly below Agriculture (bottom of horizontal chart).
    is_unclassified = pivot.index.to_series().astype(str).str.endswith(
        " / Unclassified"
    ) | pivot.index.to_series().astype(str).eq("Unclassified")
    unclassified_labels = list(pivot.index[is_unclassified.to_numpy()])
    other_labels = list(pivot.index[~is_unclassified.to_numpy()])
    pivot = pivot.reindex(unclassified_labels + other_labels)

    shed = shedding_values.reindex(pivot.index).to_numpy()

    fig, ax = plt.subplots(figsize=(12, max(4.5, len(pivot) * 0.7 + 1.5)))
    positions = np.arange(len(pivot))
    left = np.zeros(len(pivot))
    for fuel in pivot.columns:
        values = pivot[fuel].to_numpy()
        ax.barh(
            positions,
            values,
            left=left,
            height=0.72,
            color=FUEL_COLORS.get(fuel, "#999999"),
            label=fuel.replace("_", " ").title(),
            zorder=3,
        )
        left += values

    fuel_totals = left.copy()
    if (shed > 0.001).any():
        ax.barh(
            positions,
            shed,
            left=fuel_totals,
            height=0.72,
            color="#7B61A8",
            label="Load shedding",
            zorder=3,
        )

    # Do not display a misleading summed final-energy total.
    for position, fuel_total, shed_total in zip(positions, fuel_totals, shed):
        label = f"{fuel_total:.1f}"
        if shed_total > 0.001:
            label += f"  +  {shed_total:.2f} LS"
        ax.text(
            fuel_total + shed_total,
            position,
            " " + label,
            va="center",
            fontsize=9,
        )

    ax.set_yticks(positions)
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("Energy consumption (TWh/year)")
    ax.grid(axis="x", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(0, max(float((fuel_totals + shed).max()), 1.0) * 1.32)

    year_source = data if not data.empty else active_shed
    years = year_source["model_year"].dropna().unique()
    year_label = str(int(years[0])) if len(years) == 1 else "Multiple years"
    fig.suptitle(
        "Final energy consumption and load shedding by sector",
        fontsize=16,
        fontweight="bold",
        y=0.97,
    )
    ax.set_title(f"{', '.join(sorted(regions))} ({year_label})", pad=14)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        fig.legend(
            handles,
            labels,
            loc="lower center",
            bbox_to_anchor=(0.5, 0.025),
            ncol=min(len(labels), 7),
            frameon=False,
            fontsize=10,
        )
    fig.tight_layout(rect=[0, 0.13, 1, 0.88])
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--shedding")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    shedding = pd.read_csv(args.shedding) if args.shedding else None
    plot_by_sector(pd.read_csv(args.input), args.output, shedding)


if __name__ == "__main__":
    main()
