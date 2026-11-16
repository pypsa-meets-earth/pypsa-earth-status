# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot model and UNSD final energy consumption by sector and fuel."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def year_label(years):
    """Format one year or a year range."""
    years = sorted(int(y) for y in pd.Series(years).dropna().unique())
    if not years:
        return "n/a"
    return str(years[0]) if len(years) == 1 else f"{years[0]}–{years[-1]}"


def plot_comparison(table, output):
    """Create grouped horizontal bars for model and UNSD consumption."""
    required = {
        "region",
        "sector",
        "fuel",
        "model_year",
        "reference_year",
        "network_twh",
        "reference_twh",
        "status",
    }
    if missing := required - set(table.columns):
        raise ValueError(f"Missing comparison columns: {sorted(missing)}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    data = table.loc[table["status"].eq("compared")].copy()

    if data.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(
            0.5,
            0.5,
            "Fuel comparison unavailable: no comparable sector and fuel data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.suptitle(
            "Final energy consumption by sector and fuel",
            fontsize=16,
            fontweight="bold",
        )
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    data["label"] = (
        data["sector"].str.replace("_", " ").str.title()
        + " / "
        + data["fuel"].str.replace("_", " ").str.title()
    )
    if data["region"].nunique() > 1:
        data["label"] = data["region"] + " / " + data["label"]

    # Barh draws the first category at the bottom.
    data = data.sort_values(["sector", "network_twh"], ascending=[False, True])

    positions = np.arange(len(data))
    height = 0.35

    fig, ax = plt.subplots(figsize=(10, max(4.5, len(data) * 0.65 + 1.5)))

    model_bars = ax.barh(
        positions - height / 2,
        data["network_twh"],
        height,
        color="#2a78d6",
        zorder=3,
    )

    reference_name = (
        str(data["reference_source"].iloc[0])
        if "reference_source" in data.columns and data["reference_source"].notna().any()
        else "UNSD"
    )
    reference_bars = ax.barh(
        positions + height / 2,
        data["reference_twh"],
        height,
        color="#eb6834",
        zorder=3,
    )

    ax.set_yticks(positions)
    ax.set_yticklabels(data["label"])
    ax.set_xlabel("Final energy consumption (TWh/year)")
    ax.set_ylabel("")

    ax.bar_label(model_bars, fmt="%.1f", padding=3, fontsize=9)
    ax.bar_label(reference_bars, fmt="%.1f", padding=3, fontsize=9)

    ax.grid(axis="x", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(0, max(data["network_twh"].max(), data["reference_twh"].max()) * 1.18)

    regions = ", ".join(sorted(data["region"].unique()))
    model_year = year_label(data["model_year"])

    fig.suptitle(
        "Final energy consumption by sector and fuel",
        fontsize=16,
        fontweight="bold",
        x=0.5,
        y=0.96,
    )
    ax.set_title(f"{regions} ({model_year})", fontsize=12, loc="center", pad=14)

    fig.legend(
        handles=[model_bars, reference_bars],
        labels=[
            f"Model ({model_year})",
            f"{reference_name} ({year_label(data['reference_year'])})",
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.035),
        ncol=2,
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

    plot_comparison(pd.read_csv(args.input), args.output)


if __name__ == "__main__":
    main()
