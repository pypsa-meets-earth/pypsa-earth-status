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
        "district_heating": set(cfg.get("district_heating_bus_carriers", [])),
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


def component_sectors(components, mapping):
    """UNSD sector of each component; NaN when it cannot be classified."""
    sector = metadata_column(components, "sector").map(mapping["sectors"])
    # Metadata wins; the carrier list only fills components without it.
    return sector.fillna(components.carrier.map(mapping["carrier_sectors"]))


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

    sector = component_sectors(comps, mapping)
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
    """Consumption of Loads on fuel and district heating buses.

    Loads on end-use buses are not counted here, because their supply is
    counted at the Link inputs. Their annual energy is returned to split those
    inputs between sectors and for the supply diagnostic.
    """
    empty = pd.DataFrame(columns=DETAIL_COLUMNS), pd.Series(dtype=float)
    if n.loads.empty:
        return (*empty, pd.Series(dtype=float))

    carrier = bus_carriers(n, n.loads.bus)
    excluded = carrier.isin(mapping["excluded"])
    end_use = carrier.isin(mapping["end_use"])

    end_use_names = n.loads.index[end_use & ~excluded]
    end_use_twh = (
        load_profiles(n, end_use_names).mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH
    )
    end_use_demand = end_use_twh.groupby(carrier.loc[end_use_twh.index]).sum()

    names = n.loads.index[~end_use & ~excluded]
    if names.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS), end_use_demand, end_use_twh

    twh = load_profiles(n, names).mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH

    detail = create_detail(
        n, n.loads, "Load", carrier, twh, model_year, mapping, "load_fuel_bus"
    )
    # District heat is final energy where it is delivered, as in UNSD.
    district = detail["bus_carrier"].isin(mapping["district_heating"])
    detail.loc[district, "consumption_source"] = "load_district_heat"

    return detail, end_use_demand, end_use_twh


def link_ports(n):
    """Port numbers of the Link buses present in the network (0, 1, 2, ...)."""
    ports = [
        int(column[3:])
        for column in n.links.columns
        if column.startswith("bus") and column[3:].isdigit()
    ]
    return sorted(ports)


def port_energy(n, port, names, weights):
    """Annual energy in TWh at one Link port; positive means withdrawn."""
    flows = n.links_t.get(f"p{port}", pd.DataFrame())
    flows = flows.reindex(index=n.snapshots, columns=names).fillna(0.0)
    return flows.mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH


def bus_sector_shares(n, end_use_twh, mapping):
    """Share of each end-use bus's annual load energy by sector.

    Buses whose loads have no classified sector are left out, so that the
    supplying Link keeps its own sector.
    """
    if end_use_twh.empty:
        return pd.DataFrame(columns=["bus", "sector", "share"])

    loads = n.loads.loc[end_use_twh.index]
    table = pd.DataFrame(
        {
            "bus": loads.bus,
            "sector": component_sectors(loads, mapping).fillna(UNCLASSIFIED),
            "twh": end_use_twh,
        }
    )
    classified = table.groupby("bus")["sector"].transform(
        lambda s: s.ne(UNCLASSIFIED).any()
    )
    table = table[classified & table["twh"].gt(0)]

    shares = table.groupby(["bus", "sector"], as_index=False)["twh"].sum()
    shares["share"] = shares["twh"] / shares.groupby("bus")["twh"].transform("sum")

    shared = shares.groupby("bus")["sector"].nunique().gt(1)
    if shared.any():
        logger.info(
            "Link inputs to %s end-use buses shared by several sectors are split "
            "by the sectors' load energy, e.g. %s.",
            shared.sum(),
            list(shared[shared].index[:3]),
        )

    return shares[["bus", "sector", "share"]]


def link_consumption(n, model_year, weights, mapping, end_use_twh):
    """Fuel entering Links that deliver energy to end-use buses.

    Only the share of the input that ends up on end-use buses is counted, in
    proportion to the output energy: for a micro CHP feeding electricity to the
    grid and heat to a household heat bus, only the heat share is final
    consumption. Links into district heating are energy transformations and are
    not counted; the heat is counted at the district heating loads instead.
    """
    empty = pd.DataFrame(columns=DETAIL_COLUMNS), pd.Series(dtype=float)

    if n.links.empty:
        return empty

    input_carrier = bus_carriers(n, n.links.bus0)
    not_final = mapping["end_use"] | mapping["district_heating"] | mapping["excluded"]
    candidates = n.links.index[~input_carrier.isin(not_final)]

    useful = pd.Series(0.0, index=n.links.index)
    deliveries = []
    for port in link_ports(n)[1:]:
        bus = n.links[f"bus{port}"].fillna("").astype(str)
        carrier = bus_carriers(n, bus)
        output = -port_energy(n, port, n.links.index, weights)

        delivers = bus.ne("") & ~carrier.isin(mapping["excluded"]) & output.gt(0)
        useful += output.where(delivers, 0.0)

        to_end_use = delivers & carrier.isin(mapping["end_use"])
        deliveries.append(
            pd.DataFrame(
                {
                    "link": n.links.index[to_end_use],
                    "bus": bus[to_end_use],
                    "bus_carrier": carrier[to_end_use],
                    "output_twh": output[to_end_use],
                }
            )
        )

    deliveries = pd.concat(deliveries, ignore_index=True)

    # Energy delivered to end-use buses, for the supply diagnostic.
    delivered = deliveries.groupby("bus_carrier")["output_twh"].sum()

    deliveries = deliveries[deliveries["link"].isin(candidates)]
    if deliveries.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS), delivered

    names = pd.Index(deliveries["link"].unique())
    p0 = n.links_t.p0.reindex(index=n.snapshots, columns=names)
    if p0.isna().any().any():
        raise ValueError("Missing Link dispatch.")
    input_twh = p0.mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH

    deliveries["twh"] = (
        deliveries["link"].map(input_twh)
        * deliveries["output_twh"]
        / deliveries["link"].map(useful)
    )

    # Split by the sectors of the loads on the supplied bus.
    shares = bus_sector_shares(n, end_use_twh, mapping)
    allocation = deliveries.merge(shares, on="bus", how="left")
    allocation["share"] = allocation["share"].fillna(1.0)
    allocation["twh"] *= allocation["share"]
    # Sector named by the supplied bus (e.g. 'residential rural heat').
    allocation["bus_sector"] = allocation["bus_carrier"].map(mapping["carrier_sectors"])
    allocation = allocation.groupby(
        ["link", "sector", "bus_sector"], dropna=False, as_index=False
    )["twh"].sum()

    totals = allocation.groupby("link")["twh"].sum()
    detail = create_detail(
        n, n.links, "Link", input_carrier, totals, model_year, mapping, "link_input"
    )

    # One row per Link and supplied sector. Without classified loads on the
    # supplied bus, the Link's own sector is used, then the bus's sector.
    detail = detail.drop(columns="consumption_twh").merge(
        allocation.rename(columns={"link": "asset", "sector": "load_sector"}),
        on="asset",
    )
    link_sector = detail["sector"].mask(detail["sector"].eq(UNCLASSIFIED))
    detail["sector"] = (
        detail["load_sector"]
        .fillna(link_sector)
        .fillna(detail["bus_sector"])
        .fillna(UNCLASSIFIED)
    )
    detail = detail.rename(columns={"twh": "consumption_twh"})

    return detail[DETAIL_COLUMNS].reset_index(drop=True), delivered


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

    loads, end_use_demand, end_use_twh = load_consumption(
        n, model_year, weights, mapping
    )
    links, delivered = link_consumption(n, model_year, weights, mapping, end_use_twh)

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
