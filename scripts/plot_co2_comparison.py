# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot model and reference CO2 emissions by sector."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_comparison(table, output):
    """Create grouped horizontal bars for model and reference emissions."""
    required = {
        "region",
        "sector",
        "network_emissions",
        "reference_emissions",
    }

    missing = required - set(table.columns)

    if missing:
        raise ValueError(f"Missing comparison columns: {sorted(missing)}")

    if table.empty or table["sector"].eq("total").all():
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(
            0.5,
            0.5,
            "Sector comparison unavailable: no comparable sector metadata",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.suptitle("CO₂ emissions by sector", fontsize=16, fontweight="bold")
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    data = table.copy()

    required_years = {"model_year", "reference_year"}
    if missing := required_years - set(data.columns):
        raise ValueError(f"Missing comparison columns: {sorted(missing)}")

    data["label"] = data["sector"].str.replace("_", " ").str.title()

    if data["region"].nunique() > 1:
        data["label"] = data["region"] + " / " + data["label"]

    # Display total only when multiple mapped sectors are available.
    sector_counts = (
        data.loc[data["sector"].ne("total")]
        .groupby(["region", "model_year"])["sector"]
        .nunique()
    )

    if sector_counts.empty:
        raise ValueError("No sector-level comparisons available.")

    if (sector_counts == 1).all():
        data = data.loc[data["sector"].ne("total")].copy()

    # Barh draws the first category at the bottom.
    data["is_total"] = data["sector"].eq("total")
    data = data.sort_values(
        ["is_total", "network_emissions"],
        ascending=[False, True],
    )

    positions = np.arange(len(data))
    height = 0.35

    fig, ax = plt.subplots(figsize=(10, max(4, len(data) * 0.8 + 2)))

    model_bars = ax.barh(
        positions - height / 2,
        data["network_emissions"],
        height,
        color="#2a78d6",
        label="Model",
        zorder=3,
    )

    reference_label = (
        str(data["reference_source"].iloc[0])
        if "reference_source" in data.columns
        else "Reference"
    )

    reference_bars = ax.barh(
        positions + height / 2,
        data["reference_emissions"],
        height,
        color="#eb6834",
        label=reference_label,
        zorder=3,
    )

    ax.set_yticks(positions)
    ax.set_yticklabels(data["label"])

    ax.set_xlabel("CO₂ emissions (MtCO₂/year)")
    ax.set_ylabel("")

    regions = ", ".join(sorted(data["region"].unique()))

    years = data["model_year"].dropna().unique()
    year = str(int(years[0])) if len(years) == 1 else "Multiple years"

    fig.suptitle(
        "CO₂ emissions by sector",
        fontsize=16,
        fontweight="bold",
        x=0.5,
        y=0.98,
    )

    ax.set_title(
        f"{regions} ({year})",
        fontsize=12,
        fontweight="normal",
        loc="center",
        pad=14,
    )

    ax.bar_label(model_bars, fmt="%.1f", padding=3, fontsize=9)
    ax.bar_label(reference_bars, fmt="%.1f", padding=3, fontsize=9)

    ax.grid(axis="x", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    model_years = data["model_year"].dropna().unique()
    reference_years = data["reference_year"].dropna().unique()

    if len(model_years) != 1 or len(reference_years) != 1:
        raise ValueError(
            "A comparison figure must have one model year " "and one reference year."
        )

    model_label = f"Model ({int(model_years[0])})"
    reference_label = f"{reference_label} ({int(reference_years[0])})"

    fig.legend(
        handles=[model_bars, reference_bars],
        labels=[model_label, reference_label],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.025),
        ncol=2,
        frameon=False,
        fontsize=11,
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    xmax = max(
        data["network_emissions"].max(),
        data["reference_emissions"].max(),
    )
    ax.set_xlim(0, xmax * 1.18)

    fig.tight_layout(rect=[0, 0.18, 1, 0.88])

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    table = pd.read_csv(args.input)
    plot_comparison(table, args.output)


if __name__ == "__main__":
    main()
