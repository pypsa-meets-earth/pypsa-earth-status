# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Build transmission corridor statistics from a solved PyPSA network.

Transmission branches are aggregated to undirected pairs of validation bus
regions. AC Lines and transmission Links remain separate because their
capacity quantities use different units.
"""

import logging
import os

import numpy as np
import pandas as pd
import pypsa
from helpers import configure_logging

logger = logging.getLogger(__name__)

TRANSMISSION_LINK_CARRIERS = {
    "dc",
    "dc link",
    "hvdc",
    "b2b",
}

OUTPUT_COLUMNS = [
    "bus0",
    "bus1",
    "branch_type",
    "branch_count",
    "nominal_capacity",
    "optimized_capacity",
    "capacity_expansion",
    "capacity_unit",
    "voltages_kv",
]


def normalize_bus_pairs(df):
    """Normalize bus pairs so corridors are undirected."""
    df = df.copy()

    bus0 = df["bus0"].astype(str)
    bus1 = df["bus1"].astype(str)

    swap = bus0 > bus1

    df["bus0"] = bus0.where(~swap, bus1)
    df["bus1"] = bus1.where(~swap, bus0)

    return df


def join_voltages(values):
    """Join unique valid voltage levels."""
    values = pd.to_numeric(
        values,
        errors="coerce",
    )

    values = sorted({float(value) for value in values.dropna() if value > 0})

    return ",".join(f"{value:g}" for value in values)


def get_line_voltages(network):
    """Return nominal voltage for each AC Line."""
    lines = network.lines

    voltage = pd.Series(
        np.nan,
        index=lines.index,
        dtype=float,
    )

    if "v_nom" in lines.columns:
        explicit = pd.to_numeric(
            lines["v_nom"],
            errors="coerce",
        )

        voltage = explicit.where(
            explicit > 0,
            voltage,
        )

    bus_voltage = pd.to_numeric(
        network.buses["v_nom"],
        errors="coerce",
    )

    bus0_voltage = lines["bus0"].map(bus_voltage).astype(float)

    bus1_voltage = lines["bus1"].map(bus_voltage).astype(float)

    equal_bus_voltage = pd.Series(
        np.isclose(
            bus0_voltage,
            bus1_voltage,
            equal_nan=False,
        ),
        index=lines.index,
    )

    inferred = bus0_voltage.where(equal_bus_voltage & (bus0_voltage > 0))

    voltage = voltage.fillna(inferred)

    unresolved = voltage.isna()

    if unresolved.any():
        logger.warning(
            "Could not determine nominal voltage for %d AC lines.",
            unresolved.sum(),
        )

    return voltage


def get_link_voltages(links):
    """Return explicitly stored nominal voltages for transmission Links."""
    if "v_nom" not in links.columns:
        return pd.Series(
            np.nan,
            index=links.index,
            dtype=float,
        )

    voltage = pd.to_numeric(
        links["v_nom"],
        errors="coerce",
    )

    return voltage.where(voltage > 0)


def aggregate_component(
    df,
    bus_region_map,
    nominal_column,
    optimized_column,
    extendable_column,
    branch_type,
    capacity_unit,
    voltages,
):
    """Aggregate transmission branches by undirected bus-region pair."""
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    branches = df[
        [
            "bus0",
            "bus1",
            nominal_column,
        ]
    ].copy()

    branches["voltage_kv"] = voltages.reindex(branches.index)

    branches["bus0"] = branches["bus0"].astype(str).map(bus_region_map)

    branches["bus1"] = branches["bus1"].astype(str).map(bus_region_map)

    branches = branches.dropna(subset=["bus0", "bus1"])

    branches = branches.loc[branches["bus0"] != branches["bus1"]].copy()

    if branches.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    branches["nominal_capacity"] = pd.to_numeric(
        branches[nominal_column],
        errors="coerce",
    ).fillna(0.0)

    branches["optimized_capacity"] = branches["nominal_capacity"]

    if optimized_column in df.columns and extendable_column in df.columns:
        optimized = pd.to_numeric(
            df.loc[
                branches.index,
                optimized_column,
            ],
            errors="coerce",
        )

        extendable = (
            df.loc[
                branches.index,
                extendable_column,
            ]
            .fillna(False)
            .astype(bool)
        )

        branches.loc[
            extendable,
            "optimized_capacity",
        ] = optimized.loc[extendable].fillna(
            branches.loc[
                extendable,
                "nominal_capacity",
            ]
        )

    branches = normalize_bus_pairs(branches)

    corridors = branches.groupby(
        ["bus0", "bus1"],
        as_index=False,
    ).agg(
        branch_count=(
            "nominal_capacity",
            "size",
        ),
        nominal_capacity=(
            "nominal_capacity",
            "sum",
        ),
        optimized_capacity=(
            "optimized_capacity",
            "sum",
        ),
        voltages_kv=(
            "voltage_kv",
            join_voltages,
        ),
    )

    corridors["capacity_expansion"] = (
        corridors["optimized_capacity"] - corridors["nominal_capacity"]
    )

    corridors["branch_type"] = branch_type
    corridors["capacity_unit"] = capacity_unit

    return corridors[OUTPUT_COLUMNS]


def get_transmission_links(network):
    """Return Links representing electrical transmission."""
    if network.links.empty:
        return network.links.copy()

    carriers = network.links["carrier"].fillna("").astype(str).str.strip().str.lower()

    return network.links.loc[carriers.isin(TRANSMISSION_LINK_CARRIERS)].copy()


def build_transmission_statistics(
    network,
    bus_region_map,
):
    """Build corridor-level transmission statistics."""
    line_voltages = get_line_voltages(network)

    lines = aggregate_component(
        network.lines,
        bus_region_map=bus_region_map,
        nominal_column="s_nom",
        optimized_column="s_nom_opt",
        extendable_column="s_nom_extendable",
        branch_type="AC line",
        capacity_unit="MVA",
        voltages=line_voltages,
    )

    transmission_links = get_transmission_links(network)

    links = aggregate_component(
        transmission_links,
        bus_region_map=bus_region_map,
        nominal_column="p_nom",
        optimized_column="p_nom_opt",
        extendable_column="p_nom_extendable",
        branch_type="DC link",
        capacity_unit="MW",
        voltages=get_link_voltages(transmission_links),
    )

    corridors = pd.concat(
        [lines, links],
        ignore_index=True,
    )

    if corridors.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    return corridors.sort_values(
        [
            "bus0",
            "bus1",
            "branch_type",
        ]
    ).reset_index(drop=True)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_transmission_statistics")

        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    network = pypsa.Network(snakemake.input["network_path"])

    mapping = pd.read_csv(
        snakemake.input["bus_region_map"],
        dtype={
            "bus": str,
            "region_id": str,
        },
    )

    bus_region_map = mapping.set_index("bus")["region_id"].to_dict()

    corridors = build_transmission_statistics(
        network,
        bus_region_map,
    )

    os.makedirs(
        os.path.dirname(snakemake.output["corridors"]),
        exist_ok=True,
    )

    corridors.to_csv(
        snakemake.output["corridors"],
        index=False,
    )

    logger.info(
        "Built %d PyPSA transmission corridor records "
        "from %d AC lines and %d transmission links.",
        len(corridors),
        len(network.lines),
        len(get_transmission_links(network)),
    )
