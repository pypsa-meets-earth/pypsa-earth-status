# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
This script reads a PyPSA network and builds reference statistics to be used for comparison.
"""

import os
import re

import pandas as pd
import pypsa
from helpers import configure_logging, harmonize_carrier_names, to_csv_nafix

ELECTRICITY_BUS_CARRIERS = {
    "ac",
    "low voltage",
    "dc",
}
# CO2_BUS_CARRIERS = {"co2", "co2 atmosphere"}
NON_GENERATION_LINK_CARRIERS = {
    "battery discharger",
    "home battery discharger",
    "b2b",
}
NON_GENERATION_GENERATOR_CARRIERS = {
    "load shedding",
}
NON_GENERATION_STORAGE_UNIT_CARRIERS = {
    "phs",
}


def get_electricity_buses(network):
    """Return buses carrying electricity."""
    bus_carriers = network.buses.carrier.fillna("").str.strip().str.lower()
    return network.buses.index[bus_carriers.isin(ELECTRICITY_BUS_CARRIERS)]


def get_electricity_production_links(network):
    """
    Return links converting a non-electric energy carrier into electricity.

    Links whose input and output buses both carry electricity are excluded
    because they represent transmission, conversion, or distribution rather
    than primary electricity generation.

    Storage dischargers are excluded because their output is previously stored
    electricity and should not be counted as primary generation.
    """
    if network.links.empty:
        return network.links.index[:0]

    electricity_buses = get_electricity_buses(network)

    bus0_is_electric = network.links["bus0"].isin(electricity_buses)
    bus1_is_electric = network.links["bus1"].isin(electricity_buses)

    normalized_carriers = (
        network.links["carrier"].fillna("").astype(str).str.strip().str.casefold()
    )

    is_storage_discharge = normalized_carriers.isin(NON_GENERATION_LINK_CARRIERS)

    return network.links.index[
        bus1_is_electric & ~bus0_is_electric & ~is_storage_discharge
    ]


def harmonize_electricity_carrier_names(carriers):
    """
    Harmonize electricity-producing technologies while keeping rooftop and
    utility-scale solar as separate categories.
    """
    original = carriers.fillna("").astype(str)
    normalized = original.str.strip().str.casefold()

    result = original.copy()

    is_biomass = normalized.str.contains("biomass", regex=False)
    result.loc[is_biomass] = "biomass"

    is_chp = normalized.str.contains("chp", regex=False)

    result.loc[is_chp & normalized.str.contains("coal", regex=False)] = "coal"

    result.loc[is_chp & normalized.str.contains("oil", regex=False)] = "oil"

    result.loc[is_chp & normalized.str.contains("gas", regex=False)] = "gas"

    # Project-specific comparison convention; this is not a direct mapping to the
    # IRENA "Other renewable energy" category.
    is_hydrogen_generation = normalized.str.contains(
        r"\bh2\b",
        regex=True,
        na=False,
    )
    result.loc[is_hydrogen_generation] = "non-bio renewable fuels"

    result = harmonize_carrier_names(result)

    # Keep waste separate from biomass because reference statistics provide a
    # dedicated waste category.
    is_waste = normalized.str.contains("waste", regex=False, na=False)
    result.loc[is_waste] = "waste"

    # Apply this after general harmonization to prevent rooftop PV from being
    # merged with utility-scale PV.
    is_rooftop_solar = normalized.str.contains(
        "solar", regex=False
    ) & normalized.str.contains("rooftop", regex=False)
    result.loc[is_rooftop_solar] = "solar rooftop"

    return result


def get_link_capacity(network, capacity_column):
    """Return electrical output capacity of electricity-producing links."""
    production_links = get_electricity_production_links(network)

    links = network.links.loc[
        production_links,
        ["carrier", capacity_column, "efficiency", "bus1"],
    ].copy()

    if links.empty:
        return pd.DataFrame(columns=["carrier", "p_nom", "bus"])

    links[capacity_column] = pd.to_numeric(
        links[capacity_column],
        errors="coerce",
    ).fillna(0.0)

    links["efficiency"] = pd.to_numeric(
        links["efficiency"],
        errors="coerce",
    ).fillna(1.0)

    links["p_nom"] = links[capacity_column] * links["efficiency"]

    return (
        links[["carrier", "p_nom", "bus1"]]
        .rename(columns={"bus1": "bus"})
        .reset_index(drop=True)
    )


def process_network_statistics(inputs, outputs):
    """
    Extracts and processes demand, installed capacity, and optimal capacity from the PyPSA network.
    """
    network = pypsa.Network(inputs["network_path"])

    # Extract electricity demand
    electricity_buses = get_electricity_buses(network)

    generator_carriers = (
        network.generators["carrier"].fillna("").astype(str).str.strip().str.casefold()
    )

    # Exclude artificial generators from both capacity and generation statistics.
    electricity_generators = network.generators.index[
        network.generators["bus"].isin(electricity_buses)
        & ~generator_carriers.isin(NON_GENERATION_GENERATOR_CARRIERS)
    ]

    storage_unit_carriers = (
        network.storage_units["carrier"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )

    electricity_storage_units = network.storage_units.index[
        network.storage_units["bus"].isin(electricity_buses)
    ]

    # Pumped storage is excluded from generation because it is not primary
    # electricity generation.
    generation_storage_units = electricity_storage_units[
        ~storage_unit_carriers.loc[electricity_storage_units].isin(
            NON_GENERATION_STORAGE_UNIT_CARRIERS
        )
    ]

    electricity_loads = network.loads.index[
        network.loads["bus"].isin(electricity_buses)
    ]

    load_p_set = network.get_switchable_as_dense("Load", "p_set").reindex(
        index=network.snapshots,
        columns=electricity_loads,
    )

    weights = network.snapshot_weightings.generators.reindex(network.snapshots)

    demand = load_p_set.mul(weights, axis=0).sum(axis=0).mul(1e-6)

    demand = demand.rename("demand").to_frame()

    demand["region"] = (
        network.loads.loc[demand.index, "bus"].map(network.buses["country"]).to_numpy()
    )

    demand = demand.groupby("region")[["demand"]].sum()

    to_csv_nafix(demand, outputs["demand"])

    # Extract installed capacity
    generator_capacity = network.generators.loc[
        electricity_generators,
        ["carrier", "p_nom", "bus"],
    ].reset_index(drop=True)

    storage_capacity = network.storage_units.loc[
        electricity_storage_units,
        ["carrier", "p_nom", "bus"],
    ].reset_index(drop=True)

    link_capacity = get_link_capacity(network, "p_nom")

    installed_capacity = pd.concat(
        [
            generator_capacity,
            storage_capacity,
            link_capacity,
        ],
        ignore_index=True,
    )

    installed_capacity["region"] = installed_capacity["bus"].map(
        network.buses["country"]
    )

    installed_capacity["carrier"] = harmonize_electricity_carrier_names(
        installed_capacity["carrier"]
    )

    installed_capacity = installed_capacity.groupby(["region", "carrier"])[
        ["p_nom"]
    ].sum()

    to_csv_nafix(
        installed_capacity,
        outputs["installed_capacity"],
    )

    # Extract optimal capacity from generators and storage units
    generator_optimal_capacity = (
        network.generators.loc[
            electricity_generators,
            ["carrier", "p_nom_opt", "bus"],
        ]
        .rename(columns={"p_nom_opt": "p_nom"})
        .reset_index(drop=True)
    )

    storage_optimal_capacity = (
        network.storage_units.loc[
            electricity_storage_units,
            ["carrier", "p_nom_opt", "bus"],
        ]
        .rename(columns={"p_nom_opt": "p_nom"})
        .reset_index(drop=True)
    )

    link_optimal_capacity = get_link_capacity(
        network,
        "p_nom_opt",
    )

    optimal_capacity = pd.concat(
        [
            generator_optimal_capacity,
            storage_optimal_capacity,
            link_optimal_capacity,
        ],
        ignore_index=True,
    )

    optimal_capacity["region"] = optimal_capacity["bus"].map(network.buses["country"])

    optimal_capacity["carrier"] = harmonize_electricity_carrier_names(
        optimal_capacity["carrier"]
    )

    optimal_capacity = optimal_capacity.groupby(["region", "carrier"])[["p_nom"]].sum()

    to_csv_nafix(
        optimal_capacity,
        outputs["optimal_capacity"],
    )

    # Extract annual electricity generation from generators
    generator_generation = (
        network.generators_t.p.reindex(
            index=network.snapshots,
            columns=electricity_generators,
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
            columns=generation_storage_units,
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

    # Extract annual electricity generation from production links
    production_links = get_electricity_production_links(network)

    link_generation = (
        (
            -network.links_t.p1.reindex(
                index=network.snapshots,
                columns=production_links,
                fill_value=0.0,
            )
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

    link_generation["carrier"] = network.links.loc[
        link_generation.index,
        "carrier",
    ].to_numpy()

    link_generation["bus"] = network.links.loc[
        link_generation.index,
        "bus1",
    ].to_numpy()

    generation = pd.concat(
        [
            generator_generation,
            storage_generation,
            link_generation,
        ],
        ignore_index=True,
    )

    # Convert weighted MWh to GWh
    generation["generation"] /= 1e3

    generation["region"] = generation["bus"].map(network.buses["country"])

    generation["carrier"] = harmonize_electricity_carrier_names(generation["carrier"])

    generation = generation.groupby(
        ["region", "carrier"],
        as_index=True,
    )[["generation"]].sum()

    to_csv_nafix(
        generation,
        outputs["electricity_generation"],
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from helpers import mock_snakemake

        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        snakemake = mock_snakemake("build_network_statistics")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    process_network_statistics(snakemake.params["network"], snakemake.output)
