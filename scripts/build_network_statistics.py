# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
This script reads a PyPSA network and builds reference statistics to be used for comparison.
"""

import os

import pandas as pd
import pypsa
from helpers import configure_logging, harmonize_carrier_names, to_csv_nafix


def process_network_statistics(inputs, outputs):
    """
    Extracts and processes demand, installed capacity, and optimal capacity from the PyPSA network.
    """
    network = pypsa.Network(inputs["network_path"])

    # 1. Extract demand
    demand = (
        network.loads_t.p_set.multiply(network.snapshot_weightings.objective, axis=0)
        .sum()
        .T
        * 1e-6
    )  # Convert MWh to TWh
    demand = demand.reset_index()
    demand.columns = ["bus", "demand"]
    demand = demand.set_index("bus")
    demand["region"] = network.buses.loc[
        network.loads.loc[demand.index, "bus"], "country"
    ]
    demand = demand.groupby(["region"]).sum()
    to_csv_nafix(demand, outputs["demand"])

    # 2. Extract installed capacity (from both generators and storage units)
    generator_capacity = network.generators[["carrier", "p_nom", "bus"]].reset_index(
        drop=True
    )
    storage_capacity = network.storage_units[["carrier", "p_nom", "bus"]].reset_index(
        drop=True
    )
    installed_capacity = pd.concat(
        [generator_capacity, storage_capacity], ignore_index=True
    )
    installed_capacity["region"] = installed_capacity["bus"].map(
        network.buses["country"]
    )

    # Filter out load shedding units
    installed_capacity = installed_capacity[
        ~installed_capacity["carrier"].str.lower().isin(["load", "load shedding"])
    ]

    installed_capacity["carrier"] = harmonize_carrier_names(
        installed_capacity["carrier"]
    )
    installed_capacity = installed_capacity.groupby(["region", "carrier"])[
        ["p_nom"]
    ].sum()
    to_csv_nafix(installed_capacity, outputs["installed_capacity"])

    # 3. Extract optimal capacity (from both generators and storage units)
    generator_optimal_capacity = network.generators[
        ["carrier", "p_nom_opt", "bus"]
    ].rename(columns={"p_nom_opt": "p_nom"})
    storage_optimal_capacity = network.storage_units[
        ["carrier", "p_nom_opt", "bus"]
    ].rename(columns={"p_nom_opt": "p_nom"})
    optimal_capacity = pd.concat(
        [generator_optimal_capacity, storage_optimal_capacity], ignore_index=True
    )
    optimal_capacity["region"] = optimal_capacity["bus"].map(network.buses["country"])

    # Filter out load shedding units
    optimal_capacity = optimal_capacity[
        ~optimal_capacity["carrier"].str.lower().isin(["load", "load shedding"])
    ]

    optimal_capacity["carrier"] = harmonize_carrier_names(optimal_capacity["carrier"])
    optimal_capacity = optimal_capacity.groupby(["region", "carrier"])[["p_nom"]].sum()
    to_csv_nafix(optimal_capacity, outputs["optimal_capacity"])

    # Extract optimal capacity from generators and storage units
    generator_optimal_capacity = (
        network.generators[["carrier", "p_nom_opt", "bus"]]
        .rename(columns={"p_nom_opt": "p_nom"})
        .reset_index(drop=True)
    )

    storage_optimal_capacity = (
        network.storage_units[["carrier", "p_nom_opt", "bus"]]
        .rename(columns={"p_nom_opt": "p_nom"})
        .reset_index(drop=True)
    )

    optimal_capacity = pd.concat(
        [
            generator_optimal_capacity,
            storage_optimal_capacity,
        ],
        ignore_index=True,
    )

    optimal_capacity["region"] = optimal_capacity["bus"].map(network.buses["country"])

    optimal_capacity["carrier"] = harmonize_carrier_names(optimal_capacity["carrier"])

    optimal_capacity = optimal_capacity.groupby(["region", "carrier"])[["p_nom"]].sum()

    to_csv_nafix(
        optimal_capacity,
        outputs["optimal_capacity"],
    )

    # Extract annual electricity generation from generators
    generator_generation = (
        network.generators_t.p.reindex(
            index=network.snapshots,
            columns=network.generators.index,
            fill_value=0.0,
        )
        .clip(lower=0.0)
        .mul(
            network.snapshot_weightings.generators.reindex(network.snapshots),
            axis=0,
        )
        .sum(axis=0)
        .rename("generation")
        .to_frame()
    )

    generator_generation["carrier"] = network.generators.loc[
        generator_generation.index,
        "carrier",
    ].to_numpy()

    generator_generation["bus"] = network.generators.loc[
        generator_generation.index,
        "bus",
    ].to_numpy()

    # Extract annual positive discharge from storage units
    storage_generation = (
        network.storage_units_t.p.reindex(
            index=network.snapshots,
            columns=network.storage_units.index,
            fill_value=0.0,
        )
        .clip(lower=0.0)
        .mul(
            network.snapshot_weightings.generators.reindex(network.snapshots),
            axis=0,
        )
        .sum(axis=0)
        .rename("generation")
        .to_frame()
    )

    storage_generation["carrier"] = network.storage_units.loc[
        storage_generation.index,
        "carrier",
    ].to_numpy()

    storage_generation["bus"] = network.storage_units.loc[
        storage_generation.index,
        "bus",
    ].to_numpy()

    generation = pd.concat(
        [generator_generation, storage_generation], ignore_index=True
    )

    # Filter out load shedding units
    generation = generation[
        ~generation["carrier"].str.lower().isin(["load", "load shedding"])
    ]

    # Convert weighted MWh to GWh
    generation["generation"] /= 1e3

    generation["region"] = generation["bus"].map(network.buses["country"])
    generation["carrier"] = harmonize_carrier_names(generation["carrier"])
    generation = generation.groupby(["region", "carrier"])[["generation"]].sum()

    to_csv_nafix(generation, outputs["electricity_generation"])


if __name__ == "__main__":
    if "snakemake" not in globals():
        from helpers import mock_snakemake

        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        snakemake = mock_snakemake("build_network_statistics")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    process_network_statistics(snakemake.params["network"], snakemake.output)
