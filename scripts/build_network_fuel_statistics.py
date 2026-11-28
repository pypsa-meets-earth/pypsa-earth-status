# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calculate annual final energy consumption by sector and fuel from solved networks."""

import argparse
import logging
from pathlib import Path

import pandas as pd
import pypsa
from build_network_co2_statistics import (
    component_regions,
    metadata_column,
    snapshot_weights,
)
from network_capabilities import is_sector_coupled, load_mapping

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


def apply_sector_coupled_fallback(n, mapping):
    """Add the sector-coupled carrier fallback when the network is sector-coupled.

    A network counts as sector-coupled when it has at least one load with a
    sector-specific carrier. Only then do the remaining 'AC' loads represent a
    single sector instead of the total electricity demand.
    """
    extra = mapping.get("sector_coupled_carrier_sectors", {})
    if not extra or not is_sector_coupled(n, mapping):
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
        bus_col = "bus" if component_type in {"Load", "Generator"} else "bus0"
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


def subtract_dedicated_load_shedding(n, profiles, weights, mapping):
    """Exclude artificial supply from final Loads on unshared demand buses.

    Do not allocate shedding on shared buses or buses with other withdrawals.
    Positive Link port flow means withdrawal from that bus in PyPSA.
    """
    if profiles.empty or n.generators.empty:
        return profiles

    carrier = (
        n.generators.carrier.fillna("")
        .astype(str)
        .str.casefold()
        .str.replace("_", " ", regex=False)
    )
    shedding = n.generators.loc[carrier.eq("load shedding")]
    if shedding.empty:
        return profiles

    load_sectors = component_sectors(n.loads.loc[profiles.columns], mapping)
    loads_per_bus = n.loads.bus.value_counts()
    shedding_buses = set(shedding.bus)

    blocked_buses = set()
    for component in (n.stores, n.storage_units):
        blocked_buses.update(component.bus.dropna())
    for component in (n.lines, n.transformers):
        blocked_buses.update(component.bus0.dropna())
        blocked_buses.update(component.bus1.dropna())

    candidates = [
        name
        for name in profiles.columns
        if n.loads.at[name, "bus"] in shedding_buses
        and loads_per_bus.get(n.loads.at[name, "bus"], 0) == 1
        and n.loads.at[name, "bus"] not in blocked_buses
        and pd.notna(load_sectors.at[name])
        and load_sectors.at[name] != UNCLASSIFIED
    ]
    if not candidates:
        return profiles

    # A Link can withdraw from any port, including on reversible Links.
    candidate_buses = set(n.loads.loc[candidates, "bus"])
    for port in link_ports(n):
        bus_col = f"bus{port}"
        attached = n.links.index[n.links[bus_col].isin(candidate_buses)]
        if attached.empty:
            continue
        flow = n.links_t.get(f"p{port}", pd.DataFrame())
        dispatch = flow.reindex(index=n.snapshots, columns=attached)
        withdrawing_or_unknown = dispatch.isna().any() | dispatch.gt(1e-5).any()
        blocked_buses.update(
            n.links.loc[withdrawing_or_unknown[withdrawing_or_unknown].index, bus_col]
        )

    names = [
        name for name in candidates if n.loads.at[name, "bus"] not in blocked_buses
    ]
    if not names:
        return profiles

    shedding_dispatch = n.generators_t.p.reindex(
        index=n.snapshots, columns=shedding.index
    )
    if shedding_dispatch.isna().any().any():
        raise ValueError("Missing load shedding generator dispatch.")
    shedding_by_bus = shedding_dispatch.clip(lower=0).T.groupby(shedding.bus).sum().T

    served = profiles.copy()
    subtracted_twh = 0.0
    corrected = 0
    for name in names:
        bus = n.loads.at[name, "bus"]
        artificial_supply = shedding_by_bus[bus]
        demand = profiles[name]
        if (artificial_supply - demand).gt(1e-5).any():
            logger.warning(
                "Not subtracting load shedding on %s: dispatch exceeds "
                "its only final Load in at least one snapshot.",
                bus,
            )
            continue
        served[name] = (demand - artificial_supply).clip(lower=0)
        subtracted_twh += artificial_supply.mul(weights).sum() * MWH_TO_TWH
        corrected += 1

    if corrected:
        logger.info(
            "Subtracted %.6f TWh of load shedding from %d dedicated final Loads.",
            subtracted_twh,
            corrected,
        )
    return served


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

    profiles = load_profiles(n, names)
    profiles = subtract_dedicated_load_shedding(n, profiles, weights, mapping)
    twh = profiles.mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH

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


SHEDDING_COLUMNS = [
    "region",
    "sector",
    "fuel",
    "bus_carrier",
    "model_year",
    "unserved_twh",
    "load_demand_twh",
    "unserved_pct",
]


def solar_thermal_consumption(n, model_year, weights, mapping):
    """Count solar heat delivered directly to decentralized end-use heat buses."""
    if n.generators.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    carrier = (
        n.generators.carrier.fillna("")
        .astype(str)
        .str.casefold()
        .str.replace("_", " ", regex=False)
    )
    bus_carrier = bus_carriers(n, n.generators.bus)
    valid = (
        carrier.str.contains(r"solar.*thermal", regex=True)
        & bus_carrier.isin(mapping["end_use"])
        & ~bus_carrier.isin(mapping["district_heating"])
    )
    selected = n.generators.index[valid]
    if selected.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    dispatch = n.generators_t.p.reindex(index=n.snapshots, columns=selected)
    if dispatch.isna().any().any():
        raise ValueError("Missing solar thermal generator dispatch.")
    annual = dispatch.mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH
    annual = annual[annual.gt(0)]
    if annual.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    detail = create_detail(
        n,
        n.generators,
        "Generator",
        bus_carrier,
        annual,
        model_year,
        mapping,
        "direct_solar_thermal",
    )
    detail["sector"] = (
        detail["bus_carrier"].map(mapping["carrier_sectors"]).fillna(detail["sector"])
    )
    detail["fuel"] = "heat"
    return detail[DETAIL_COLUMNS]


def load_shedding_statistics(n, model_year, weights, mapping):
    """Summarize unmet demand without treating load shedding as a fuel."""
    if n.generators.empty:
        return pd.DataFrame(columns=SHEDDING_COLUMNS)

    carriers = (
        n.generators.carrier.fillna("")
        .astype(str)
        .str.casefold()
        .str.replace("_", " ", regex=False)
    )
    names = n.generators.index[carriers.eq("load shedding")]
    if names.empty:
        return pd.DataFrame(columns=SHEDDING_COLUMNS)

    dispatch = n.generators_t.p.reindex(index=n.snapshots, columns=names)
    if dispatch.isna().any().any():
        raise ValueError("Missing load shedding dispatch.")
    annual = dispatch.clip(lower=0).mul(weights, axis=0).sum(axis=0) * MWH_TO_TWH
    active = annual.index[annual.gt(0)]
    if active.empty:
        return pd.DataFrame(columns=SHEDDING_COLUMNS)

    generators = n.generators.loc[active]
    per_bus = pd.DataFrame(
        {
            "region": component_regions(n, generators, "Generator"),
            "bus": generators.bus,
            "unserved_twh": annual.loc[active],
        }
    )
    per_bus = per_bus.groupby(["region", "bus"], as_index=False)["unserved_twh"].sum()
    per_bus["bus_carrier"] = per_bus["bus"].map(n.buses.carrier).fillna("")
    per_bus["sector"] = (
        per_bus["bus_carrier"].map(mapping["carrier_sectors"]).fillna(UNCLASSIFIED)
    )
    per_bus["fuel"] = per_bus["bus_carrier"].map(mapping["fuels"])
    heat_buses = per_bus["bus_carrier"].str.casefold().str.endswith(" heat")
    per_bus.loc[heat_buses, "fuel"] = "heat"
    per_bus["fuel"] = per_bus["fuel"].fillna(UNCLASSIFIED)
    per_bus["model_year"] = int(model_year)

    # Only quote an unmet-demand share when same-bus final Loads identify demand.
    relevant = per_bus.loc[per_bus.sector.ne(UNCLASSIFIED), "bus"]
    names = n.loads.index[n.loads.bus.isin(relevant)]
    demand = pd.Series(dtype=float)
    if len(names):
        annual_load = (
            load_profiles(n, names).clip(lower=0).mul(weights, axis=0).sum(axis=0)
            * MWH_TO_TWH
        )
        demand = annual_load.groupby(n.loads.loc[names, "bus"]).sum()
    per_bus["load_demand_twh"] = per_bus["bus"].map(demand)
    per_bus.loc[per_bus.sector.eq(UNCLASSIFIED), "load_demand_twh"] = float("nan")

    grouped = per_bus.groupby(
        ["region", "sector", "fuel", "bus_carrier", "model_year"],
        as_index=False,
        dropna=False,
    ).agg(
        unserved_twh=("unserved_twh", "sum"),
        load_demand_twh=(
            "load_demand_twh",
            lambda values: values.sum() if values.notna().all() else float("nan"),
        ),
    )
    grouped["unserved_pct"] = (
        100
        * grouped["unserved_twh"]
        / grouped["load_demand_twh"].where(grouped["load_demand_twh"].gt(0))
    )
    return grouped[SHEDDING_COLUMNS]


def build_statistics(n, model_year, mapping):
    """Build asset-level and aggregated final energy consumption statistics."""
    weights = snapshot_weights(n)
    mapping = apply_sector_coupled_fallback(n, mapping)

    loads, end_use_demand, end_use_twh = load_consumption(
        n, model_year, weights, mapping
    )
    links, delivered = link_consumption(n, model_year, weights, mapping, end_use_twh)

    log_end_use_supply(end_use_demand, delivered)

    solar = solar_thermal_consumption(n, model_year, weights, mapping)
    detail = pd.concat([loads, links, solar], ignore_index=True)[DETAIL_COLUMNS]

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
    parser.add_argument("--shedding-output")
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

    if args.shedding_output:
        shedding = load_shedding_statistics(
            n,
            args.year,
            snapshot_weights(n),
            apply_sector_coupled_fallback(n, mapping),
        )
        shedding_path = Path(args.shedding_output)
        shedding_path.parent.mkdir(parents=True, exist_ok=True)
        shedding.to_csv(shedding_path, index=False)
        logger.info("Annual load shedding: %.3f TWh", shedding.unserved_twh.sum())

    if not summary.empty:
        totals = summary.groupby(["region", "sector"])["consumption_twh"].sum()
        logger.info("Annual final energy consumption [TWh]:\n%s", totals.to_string())


if __name__ == "__main__":
    main()
