# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
This script compares the reference and network statistics by searching unique
region and carrier combinations for capacities and unique countries for demand.
It also compares transmission line properties (s_nom and length) by computing
ratios and outputs a comparison GeoJSON.
"""

import json
import logging
import os

import numpy as np
import pandas as pd
from helpers import (
    collapse_wind_carriers,
    configure_logging,
    read_csv_nafix,
    reference_splits_offshore_wind,
    to_csv_nafix,
)


def compute_differences(network_val, reference_val):
    """
    Signed, absolute and relative differences between a network value and its
    reference. The relative difference is a percentage of the reference and is
    undefined when the reference is zero.
    """
    difference = network_val - reference_val
    return {
        "difference": difference,
        "absolute_difference": abs(difference),
        "relative_difference_pct": (
            difference / reference_val * 100.0 if reference_val != 0.0 else np.inf
        ),
    }


def compare_capacity_statistics(reference_df, network_df, source_name):
    comparison_results = []

    # We want to match unique combinations of region and carrier from both dfs
    unique_combinations = pd.concat(
        [reference_df[["region", "carrier"]], network_df[["region", "carrier"]]]
    ).drop_duplicates()

    for _, row in unique_combinations.iterrows():
        region = row["region"]
        carrier = row["carrier"]

        reference_row = reference_df[
            (reference_df["region"] == region) & (reference_df["carrier"] == carrier)
        ]
        network_row = network_df[
            (network_df["region"] == region) & (network_df["carrier"] == carrier)
        ]

        network_val = network_row["p_nom"].values[0] if not network_row.empty else 0.0
        reference_val = (
            reference_row["p_nom"].values[0] if not reference_row.empty else 0.0
        )

        if network_val == 0.0 and reference_val == 0.0:
            continue

        comparison_results.append(
            {
                "region": region,
                "carrier": carrier,
                "network_capacity": network_val,
                "reference_capacity": reference_val,
                **compute_differences(network_val, reference_val),
                "reference_source": source_name,
            }
        )

    if comparison_results:
        comparison_df = pd.DataFrame(comparison_results)
        comparison_df = comparison_df.set_index("region")
    else:
        comparison_df = pd.DataFrame(
            columns=[
                "region",
                "carrier",
                "network_capacity",
                "reference_capacity",
                "difference",
                "absolute_difference",
                "relative_difference_pct",
                "reference_source",
            ]
        ).set_index("region")

    return comparison_df


def compare_demand_statistics(reference_df, network_df, source_name):
    comparison_results = []
    unique_countries = pd.concat(
        [reference_df["region"], network_df["region"]]
    ).drop_duplicates()

    for region in unique_countries:
        reference_row = reference_df[reference_df["region"] == region]
        network_row = network_df[network_df["region"] == region]

        network_val = network_row["demand"].values[0] if not network_row.empty else 0.0
        reference_val = (
            reference_row["demand"].values[0] if not reference_row.empty else 0.0
        )

        if network_val == 0.0 and reference_val == 0.0:
            continue

        comparison_results.append(
            {
                "region": region,
                "network_demand": network_val,
                "reference_demand": reference_val,
                **compute_differences(network_val, reference_val),
                "reference_source": source_name,
            }
        )

    if comparison_results:
        comparison_df = pd.DataFrame(comparison_results)
        comparison_df = comparison_df.set_index("region")
    else:
        comparison_df = pd.DataFrame(
            columns=[
                "region",
                "network_demand",
                "reference_demand",
                "difference",
                "absolute_difference",
                "relative_difference_pct",
                "reference_source",
            ]
        ).set_index("region")

    return comparison_df


def compare_generation_statistics(reference_df, network_df, source_name):
    comparison_results = []

    unique_combinations = pd.concat(
        [reference_df[["region", "carrier"]], network_df[["region", "carrier"]]]
    ).drop_duplicates()

    for _, row in unique_combinations.iterrows():
        region = row["region"]
        carrier = row["carrier"]

        reference_row = reference_df[
            (reference_df["region"] == region) & (reference_df["carrier"] == carrier)
        ]
        network_row = network_df[
            (network_df["region"] == region) & (network_df["carrier"] == carrier)
        ]

        network_val = (
            network_row["generation"].values[0] if not network_row.empty else 0.0
        )
        reference_val = (
            reference_row["generation"].values[0] if not reference_row.empty else 0.0
        )

        if network_val == 0.0 and reference_val == 0.0:
            continue

        comparison_results.append(
            {
                "region": region,
                "carrier": carrier,
                "network_generation": network_val,
                "reference_generation": reference_val,
                **compute_differences(network_val, reference_val),
                "reference_source": source_name,
            }
        )

    if comparison_results:
        comparison_df = pd.DataFrame(comparison_results)
        comparison_df = comparison_df.set_index("region")
    else:
        comparison_df = pd.DataFrame(
            columns=[
                "region",
                "carrier",
                "network_generation",
                "reference_generation",
                "difference",
                "absolute_difference",
                "relative_difference_pct",
                "reference_source",
            ]
        ).set_index("region")

    return comparison_df


def compute_line_ratios_geojson(reference_path, model_path, output_path):
    """
    Compute the ratio of s_nom and length between model and reference networks,
    and store the results in a new GeoJSON with only ratio values.
    """
    if os.path.getsize(model_path) <= 0:  # skip if file is empty
        with open(output_path, "w") as f:
            pass
        return

    with open(reference_path, "r") as f:
        geojson_ref = json.load(f)

    with open(model_path, "r") as f:
        geojson_model = json.load(f)

    # Index reference features by line key
    ref_lines = {}
    for feature in geojson_ref["features"]:
        props = feature["properties"]
        key = f"{props['bus0']}_{props['bus1']}"
        ref_lines[key] = {
            "s_nom": props.get("s_nom", 0),
            "length": props.get("length", 0),
        }

    # Compute ratios and clean up properties
    for feature in geojson_model["features"]:
        props = feature["properties"]
        key = f"{props['bus0']}_{props['bus1']}"

        s_nom_model = props.get("s_nom", 0)
        length_model = props.get("length", 0)

        s_nom_ref = ref_lines.get(key, {}).get("s_nom", 0)
        length_ref = ref_lines.get(key, {}).get("length", 0)

        # Compute ratios
        s_nom_ratio = s_nom_model / s_nom_ref if s_nom_ref else None
        length_ratio = length_model / length_ref if length_ref else None

        # Replace properties with ratios only
        feature["properties"] = {
            "bus0": props["bus0"],
            "bus1": props["bus1"],
            "s_nom_ratio": s_nom_ratio,
            "length_ratio": length_ratio,
        }

    with open(output_path, "w") as f:
        json.dump(geojson_model, f)


def _collapse_wind_and_regroup(df, value_col):
    """
    Fold offshore wind into onshore wind and re-sum so folded rows combine
    instead of one silently overwriting the other on lookup.
    """
    df = df.copy()
    df["carrier"] = collapse_wind_carriers(df["carrier"])
    return df.groupby(["region", "carrier"], as_index=False)[value_col].sum()


def make_comparison(inputs, outputs, datasets):
    demand_source = datasets.get("demand", ["ourworldindata"])[0]
    capacity_source = datasets.get("installed_capacity", ["irena"])[0]
    generation_source = datasets.get("electricity_generation", ["ember"])[0]

    df_reference_installed_capacity = read_csv_nafix(
        inputs["installed_capacity_reference"]
    )
    df_reference_optimal_capacity = read_csv_nafix(
        inputs["installed_capacity_reference"]
    )  # same source assumed
    df_reference_demand = read_csv_nafix(inputs["demand_reference"])
    df_reference_generation = read_csv_nafix(inputs["electricity_generation_reference"])

    df_network_installed_capacity = read_csv_nafix(inputs["installed_capacity_network"])
    df_network_optimal_capacity = read_csv_nafix(inputs["optimal_capacity_network"])
    df_network_demand = read_csv_nafix(inputs["demand_network"])
    df_network_generation = read_csv_nafix(inputs["electricity_generation_network"])

    # The network side always keeps onshore/offshore wind distinct. Fold them
    # together when comparing against a reference source that doesn't split them,
    # re-aggregating so folded rows are summed rather than silently dropped.
    if not reference_splits_offshore_wind(df_reference_installed_capacity):
        df_network_installed_capacity = _collapse_wind_and_regroup(
            df_network_installed_capacity, "p_nom"
        )
        df_network_optimal_capacity = _collapse_wind_and_regroup(
            df_network_optimal_capacity, "p_nom"
        )
    if not reference_splits_offshore_wind(df_reference_generation):
        df_network_generation = _collapse_wind_and_regroup(
            df_network_generation, "generation"
        )

    installed_capacity_comparison = compare_capacity_statistics(
        df_reference_installed_capacity, df_network_installed_capacity, capacity_source
    )
    optimal_capacity_comparison = compare_capacity_statistics(
        df_reference_optimal_capacity, df_network_optimal_capacity, capacity_source
    )
    demand_comparison = compare_demand_statistics(
        df_reference_demand, df_network_demand, demand_source
    )
    electricity_generation_comparison = compare_generation_statistics(
        df_reference_generation, df_network_generation, generation_source
    )

    to_csv_nafix(
        installed_capacity_comparison, outputs["installed_capacity_comparison"]
    )
    to_csv_nafix(optimal_capacity_comparison, outputs["optimal_capacity_comparison"])
    to_csv_nafix(demand_comparison, outputs["demand_comparison"])
    to_csv_nafix(
        electricity_generation_comparison,
        outputs["electricity_generation_comparison"],
    )

    compute_line_ratios_geojson(
        reference_path=inputs["network_geojson_reference"],
        model_path=inputs["network_geojson_network"],
        output_path=outputs["network_comparison_geojson"],
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("make_comparison")

    configure_logging(snakemake)
    make_comparison(snakemake.input, snakemake.output, snakemake.params["datasets"])
