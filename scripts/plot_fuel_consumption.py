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
    "electricity": "#2a78d6",
    "gas": "#eb6834",
    "oil": "#5b5b5b",
    "coal": "#8c564b",
    "biomass": "#2ca02c",
    "hydrogen": "#17becf",
    "unclassified": "#bbbbbb",
}


def plot_by_sector(table, output):
    """Create stacked horizontal bars of consumption by sector and fuel."""
    required = {"region", "sector", "fuel", "model_year", "consumption_twh"}
    if missing := required - set(table.columns):
        raise ValueError(f"Missing columns: {sorted(missing)}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    data = table.dropna(subset=["consumption_twh"]).copy()
    data["sector"] = data["sector"].fillna("unclassified").replace("", "unclassified")
    data["fuel"] = data["fuel"].fillna("unclassified").replace("", "unclassified")

    if data.empty or data["consumption_twh"].abs().sum() == 0:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(
            0.5,
            0.5,
            "Fuel consumption unavailable: no final consumption found in the network",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.suptitle(
            "Final energy consumption by sector", fontsize=16, fontweight="bold"
        )
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    data["label"] = data["sector"].str.replace("_", " ").str.title()
    if data["region"].nunique() > 1:
        data["label"] = data["region"] + " / " + data["label"]

    pivot = data.pivot_table(
        index="label",
        columns="fuel",
        values="consumption_twh",
        aggfunc="sum",
        fill_value=0.0,
    )
    pivot = pivot.loc[pivot.sum(axis=1).sort_values().index]

    fig, ax = plt.subplots(figsize=(10, max(4.5, len(pivot) * 0.65 + 1.5)))

    left = np.zeros(len(pivot))
    positions = np.arange(len(pivot))
    for fuel in pivot.columns:
        values = pivot[fuel].to_numpy()
        ax.barh(
            positions,
            values,
            left=left,
            color=FUEL_COLORS.get(fuel, "#999999"),
            label=fuel.replace("_", " ").title(),
            zorder=3,
        )
        left += values

    for position, total in zip(positions, left):
        ax.text(total, position, f" {total:.1f}", va="center", fontsize=9)

    ax.set_yticks(positions)
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("Final energy consumption (TWh/year)")
    ax.set_ylabel("")
    ax.grid(axis="x", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(0, left.max() * 1.15)

    regions = ", ".join(sorted(data["region"].unique()))
    years = data["model_year"].dropna().unique()
    year = str(int(years[0])) if len(years) == 1 else "Multiple years"

    fig.suptitle(
        "Final energy consumption by sector",
        fontsize=16,
        fontweight="bold",
        x=0.5,
        y=0.96,
    )
    ax.set_title(f"{regions} ({year})", fontsize=12, loc="center", pad=14)

    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.035),
        ncol=min(len(labels), 6),
        frameon=False,
        fontsize=11,
    )

    fig.tight_layout(rect=[0, 0.15, 1, 0.88])
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plot_by_sector(pd.read_csv(args.input), args.output)


if __name__ == "__main__":
    main()
