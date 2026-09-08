# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
This script collects clean statistics data and merges the datasets to create reference statistics to be used to validate energy systems.
"""

import logging
import os

import pandas as pd
from helpers import (
    configure_logging,
    harmonize_carrier_names,
    read_csv_nafix,
    to_csv_nafix,
)

logger = logging.getLogger(__name__)


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
    generation_source = datasets.get("electricity_generation", ["ember"])[0]

    # 1. Process demand data
    demand_input_key = f"demand_{demand_source}"
    if demand_source:
        df_demand = read_csv_nafix(inputs[demand_input_key])
        df_demand = filter_data_by_config(df_demand, "region", countries)
        df_demand = df_demand[df_demand["Year"] == year]
        df_demand = df_demand[["region", "demand"]].set_index("region")
    else:
        df_demand = pd.DataFrame(columns=["demand"])
        logger.warning("No demand source configured; demand reference will be empty.")
    to_csv_nafix(df_demand, outputs["demand"])

    # 2. Process installed capacity data
    capacity_input_key = f"cap_{capacity_source}"
    if capacity_source:
        df_capacity = read_csv_nafix(inputs[capacity_input_key])
    else:
        df_capacity = pd.DataFrame()
        logger.warning(
            "No installed capacity source configured; installed capacity reference will be empty."
        )

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

    # 3. Process electricity generation data
    generation_input_key = f"gen_{generation_source}"
    if generation_source:
        df_generation = read_csv_nafix(inputs[generation_input_key])
        df_generation = filter_data_by_config(df_generation, "region", countries)
        df_generation = df_generation[df_generation["Year"] == year]
        df_generation = df_generation.rename(columns={"Technology": "carrier"})
        df_generation = df_generation[["region", "carrier", "generation"]].set_index(
            "region"
        )
        df_generation["carrier"] = harmonize_carrier_names(df_generation["carrier"])
        df_generation = df_generation.groupby(["region", "carrier"]).sum()
    else:
        df_generation = pd.DataFrame(columns=["carrier", "generation"]).set_index(
            "carrier"
        )
        logger.warning(
            "No electricity generation source configured; electricity generation reference will be empty."
        )
    to_csv_nafix(df_generation, outputs["electricity_generation"])


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_statistics")

    configure_logging(snakemake)

    year = snakemake.params["year"][0]
    countries = snakemake.params["countries"]

    process_reference_statistics(snakemake.input, snakemake.output, snakemake.config)
