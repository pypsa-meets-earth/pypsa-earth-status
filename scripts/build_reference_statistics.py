# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
This script collects clean statistics data and merges the datasets to create reference statistics to be used to validate energy systems.
"""

import os

import pandas as pd
from helpers import (
    configure_logging,
    harmonize_carrier_names,
    read_csv_nafix,
    to_csv_nafix,
)


def filter_data_by_config(df, column, valid_values):
    """
    Filters the dataframe based on the provided column and valid values from config.yaml.
    """
    return df[df[column].isin(valid_values)]


def process_reference_statistics(inputs, outputs, config):
    """
    Processes demand, installed capacity, and generation data based on specified years and countries.
    """
    year = config["network_validation"]["year"][0]
    countries = config["network_validation"]["countries"]

    datasets = config.get("datasets", {})
    demand_source = datasets.get("demand", ["ourworldindata"])[0]
    capacity_source = datasets.get("installed_capacity", ["irena"])[0]
    generation_source = datasets.get("generation", ["ember"])[0]

    # 1. Process demand data
    if demand_source == "ourworldindata":
        df_demand = read_csv_nafix(inputs["demand_owid"])
        df_demand = filter_data_by_config(df_demand, "region", countries)
        df_demand = df_demand[df_demand["year"] == year]
        df_demand = (
            df_demand[["region", "electricity_demand"]]
            .rename(columns={"electricity_demand": "demand"})
            .set_index("region")
        )
    elif demand_source == "ember":
        df_demand = read_csv_nafix(inputs["demand_ember"])
        df_demand = filter_data_by_config(df_demand, "region", countries)
        df_demand = df_demand[df_demand["Year"] == year]
        df_demand = df_demand[["region", "demand"]].set_index("region")
    else:
        df_demand = pd.DataFrame(columns=["demand"])
    to_csv_nafix(df_demand, outputs["demand"])

    # 2. Process installed capacity data
    if capacity_source == "irena":
        df_capacity = read_csv_nafix(inputs["cap_irena"])
    elif capacity_source == "ember":
        df_capacity = read_csv_nafix(inputs["cap_ember"])
    else:
        df_capacity = pd.DataFrame()

    if not df_capacity.empty:
        df_capacity = filter_data_by_config(df_capacity, "region", countries)
        df_capacity = df_capacity[df_capacity["Year"] == year]
        df_capacity = df_capacity.rename(columns={"Technology": "carrier"})
        df_capacity = df_capacity[["region", "carrier", "p_nom"]].set_index("region")
        df_capacity["carrier"] = harmonize_carrier_names(df_capacity["carrier"])
        df_capacity = df_capacity.groupby(["region", "carrier"]).sum()
    else:
        df_capacity = pd.DataFrame(columns=["carrier", "p_nom"]).set_index("carrier")
    to_csv_nafix(df_capacity, outputs["installed_capacity"])

    # 3. Process generation mix data
    if generation_source == "ember":
        df_gen = read_csv_nafix(inputs["gen_ember"])
    else:
        df_gen = pd.DataFrame()

    if not df_gen.empty:
        df_gen = filter_data_by_config(df_gen, "region", countries)
        df_gen = df_gen[df_gen["Year"] == year]
        df_gen = df_gen.rename(columns={"Technology": "carrier"})
        df_gen = df_gen[["region", "carrier", "generation"]].set_index("region")
        df_gen["carrier"] = harmonize_carrier_names(df_gen["carrier"])
        df_gen = df_gen.groupby(["region", "carrier"]).sum()
    else:
        df_gen = pd.DataFrame(columns=["carrier", "generation"]).set_index("carrier")
    to_csv_nafix(df_gen, outputs["generation"])


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_statistics")

    configure_logging(snakemake)

    year = snakemake.params["year"][0]
    countries = snakemake.params["countries"]

    process_reference_statistics(snakemake.input, snakemake.output, snakemake.config)
