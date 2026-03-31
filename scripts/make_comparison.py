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

import pandas as pd
from helpers import (
    configure_logging,
    country_name_2_two_digits,
    read_csv_nafix,
    to_csv_nafix,
)


def compare_capacity_statistics(reference_df, network_df):
    comparison_results = []
    unique_combinations = reference_df[["region", "carrier"]].drop_duplicates()

    for _, row in unique_combinations.iterrows():
        region = row["region"]
        carrier = row["carrier"]
        reference_row = reference_df[
            (reference_df["region"] == region) & (reference_df["carrier"] == carrier)
        ]
        network_row = network_df[
            (network_df["region"] == region) & (network_df["carrier"] == carrier)
        ]

        if not reference_row.empty and not network_row.empty:
            comparison_results.append(
                {
                    "region": region,
                    "carrier": carrier,
                    "network_capacity": network_row["p_nom"].values[0],
                    "reference_capacity": reference_row["p_nom"].values[0],
                }
            )

    comparison_df = pd.DataFrame(comparison_results)
    comparison_df = comparison_df.set_index("region")
    return comparison_df


def compare_demand_statistics(reference_df, network_df):
    comparison_results = []
    unique_countries = reference_df["region"].drop_duplicates()

    for region in unique_countries:
        reference_row = reference_df[reference_df["region"] == region]
        network_row = network_df[network_df["region"] == region]

        if not reference_row.empty and not network_row.empty:
            comparison_results.append(
                {
                    "region": region,
                    "network_demand": network_row["demand"].values[0],
                    "reference_demand": reference_row["demand"].values[0],
                }
            )

    comparison_df = pd.DataFrame(comparison_results)
    comparison_df = comparison_df.set_index("region")
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


def make_comparison(inputs, outputs):
    df_reference_installed_capacity = read_csv_nafix(
        inputs["installed_capacity_reference"]
    )
    df_reference_optimal_capacity = read_csv_nafix(
        inputs["installed_capacity_reference"]
    )  # same source assumed
    df_reference_demand = read_csv_nafix(inputs["demand_reference"])

    df_network_installed_capacity = read_csv_nafix(inputs["installed_capacity_network"])
    df_network_optimal_capacity = read_csv_nafix(inputs["optimal_capacity_network"])
    df_network_demand = read_csv_nafix(inputs["demand_network"])

    installed_capacity_comparison = compare_capacity_statistics(
        df_reference_installed_capacity, df_network_installed_capacity
    )
    optimal_capacity_comparison = compare_capacity_statistics(
        df_reference_optimal_capacity, df_network_optimal_capacity
    )
    demand_comparison = compare_demand_statistics(
        df_reference_demand, df_network_demand
    )

    to_csv_nafix(
        installed_capacity_comparison, outputs["installed_capacity_comparison"]
    )
    to_csv_nafix(optimal_capacity_comparison, outputs["optimal_capacity_comparison"])
    to_csv_nafix(demand_comparison, outputs["demand_comparison"])

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
    make_comparison(snakemake.input, snakemake.output)
