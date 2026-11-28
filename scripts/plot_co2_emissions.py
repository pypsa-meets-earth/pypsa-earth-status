# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot annual CO2 emissions from network statistics."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


def plot_co2_emissions(table, output_path, groupby="carrier"):
    """Create a horizontal bar plot of annual CO2 emissions."""
    valid_groups = {"carrier", "sector", "subsector"}

    if groupby not in valid_groups:
        raise ValueError(f"Unsupported grouping: {groupby}")

    required_columns = {"region", groupby, "network_emissions"}
    missing = required_columns - set(table.columns)

    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    data = table.copy()

    if groupby == "subsector":
        data[groupby] = data[groupby].fillna("").replace("", "unspecified")
    else:
        data[groupby] = data[groupby].fillna("unspecified")

    regions = sorted(data["region"].dropna().unique())
    multiple_regions = len(regions) > 1

    if groupby == "subsector" and "sector" in data.columns:
        data["label"] = (
            data["sector"].fillna("unspecified").astype(str)
            + " / "
            + data["subsector"].astype(str)
        )
    else:
        data["label"] = data[groupby].astype(str)

    if multiple_regions:
        data["label"] = data["region"].astype(str) + " / " + data["label"]

    emissions = (
        data.groupby("label")["network_emissions"]
        .sum()
        .loc[lambda values: values.abs() > 1e-9]
        .sort_values()
    )

    fig, ax = plt.subplots(figsize=(10, max(4, 0.45 * len(emissions) + 1.5)))

    if emissions.empty:
        ax.text(
            0.5,
            0.5,
            "No CO2 emissions available",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
    else:
        emissions.plot.barh(ax=ax, zorder=3)

        ax.axvline(0, color="black", linewidth=0.8)
        ax.grid(axis="x", alpha=0.3, zorder=0)
        ax.set_xlabel("CO2 emissions (MtCO2/year)")
        ax.set_ylabel("")

        for index, value in enumerate(emissions):
            ax.annotate(
                f"{value:,.2f}",
                xy=(value, index),
                xytext=(5 if value >= 0 else -5, 0),
                textcoords="offset points",
                ha="left" if value >= 0 else "right",
                va="center",
                fontsize=9,
            )

        xmin, xmax = ax.get_xlim()
        padding = max(xmax - xmin, 1.0) * 0.12
        ax.set_xlim(xmin - padding, xmax + padding)

    title = f"CO₂ emissions by {groupby}"

    regions_label = ", ".join(regions) if regions else "Unknown region"

    years = (
        table["model_year"].dropna().unique() if "model_year" in table.columns else []
    )
    year_label = str(int(years[0])) if len(years) == 1 else "Multiple years"

    fig.suptitle(
        title,
        fontsize=16,
        fontweight="bold",
        y=0.98,
    )

    ax.set_title(
        f"{regions_label} ({year_label})",
        fontsize=12,
        fontweight="normal",
        loc="center",
        pad=14,
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout(rect=[0, 0, 1, 0.92])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--groupby",
        choices=["carrier", "sector", "subsector"],
        default="carrier",
    )
    args = parser.parse_args()

    table = pd.read_csv(args.input)

    plot_co2_emissions(
        table,
        args.output,
        groupby=args.groupby,
    )


if __name__ == "__main__":
    main()
