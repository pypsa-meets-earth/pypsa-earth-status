# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Compare PyPSA and OSM transmission topology at bus-region level.
"""

import logging
import os

import numpy as np
import pandas as pd
from helpers import configure_logging

logger = logging.getLogger(__name__)


def parse_voltage_set(value):
    """Parse a comma-separated voltage list."""
    if pd.isna(value):
        return set()

    values = set()

    for item in str(value).split(","):
        item = item.strip()

        if not item:
            continue

        try:
            value = float(item)
        except ValueError:
            continue

        if value > 0:
            values.add(value)

    return values


def join_voltage_strings(values):
    """Join voltage strings into one sorted unique list."""
    voltages = set()

    for value in values:
        voltages.update(parse_voltage_set(value))

    return ",".join(f"{voltage:g}" for voltage in sorted(voltages))


def aggregate_pypsa_corridors(corridors):
    """Reduce PyPSA transmission data to one record per spatial corridor."""
    pairs = corridors[["bus0", "bus1"]].drop_duplicates().copy()

    component_definitions = {
        "AC line": {
            "prefix": "pypsa_ac",
            "unit": "mva",
        },
        "DC link": {
            "prefix": "pypsa_dc",
            "unit": "mw",
        },
    }

    for branch_type, definition in component_definitions.items():
        subset = corridors.loc[corridors["branch_type"] == branch_type].copy()

        prefix = definition["prefix"]
        unit = definition["unit"]

        voltage_column = f"{prefix}_voltages_kv"

        if subset.empty:
            pairs[f"{prefix}_branch_count"] = 0

            pairs[f"{prefix}_nominal_capacity_{unit}"] = 0.0

            pairs[f"{prefix}_optimized_capacity_{unit}"] = 0.0

            pairs[f"{prefix}_capacity_expansion_{unit}"] = 0.0

            pairs[voltage_column] = ""

            continue

        subset = (
            subset.groupby(
                ["bus0", "bus1"],
                as_index=False,
            )
            .agg(
                branch_count=(
                    "branch_count",
                    "sum",
                ),
                nominal_capacity=(
                    "nominal_capacity",
                    "sum",
                ),
                optimized_capacity=(
                    "optimized_capacity",
                    "sum",
                ),
                capacity_expansion=(
                    "capacity_expansion",
                    "sum",
                ),
                voltages_kv=(
                    "voltages_kv",
                    join_voltage_strings,
                ),
            )
            .rename(
                columns={
                    "branch_count": (f"{prefix}_branch_count"),
                    "nominal_capacity": (f"{prefix}_nominal_capacity_{unit}"),
                    "optimized_capacity": (f"{prefix}_optimized_capacity_{unit}"),
                    "capacity_expansion": (f"{prefix}_capacity_expansion_{unit}"),
                    "voltages_kv": voltage_column,
                }
            )
        )

        pairs = pairs.merge(
            subset,
            on=["bus0", "bus1"],
            how="left",
        )

    numeric_columns = [
        column
        for column in pairs.columns
        if (
            column.endswith("_branch_count")
            or column.endswith("_mva")
            or column.endswith("_mw")
        )
    ]

    pairs[numeric_columns] = pairs[numeric_columns].fillna(0)

    count_columns = [
        column for column in numeric_columns if column.endswith("_branch_count")
    ]

    pairs[count_columns] = pairs[count_columns].astype(int)

    for column in [
        "pypsa_ac_voltages_kv",
        "pypsa_dc_voltages_kv",
    ]:
        pairs[column] = pairs[column].fillna("")

    return pairs


def compare_voltage_sets(
    reference_value,
    model_value,
):
    """Classify agreement between two voltage-level sets."""
    reference = parse_voltage_set(reference_value)

    model = parse_voltage_set(model_value)

    if not reference or not model:
        return "not_comparable"

    if reference == model:
        return "exact"

    if reference < model:
        return "osm_subset"

    if model < reference:
        return "pypsa_subset"

    if reference & model:
        return "overlap"

    return "different"


def compare_transmission_topology(
    pypsa_corridors,
    osm_corridors,
):
    """Outer-join PyPSA and OSM corridors and classify agreement."""
    pypsa = aggregate_pypsa_corridors(pypsa_corridors)

    osm = osm_corridors.copy()

    pypsa["pypsa_exists"] = True
    osm["osm_exists"] = True

    comparison = osm.merge(
        pypsa,
        on=["bus0", "bus1"],
        how="outer",
    )

    comparison["osm_exists"] = comparison["osm_exists"].fillna(False).astype(bool)

    comparison["pypsa_exists"] = comparison["pypsa_exists"].fillna(False).astype(bool)

    osm_count_columns = [
        "osm_line_count",
        "osm_ac_line_count",
        "osm_dc_line_count",
    ]

    for column in osm_count_columns:
        comparison[column] = comparison[column].fillna(0).astype(int)

    pypsa_numeric_columns = [
        column
        for column in comparison.columns
        if (
            column.endswith("_branch_count")
            or column.endswith("_mva")
            or column.endswith("_mw")
        )
    ]

    comparison[pypsa_numeric_columns] = comparison[pypsa_numeric_columns].fillna(0)

    count_columns = [
        column for column in pypsa_numeric_columns if column.endswith("_branch_count")
    ]

    comparison[count_columns] = comparison[count_columns].astype(int)

    voltage_columns = [
        "osm_voltages_kv",
        "osm_ac_voltages_kv",
        "osm_dc_voltages_kv",
        "pypsa_ac_voltages_kv",
        "pypsa_dc_voltages_kv",
    ]

    for column in voltage_columns:
        comparison[column] = comparison[column].fillna("")

    comparison["status"] = np.select(
        [
            comparison["osm_exists"] & comparison["pypsa_exists"],
            comparison["osm_exists"] & ~comparison["pypsa_exists"],
            ~comparison["osm_exists"] & comparison["pypsa_exists"],
        ],
        [
            "matched",
            "osm_only",
            "pypsa_only",
        ],
        default="unknown",
    )

    comparison["ac_voltage_status"] = [
        (
            compare_voltage_sets(
                osm_voltage,
                pypsa_voltage,
            )
            if status == "matched"
            else "not_comparable"
        )
        for (
            osm_voltage,
            pypsa_voltage,
            status,
        ) in zip(
            comparison["osm_ac_voltages_kv"],
            comparison["pypsa_ac_voltages_kv"],
            comparison["status"],
        )
    ]

    comparison["dc_voltage_status"] = [
        (
            compare_voltage_sets(
                osm_voltage,
                pypsa_voltage,
            )
            if status == "matched"
            else "not_comparable"
        )
        for (
            osm_voltage,
            pypsa_voltage,
            status,
        ) in zip(
            comparison["osm_dc_voltages_kv"],
            comparison["pypsa_dc_voltages_kv"],
            comparison["status"],
        )
    ]

    return comparison.sort_values(
        [
            "status",
            "bus0",
            "bus1",
        ]
    ).reset_index(drop=True)


def build_summary(comparison):
    """Build topology-level summary diagnostics."""
    matched = (comparison["status"] == "matched").sum()

    osm_only = (comparison["status"] == "osm_only").sum()

    pypsa_only = (comparison["status"] == "pypsa_only").sum()

    osm_corridors = (comparison["osm_exists"]).sum()

    pypsa_corridors = (comparison["pypsa_exists"]).sum()

    records = [
        {
            "metric": "matched_corridors",
            "value": matched,
        },
        {
            "metric": "osm_only_corridors",
            "value": osm_only,
        },
        {
            "metric": "pypsa_only_corridors",
            "value": pypsa_only,
        },
        {
            "metric": "osm_corridors",
            "value": osm_corridors,
        },
        {
            "metric": "pypsa_corridors",
            "value": pypsa_corridors,
        },
        {
            "metric": "union_corridors",
            "value": len(comparison),
        },
        {
            "metric": ("fraction_osm_corridors_represented"),
            "value": (matched / osm_corridors if osm_corridors else np.nan),
        },
        {
            "metric": ("fraction_pypsa_corridors_in_osm"),
            "value": (matched / pypsa_corridors if pypsa_corridors else np.nan),
        },
    ]

    return pd.DataFrame(records)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        from helpers import mock_snakemake

        snakemake = mock_snakemake("compare_transmission_topology")

        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    pypsa_corridors = pd.read_csv(
        snakemake.input["pypsa"],
        dtype={
            "bus0": str,
            "bus1": str,
            "voltages_kv": str,
        },
    )

    osm_corridors = pd.read_csv(
        snakemake.input["osm"],
        dtype={
            "bus0": str,
            "bus1": str,
            "osm_voltages_kv": str,
            "osm_ac_voltages_kv": str,
            "osm_dc_voltages_kv": str,
        },
    )

    comparison = compare_transmission_topology(
        pypsa_corridors,
        osm_corridors,
    )

    summary = build_summary(comparison)

    os.makedirs(
        os.path.dirname(snakemake.output["comparison"]),
        exist_ok=True,
    )

    comparison.to_csv(
        snakemake.output["comparison"],
        index=False,
    )

    summary.to_csv(
        snakemake.output["summary"],
        index=False,
    )

    logger.info(
        "Compared %d transmission corridors: %d matched, "
        "%d OSM-only and %d PyPSA-only.",
        len(comparison),
        (comparison["status"] == "matched").sum(),
        (comparison["status"] == "osm_only").sum(),
        (comparison["status"] == "pypsa_only").sum(),
    )
