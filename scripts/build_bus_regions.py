# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Build spatial validation regions around electrical transmission buses.

The Voronoi construction follows the approach used by PyPSA-Earth's
build_bus_regions workflow. Only buses participating in electrical transmission
are included, so the same logic works for electricity-only and sector-coupled
networks.
"""

import logging
import os
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
from helpers import configure_logging
from shapely.geometry import box

logger = logging.getLogger(__name__)

TRANSMISSION_LINK_CARRIERS = {
    "dc",
    "dc link",
    "hvdc",
    "b2b",
}


def voronoi(points, outline, geo_crs="EPSG:4326"):
    """
    Create Voronoi polygons for points clipped to an outline.

    Adapted from PyPSA-Earth scripts/build_bus_regions.py.
    """
    pts = gpd.GeoSeries(
        gpd.points_from_xy(points.x, points.y),
        index=points.index,
        crs=geo_crs,
    )

    polygons = pts.voronoi_polygons(
        extend_to=outline,
    ).clip(outline)

    # Preserve point-to-polygon association also with Shapely versions where
    # Voronoi output ordering is not guaranteed.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=UserWarning,
        )

        pts_gdf = gpd.GeoDataFrame(
            geometry=pts,
        )
        polygons_gdf = gpd.GeoDataFrame(
            geometry=polygons,
        )

        joined = gpd.sjoin_nearest(
            pts_gdf,
            polygons_gdf,
            how="right",
        )

    return joined.dissolve(by=points.index.name).reindex(points.index).geometry


def get_transmission_links(network):
    """Return Links representing electrical transmission."""
    if network.links.empty:
        return network.links.copy()

    carriers = network.links["carrier"].fillna("").astype(str).str.strip().str.lower()

    return network.links.loc[carriers.isin(TRANSMISSION_LINK_CARRIERS)].copy()


def get_transmission_bus_ids(network):
    """Return buses participating in electrical transmission."""
    buses = set()

    if not network.lines.empty:
        buses.update(network.lines["bus0"].dropna().astype(str))
        buses.update(network.lines["bus1"].dropna().astype(str))

    links = get_transmission_links(network)

    if not links.empty:
        buses.update(links["bus0"].dropna().astype(str))
        buses.update(links["bus1"].dropna().astype(str))

    return sorted(buses)


def build_transmission_bus_points(network):
    """Return valid coordinates for electrical transmission buses."""
    bus_ids = get_transmission_bus_ids(network)

    buses = network.buses.copy()
    buses.index = buses.index.astype(str)

    buses = buses.loc[
        buses.index.intersection(bus_ids),
        ["x", "y"],
    ].copy()

    buses["x"] = pd.to_numeric(
        buses["x"],
        errors="coerce",
    )
    buses["y"] = pd.to_numeric(
        buses["y"],
        errors="coerce",
    )

    buses = buses.dropna(
        subset=["x", "y"],
    )

    buses = buses.loc[np.isfinite(buses["x"]) & np.isfinite(buses["y"])]

    if buses.empty:
        raise ValueError(
            "No electrical transmission buses with valid coordinates found."
        )

    return buses


def group_colocated_buses(buses):
    """Collapse buses sharing the same coordinates to one region seed."""
    grouped = {}

    for bus, row in buses.iterrows():
        key = (
            float(row["x"]),
            float(row["y"]),
        )
        grouped.setdefault(key, []).append(str(bus))

    records = []

    for (x, y), bus_ids in grouped.items():
        bus_ids = sorted(bus_ids)

        records.append(
            {
                "region_id": bus_ids[0],
                "bus_ids": "|".join(bus_ids),
                "x": x,
                "y": y,
            }
        )

    points = pd.DataFrame(records).set_index("region_id")
    points.index.name = "region_id"

    return points


def build_outline(points, osm_lines):
    """Build a finite common outline for the network and OSM data."""
    osm = osm_lines.to_crs("EPSG:4326")

    xmin = min(
        points["x"].min(),
        osm.total_bounds[0],
    )
    ymin = min(
        points["y"].min(),
        osm.total_bounds[1],
    )
    xmax = max(
        points["x"].max(),
        osm.total_bounds[2],
    )
    ymax = max(
        points["y"].max(),
        osm.total_bounds[3],
    )

    span = max(
        xmax - xmin,
        ymax - ymin,
    )

    margin = max(
        0.02 * span,
        0.01,
    )

    return box(
        xmin - margin,
        ymin - margin,
        xmax + margin,
        ymax + margin,
    )


def check_spatial_overlap(points, osm_lines):
    """Require network and OSM data to cover overlapping geographic areas."""
    network_bounds = box(
        points["x"].min(),
        points["y"].min(),
        points["x"].max(),
        points["y"].max(),
    )

    osm = osm_lines.to_crs("EPSG:4326")
    osm_bounds = box(*osm.total_bounds)

    if not network_bounds.intersects(osm_bounds):
        raise ValueError(
            "The solved network and OSM transmission data do not overlap "
            "spatially. Check plot_osm_grid_network.grid_path."
        )


def build_bus_regions(network, osm_lines):
    """Build PyPSA-Earth-style Voronoi regions for transmission buses."""
    buses = build_transmission_bus_points(network)

    points = group_colocated_buses(buses)

    check_spatial_overlap(
        points,
        osm_lines,
    )

    outline = build_outline(
        points,
        osm_lines,
    )

    geometry = voronoi(
        points,
        outline,
    )

    regions = gpd.GeoDataFrame(
        {
            "region_id": points.index.to_numpy(),
            "bus_ids": points["bus_ids"].to_numpy(),
            "x": points["x"].to_numpy(),
            "y": points["y"].to_numpy(),
            "geometry": geometry.to_numpy(),
        },
        crs="EPSG:4326",
    )

    regions = regions.loc[
        regions.geometry.notna()
        & ~regions.geometry.is_empty
        & regions.geometry.is_valid
    ].copy()

    return regions


def build_bus_region_map(bus_regions):
    """Build a bus-to-region mapping."""
    records = []

    for row in bus_regions.itertuples():
        for bus in row.bus_ids.split("|"):
            records.append(
                {
                    "bus": bus,
                    "region_id": str(row.region_id),
                }
            )

    return pd.DataFrame(records).sort_values("bus").reset_index(drop=True)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_bus_regions")

        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    network = pypsa.Network(snakemake.input["network_path"])

    osm_lines = gpd.read_file(snakemake.input["osm_lines"])

    bus_regions = build_bus_regions(
        network,
        osm_lines,
    )

    bus_region_map = build_bus_region_map(bus_regions)

    os.makedirs(
        os.path.dirname(snakemake.output["regions"]),
        exist_ok=True,
    )

    bus_regions.to_file(
        snakemake.output["regions"],
        driver="GeoJSON",
        index=False,
    )

    bus_region_map.to_csv(
        snakemake.output["mapping"],
        index=False,
    )

    logger.info(
        "Built %d bus regions for %d transmission buses.",
        len(bus_regions),
        len(bus_region_map),
    )
