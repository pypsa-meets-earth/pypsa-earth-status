# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot AC transmission corridor capacity preservation."""

import logging
import os

import matplotlib.pyplot as plt
import pandas as pd
from helpers import configure_logging

logger = logging.getLogger(__name__)


def plot_capacity_comparison(
    capacity_comparison,
    output_path,
):
    """Plot OSM-derived versus evaluated PyPSA AC corridor capacity."""
    data = capacity_comparison.loc[
        capacity_comparison["capacity_status"] == "comparable"
    ].copy()

    data = data.dropna(
        subset=[
            "osm_ac_capacity_mva",
            "pypsa_ac_optimized_capacity_mva",
        ]
    )

    fig, ax = plt.subplots(figsize=(8, 7))

    if data.empty:
        ax.text(
            0.5,
            0.5,
            "No comparable AC corridor capacity data available",
            ha="center",
            va="center",
        )

        ax.set_axis_off()

        fig.savefig(
            output_path,
            dpi=150,
            bbox_inches="tight",
        )

        plt.close(fig)
        return

    x = data["osm_ac_capacity_mva"]

    y = data["pypsa_ac_optimized_capacity_mva"]

    lower = min(
        x.min(),
        y.min(),
    )

    upper = max(
        x.max(),
        y.max(),
    )

    ax.scatter(
        x,
        y,
        alpha=0.7,
        zorder=3,
    )

    ax.plot(
        [lower, upper],
        [lower, upper],
        linestyle="--",
        linewidth=1.5,
        label="1:1 capacity preservation",
        zorder=2,
    )

    ax.set_xscale("log")
    ax.set_yscale("log")

    ax.set_xlim(
        lower * 0.8,
        upper * 1.2,
    )

    ax.set_ylim(
        lower * 0.8,
        upper * 1.2,
    )

    ax.set_title(
        "Transmission Capacity Preservation",
        fontsize=18,
        fontweight="bold",
        pad=18,
    )

    ax.set_xlabel("OSM-derived corridor capacity (MVA)")

    ax.set_ylabel("Evaluated PyPSA corridor capacity (MVA)")

    ax.grid(
        True,
        alpha=0.3,
        zorder=0,
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(
        frameon=False,
    )

    ratio = y / x

    comparable_corridors = len(data)

    median_ratio = ratio.median()

    within_10_percent = ((ratio >= 0.90) & (ratio <= 1.10)).mean() * 100.0

    within_25_percent = ((ratio >= 0.75) & (ratio <= 1.25)).mean() * 100.0

    aggregate_ratio = y.sum() / x.sum()

    fig.text(
        0.5,
        0.02,
        (
            f"Comparable AC corridors: {comparable_corridors}\n"
            f"Median PyPSA / OSM capacity ratio: {median_ratio:.2f}\n"
            f"Within ±10%: {within_10_percent:.1f}%   |   "
            f"Within ±25%: {within_25_percent:.1f}%\n"
            f"Aggregate PyPSA / OSM capacity ratio: {aggregate_ratio:.2f}"
        ),
        ha="center",
        va="bottom",
        fontsize=9,
        linespacing=1.35,
    )

    fig.tight_layout()

    fig.subplots_adjust(bottom=0.23)

    fig.savefig(
        output_path,
        dpi=150,
        bbox_inches="tight",
    )

    plt.close(fig)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        from helpers import mock_snakemake

        snakemake = mock_snakemake("plot_transmission_capacity_validation")

        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    capacity_comparison = pd.read_csv(snakemake.input["capacity_comparison"])

    plot_capacity_comparison(
        capacity_comparison,
        snakemake.output["capacity_plot"],
    )

    logger.info("Created transmission capacity validation plot.")
