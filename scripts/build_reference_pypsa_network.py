# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
This script reads the reference statistics (demand and installed capacity) for
the region of interest and creates a PyPSA network whose statistics match the
reference data. The resulting network can be used for validation or as sample
output for users interested in reference energy system data.

The network contains:
- One bus per country/region
- Loads matching the reference annual electricity demand
- Generators matching the reference installed capacity by carrier
"""

import logging
import os

import pandas as pd
import pypsa
from helpers import configure_logging, read_csv_nafix

logger = logging.getLogger(__name__)

# Hours per year used for unit conversion between TWh/year and MW
HOURS_PER_YEAR = 8760
# Conversion factor from TWh to MWh (used to convert demand from TWh/year to MW)
TWH_TO_MWH = 1e6


def build_reference_pypsa_network(inputs, outputs, params):
    """
    Build a reference PyPSA network from the reference statistics.

    Creates a simplified network with one bus per country/region,
    loads matching the reference annual demand, and generators matching
    the reference installed capacity. The network uses a single snapshot
    weighted by the number of hours in a year so that statistics
    computed from the network are consistent with annual reference values.

    Parameters
    ----------
    inputs : snakemake.io.InputFiles
        - demand : path to the reference demand CSV (region index, demand column in TWh/year)
        - installed_capacity : path to the reference installed capacity CSV
          (region+carrier multi-index, p_nom column in MW)
    outputs : snakemake.io.OutputFiles
        - network : path to write the output NetCDF network file
    params : snakemake.io.Params
        - year : reference year (used as snapshot label)
        - countries : list of country codes to include
    """
    year = params["year"]
    countries = params["countries"]

    demand_df = read_csv_nafix(inputs["demand"])
    capacity_df = read_csv_nafix(inputs["installed_capacity"])

    # The demand CSV has 'region' as the first column (written as index by
    # build_reference_statistics.py, read back as a regular column here).
    # Set it as the index to simplify lookups.
    if "region" in demand_df.columns:
        demand_df = demand_df.set_index("region")

    # Filter to configured countries only
    demand_df = demand_df[demand_df.index.isin(countries)]
    capacity_df = capacity_df[capacity_df["region"].isin(countries)]

    if demand_df.empty:
        logger.warning(
            "No demand data found for the configured countries. The network will have no loads."
        )

    if capacity_df.empty:
        logger.warning(
            "No capacity data found for the configured countries. The network will have no generators."
        )

    # Create PyPSA network with a single snapshot representing a full year
    n = pypsa.Network()
    snapshot_label = pd.Timestamp(f"{year}-01-01")
    n.set_snapshots([snapshot_label])
    n.snapshot_weightings.loc[snapshot_label, :] = HOURS_PER_YEAR

    # Add one bus per country/region
    regions = set(demand_df.index.tolist()) | set(capacity_df["region"].tolist())
    for region in sorted(regions):
        n.add("Bus", region, country=region)
    logger.info("Added %d buses.", len(regions))

    # Add loads: reference demand is in TWh/year; convert to MW (average power)
    loads_added = 0
    for region, row in demand_df.iterrows():
        if region not in n.buses.index:
            logger.warning("Region %s has demand but no bus; skipping.", region)
            continue
        demand_mw = row["demand"] * TWH_TO_MWH / HOURS_PER_YEAR
        # Store as time-series so that loads_t.p_set.mean() * 8760 * 1e-6
        # correctly recovers the original TWh/year demand value
        n.add(
            "Load",
            f"load_{region}",
            bus=region,
            p_set=pd.Series([demand_mw], index=n.snapshots),
        )
        loads_added += 1
    logger.info("Added %d loads.", loads_added)

    # Add generators: reference installed capacity is already in MW
    generators_added = 0
    for _, row in capacity_df.iterrows():
        region = row["region"]
        carrier = row["carrier"]
        p_nom = row["p_nom"]
        if pd.isna(p_nom) or p_nom <= 0:
            continue
        if region not in n.buses.index:
            logger.warning("Region %s has capacity but no bus; skipping.", region)
            continue
        gen_name = f"{region}_{carrier}"
        # Avoid duplicate generator names if the same combination appears twice
        suffix = 0
        while gen_name in n.generators.index:
            suffix += 1
            gen_name = f"{region}_{carrier}_{suffix}"
        n.add("Generator", gen_name, bus=region, carrier=carrier, p_nom=p_nom)
        generators_added += 1
    logger.info("Added %d generators.", generators_added)

    n.export_to_netcdf(outputs["network"])
    logger.info("Reference PyPSA network exported to %s.", outputs["network"])


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_pypsa_network")

    configure_logging(snakemake)

    build_reference_pypsa_network(
        snakemake.input,
        snakemake.output,
        snakemake.params,
    )
