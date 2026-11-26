# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared OSM bus mapping for transmission validation."""

from decimal import Decimal, InvalidOperation

import geopandas as gpd
import pandas as pd


def normalize_id(value):
    """Normalize numeric and string bus identifiers."""
    if pd.isna(value):
        return None

    try:
        numeric = Decimal(str(value))
        if numeric.is_finite() and numeric == numeric.to_integral_value():
            return str(int(numeric))
    except InvalidOperation:
        pass

    return str(value)


def assign_osm_buses_to_regions(osm_buses, regions, busmap=None):
    """Assign OSM buses using an existing busmap or spatial regions."""
    buses = osm_buses.copy()
    buses["bus_id"] = buses["bus_id"].map(normalize_id)

    columns = ["bus_id", "geometry"]
    if "country" in buses.columns:
        columns.insert(1, "country")

    buses = buses[columns].drop_duplicates("bus_id")

    if busmap is not None:
        mapping = busmap.copy()
        mapping.index = mapping.index.map(normalize_id)
        buses["region_id"] = buses["bus_id"].map(mapping)
        return buses

    regions = regions.copy()
    regions["region_id"] = regions["region_id"].astype(str)

    if buses.crs is None or regions.crs is None:
        raise ValueError("OSM buses and regions must have a valid CRS.")

    buses = buses.to_crs(regions.crs)
    buses["geometry"] = buses.geometry.apply(
        lambda geom: (
            geom
            if geom is None or geom.is_empty or geom.geom_type == "Point"
            else geom.representative_point()
        )
    )

    joined = gpd.sjoin(
        buses,
        regions[["region_id", "geometry"]],
        how="left",
        predicate="intersects",
    )

    return joined.sort_values(
        ["bus_id", "region_id"]
    ).drop_duplicates("bus_id")


def read_busmap(path):
    """Read and validate a PyPSA-Earth busmap."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)

    if frame.shape[1] != 2:
        raise ValueError(f"Invalid busmap format: {path}")

    source = frame.iloc[:, 0].map(normalize_id)
    target = frame.iloc[:, 1].replace("", None).map(normalize_id)

    if source.duplicated().any() or source.isna().any():
        raise ValueError(f"Invalid source bus identifiers: {path}")

    return pd.Series(target.to_numpy(), index=source.to_numpy())


def compose_busmaps(paths, osm_bus_ids, final_bus_ids):
    """Compose successive PyPSA-Earth busmaps."""
    if not paths:
        raise ValueError("No busmaps provided.")

    mapping = read_busmap(paths[0])

    for path in paths[1:]:
        next_mapping = read_busmap(path)

        missing = set(mapping.dropna()) - set(next_mapping.index)
        if missing:
            raise ValueError(
                f"{len(missing)} intermediate buses missing from {path}"
            )

        mapping = mapping.map(next_mapping)

    original_ids = {normalize_id(bus) for bus in osm_bus_ids}
    final_ids = {normalize_id(bus) for bus in final_bus_ids}

    missing = original_ids - set(mapping.index)
    if missing:
        raise ValueError(
            f"{len(missing)} OSM buses missing from the original busmap."
        )

    invalid = set(mapping.dropna()) - final_ids
    if invalid:
        raise ValueError(
            f"{len(invalid)} mapped buses absent from the evaluated network."
        )

    return mapping


def discover_busmaps(network, network_path, osm_buses_path, check_mtime=True):
    """Discover compatible PyPSA-Earth busmap candidates."""
    from pathlib import Path

    meta = network.meta or {}
    wildcards = meta.get("wildcards", {})
    run_name = meta.get("run", {}).get("name")

    if "simpl" not in wildcards or "clusters" not in wildcards:
        raise ValueError("Missing PyPSA-Earth clustering wildcards.")

    osm_path = Path(osm_buses_path)
    resource_dir = osm_path.parent.parent

    if osm_path.parent.name != "base_network":
        raise ValueError("Non-standard PyPSA-Earth OSM resource path.")

    if run_name and resource_dir.name != run_name:
        raise ValueError("OSM resources do not match the network run name.")

    simpl = wildcards["simpl"]
    clusters = wildcards["clusters"]

    paths = [
        resource_dir / "bus_regions" / f"busmap_elec_s{simpl}.csv",
        resource_dir / "bus_regions" / f"busmap_elec_s{simpl}_{clusters}.csv",
    ]

    network_mtime = Path(network_path).stat().st_mtime

    for path in paths:
        if not path.is_file():
            raise ValueError(f"Missing busmap: {path}")

        if check_mtime and path.stat().st_mtime > network_mtime:
            raise ValueError(f"Busmap is newer than the evaluated network: {path}")

    return paths
