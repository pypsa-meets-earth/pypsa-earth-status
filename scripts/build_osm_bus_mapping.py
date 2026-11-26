# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a common OSM bus mapping for transmission validation."""

import logging

import geopandas as gpd
import pandas as pd
import pypsa
from helpers import configure_logging
from transmission_mapping import (
    assign_osm_buses_to_regions,
    compose_busmaps,
    discover_busmaps,
)

logger = logging.getLogger(__name__)


def build_mapping(network, network_path, osm_buses, osm_path, regions, region_map):
    """Prefer compatible PyPSA-Earth busmaps over spatial assignment."""
    try:
        paths = discover_busmaps(network, network_path, osm_path)

        mapping = compose_busmaps(
            paths,
            osm_buses["bus_id"],
            network.buses.index,
        )

        final_bus_mapping = mapping.copy()
        mapping = mapping.map(region_map)

        assignments = assign_osm_buses_to_regions(osm_buses, regions, busmap=mapping)

        method = "topological"
        logger.info("Using PyPSA-Earth busmaps: %s", paths)

    except ValueError as exc:
        logger.warning("Using geographic OSM mapping: %s", exc)

        assignments = assign_osm_buses_to_regions(osm_buses, regions)
        method = "geographic"

    assignments["mapping_method"] = method
    assignments["mapped_bus"] = pd.NA
    assignments["mapping_status"] = "unassigned"

    if method == "topological":
        assignments["mapped_bus"] = assignments["bus_id"].map(final_bus_mapping)
        assignments.loc[
            assignments["mapped_bus"].notna() & assignments["region_id"].isna(),
            "mapping_status",
        ] = "outside_transmission_regions"

    assignments.loc[
        assignments["region_id"].notna(),
        "mapping_status",
    ] = "assigned"

    logger.info(
        "OSM mapping status: %s",
        assignments["mapping_status"].value_counts().to_dict(),
    )

    logger.info(
        "OSM mapping method: %s; assigned buses: %d/%d",
        method,
        assignments["region_id"].notna().sum(),
        len(assignments),
    )

    return assignments.drop(columns=["geometry", "index_right"], errors="ignore")


if __name__ == "__main__":
    configure_logging(snakemake)

    network = pypsa.Network(snakemake.input["network_path"])
    osm_buses = gpd.read_file(snakemake.input["osm_buses"])
    regions = gpd.read_file(snakemake.input["bus_regions"])

    region_map = pd.read_csv(snakemake.input["bus_region_map"], dtype=str).set_index(
        "bus"
    )["region_id"]

    mapping = build_mapping(
        network,
        snakemake.input["network_path"],
        osm_buses,
        snakemake.input["osm_buses"],
        regions,
        region_map,
    )

    mapping.to_csv(snakemake.output["mapping"], index=False)
