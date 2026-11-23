# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot installed heating capacity and annual heat production by carrier."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


def plot_heat_statistics(table, output_path):
    """Create horizontal bar plots of heating capacity and annual heat production."""
    required_columns = {"carrier", "category", "capacity_mw", "heat_output_mwh"}
    missing = required_columns - set(table.columns)

    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    production = table[table["category"] == "production"].set_index("carrier")
    capacity = (production["capacity_mw"] / 1e3).sort_values()  # GW
    heat = (production["heat_output_mwh"] / 1e6).sort_values()  # TWh

    fig, axes = plt.subplots(1, 2, figsize=(16, max(4, 0.4 * len(production) + 1.5)))

    if production.empty:
        for ax in axes:
            ax.text(
                0.5,
                0.5,
                "No heating components available",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
    else:
        panels = [
            (axes[0], capacity, "Installed capacity (GW)", "{:,.2f}"),
            (axes[1], heat, "Annual heat production (TWh)", "{:,.2f}"),
        ]
        for ax, values, label, fmt in panels:
            values.plot.barh(ax=ax, zorder=3)
            ax.grid(axis="x", alpha=0.3, zorder=0)
            ax.set_xlabel(label)
            ax.set_ylabel("")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

            for index, value in enumerate(values):
                ax.annotate(
                    fmt.format(value),
                    xy=(value, index),
                    xytext=(5, 0),
                    textcoords="offset points",
                    ha="left",
                    va="center",
                    fontsize=9,
                )

            xmax = ax.get_xlim()[1]
            ax.set_xlim(0, xmax * 1.15)

    fig.suptitle(
        "Heating sector by technology (excluding thermal storage)",
        fontsize=16,
        fontweight="bold",
    )
    fig.tight_layout()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    table = pd.read_csv(args.input)
    plot_heat_statistics(table, args.output)


if __name__ == "__main__":
    main()
