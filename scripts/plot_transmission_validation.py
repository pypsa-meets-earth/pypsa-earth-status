# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Plot transmission topology and voltage validation results.
"""

import logging
import os

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from helpers import configure_logging
from matplotlib.lines import Line2D

logger = logging.getLogger(__name__)


STATUS_COLORS = {
    "matched": "#2ca02c",
    "osm_only": "#d62728",
    "pypsa_only": "#7f7f7f",
}

STATUS_LABELS = {
    "matched": "Matched",
    "osm_only": "OSM only",
    "pypsa_only": "PyPSA only",
}


def plot_topology_comparison(
    comparison,
    bus_regions,
    output_path,
):
    """Plot transmission topology with explicit OSM/PyPSA overlap."""
    regions = bus_regions.copy()

    regions["region_id"] = regions["region_id"].astype(str)

    coordinates = regions.set_index("region_id")[["x", "y"]]

    projection = ccrs.PlateCarree()

    fig, ax = plt.subplots(
        figsize=(13, 10),
        subplot_kw={"projection": projection},
    )

    # Geographic context.
    ax.add_feature(
        cfeature.LAND.with_scale("50m"),
        facecolor="#f7f7f7",
        edgecolor="none",
        zorder=0,
    )

    ax.add_feature(
        cfeature.BORDERS.with_scale("50m"),
        edgecolor="#333333",
        linewidth=1.2,
        zorder=1,
    )

    ax.coastlines(
        resolution="50m",
        color="#333333",
        linewidth=1.0,
        zorder=1,
    )

    minx, miny, maxx, maxy = regions.total_bounds

    dx = maxx - minx
    dy = maxy - miny

    ax.set_extent(
        [
            minx - 0.02 * dx,
            maxx + 0.02 * dx,
            miny - 0.02 * dy,
            maxy + 0.02 * dy,
        ],
        crs=projection,
    )

    def draw_corridors(
        subset,
        color,
        linewidth,
        linestyle,
        alpha,
        zorder,
    ):
        for row in subset.itertuples():
            bus0 = str(row.bus0)
            bus1 = str(row.bus1)

            if bus0 not in coordinates.index or bus1 not in coordinates.index:
                continue

            x0, y0 = coordinates.loc[
                bus0,
                ["x", "y"],
            ]

            x1, y1 = coordinates.loc[
                bus1,
                ["x", "y"],
            ]

            ax.plot(
                [x0, x1],
                [y0, y1],
                color=color,
                linewidth=linewidth,
                linestyle=linestyle,
                alpha=alpha,
                zorder=zorder,
                transform=projection,
                solid_capstyle="round",
                dash_capstyle="round",
            )

    matched = comparison.loc[comparison["status"] == "matched"]

    model_only = comparison.loc[comparison["status"] == "pypsa_only"]

    osm_only = comparison.loc[comparison["status"] == "osm_only"]

    # Matched corridors form the main evaluated PyPSA topology.
    draw_corridors(
        matched,
        color="#263238",
        linewidth=2.2,
        linestyle="-",
        alpha=0.90,
        zorder=3,
    )

    # Corridors present only in the evaluated model.
    draw_corridors(
        model_only,
        color="#e68613",
        linewidth=3.0,
        linestyle="-",
        alpha=1.0,
        zorder=4,
    )

    # OSM corridors not represented in the evaluated model.
    draw_corridors(
        osm_only,
        color="#d62728",
        linewidth=2.8,
        linestyle=(0, (5, 3)),
        alpha=1.0,
        zorder=5,
    )

    # Evaluated PyPSA transmission buses.
    ax.scatter(
        regions["x"],
        regions["y"],
        s=12,
        color="#111111",
        edgecolor="white",
        linewidth=0.35,
        alpha=0.95,
        zorder=6,
        transform=projection,
    )

    legend = [
        Line2D(
            [0],
            [0],
            color="#263238",
            linewidth=2.2,
            linestyle="-",
            label=f"Matched ({len(matched)})",
        ),
        Line2D(
            [0],
            [0],
            color="#e68613",
            linewidth=3.0,
            linestyle="-",
            label=f"PyPSA only ({len(model_only)})",
        ),
        Line2D(
            [0],
            [0],
            color="#d62728",
            linewidth=2.8,
            linestyle=(0, (5, 3)),
            label=f"OSM only ({len(osm_only)})",
        ),
    ]

    ax.legend(
        handles=legend,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.025),
        ncol=3,
    )

    ax.text(
        0.5,
        -0.095,
        (
            "OSM is aggregated to the same spatial resolution as the PyPSA "
            "network before comparison."
        ),
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=9,
    )

    ax.set_title(
        "Transmission Topology Comparison",
        fontsize=18,
        fontweight="bold",
        pad=18,
    )

    ax.set_axis_off()

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.16)

    fig.savefig(
        output_path,
        dpi=180,
        bbox_inches="tight",
    )

    plt.close(fig)


def plot_voltage_representation(
    voltage_representation,
    comparison,
    output_path,
):
    """Plot OSM voltage representation separately for each area."""
    data = voltage_representation.copy()

    if data.empty:
        fig, ax = plt.subplots(figsize=(10, 6))

        ax.text(
            0.5,
            0.5,
            "No comparable AC voltage data available",
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

    pypsa_voltage_classes = sorted(
        {
            float(voltage)
            for value in comparison["pypsa_ac_voltages_kv"].dropna()
            for voltage in str(value).split(",")
            if voltage.strip()
        }
    )

    if len(pypsa_voltage_classes) == 1:
        simplification_voltage_note = (
            "Adopted simplification voltage: " f"{pypsa_voltage_classes[0]:g} kV"
        )
    elif pypsa_voltage_classes:
        voltage_labels = ", ".join(
            f"{voltage:g} kV" for voltage in pypsa_voltage_classes
        )

        simplification_voltage_note = "Evaluated PyPSA AC voltages: " + voltage_labels
    else:
        simplification_voltage_note = "Evaluated PyPSA AC voltage: unavailable"

    voltage_classes = sorted(data["voltage_kv"].unique())

    regular_areas = sorted(
        area
        for area in data["area"].unique()
        if area
        not in {
            "Cross-border",
            "Unknown",
        }
    )

    areas = regular_areas.copy()

    for special_area in [
        "Cross-border",
        "Unknown",
    ]:
        if special_area in data["area"].values:
            areas.append(special_area)

    nrows = len(areas)

    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=1,
        figsize=(
            10,
            6.0 if nrows == 1 else 4.8 * nrows + 1.5,
        ),
        sharex=True,
        squeeze=False,
    )

    axes = axes[:, 0]

    global_max = data["class_share_total_pct"].max()

    xmax = max(
        10.0,
        global_max * 1.15,
    )

    legend_handles = None
    legend_labels = None
    panel_notes = []

    for ax, area in zip(
        axes,
        areas,
    ):
        panel = (
            data.loc[data["area"] == area]
            .set_index("voltage_kv")
            .reindex(voltage_classes)
        )

        numeric_columns = [
            "represented_capacity_mva",
            "not_represented_capacity_mva",
            "total_capacity_mva",
            "represented_share_total_pct",
            "not_represented_share_total_pct",
            "class_share_total_pct",
            "coverage_pct",
        ]

        for column in numeric_columns:
            panel[column] = panel[column].fillna(0.0)

        panel = panel.reset_index()

        represented = panel["represented_share_total_pct"]

        not_represented = panel["not_represented_share_total_pct"]

        total = panel["class_share_total_pct"]

        y = range(len(voltage_classes))

        ax.barh(
            y,
            represented,
            label="Represented in PyPSA AC network",
            color="#4c78a8",
            zorder=3,
        )

        ax.barh(
            y,
            not_represented,
            left=represented,
            label="Not represented in PyPSA AC network",
            color="#f28e2b",
            zorder=3,
        )

        ax.set_yticks(list(y))

        ax.set_yticklabels([f"{voltage:g} kV" for voltage in voltage_classes])

        ax.set_xlim(
            0,
            xmax,
        )

        ax.set_title(
            area,
            fontsize=12,
            fontweight="bold",
            pad=8,
        )

        label_offset = max(
            0.3,
            global_max * 0.01,
        )

        for index, value in enumerate(total):
            if value <= 0:
                continue

            ax.text(
                value + label_offset,
                index,
                f"{value:.1f}%",
                va="center",
                fontsize=9,
            )

        total_capacity = panel["total_capacity_mva"].sum()

        represented_capacity = panel["represented_capacity_mva"].sum()

        overall_coverage = (
            100.0 * represented_capacity / total_capacity if total_capacity > 0 else 0.0
        )

        capacity_weighted_voltage = (
            (panel["voltage_kv"] * panel["total_capacity_mva"]).sum() / total_capacity
            if total_capacity > 0
            else float("nan")
        )

        panel_notes.append(
            (
                area,
                overall_coverage,
                capacity_weighted_voltage,
            )
        )

        ax.grid(
            True,
            axis="x",
            alpha=0.25,
            zorder=0,
        )

        ax.spines["top"].set_visible(False)

        ax.spines["right"].set_visible(False)

        ax.spines["left"].set_visible(False)

        if legend_handles is None:
            (
                legend_handles,
                legend_labels,
            ) = ax.get_legend_handles_labels()

    axes[-1].set_xlabel("Share of total OSM-derived inter-region AC capacity (%)")

    fig.suptitle(
        "Transmission Voltage Representation",
        fontsize=18,
        fontweight="bold",
        y=0.985,
    )

    fig.legend(
        legend_handles,
        legend_labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.095),
        ncol=2,
        frameon=False,
    )

    note_lines = []

    for (
        area,
        overall_coverage,
        capacity_weighted_voltage,
    ) in panel_notes:
        if len(panel_notes) > 1:
            note_lines.append(f"{area}")

        note_lines.extend(
            [
                (
                    "OSM-derived AC capacity represented in PyPSA: "
                    f"{overall_coverage:.1f}%"
                ),
                (
                    "OSM capacity-weighted voltage: "
                    f"{capacity_weighted_voltage:.0f} kV"
                ),
                simplification_voltage_note,
            ]
        )

        if len(panel_notes) > 1:
            note_lines.append("")

    fig.text(
        0.5,
        0.025,
        "\n".join(note_lines).rstrip(),
        ha="center",
        va="bottom",
        fontsize=9,
        linespacing=1.35,
    )

    fig.subplots_adjust(
        top=0.86,
        bottom=0.23,
        hspace=0.75,
    )

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

        snakemake = mock_snakemake("plot_transmission_validation")

        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    comparison = pd.read_csv(
        snakemake.input["comparison"],
        dtype={
            "bus0": str,
            "bus1": str,
        },
    )

    voltage_representation = pd.read_csv(snakemake.input["voltage_representation"])

    bus_regions = gpd.read_file(snakemake.input["bus_regions"])

    os.makedirs(
        os.path.dirname(snakemake.output["topology_plot"]),
        exist_ok=True,
    )

    plot_topology_comparison(
        comparison,
        bus_regions,
        snakemake.output["topology_plot"],
    )

    plot_voltage_representation(
        voltage_representation,
        comparison,
        snakemake.output["voltage_plot"],
    )

    logger.info("Created transmission topology and voltage validation plots.")
