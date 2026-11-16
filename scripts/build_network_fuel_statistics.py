# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calculate annual final energy consumption by sector and fuel from solved networks."""

import argparse
import logging
from pathlib import Path

import pandas as pd
import pypsa
import yaml
from build_network_co2_statistics import (
    component_regions,
    metadata_column,
    snapshot_weights,
)

logger = logging.getLogger(__name__)

MWH_TO_TWH = 1e-6
UNCLASSIFIED = "unclassified"

DETAIL_COLUMNS = [
    "region",
    "sector",
    "subsector",
    "fuel",
    "bus_carrier",
    "carrier",
    "component",
    "asset",
    "model_year",
    "consumption_twh",
    "consumption_source",
]

GROUP_COLUMNS = [
    "region",
    "sector",
    "subsector",
    "fuel",
    "bus_carrier",
    "component",
    "model_year",
    "consumption_source",
]

SUMMARY_COLUMNS = GROUP_COLUMNS + ["consumption_twh"]


def load_mapping(path):
    """Read the sector and fuel mapping."""
    with open(path) as f:
        cfg = yaml.safe_load(f)

    return {
        "sectors": {
            model: unsd for unsd, models in cfg["sectors"].items() for model in models
        },
        "carrier_sectors": {
            carrier: unsd
            for unsd, carriers in cfg.get("carrier_sectors", {}).items()
            for carrier in carriers
        },
        "sector_coupled_carrier_sectors": {
            carrier: unsd
            for unsd, carriers in cfg.get("sector_coupled_carrier_sectors", {}).items()
            for carrier in carriers
        },
        "fuels": {
            carrier: fuel
            for fuel, carriers in cfg["fuels"].items()
            for carrier in carriers
        },
        "end_use": set(cfg.get("end_use_bus_carriers", [])),
        "excluded": set(cfg.get("excluded_bus_carriers", [])),
    }


def apply_sector_coupled_fallback(n, mapping):
    """Add the sector-coupled carrier fallback when the network is sector-coupled.

    A network counts as sector-coupled when it has at least one load with a
    sector-specific carrier. Only then do the remaining 'AC' loads represent a
    single sector instead of the total electricity demand.
    """
    extra = mapping.get("sector_coupled_carrier_sectors", {})
    if not extra or not n.loads.carrier.isin(mapping["carrier_sectors"]).any():
        return mapping

    return {**mapping, "carrier_sectors": {**extra, **mapping["carrier_sectors"]}}


def bus_carriers(n, buses):
    """Return the carrier of each given bus name."""
    return buses.map(n.buses.carrier).fillna("").astype(str)


def create_detail(
    n, components, component_type, bus_carrier, twh, model_year, mapping, source
):
    """Convert component consumption into the common asset-level table."""
    if twh.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    comps = components.loc[twh.index]

    region = component_regions(n, comps, component_type)
    missing = region.eq("")
    if missing.any() and "country" in n.buses.columns:
        bus_col = "bus" if component_type == "Load" else "bus0"
        region.loc[missing] = (
            comps.loc[missing, bus_col]
            .map(n.buses.country)
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )

    sector = metadata_column(comps, "sector").map(mapping["sectors"])
    # Metadata wins; the carrier list only fills components without it.
    sector = sector.fillna(comps.carrier.map(mapping["carrier_sectors"]))
    fuel = bus_carrier.loc[twh.index].map(mapping["fuels"])

    detail = pd.DataFrame(index=twh.index)
    detail["region"] = region
    detail["sector"] = sector.fillna(UNCLASSIFIED)
    detail["subsector"] = metadata_column(comps, "subsector")
    detail["fuel"] = fuel.fillna(UNCLASSIFIED)
    detail["bus_carrier"] = bus_carrier.loc[twh.index]
    detail["carrier"] = comps.carrier.fillna("")
    detail["component"] = component_type
    detail["asset"] = twh.index
    detail["model_year"] = int(model_year)
    detail["consumption_twh"] = twh
    detail["consumption_source"] = source

    return detail[DETAIL_COLUMNS].reset_index(drop=True)


def load_profiles(n, names):
    """Return load profiles, using static p_set when no time series exists."""
    p_set = n.loads_t.p_set

    profiles = pd.DataFrame(
        {
            name: (
                p_set[name]
                if name in p_set.columns
                else pd.Series(n.loads.at[name, "p_set"], index=n.snapshots)
            )
            for name in names
        },
        index=n.snapshots,
    )

    missing = profiles.columns[profiles.isna().any()]
    if len(missing):
        logger.warning(
            "Skipping %s Loads with missing profile values: %s",
            len(missing),
            list(missing[:10]),
        )
        profiles = profiles.drop(columns=missing)

    return profiles


def load_consumption(n, model_year, weights, mapping):
    """Consumption of Loads on fuel buses; end-use bus Loads are skipped."""
    if n.loads.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS), pd.Series(dtype=float)

    carrier = bus_carriers(n, n.loads.bus)
    excluded = carrier.isin(mapping["excluded"])
    end_use = carrier.isin(mapping["end_use"])

    # Demand on end-use buses is kept only for the supply diagnostic below.
    end_use_names = n.loads.index[end_use & ~excluded]
    end_use_twh = (
        load_profiles(n, end_use_names).mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH
    )
    end_use_demand = end_use_twh.groupby(carrier.loc[end_use_twh.index]).sum()

    names = n.loads.index[~end_use & ~excluded]
    if names.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS), end_use_demand

    twh = load_profiles(n, names).mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH

    detail = create_detail(
        n, n.loads, "Load", carrier, twh, model_year, mapping, "load_fuel_bus"
    )

    return detail, end_use_demand


def link_consumption(n, model_year, weights, mapping):
    """Fuel entering links that deliver to an end-use bus (p0 side)."""
    empty = pd.DataFrame(columns=DETAIL_COLUMNS), pd.Series(dtype=float)

    if n.links.empty:
        return empty

    input_carrier = bus_carriers(n, n.links.bus0)
    output_carrier = bus_carriers(n, n.links.bus1)

    feeds_end_use = output_carrier.isin(mapping["end_use"])

    # Energy delivered to end-use buses, for the supply diagnostic.
    p1 = n.links_t.p1.reindex(index=n.snapshots)
    delivered_names = n.links.index[feeds_end_use].intersection(p1.columns)
    delivered = (
        (-p1[delivered_names].mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH)
        .groupby(output_carrier.loc[delivered_names])
        .sum()
    )

    counted = feeds_end_use & ~input_carrier.isin(mapping["end_use"])
    counted &= ~input_carrier.isin(mapping["excluded"])
    names = n.links.index[counted]

    if names.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS), delivered

    p0 = n.links_t.p0.reindex(index=n.snapshots, columns=names)
    if p0.isna().any().any():
        raise ValueError("Missing Link dispatch.")

    twh = p0.mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH

    detail = create_detail(
        n, n.links, "Link", input_carrier, twh, model_year, mapping, "link_input"
    )

    return detail, delivered


def log_end_use_supply(demand, delivered):
    """Report how much end-use demand is covered by counted link outputs."""
    table = pd.DataFrame({"load_twh": demand, "link_delivered_twh": delivered})
    table = table.fillna(0.0)

    if table.empty:
        return

    table["not_from_links_twh"] = table.load_twh - table.link_delivered_twh
    logger.info(
        "End-use demand vs energy delivered by counted links [TWh]:\n%s",
        table.round(3).to_string(),
    )


def build_statistics(n, model_year, mapping):
    """Build asset-level and aggregated final energy consumption statistics."""
    weights = snapshot_weights(n)
    mapping = apply_sector_coupled_fallback(n, mapping)

    loads, end_use_demand = load_consumption(n, model_year, weights, mapping)
    links, delivered = link_consumption(n, model_year, weights, mapping)

    log_end_use_supply(end_use_demand, delivered)

    detail = pd.concat([loads, links], ignore_index=True)[DETAIL_COLUMNS]

    if detail.empty:
        logger.warning("No final energy consumption found in the network.")
        return detail, pd.DataFrame(columns=SUMMARY_COLUMNS)

    summary = (
        detail.groupby(GROUP_COLUMNS, dropna=False)["consumption_twh"]
        .sum(min_count=1)
        .reset_index()
    )

    for column in ["sector", "fuel"]:
        share = detail.loc[detail[column].eq(UNCLASSIFIED), "consumption_twh"].sum()
        if share > 0:
            logger.warning(
                "%.3f TWh of consumption has unclassified %s "
                "(missing metadata or unmapped carrier).",
                share,
                column,
            )

    missing_region = detail.region.eq("")
    if missing_region.any():
        logger.warning(
            "%s consuming components have no country assignment.",
            missing_region.sum(),
        )

    return detail, summary[SUMMARY_COLUMNS]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--detail-output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    n = pypsa.Network(args.network)
    mapping = load_mapping(args.mapping)
    detail, summary = build_statistics(n, args.year, mapping)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output, index=False)

    if args.detail_output:
        detail_output = Path(args.detail_output)
        detail_output.parent.mkdir(parents=True, exist_ok=True)
        detail.to_csv(detail_output, index=False)

    if not summary.empty:
        totals = summary.groupby(["region", "sector"])["consumption_twh"].sum()
        logger.info("Annual final energy consumption [TWh]:\n%s", totals.to_string())


if __name__ == "__main__":
    main()
