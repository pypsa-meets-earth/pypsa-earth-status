# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Aggregate OSM transmission topology to solved-network bus regions.

OSM line endpoints are identified through the post-build OSM bus0/bus1 topology.
The corresponding OSM substations are spatially assigned to the validation
bus regions derived from the solved PyPSA network.
"""

import logging
import os

import geopandas as gpd
import pandas as pd
from helpers import configure_logging

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "bus0",
    "bus1",
    "osm_line_count",
    "osm_ac_line_count",
    "osm_dc_line_count",
    "osm_circuits",
    "osm_ac_circuits",
    "osm_dc_circuits",
    "osm_voltages_kv",
    "osm_ac_voltages_kv",
    "osm_dc_voltages_kv",
]


def normalize_bus_pairs(df):
    """Normalize region pairs so transmission corridors are undirected."""
    df = df.copy()

    bus0 = df["bus0"].astype(str)
    bus1 = df["bus1"].astype(str)

    swap = bus0 > bus1

    df["bus0"] = bus0.where(~swap, bus1)
    df["bus1"] = bus1.where(~swap, bus0)

    return df


def assign_osm_buses_to_regions(substations, bus_regions):
    """Assign each OSM network bus to one solved-network bus region."""
    if "bus_id" not in substations.columns:
        raise ValueError("OSM substations must contain a 'bus_id' column.")

    required_region_columns = {
        "region_id",
        "geometry",
    }

    missing = required_region_columns - set(bus_regions.columns)

    if missing:
        raise ValueError(
            "Bus regions are missing required columns: " + ", ".join(sorted(missing))
        )

    substations = substations.copy()
    bus_regions = bus_regions.copy()

    if substations.crs is None:
        raise ValueError("OSM substations have no CRS.")

    if bus_regions.crs is None:
        raise ValueError("Bus regions have no CRS.")

    substations = substations.to_crs(bus_regions.crs)

    # Cleaned OSM substations are normally points. Use a representative
    # point as a safe fallback for polygon geometries.
    substations["geometry"] = substations.geometry.apply(
        lambda geometry: (
            geometry
            if geometry is None or geometry.is_empty or geometry.geom_type == "Point"
            else geometry.representative_point()
        )
    )

    joined = gpd.sjoin(
        substations[["bus_id", "geometry"]],
        bus_regions[["region_id", "geometry"]],
        how="left",
        predicate="intersects",
    )

    # A point exactly on a Voronoi boundary may match more than one region.
    # Keep one deterministic assignment.
    joined["bus_id"] = joined["bus_id"].astype(str)
    joined["region_id"] = joined["region_id"].astype("string")

    joined = (
        joined.dropna(subset=["region_id"])
        .sort_values(["bus_id", "region_id"])
        .drop_duplicates(subset=["bus_id"], keep="first")
    )

    mapping = joined.set_index("bus_id")["region_id"].astype(str)

    return mapping


def parse_numeric(series):
    """Convert an OSM attribute to numeric values."""
    return pd.to_numeric(
        series,
        errors="coerce",
    )


def join_voltages(values):
    """Join unique non-null voltage levels."""
    values = sorted({float(value) for value in values.dropna()})

    return ",".join(f"{value:g}" for value in values)


def sum_with_nan(values):
    """Sum values while preserving NaN when no value is known."""
    return values.sum(min_count=1)


def build_osm_corridors(
    osm_lines,
    substations,
    bus_regions,
):
    """Aggregate OSM network lines to undirected bus-region corridors."""
    required_line_columns = {
        "bus0",
        "bus1",
    }

    missing = required_line_columns - set(osm_lines.columns)

    if missing:
        raise ValueError(
            "OSM lines are missing required topology columns: "
            + ", ".join(sorted(missing))
        )

    bus_to_region = assign_osm_buses_to_regions(
        substations,
        bus_regions,
    )

    lines = osm_lines.copy()

    lines["osm_bus0"] = lines["bus0"].astype(str)
    lines["osm_bus1"] = lines["bus1"].astype(str)

    lines["bus0"] = lines["osm_bus0"].map(bus_to_region)
    lines["bus1"] = lines["osm_bus1"].map(bus_to_region)

    missing_endpoints = lines["bus0"].isna() | lines["bus1"].isna()

    if missing_endpoints.any():
        logger.warning(
            "Dropping %d OSM lines whose endpoints could not be "
            "assigned to solved-network bus regions.",
            missing_endpoints.sum(),
        )

    lines = lines.loc[~missing_endpoints].copy()

    # Lines entirely contained within one validation region are not
    # inter-region transmission corridors.
    lines = lines.loc[lines["bus0"] != lines["bus1"]].copy()

    if lines.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    lines = normalize_bus_pairs(lines)

    if "line_id" in lines.columns:
        lines["osm_line_id"] = lines["line_id"].astype(str)
    else:
        lines["osm_line_id"] = lines.index.astype(str)

    if "circuits" in lines.columns:
        lines["osm_circuits"] = parse_numeric(lines["circuits"])
    else:
        lines["osm_circuits"] = pd.NA

    if "voltage" in lines.columns:
        lines["osm_voltage_kv"] = parse_numeric(lines["voltage"]) / 1000.0
    else:
        lines["osm_voltage_kv"] = pd.NA

    if "dc" in lines.columns:
        dc_values = lines["dc"].fillna(False).astype(str).str.strip().str.lower()

        lines["is_dc"] = dc_values.isin(
            {
                "true",
                "1",
                "yes",
                "dc",
            }
        )
    else:
        lines["is_dc"] = False

    lines["ac_line_id"] = lines["osm_line_id"].where(~lines["is_dc"])

    lines["dc_line_id"] = lines["osm_line_id"].where(lines["is_dc"])

    lines["ac_circuits"] = lines["osm_circuits"].where(~lines["is_dc"])

    lines["dc_circuits"] = lines["osm_circuits"].where(lines["is_dc"])

    lines["ac_voltage_kv"] = lines["osm_voltage_kv"].where(~lines["is_dc"])

    lines["dc_voltage_kv"] = lines["osm_voltage_kv"].where(lines["is_dc"])

    corridors = lines.groupby(
        ["bus0", "bus1"],
        as_index=False,
    ).agg(
        osm_line_count=(
            "osm_line_id",
            "nunique",
        ),
        osm_ac_line_count=(
            "ac_line_id",
            "nunique",
        ),
        osm_dc_line_count=(
            "dc_line_id",
            "nunique",
        ),
        osm_circuits=(
            "osm_circuits",
            sum_with_nan,
        ),
        osm_ac_circuits=(
            "ac_circuits",
            sum_with_nan,
        ),
        osm_dc_circuits=(
            "dc_circuits",
            sum_with_nan,
        ),
        osm_voltages_kv=(
            "osm_voltage_kv",
            join_voltages,
        ),
        osm_ac_voltages_kv=(
            "ac_voltage_kv",
            join_voltages,
        ),
        osm_dc_voltages_kv=(
            "dc_voltage_kv",
            join_voltages,
        ),
    )

    return corridors[OUTPUT_COLUMNS]


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_osm_transmission_statistics")

        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    osm_lines = gpd.read_file(snakemake.input["osm_lines"])

    substations = gpd.read_file(snakemake.input["osm_buses"])

    bus_regions = gpd.read_file(snakemake.input["bus_regions"])

    corridors = build_osm_corridors(
        osm_lines,
        substations,
        bus_regions,
    )

    os.makedirs(
        os.path.dirname(snakemake.output["corridors"]),
        exist_ok=True,
    )

    corridors.to_csv(
        snakemake.output["corridors"],
        index=False,
    )

    logger.info(
        "Built %d OSM transmission corridors from %d OSM network lines.",
        len(corridors),
        len(osm_lines),
    )
