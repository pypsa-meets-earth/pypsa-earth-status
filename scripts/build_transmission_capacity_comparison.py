# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compare OSM-derived and evaluated PyPSA AC corridor capacities."""

import logging
import os

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
from helpers import configure_logging

logger = logging.getLogger(__name__)


def normalize_id(value):
    """Normalize bus identifiers read from GeoJSON."""
    if pd.isna(value):
        return None

    try:
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass

    return str(value)


def parse_bool(value):
    """Parse common boolean representations."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)

    if pd.isna(value):
        return False

    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
    }


def normalize_pair(bus0, bus1):
    """Return an undirected corridor key."""
    return tuple(sorted((str(bus0), str(bus1))))


def get_lines_config(network):
    """Return the PyPSA-Earth line configuration stored in network metadata."""
    if not isinstance(network.meta, dict):
        return {}

    lines = network.meta.get("lines")

    if isinstance(lines, dict):
        return lines

    config = network.meta.get("config")

    if isinstance(config, dict):
        lines = config.get("lines")

        if isinstance(lines, dict):
            return lines

    return {}


def get_linetype(
    voltage,
    country,
    mappings,
    use_country_specific_types,
):
    """Mirror PyPSA-Earth's closest-voltage line-type selection."""
    if pd.isna(voltage) or "default" not in mappings:
        return None

    mapping_name = (
        country if (use_country_specific_types and country in mappings) else "default"
    )

    mapping = mappings.get(mapping_name, {})

    if not mapping:
        return None

    voltage_key = min(
        mapping,
        key=lambda candidate: abs(float(candidate) - float(voltage)),
    )

    return mapping[voltage_key]


def assign_osm_buses_to_regions(
    osm_buses,
    regions,
):
    """Assign OSM buses to evaluated-network transmission regions."""
    osm_buses = osm_buses.copy()
    regions = regions.copy()

    osm_buses["bus_id"] = osm_buses["bus_id"].map(normalize_id)

    regions["region_id"] = regions["region_id"].astype(str)

    osm_buses = osm_buses.to_crs(regions.crs)

    columns = [
        "bus_id",
        "geometry",
    ]

    if "country" in osm_buses.columns:
        columns.insert(1, "country")

    joined = gpd.sjoin(
        osm_buses[columns],
        regions[
            [
                "region_id",
                "geometry",
            ]
        ],
        how="left",
        predicate="intersects",
    )

    joined = joined.sort_values(
        [
            "bus_id",
            "region_id",
        ]
    ).drop_duplicates(
        subset="bus_id",
        keep="first",
    )

    return joined


def build_osm_capacity_reference(
    network,
    osm_lines,
    osm_buses,
    regions,
):
    """Build OSM-derived AC capacity at evaluated-network resolution."""
    lines_config = get_lines_config(network)

    mappings = lines_config.get(
        "ac_types",
        {},
    )

    use_country_specific_types = lines_config.get(
        "use_country_specific_types",
        False,
    )

    assignments = assign_osm_buses_to_regions(
        osm_buses,
        regions,
    )

    region_map = (
        assignments.dropna(subset=["region_id"])
        .set_index("bus_id")["region_id"]
        .astype(str)
        .to_dict()
    )

    if "country" in assignments.columns:
        country_map = (
            assignments.dropna(subset=["country"])
            .set_index("bus_id")["country"]
            .astype(str)
            .to_dict()
        )
    else:
        country_map = {}

    lines = osm_lines.copy()

    lines["bus0_id"] = lines["bus0"].map(normalize_id)

    lines["bus1_id"] = lines["bus1"].map(normalize_id)

    lines["region0"] = lines["bus0_id"].map(region_map)

    lines["region1"] = lines["bus1_id"].map(region_map)

    lines["country0"] = lines["bus0_id"].map(country_map)

    lines["country1"] = lines["bus1_id"].map(country_map)

    # Keep bus0 country for PyPSA-Earth line-type selection.
    lines["country"] = lines["country0"]

    if "dc" in lines.columns:
        lines["is_dc"] = lines["dc"].map(parse_bool)
    else:
        lines["is_dc"] = False

    lines["voltage_kv"] = (
        pd.to_numeric(
            lines["voltage"],
            errors="coerce",
        )
        / 1000.0
    )

    lines["circuits"] = pd.to_numeric(
        lines["circuits"],
        errors="coerce",
    )

    lines = lines.loc[
        (~lines["is_dc"])
        & lines["region0"].notna()
        & lines["region1"].notna()
        & (lines["region0"] != lines["region1"])
    ].copy()

    lines["line_type"] = lines.apply(
        lambda row: get_linetype(
            row["voltage_kv"],
            row["country"],
            mappings,
            use_country_specific_types,
        ),
        axis=1,
    )

    lines["i_nom"] = lines["line_type"].map(network.line_types["i_nom"])

    lines["capacity_mva"] = (
        np.sqrt(3.0) * lines["i_nom"] * lines["voltage_kv"] * lines["circuits"]
    )

    pairs = lines.apply(
        lambda row: normalize_pair(
            row["region0"],
            row["region1"],
        ),
        axis=1,
    )

    lines["bus0"] = [pair[0] for pair in pairs]

    lines["bus1"] = [pair[1] for pair in pairs]

    records = []

    for (bus0, bus1), group in lines.groupby(["bus0", "bus1"]):
        comparable = group["capacity_mva"].notna()

        records.append(
            {
                "bus0": bus0,
                "bus1": bus1,
                "osm_physical_ac_lines": len(group),
                "osm_ac_circuits": group["circuits"].sum(),
                "osm_capacity_complete": bool(comparable.all()),
                "osm_ac_capacity_mva": (
                    group["capacity_mva"].sum() if comparable.all() else np.nan
                ),
            }
        )

    build_osm_capacity_reference.lines = lines.copy()

    return pd.DataFrame(records)


def build_voltage_representation(
    osm_lines,
    comparison,
):
    """Summarize OSM AC capacity by area and voltage class."""
    columns = [
        "bus0",
        "bus1",
        "pypsa_ac_branch_count",
    ]

    model_corridors = comparison[columns].copy()

    model_corridors["pypsa_ac_branch_count"] = pd.to_numeric(
        model_corridors["pypsa_ac_branch_count"],
        errors="coerce",
    ).fillna(0)

    model_corridors["represented"] = model_corridors["pypsa_ac_branch_count"] > 0

    lines = osm_lines.merge(
        model_corridors[
            [
                "bus0",
                "bus1",
                "represented",
            ]
        ],
        on=[
            "bus0",
            "bus1",
        ],
        how="left",
        validate="many_to_one",
    )

    lines["represented"] = lines["represented"].fillna(False).astype(bool)

    def classify_area(row):
        country0 = row["country0"]
        country1 = row["country1"]

        has_country0 = pd.notna(country0)
        has_country1 = pd.notna(country1)

        if has_country0 and has_country1:
            if str(country0) == str(country1):
                return str(country0)

            return "Cross-border"

        if has_country0:
            return str(country0)

        if has_country1:
            return str(country1)

        return "Unknown"

    lines["area"] = lines.apply(
        classify_area,
        axis=1,
    )

    lines = lines.loc[
        lines["voltage_kv"].notna()
        & lines["capacity_mva"].notna()
        & (lines["capacity_mva"] > 0)
    ].copy()

    if lines.empty:
        return pd.DataFrame(
            columns=[
                "area",
                "voltage_kv",
                "represented_capacity_mva",
                "not_represented_capacity_mva",
                "total_capacity_mva",
                "represented_share_total_pct",
                "not_represented_share_total_pct",
                "class_share_total_pct",
                "coverage_pct",
            ]
        )

    lines["representation_status"] = np.where(
        lines["represented"],
        "represented",
        "not_represented",
    )

    summary = (
        lines.groupby(
            [
                "area",
                "voltage_kv",
                "representation_status",
            ]
        )["capacity_mva"]
        .sum()
        .unstack(fill_value=0.0)
    )

    for column in [
        "represented",
        "not_represented",
    ]:
        if column not in summary.columns:
            summary[column] = 0.0

    summary = summary.rename(
        columns={
            "represented": ("represented_capacity_mva"),
            "not_represented": ("not_represented_capacity_mva"),
        }
    )

    summary["total_capacity_mva"] = (
        summary["represented_capacity_mva"] + summary["not_represented_capacity_mva"]
    )

    summary = summary.reset_index()

    summary["area_total_capacity_mva"] = summary.groupby("area")[
        "total_capacity_mva"
    ].transform("sum")

    summary["represented_share_total_pct"] = (
        100.0 * summary["represented_capacity_mva"] / summary["area_total_capacity_mva"]
    )

    summary["not_represented_share_total_pct"] = (
        100.0
        * summary["not_represented_capacity_mva"]
        / summary["area_total_capacity_mva"]
    )

    summary["class_share_total_pct"] = (
        100.0 * summary["total_capacity_mva"] / summary["area_total_capacity_mva"]
    )

    summary["coverage_pct"] = (
        100.0 * summary["represented_capacity_mva"] / summary["total_capacity_mva"]
    )

    return summary.sort_values(
        [
            "area",
            "voltage_kv",
        ]
    ).reset_index(drop=True)


def compare_capacity(
    comparison,
    osm_capacity,
):
    """Compare AC capacity on topologically matched transmission corridors."""
    matched = comparison.loc[comparison["status"] == "matched"].copy()

    columns = [
        "bus0",
        "bus1",
        "pypsa_ac_nominal_capacity_mva",
        "pypsa_ac_optimized_capacity_mva",
    ]

    matched = matched[columns]

    matched["bus0"] = matched["bus0"].astype(str)
    matched["bus1"] = matched["bus1"].astype(str)

    result = matched.merge(
        osm_capacity,
        on=[
            "bus0",
            "bus1",
        ],
        how="left",
    )

    osm_value = pd.to_numeric(
        result["osm_ac_capacity_mva"],
        errors="coerce",
    )

    nominal = pd.to_numeric(
        result["pypsa_ac_nominal_capacity_mva"],
        errors="coerce",
    )

    optimized = pd.to_numeric(
        result["pypsa_ac_optimized_capacity_mva"],
        errors="coerce",
    )

    has_osm_ac = osm_value.gt(0)
    has_pypsa_ac = optimized.gt(0)

    result["capacity_status"] = "not_comparable"

    result.loc[
        has_osm_ac & has_pypsa_ac,
        "capacity_status",
    ] = "comparable"

    result.loc[
        has_osm_ac & ~has_pypsa_ac,
        "capacity_status",
    ] = "osm_ac_only"

    result.loc[
        ~has_osm_ac & has_pypsa_ac,
        "capacity_status",
    ] = "pypsa_ac_only"

    comparable = result["capacity_status"] == "comparable"

    result["nominal_capacity_ratio"] = np.nan
    result["optimized_capacity_ratio"] = np.nan

    result.loc[
        comparable,
        "nominal_capacity_ratio",
    ] = (
        nominal.loc[comparable] / osm_value.loc[comparable]
    )

    result.loc[
        comparable,
        "optimized_capacity_ratio",
    ] = (
        optimized.loc[comparable] / osm_value.loc[comparable]
    )

    result["capacity_expansion_mva"] = optimized - nominal

    return result


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_transmission_capacity_comparison")

        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    network = pypsa.Network(snakemake.input["network_path"])

    osm_lines = gpd.read_file(snakemake.input["osm_lines"])

    osm_buses = gpd.read_file(snakemake.input["osm_buses"])

    regions = gpd.read_file(snakemake.input["bus_regions"])

    comparison = pd.read_csv(
        snakemake.input["comparison"],
        dtype={
            "bus0": str,
            "bus1": str,
        },
    )

    osm_capacity = build_osm_capacity_reference(
        network,
        osm_lines,
        osm_buses,
        regions,
    )

    osm_capacity_lines = build_osm_capacity_reference.lines

    voltage_representation = build_voltage_representation(
        osm_capacity_lines,
        comparison,
    )

    result = compare_capacity(
        comparison,
        osm_capacity,
    )

    result.to_csv(
        snakemake.output["capacity_comparison"],
        index=False,
    )

    voltage_representation.to_csv(
        snakemake.output["voltage_representation"],
        index=False,
    )

    logger.info(
        "Built voltage representation for %s OSM AC voltage classes; "
        "%.2f%% of total OSM-derived inter-region AC capacity is "
        "represented by PyPSA AC corridors.",
        len(voltage_representation),
        (
            voltage_representation["represented_capacity_mva"].sum()
            / voltage_representation["total_capacity_mva"].sum()
            * 100.0
            if not voltage_representation.empty
            else 0.0
        ),
    )

    logger.info(
        "Built capacity comparison for %s matched corridors, "
        "%s with comparable AC capacity data.",
        len(result),
        result["optimized_capacity_ratio"].notna().sum(),
    )
