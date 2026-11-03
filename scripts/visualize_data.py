# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
import os

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.img_tiles as cimgt
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from helpers import configure_logging, read_csv_nafix

colors = [
    "#b80404",
    "#0c6013",
    "#707070",
    "#ba91b1",
    "#6895dd",
    "#262626",
    "#235ebc",
    "#4adbc8",
    "#f9d002",
]


def plot_demand_comparison(demand_df, output_path):
    """
    Plot a side-by-side bar graph comparing electricity demand for each region (reference vs network).
    """
    if demand_df.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(
            0.5, 0.5, "No Demand Data Available", ha="center", va="center", fontsize=12
        )
        ax.set_axis_off()
        plt.savefig(output_path)
        plt.close()
        return

    # Set up the plot
    plt.figure(figsize=(10, 6))

    # Plot in reverse order: reference first, then network
    demand_df[["reference_demand", "network_demand"]].fillna(0).plot(
        kind="bar", stacked=False, color=colors[:2], zorder=3
    )

    plt.title("Electricity Demand Comparison (Reference vs Network)")
    plt.ylabel("Demand (TWh)")
    plt.xlabel("Region")
    plt.xticks(ticks=range(len(demand_df)), labels=demand_df["region"])

    # Remove plot box (spines)
    ax = plt.gca()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)

    # Add horizontal grid lines
    plt.grid(True, axis="y", zorder=0)

    plt.tight_layout()

    # Save the plot
    plt.savefig(output_path)
    plt.close()


def plot_carrier_capacity_comparison(
    installed_capacity_df,
    optimal_capacity_df,
    output_path,
    carrier="coal",
    normalize=False,
):
    """
    Plot a side-by-side bar graph comparing installed, optimal, and reference capacities for a given carrier (default: coal).
    """
    if installed_capacity_df.empty or optimal_capacity_df.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(
            0.5,
            0.5,
            f"No Capacity Data Available for {carrier}",
            ha="center",
            va="center",
            fontsize=12,
        )
        ax.set_axis_off()
        plt.savefig(output_path)
        plt.close()
        return

    # Check if requested carrier exists, if not, apply fallback logic
    available_carriers = installed_capacity_df["carrier"].unique()
    if carrier not in available_carriers:
        original_carrier = carrier
        # Priority: Coal > gas
        if "coal" in available_carriers:
            carrier = "coal"
        elif "gas" in available_carriers:
            carrier = "gas"
            print(f"{original_carrier} not found. Switching to gas.")

    # Filter for the chosen carrier
    installed_capacity_df = installed_capacity_df[
        installed_capacity_df["carrier"] == carrier
    ]
    optimal_capacity_df = optimal_capacity_df[optimal_capacity_df["carrier"] == carrier]
    reference_capacity_df = optimal_capacity_df[
        optimal_capacity_df["carrier"] == carrier
    ]

    # Merge the dataframes
    capacity_df = pd.merge(
        installed_capacity_df[["region", "network_capacity"]],
        optimal_capacity_df[["region", "network_capacity"]],
        on=["region"],
        suffixes=("_network", "_optimal"),
    )

    capacity_df = pd.merge(
        capacity_df,
        reference_capacity_df[["region", "reference_capacity"]],
        on="region",
        how="left",
    )

    # Rename the columns to correct names
    capacity_df = capacity_df.rename(
        columns={
            "network_capacity_network": "network_capacity",
            "network_capacity_optimal": "optimal_capacity",
        }
    )

    if capacity_df.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(
            0.5,
            0.5,
            f"No Capacity Data Available for {carrier} (After Filter)",
            ha="center",
            va="center",
            fontsize=12,
        )
        ax.set_axis_off()
        plt.savefig(output_path)
        plt.close()
        return

    if normalize:
        # Normalize data with respect to reference data (element-wise division)
        # Avoid division by zero
        capacity_df["network_capacity"] = capacity_df.apply(
            lambda row: (
                row["network_capacity"] / row["reference_capacity"]
                if row["reference_capacity"] != 0
                else 0
            ),
            axis=1,
        )
        capacity_df["optimal_capacity"] = capacity_df.apply(
            lambda row: (
                row["optimal_capacity"] / row["reference_capacity"]
                if row["reference_capacity"] != 0
                else 0
            ),
            axis=1,
        )
        capacity_df["reference_capacity"] = capacity_df.apply(
            lambda row: 1.0 if row["reference_capacity"] != 0 else 0.0, axis=1
        )

    # Set up the plot
    plt.figure(figsize=(10, 6))

    # Plot in reverse order: reference_capacity, network_capacity, optimal_capacity
    capacity_df[["reference_capacity", "network_capacity", "optimal_capacity"]].fillna(
        0
    ).plot(kind="bar", stacked=False, color=colors[:3], zorder=3)

    plt.title(
        f"{'Normalized ' if normalize else ''}Capacity Comparison for {carrier.capitalize()} per Region"
    )
    plt.ylabel(f"Capacity {'(Ratio to Reference)' if normalize else '(MW)'}")
    plt.xlabel("Region")
    plt.xticks(ticks=range(len(capacity_df)), labels=capacity_df["region"])

    # Remove plot box (spines)
    ax = plt.gca()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)

    # Add horizontal grid lines
    plt.grid(True, axis="y", zorder=0)
    plt.tight_layout()

    # Save the plot
    plt.savefig(output_path)
    plt.close()


def plot_stack_carrier_capacity_comparison(
    installed_capacity_df, optimal_capacity_df, output_path, stack_percent=False
):
    """
    Plot a single stacked bar graph comparing network, optimal, and reference capacity mix for each region.
    Each region will have 3 bars side by side: one for reference capacity, one for network capacity, and one for optimal capacity.
    The bars will be stacked with different carriers' capacities.
    """
    if installed_capacity_df.empty or optimal_capacity_df.empty:
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.text(
            0.5,
            0.5,
            "No Capacity Mix Data Available",
            ha="center",
            va="center",
            fontsize=12,
        )
        ax.set_axis_off()
        plt.savefig(output_path)
        plt.close()
        return

    # Merge the dataframes on region and carrier
    merged_df = pd.merge(
        installed_capacity_df[["carrier", "region", "network_capacity"]],
        optimal_capacity_df[["carrier", "region", "network_capacity"]],
        on=["carrier", "region"],
        suffixes=("_network", "_optimal"),
    )

    merged_df = pd.merge(
        merged_df,
        installed_capacity_df[["carrier", "region", "reference_capacity"]],
        on=["carrier", "region"],
        how="left",
    )

    # Rename columns for clarity
    merged_df = merged_df.rename(
        columns={
            "network_capacity_network": "network_capacity",
            "network_capacity_optimal": "optimal_capacity",
        }
    )

    if stack_percent:
        # Normalize per region's total capacity mix
        merged_df["network_capacity"] = merged_df.groupby("region")[
            "network_capacity"
        ].transform(lambda x: x * 100 / x.sum())
        merged_df["optimal_capacity"] = merged_df.groupby("region")[
            "optimal_capacity"
        ].transform(lambda x: x * 100 / x.sum())
        merged_df["reference_capacity"] = merged_df.groupby("region")[
            "reference_capacity"
        ].transform(lambda x: x * 100 / x.sum())

    # Set up the plot
    fig, ax = plt.subplots(figsize=(12, 8))

    # Create a pivot table for each type of capacity
    network_pivot = merged_df.pivot_table(
        index="region", columns="carrier", values="network_capacity", aggfunc="sum"
    )
    optimal_pivot = merged_df.pivot_table(
        index="region", columns="carrier", values="optimal_capacity", aggfunc="sum"
    )
    reference_pivot = merged_df.pivot_table(
        index="region", columns="carrier", values="reference_capacity", aggfunc="sum"
    )

    # Plot the stacked bars for each capacity type (reference, network, optimal)
    width = 0.25  # Width of the bars
    x = np.arange(len(network_pivot))  # X positions for the regions

    # Stacked bar plots without duplicate legends
    optimal_pivot.fillna(0).plot(
        kind="bar", stacked=True, ax=ax, width=width, position=1, color=colors, zorder=3
    )
    network_pivot.fillna(0).plot(
        kind="bar", stacked=True, ax=ax, width=width, position=2, color=colors, zorder=3
    )
    reference_pivot.fillna(0).plot(
        kind="bar", stacked=True, ax=ax, width=width, position=3, color=colors, zorder=3
    )

    # Get legend handles from just one of the plots to avoid duplicates
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(
        handles[: len(reference_pivot.columns)],
        labels[: len(reference_pivot.columns)],
        title="Carriers",
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        ncol=1,
        frameon=False,
    )

    # Create formatted x-axis labels (each region appears 3 times)
    xtick_labels = []
    xtick_positions = []
    for i, region in enumerate(network_pivot.index):
        xtick_labels.extend(
            [f"{region}, REFR", f"{region}, INST", f"{region}, OPTI", ""]
        )
        xtick_positions.extend(
            [
                x[i] + -2.5 * width,
                x[i] + -1.5 * width,
                x[i] + -0.5 * width,
                x[i] + 0.5 * width,
            ]
        )

    # Customize the plot
    ax.set_title("Capacity Mix Comparison per Region")
    ax.set_xlabel("Region")
    ax.set_ylabel(f"Capacity Mix {'(%)' if stack_percent else '(MW)'}")
    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(xtick_labels)

    # Add grid lines and clean up the plot
    ax.grid(True, axis="y", zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)

    # Adjust the layout for better spacing
    plt.tight_layout()

    # Save the plot
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def plot_capacity_grid_comparison(
    installed_capacity_df,
    optimal_capacity_df,
    output_path,
    normalize=False,
    share_y=False,
):
    """
    Create a subplot grid where:
    - Rows = regions (unique)
    - Columns = carriers
    - Each subplot shows bar plots: [Reference, Network, Optimal] for that region-carrier combo
    """
    if installed_capacity_df.empty or optimal_capacity_df.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(
            0.5,
            0.5,
            "No Capacity Grid Data Available",
            ha="center",
            va="center",
            fontsize=12,
        )
        ax.set_axis_off()
        plt.savefig(output_path)
        plt.close()
        return

    # Validate region uniqueness
    if installed_capacity_df.duplicated(subset=["region", "carrier"]).any():
        raise ValueError(
            "Found duplicate (region, carrier) pairs in installed_capacity_df."
        )

    # Rename installed capacity columns to prevent conflict
    installed = installed_capacity_df.rename(
        columns={
            "network_capacity": "network_capacity",
            "reference_capacity": "reference_capacity",
        }
    )
    optimal = optimal_capacity_df.rename(
        columns={"network_capacity": "optimal_capacity"}
    )

    # Get full set of region-carrier combinations
    all_regions = sorted(set(installed["region"]).union(set(optimal["region"])))
    all_carriers = sorted(set(installed["carrier"]).union(set(optimal["carrier"])))
    full_index = pd.MultiIndex.from_product(
        [all_regions, all_carriers], names=["region", "carrier"]
    )
    full_df = pd.DataFrame(index=full_index).reset_index()

    # Merge all sources into the complete grid
    merged = full_df.merge(
        installed[["region", "carrier", "reference_capacity", "network_capacity"]],
        on=["region", "carrier"],
        how="left",
    )
    merged = merged.merge(
        optimal[["region", "carrier", "optimal_capacity"]],
        on=["region", "carrier"],
        how="left",
    )

    # Fill missing values with 0s for plotting (or np.nan to leave empty bars)
    merged.fillna(0, inplace=True)

    # Plotting grid setup
    n_rows, n_cols = len(all_regions), len(all_carriers)
    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(4 * n_cols, 3.5 * n_rows), sharey=share_y
    )

    # Handle axis shape if 1D
    if n_rows == 1:
        axes = np.expand_dims(axes, axis=0)
    if n_cols == 1:
        axes = np.expand_dims(axes, axis=1)

    for i, region in enumerate(all_regions):
        for j, carrier in enumerate(all_carriers):
            ax = axes[i][j]
            row = merged[
                (merged["region"] == region) & (merged["carrier"] == carrier)
            ].iloc[0]

            values = [
                row["reference_capacity"],
                row["network_capacity"],
                row["optimal_capacity"],
            ]

            if normalize and row["reference_capacity"] != 0:
                values = [v / row["reference_capacity"] for v in values]

            # Draw bars
            ax.bar(["REFR", "INST", "OPTI"], values, color=colors[:3], zorder=3)

            # Titles and labels
            if i == 0:
                ax.set_title(carrier.capitalize(), fontsize=10)
            if j == 0:
                ax.set_ylabel(region, fontsize=10)

            ax.set_xticks([0, 1, 2])
            ax.set_xticklabels(["REFR", "INST", "OPTI"])
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_visible(False)
            ax.grid(True, axis="y", zorder=0)

    plt.suptitle(
        f"{'Normalized ' if normalize else ''}Capacity Comparison per Region and Carrier (in MW)",
        fontsize=14,
    )
    plt.tight_layout(rect=[0, 0.03, 1, 0.96])
    plt.savefig(output_path)
    plt.close()


def get_voltage_color(
    voltage: float, line_voltages: list[float], voltage_colors: list[str]
) -> str:
    """
    Get the line colors corresponding to a voltage level based on defined thresholds.
    """
    for threshold, color in zip(line_voltages, voltage_colors):
        if voltage <= threshold:
            return color
    return "#000000"


def plot_generation_comparison(
    generation_df,
    output_path,
):
    """
    Plot reference and modeled annual electricity generation by carrier.
    """
    if generation_df.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(
            0.5,
            0.5,
            "No Electricity Generation Data Available",
            ha="center",
            va="center",
            fontsize=12,
        )
        ax.set_axis_off()
        fig.savefig(
            output_path,
            bbox_inches="tight",
        )
        plt.close(fig)
        return

    regions = sorted(generation_df["region"].unique())

    fig, axes = plt.subplots(
        nrows=len(regions),
        ncols=1,
        figsize=(
            12,
            max(6, 5 * len(regions)),
        ),
        squeeze=False,
    )

    for ax, region in zip(
        axes.flat,
        regions,
    ):
        region_df = generation_df[generation_df["region"] == region].copy()

        region_df = (
            region_df[
                [
                    "carrier",
                    "reference_generation",
                    "network_generation",
                ]
            ]
            .set_index("carrier")
            .sort_index()
        )

        region_df.fillna(0).plot(
            kind="bar",
            stacked=False,
            ax=ax,
            color=colors[:2],
            zorder=3,
        )

        ax.set_title(f"Electricity Generation Comparison — {region}")
        ax.set_xlabel("Carrier")
        ax.set_ylabel("Generation (GWh)")
        ax.tick_params(
            axis="x",
            rotation=45,
        )

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.grid(
            True,
            axis="y",
            zorder=0,
        )

    fig.tight_layout()
    fig.savefig(
        output_path,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_grid_network(
    input: dict[str, str],
    output: str,
    line_voltages: list[float],
    voltage_colors: list[str],
    plot_circuits: bool,
) -> None:
    """
    Plot the grid network with lines colored by voltage levels and substations highlighted.

    Parameters:
    -----------
    input: dict[str, str]
        A dictionary containing paths to input files, specifically:
        - "osm_lines": Path to the GeoJSON file containing line geometries and attributes.
        - "osm_substations": Path to the GeoJSON file containing substation geometries.
    output: str
        A dictionary containing paths to output files, specifically:
        - "plot_grid_network": Path where the generated grid network plot will be saved (e.g., as a PNG file).
    line_voltages: list[float]
        A list of voltage thresholds used to categorize lines into different voltage levels for coloring.
    voltage_colors: list[str]
        A list of colors corresponding to each voltage level in line_voltages.
    plot_circuits: bool
        Whether to display the number of circuits on the plot.
    """
    df_lines = gpd.read_file(input["osm_lines"])
    df_substations = gpd.read_file(input["osm_substations"])

    df_lines["color"] = df_lines["voltage"].apply(
        lambda x: get_voltage_color(x / 1000, line_voltages, voltage_colors)
    )

    osm_tiles = cimgt.OSM()

    fig, ax = plt.subplots(figsize=(12, 8), subplot_kw={"projection": osm_tiles.crs})

    minx, miny, maxx, maxy = df_lines.total_bounds
    ax.set_extent([minx, maxx, miny, maxy], crs=ccrs.PlateCarree())
    ax.add_image(osm_tiles, 8)

    # loop by color group so each line is plotted with its corresponding color
    for color, group in df_lines.groupby("color"):
        ax.add_geometries(
            group.geometry,
            crs=ccrs.PlateCarree(),
            edgecolor=color,
            facecolor="none",
            linewidth=1,
            zorder=2,
        )

    # circuit values on the plot if available, positioned at the midpoint of each line
    if plot_circuits and "circuits" in df_lines.columns:
        for _, row in df_lines.iterrows():
            if pd.notna(row["circuits"]):
                midpoint = row.geometry.interpolate(0.5, normalized=True)
                ax.text(
                    midpoint.x,
                    midpoint.y,
                    str(int(row["circuits"])),
                    fontsize=6,
                    color="black",
                    ha="center",
                    va="center",
                    fontweight="bold",
                    zorder=4,
                    transform=ccrs.PlateCarree(),
                    bbox=dict(
                        boxstyle="round, pad=0.1",
                        facecolor="white",
                        edgecolor="none",
                        alpha=0.5,
                    ),
                )

    ax.scatter(
        df_substations.geometry.x,
        df_substations.geometry.y,
        color="red",
        s=5,
        zorder=3,
        transform=ccrs.PlateCarree(),
    )

    ax.set_title("Grid Network as Presented in OSM Data", fontsize=14)
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches="tight")
    plt.close()


def compute_line_lengths_by_voltage(
    input: dict[str, str], output: dict[str, str]
) -> None:
    """
    Compute total line lengths by voltage level and save to CSV.

    Parameters:
    -----------
    input: dict[str, str]
        A dictionary containing paths to input files, specifically:
        - "osm_lines": Path to the GeoJSON file containing line geometries and attributes.
    output: dict[str, str]
        A dictionary containing paths to output files, specifically:
        - "line_length_by_voltage": Path where the computed line lengths by voltage will be saved as a CSV file.
    """
    df_lines = gpd.read_file(input["osm_lines"])

    df_lines = df_lines.to_crs(epsg=3857)

    df_lines["length_km"] = df_lines.geometry.length / 1000
    length_by_voltage = (
        df_lines.groupby("voltage")["length_km"].sum().round(2).reset_index()
    )
    length_by_voltage.to_csv(output["line_length_by_voltage"], index=False)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("visualize_data")

    configure_logging(snakemake)

    # Load comparison data
    demand_comparison = read_csv_nafix(snakemake.input["demand_comparison"])
    installed_capacity_comparison = read_csv_nafix(
        snakemake.input["installed_capacity_comparison"]
    )
    optimal_capacity_comparison = read_csv_nafix(
        snakemake.input["optimal_capacity_comparison"]
    )
    electricity_generation_comparison = read_csv_nafix(
        snakemake.input["electricity_generation_comparison"]
    )

    plot_demand_comparison(demand_comparison, snakemake.output["plot_demand"])
    plot_generation_comparison(
        electricity_generation_comparison,
        snakemake.output["plot_electricity_generation"],
    )

    # Compares capacities per region one carrier at a time
    # Select carrier value: ['solar' 'onwind' 'offwind-dc' 'coal' 'CCGT' 'ror' 'biomass' 'oil' 'geothermal']
    plot_carrier_capacity_comparison(
        installed_capacity_comparison,
        optimal_capacity_comparison,
        snakemake.output["plot_installed_capacity"],
        normalize=True,
    )

    # Compares network capacity mix per region with respect to reference with a stacked bargraph
    plot_stack_carrier_capacity_comparison(
        installed_capacity_comparison,
        optimal_capacity_comparison,
        snakemake.output["plot_capacity_mix"],
        stack_percent=False,
    )

    plot_capacity_grid_comparison(
        installed_capacity_comparison,
        optimal_capacity_comparison,
        snakemake.output["plot_capacity_grid"],
        normalize=False,
        share_y=False,
    )

    plot_grid_network(
        snakemake.input,
        snakemake.output["plot_grid_network"],
        line_voltages=snakemake.params["line_voltages"],
        voltage_colors=snakemake.params["voltage_colors"],
        plot_circuits=snakemake.params["plot_circuits"],
    )

    compute_line_lengths_by_voltage(snakemake.input, snakemake.output)
