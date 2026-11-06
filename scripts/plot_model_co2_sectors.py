# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot modeled CO2 emissions by sector or subsector."""

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

logger = logging.getLogger(__name__)

SECTOR_GROUPS = {
    "residential": "buildings",
    "services": "buildings",
}


def prepare_sector_data(detail, groupby="sector"):
    """Aggregate emissions without assigning missing sector metadata."""
    required = {
        "region",
        "sector",
        "subsector",
        "model_year",
        "network_emissions",
    }

    missing = required - set(detail.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    data = detail.copy()
    data["sector"] = data["sector"].fillna("").astype(str).str.strip()
    data["subsector"] = data["subsector"].fillna("").astype(str).str.strip()

    unassigned = data.loc[data["sector"].eq(""), "network_emissions"].sum()

    logger.info("Unassigned emissions: %.6f MtCO2", unassigned)

    data = data.loc[data["sector"].ne("")].copy()
    data["sector"] = data["sector"].replace(SECTOR_GROUPS)

    if groupby == "subsector":
        data["label"] = data["sector"] + " / " + data["subsector"]
        data = data.loc[data["subsector"].ne("")]
    elif groupby == "sector":
        data["label"] = data["sector"]
    else:
        raise ValueError(f"Unsupported grouping: {groupby}")

    return data.groupby(["region", "model_year", "label"], as_index=False)[
        "network_emissions"
    ].sum()


def plot_sector_emissions(detail, output, groupby="sector"):
    """Create one subplot per country and model year."""
    data = prepare_sector_data(detail, groupby)

    if data.empty:
        logger.warning(
            "No classified CO2 emissions available for %s plotting.",
            groupby,
        )

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(
            0.5,
            0.5,
            "No classified sector metadata available",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.suptitle(
            f"CO₂ emissions by {groupby}",
            fontsize=16,
            fontweight="bold",
        )

        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    groups = list(data.groupby(["region", "model_year"], sort=True))

    fig, axes = plt.subplots(
        len(groups),
        1,
        figsize=(13, max(6, 0.7 * len(data) + 2 * len(groups))),
        squeeze=False,
    )

    for ax, ((region, year), group) in zip(axes.flat, groups):
        emissions = (
            group.set_index("label")["network_emissions"]
            .loc[lambda values: values.abs() > 1e-9]
            .sort_values()
        )

        if emissions.empty:
            ax.text(
                0.5,
                0.5,
                "No emissions",
                transform=ax.transAxes,
                ha="center",
                va="center",
            )
        else:
            bars = ax.barh(
                emissions.index.str.replace("_", " ").str.capitalize(),
                emissions.values,
                color="#2a78d6",
                height=0.65,
                zorder=3,
            )

            ax.bar_label(
                bars,
                fmt="%.1f",
                padding=4,
                fontsize=9,
            )

            xmin = min(0.0, float(emissions.min()))
            xmax = max(0.0, float(emissions.max()))
            padding = max(xmax - xmin, 1.0) * 0.15
            ax.set_xlim(xmin - padding, xmax + padding)

        ax.set_title(
            f"{region} ({int(year)})",
            fontsize=12,
            pad=14,
        )

        ax.set_xlabel("CO₂ emissions (MtCO₂/year)")
        ax.grid(axis="x", alpha=0.25, zorder=0)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.suptitle(
        f"CO₂ emissions by {groupby}",
        fontsize=16,
        fontweight="bold",
        y=0.99,
    )

    fig.tight_layout(rect=[0, 0, 1, 0.95])

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--groupby",
        choices=["sector", "subsector"],
        default="sector",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    detail = pd.read_csv(args.input)

    plot_sector_emissions(
        detail,
        args.output,
        groupby=args.groupby,
    )


if __name__ == "__main__":
    main()
