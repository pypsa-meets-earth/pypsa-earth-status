# -*- coding: utf-8 -*-
"""
Script to generate GeoJSON files representing:
1. Existing cross-border electricity lines
2. Planned cross-border electricity lines
3. Modeled (PyPSA) cross-border electricity lines

The script uses line coordinate data from a center-points CSV and a PyPSA network file.
It aggregates buses and lines based on region and applies specified aggregation rules.
"""

import os

import country_converter as coco
import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
from pyproj import Geod
from shapely.geometry import LineString, Point

cc = coco.CountryConverter()

from helpers import (
    configure_logging,
)


def build_network(df, buscodes_path, countries, year=None):
    """
    Adds buses and lines to a PyPSA network from line data and a buscodes CSV.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing existing or planned line data.
    buscodes_path : str
        Path to the buscodes CSV file.
    countries : list of str
        List of ISO2 country codes to include in the network.
    year : int, optional
        Year to filter planned lines by 'year_planned'. If 'year_planned' is "-" or NA, it is treated as 2025.

    Returns
    -------
    network : pypsa.Network
        The PyPSA network with buses and lines added.
    """
    network = pypsa.Network()

    # Load bus codes with coordinates
    buscodes = pd.read_csv(buscodes_path)
    buscodes = buscodes.set_index("Node")

    # Always clean numeric columns
    for col in ["max_flow", "max_counter_flow", "distance"]:
        if col in df.columns:
            df[col] = df[col].replace("-", np.nan)
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filter for planned lines only if year is provided
    if "year_planned" in df.columns and year is not None:
        df["year_planned"] = df["year_planned"].replace("-", 2025)
        df["year_planned"] = pd.to_numeric(df["year_planned"], errors="coerce").fillna(
            2025
        )
        df = df[df["year_planned"] <= year]
        df = df.sort_values(["pathway", "year_planned"], ascending=[True, False])
        df = df.drop_duplicates(subset="pathway", keep="first")

    added_buses = set()

    for _, row in df.iterrows():
        line_name = row["pathway"]
        bus0_name = row["from_region"]
        bus1_name = row["to_region"]

        # Skip line if either bus is not in buscodes
        if bus0_name not in buscodes.index or bus1_name not in buscodes.index:
            print(
                f"Warning: One or both buses ({bus0_name}, {bus1_name}) not in buscodes, skipping line {line_name}"
            )
            continue

        # Get ISO2 country codes for both buses
        iso3_0 = bus0_name[:3].upper()
        iso2_0 = (
            "XK"
            if iso3_0 == "KOS"
            else cc.convert(names=iso3_0, to="ISO2", not_found=None)
        )

        iso3_1 = bus1_name[:3].upper()
        iso2_1 = (
            "XK"
            if iso3_1 == "KOS"
            else cc.convert(names=iso3_1, to="ISO2", not_found=None)
        )

        # Filter based on allowed countries
        if iso2_0 not in countries or iso2_1 not in countries:
            continue

        # Add bus0 if not already added
        if bus0_name not in added_buses:
            lat0, lon0 = buscodes.loc[bus0_name, ["Lat", "Long"]]
            network.add("Bus", name=bus0_name, x=lon0, y=lat0)
            network.buses.loc[bus0_name, "country"] = iso2_0
            added_buses.add(bus0_name)

        # Add bus1 if not already added
        if bus1_name not in added_buses:
            lat1, lon1 = buscodes.loc[bus1_name, ["Lat", "Long"]]
            network.add("Bus", name=bus1_name, x=lon1, y=lat1)
            network.buses.loc[bus1_name, "country"] = iso2_1
            added_buses.add(bus1_name)

        # Add line
        p0 = row["max_flow"]
        p1 = row["max_counter_flow"]
        s_nom = min(p0, p1) if pd.notnull(p0) and pd.notnull(p1) else None
        length = row["distance"] if pd.notnull(row["distance"]) else 0.0

        network.add(
            "Line",
            name=line_name,
            bus0=bus0_name,
            bus1=bus1_name,
            s_nom=s_nom,
            length=length,
        )

    return network


def update_line_lengths_from_geometry(network):
    """
    Updates the `length` attribute of PyPSA lines based on their geometry in km.

    Parameters
    ----------
    network : pypsa.Network
        The input PyPSA network. Requires each line to have a 'geometry' entry.
    """
    geod = Geod(ellps="WGS84")

    for line_name, line in network.lines.iterrows():
        if isinstance(line.get("geometry"), LineString):
            lons, lats = line.geometry.xy
            length_m = geod.line_length(lons, lats)
            network.lines.at[line_name, "length"] = length_m / 1000  # convert to km

    return network


def aggregate_cross_country_lines(network, buscodes_path, region_shapefile=False):
    """
    Aggregates cross-country or cross-region lines in a PyPSA network.
    Internal lines (within the same country or region) are dropped.

    Parameters
    ----------
    network : pypsa.Network
        The input PyPSA network with 'country' (ISO2) in buses.
    buscodes_path : str
        Path to buscodes CSV containing coordinate data, using only entries
        with node names ending in 'XX' and valid ISO3 codes.
    region_shapefile : str, optional
        Optional shapefile for custom regions.

    Returns
    -------
    agg_network : pypsa.Network
        New PyPSA network with aggregated buses and trans-region lines only.
    """
    if network.buses.empty:
        return pypsa.Network()

    buses = network.buses.copy()

    # Load and filter buscodes with national-level entries only (ending in XX)
    buscodes = pd.read_csv(buscodes_path)
    buscodes = buscodes[buscodes["Node"].str.endswith("XX")]
    buscodes = buscodes.set_index("Node")

    # Extract ISO3 and convert to ISO2, handle Kosovo
    buscodes["iso3"] = buscodes.index.str[:3]
    buscodes["iso2"] = buscodes["iso3"].apply(
        lambda x: "XK" if x == "KOS" else cc.convert(x, to="ISO2", not_found=None)
    )
    buscodes = buscodes.dropna(subset=["iso2"])

    # Use country-level buscodes to define central coordinates for countries
    region_centers = buscodes.groupby("iso2")[["Lat", "Long"]].mean()

    # Assign custom regions if shapefile is provided
    if region_shapefile != False:
        regions = gpd.read_file(region_shapefile)
        bus_gdf = gpd.GeoDataFrame(
            buses,
            geometry=[Point(xy) for xy in zip(buses["x"], buses["y"])],
            crs=regions.crs,
        )
        bus_gdf = gpd.sjoin(bus_gdf, regions, how="left")
        buses["region"] = bus_gdf.iloc[:, -1].fillna(
            buses["country"]
        )  # fallback to country
    else:
        buses["region"] = buses["country"]

    # Initialize new network
    agg_network = pypsa.Network()

    # Add one bus per region with coordinates from region_centers
    for region in buses["region"].unique():
        if region in region_centers.index:
            lat, lon = region_centers.loc[region, ["Lat", "Long"]]
        else:
            lat, lon = 0.0, 0.0  # fallback if no coords
        agg_network.add("Bus", name=region, x=lon, y=lat)

    # Aggregate cross-region lines
    line_data = []

    for _, line in network.lines.iterrows():
        r0 = buses.loc[line["bus0"], "region"]
        r1 = buses.loc[line["bus1"], "region"]
        if r0 != r1:
            key = tuple(sorted([r0, r1]))
            line_data.append((key, line["s_nom"], line["length"]))

    # Sum s_nom and length per region pair
    df = pd.DataFrame(line_data, columns=["regions", "s_nom", "length"])
    grouped = df.groupby("regions").sum().reset_index()

    # Add aggregated lines to network
    for (r0, r1), row in zip(grouped["regions"], grouped.itertuples()):
        agg_network.add(
            "Line",
            name=f"{r0}_{r1}",
            bus0=r0,
            bus1=r1,
            s_nom=row.s_nom,
            length=row.length,
        )

    return agg_network


def export_network_lines_to_geojson(network, output_path):
    """
    Export the line data of a PyPSA network to a GeoJSON file.

    Parameters
    ----------
    network : pypsa.Network
        The PyPSA network containing line and bus data with coordinates.
    output_path : str
        Path to the output GeoJSON file.
    """
    if network.lines.empty:
        with open(output_path, "w") as f:
            pass
        return
    features = []

    for name, line in network.lines.iterrows():
        bus0 = network.buses.loc[line["bus0"]]
        bus1 = network.buses.loc[line["bus1"]]

        # Geometry as a LineString between bus coordinates
        geometry = LineString([(bus0["x"], bus0["y"]), (bus1["x"], bus1["y"])])

        # Line properties to include
        properties = {
            "name": name,
            "bus0": line["bus0"],
            "bus1": line["bus1"],
            "s_nom": line["s_nom"],
            "length": line.get("length", None),
        }

        features.append({"geometry": geometry, "properties": properties})

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf.to_file(output_path, driver="GeoJSON")


if __name__ == "__main__":
    if "snakemake" not in globals():
        from helpers import mock_snakemake

        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        snakemake = mock_snakemake("build_network_geojson")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)

    buscodes = snakemake.input["buscodes"]
    lineexist = snakemake.input["lineexist"]
    lineplan = snakemake.input["lineplan"]
    network_path = snakemake.input["network_path"]
    shapefile = snakemake.params["shapefile"]
    country_list = snakemake.params["countries"]

    validate_cross_border_capacity = snakemake.params.get(
        "validate_cross_border_capacity", True
    )

    output_exist = snakemake.output["network_existing"]
    output_plan = snakemake.output["network_planned"]
    output_model = snakemake.output["network_model"]

    # Existing network GeoJSON
    if validate_cross_border_capacity:
        df_exist = pd.read_csv(lineexist, encoding="ISO-8859-1")
        n_exist = build_network(df_exist, buscodes, country_list)
        agg_exist = aggregate_cross_country_lines(
            n_exist, buscodes, region_shapefile=shapefile
        )
        export_network_lines_to_geojson(agg_exist, output_exist)
    else:
        export_network_lines_to_geojson(pypsa.Network(), output_exist)

    # Planned network GeoJSON
    if validate_cross_border_capacity:
        df_plan = pd.read_csv(lineplan, encoding="ISO-8859-1")
        n_plan = build_network(df_plan, buscodes, country_list, year=2040)
        agg_plan = aggregate_cross_country_lines(
            n_plan, buscodes, region_shapefile=shapefile
        )
        export_network_lines_to_geojson(agg_plan, output_plan)
    else:
        export_network_lines_to_geojson(pypsa.Network(), output_plan)

    # PyPSA Modeled network GeoJSON
    n_model = pypsa.Network(network_path)
    if not n_model.lines.empty:
        n_model = update_line_lengths_from_geometry(n_model)
        agg_model = aggregate_cross_country_lines(
            n_model, buscodes, region_shapefile=shapefile
        )
        export_network_lines_to_geojson(agg_model, output_model)
    else:
        export_network_lines_to_geojson(pypsa.Network(), output_model)
