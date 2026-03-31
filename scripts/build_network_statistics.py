# -*- coding: utf-8 -*-
"""
This script reads a PyPSA network and builds reference statistics to be used for comparison.
"""

import os
import re

import pandas as pd
import pypsa
from helpers import configure_logging, harmonize_carrier_names, to_csv_nafix


def process_network_statistics(inputs, outputs):
    """
    Extracts and processes demand, installed capacity, and optimal capacity from the PyPSA network.
    """
    network = pypsa.Network(inputs["network_path"])

    # Extract demand
    demand = network.loads_t.p_set.mean().T * 8760 * 1e-6
    demand = demand.reset_index()
    demand.columns = ["bus", "demand"]
    demand = demand.set_index("bus")
    demand["region"] = network.buses.loc[
        network.loads.loc[demand.index, "bus"], "country"
    ]
    demand = demand.groupby(["region"]).sum()
    to_csv_nafix(demand, outputs["demand"])

    # Extract installed capacity
    installed_capacity = network.generators[["carrier", "p_nom", "bus"]].reset_index()
    installed_capacity["region"] = network.buses.loc[
        installed_capacity.loc[installed_capacity.index, "bus"], "country"
    ].reset_index()["country"]
    installed_capacity["carrier"] = harmonize_carrier_names(
        installed_capacity["carrier"]
    )
    installed_capacity = installed_capacity.set_index("Generator")
    installed_capacity = installed_capacity.groupby(["region", "carrier"]).sum()
    installed_capacity.drop(columns="bus", inplace=True)
    to_csv_nafix(installed_capacity, outputs["installed_capacity"])

    # Extract optimal capacity
    optimal_capacity = network.generators[["carrier", "p_nom_opt", "bus"]].reset_index()
    optimal_capacity["region"] = network.buses.loc[
        optimal_capacity.loc[optimal_capacity.index, "bus"], "country"
    ].reset_index()["country"]
    optimal_capacity = optimal_capacity.rename(columns={"p_nom_opt": "p_nom"})
    optimal_capacity["carrier"] = harmonize_carrier_names(optimal_capacity["carrier"])
    optimal_capacity.set_index("Generator")
    optimal_capacity = optimal_capacity.groupby(["region", "carrier"]).sum()
    optimal_capacity.drop(columns="bus", inplace=True)
    to_csv_nafix(optimal_capacity, outputs["optimal_capacity"])


if __name__ == "__main__":
    if "snakemake" not in globals():
        from helpers import mock_snakemake

        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        snakemake = mock_snakemake("build_network_statistics")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    process_network_statistics(snakemake.params["network"], snakemake.output)
