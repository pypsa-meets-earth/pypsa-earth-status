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
    gen_cap = network.generators[["carrier", "p_nom", "bus"]].copy()
    gen_cap["region"] = network.buses.loc[gen_cap["bus"], "country"].values

    if not network.storage_units.empty:
        store_cap = network.storage_units[["carrier", "p_nom", "bus"]].copy()
        store_cap["region"] = network.buses.loc[store_cap["bus"], "country"].values
        installed_capacity = pd.concat([gen_cap, store_cap], axis=0)
    else:
        installed_capacity = gen_cap

    # Filter out load shedding units
    installed_capacity = installed_capacity[
        ~installed_capacity["carrier"].str.lower().isin(["load", "load shedding"])
    ]

    installed_capacity["carrier"] = harmonize_carrier_names(
        installed_capacity["carrier"]
    )
    installed_capacity = installed_capacity.groupby(["region", "carrier"]).sum()
    installed_capacity.drop(columns="bus", inplace=True, errors="ignore")
    to_csv_nafix(installed_capacity, outputs["installed_capacity"])

    # 3. Extract optimal capacity
    gen_opt = network.generators[["carrier", "p_nom_opt", "bus"]].copy()
    gen_opt["region"] = network.buses.loc[gen_opt["bus"], "country"].values
    gen_opt = gen_opt.rename(columns={"p_nom_opt": "p_nom"})

    if not network.storage_units.empty:
        store_opt = network.storage_units[["carrier", "p_nom_opt", "bus"]].copy()
        store_opt["region"] = network.buses.loc[store_opt["bus"], "country"].values
        store_opt = store_opt.rename(columns={"p_nom_opt": "p_nom"})
        optimal_capacity = pd.concat([gen_opt, store_opt], axis=0)
    else:
        optimal_capacity = gen_opt

    # Filter out load shedding units
    optimal_capacity = optimal_capacity[
        ~optimal_capacity["carrier"].str.lower().isin(["load", "load shedding"])
    ]

    optimal_capacity["carrier"] = harmonize_carrier_names(optimal_capacity["carrier"])
    optimal_capacity = optimal_capacity.groupby(["region", "carrier"]).sum()
    optimal_capacity.drop(columns="bus", inplace=True, errors="ignore")
    to_csv_nafix(optimal_capacity, outputs["optimal_capacity"])

    # 4. Extract generation mix (from both generators and storage units)
    gen_p_t = network.generators_t.p.multiply(
        network.snapshot_weightings.objective, axis=0
    )
    gen_gen_sum = gen_p_t.sum() * 1e-6  # TWh
    df_gen = pd.DataFrame(
        {
            "generation": gen_gen_sum,
            "carrier": network.generators.carrier,
            "bus": network.generators.bus,
        }
    )
    df_gen["region"] = network.buses.loc[df_gen["bus"], "country"].values

    if not network.storage_units.empty:
        store_p_t = network.storage_units_t.p.multiply(
            network.snapshot_weightings.objective, axis=0
        )
        store_gen_sum = store_p_t.sum() * 1e-6  # TWh
        df_store = pd.DataFrame(
            {
                "generation": store_gen_sum,
                "carrier": network.storage_units.carrier,
                "bus": network.storage_units.bus,
            }
        )
        df_store["region"] = network.buses.loc[df_store["bus"], "country"].values
        generation = pd.concat([df_gen, df_store], axis=0)
    else:
        generation = df_gen

    # Filter out load shedding units
    generation = generation[
        ~generation["carrier"].str.lower().isin(["load", "load shedding"])
    ]

    generation["carrier"] = harmonize_carrier_names(generation["carrier"])
    generation = generation.groupby(["region", "carrier"]).sum()
    generation.drop(columns="bus", inplace=True, errors="ignore")
    to_csv_nafix(generation, outputs["generation"])


if __name__ == "__main__":
    if "snakemake" not in globals():
        from helpers import mock_snakemake

        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        snakemake = mock_snakemake("build_network_statistics")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    process_network_statistics(snakemake.params["network"], snakemake.output)
