# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Identify actionable transmission network validation findings."""

import logging

import numpy as np
import pandas as pd
import pypsa
from helpers import configure_logging

logger = logging.getLogger(__name__)

CAPACITY_RATIO_MIN = 0.8
CAPACITY_RATIO_MAX = 1.2
UTILIZATION_THRESHOLD = 0.99
EXPANSION_THRESHOLD = 0.2
SHEDDING_THRESHOLD_MW = 0.1

COLUMNS = [
    "severity",
    "category",
    "bus0",
    "bus1",
    "value",
    "unit",
    "parameters_to_check",
    "description",
]


def add_operational_diagnostics(network, region_map, add):
    """Report transmission constraints and significant unmet demand."""
    dc_carriers = {"dc", "dc link", "hvdc", "b2b"}
    congested_branches = {}

    components = [
        ("Line", network.lines, network.lines_t.p0, "s_nom", "MVA"),
        (
            "Link",
            network.links.loc[network.links.carrier.str.lower().isin(dc_carriers)],
            network.links_t.p0,
            "p_nom",
            "MW",
        ),
    ]

    for component, branches, dispatch, nominal, unit in components:
        if branches.empty:
            continue

        nominal_capacity = branches[nominal]
        optimized_capacity = branches[f"{nominal}_opt"].where(
            branches[f"{nominal}_extendable"],
            nominal_capacity,
        )

        # Report expansion separately from congestion.
        for name, branch in branches.iterrows():
            original = nominal_capacity.at[name]
            optimized = optimized_capacity.at[name]
            expansion = optimized - original

            if (
                branch[f"{nominal}_extendable"]
                and expansion > 1.0
                and expansion > EXPANSION_THRESHOLD * original
            ):
                add(
                    "info",
                    "transmission_expansion",
                    branch.bus0,
                    branch.bus1,
                    expansion,
                    unit,
                    "scenario.ll; transmission expansion limits",
                    f"{name}: nominal capacity {original:.2f}; "
                    f"optimized capacity {optimized:.2f}.",
                )

        active = branches.index.intersection(dispatch.columns)

        if active.empty or dispatch.empty:
            logger.info("No transmission dispatch available for %s.", component)
            continue

        flow = dispatch.loc[:, active]
        ratings = optimized_capacity.reindex(active)

        if component == "Line":
            parameter = "s_max_pu"

            upper = network.get_switchable_as_dense(component, parameter).reindex(
                columns=active
            )

            factor = upper
            parameters = "lines.s_max_pu; nominal line capacity"

        else:
            upper = network.get_switchable_as_dense(component, "p_max_pu").reindex(
                columns=active
            )

            lower = network.get_switchable_as_dense(component, "p_min_pu").reindex(
                columns=active
            )

            factor = upper.where(flow >= 0, -lower)
            parameters = "links.p_max_pu; links.p_min_pu; nominal link capacity"

        limits = factor.mul(ratings, axis=1)
        utilization = flow.abs().div(limits.where(limits > 0))

        for name in active:
            values = utilization[name].dropna()

            if values.empty or values.max() < UTILIZATION_THRESHOLD:
                continue

            peak = values.idxmax()
            branch = branches.loc[name]
            saturated = int((values >= UTILIZATION_THRESHOLD).sum())

            for bus in [branch.bus0, branch.bus1]:
                region = region_map.get(bus, bus)
                congested_branches.setdefault(region, []).append(
                    (f"{component} {name}", values)
                )

            add(
                "warning",
                "transmission_congestion",
                branch.bus0,
                branch.bus1,
                100 * values.max(),
                "%",
                parameters,
                f"{name}: {saturated} saturated snapshots; "
                f"peak at {peak}; "
                f"flow {abs(flow.at[peak, name]):.2f} MW; "
                f"effective limit {limits.at[peak, name]:.2f} MW; "
                f"capacity factor {factor.at[peak, name]:.3f}; "
                f"nominal rating {ratings.at[name]:.2f} {unit}.",
            )

    # Associate electricity distribution and EV buses with their AC regions.
    electrical_regions = region_map.to_dict()

    for carrier in ["electricity distribution grid", "bev charger"]:
        links = network.links.loc[network.links.carrier.str.lower().eq(carrier)]

        for link in links.itertuples():
            if link.bus0 in electrical_regions:
                electrical_regions[link.bus1] = electrical_regions[link.bus0]

    generators = network.generators
    shedding = generators.loc[generators.carrier.str.lower().eq("load shedding")]

    dispatch = network.generators_t.p
    active = shedding.index.intersection(dispatch.columns)

    if active.empty or dispatch.empty:
        logger.info("No load shedding dispatch available.")
        return

    unmet = (
        dispatch.loc[:, active].mul(shedding.loc[active, "sign"], axis=1).clip(lower=0)
    )

    by_bus = unmet.T.groupby(shedding.loc[active, "bus"]).sum().T

    weights = network.snapshot_weightings.generators
    weighted_energy = by_bus.mul(weights, axis=0).sum()

    for bus in by_bus.columns:
        peak = by_bus[bus].max()

        if not np.isfinite(peak) or peak < SHEDDING_THRESHOLD_MW:
            continue

        region = electrical_regions.get(bus, "")
        carrier = network.buses.at[bus, "carrier"]
        peak_snapshot = by_bus[bus].idxmax()

        coincident = [
            name
            for name, values in congested_branches.get(region, [])
            if values.get(peak_snapshot, 0.0) >= UTILIZATION_THRESHOLD
        ]

        congestion_context = ", ".join(coincident) if coincident else "none detected"

        add(
            "warning",
            "load_shedding",
            region,
            bus,
            peak,
            "MW",
            "transmission; distribution; local supply; demand",
            f"{carrier}: peak unmet demand {peak:.2f} MW; "
            f"weighted unserved energy {weighted_energy.at[bus]:.2f} MWh; "
            f"peak at {peak_snapshot}. "
            f"Adjacent congested branches at shedding peak: "
            f"{congestion_context}.",
        )


def build_diagnostics(network, corridors, capacity, mapping, region_map):
    """Identify structural transmission validation findings."""
    records = []

    def add(severity, category, bus0, bus1, value, unit, parameters, description):
        records.append(
            dict(
                zip(
                    COLUMNS,
                    [
                        severity,
                        category,
                        bus0,
                        bus1,
                        value,
                        unit,
                        parameters,
                        description,
                    ],
                )
            )
        )

    # Identify corridors consisting exclusively of B2B converters.
    b2b = network.links[network.links.carrier.str.lower().eq("b2b")].copy()

    b2b["region0"] = b2b.bus0.map(region_map)
    b2b["region1"] = b2b.bus1.map(region_map)

    b2b_counts = (
        (
            b2b.dropna(subset=["region0", "region1"])
            .apply(
                lambda row: tuple(sorted([row.region0, row.region1])),
                axis=1,
            )
            .value_counts()
        )
        if not b2b.empty
        else pd.Series(dtype=int)
    )

    for row in corridors.itertuples(index=False):
        pair = tuple(sorted([row.bus0, row.bus1]))

        if row.status == "osm_only":
            add(
                "warning",
                "missing_corridor",
                *pair,
                row.osm_line_count,
                "lines",
                "base_network; clustering.simplify_network",
                "OSM corridor not represented in the evaluated network.",
            )

        elif row.status == "pypsa_only":
            only_b2b = (
                row.pypsa_ac_branch_count == 0
                and row.pypsa_dc_branch_count > 0
                and b2b_counts.get(pair, 0) == row.pypsa_dc_branch_count
            )

            add(
                "info" if only_b2b else "warning",
                "b2b_converter" if only_b2b else "pypsa_only_corridor",
                *pair,
                row.pypsa_dc_branch_count + row.pypsa_ac_branch_count,
                "branches",
                "base_network; links",
                (
                    "B2B converter without a direct OSM line counterpart."
                    if only_b2b
                    else "PyPSA corridor without a matching OSM corridor."
                ),
            )

    # Compare nominal capacities rather than optimized capacities.
    for row in capacity.itertuples(index=False):
        if row.capacity_status != "comparable":
            continue

        ratio = row.nominal_capacity_ratio

        if ratio < CAPACITY_RATIO_MIN or ratio > CAPACITY_RATIO_MAX:
            add(
                "warning",
                "capacity_discrepancy",
                row.bus0,
                row.bus1,
                ratio,
                "ratio",
                "lines.ac_types; lines.use_country_specific_types; clustering",
                "Nominal AC capacity differs from the OSM-derived estimate.",
            )

    # Report mapping coverage and distinguish isolated clusters.
    for status, group in mapping.groupby("mapping_status"):
        if status == "assigned":
            continue

        add(
            "info" if status == "outside_transmission_regions" else "warning",
            status,
            "",
            "",
            len(group),
            "buses",
            "clustering.simplify_network",
            (
                "OSM buses mapped outside transmission regions."
                if status == "outside_transmission_regions"
                else "OSM buses without a valid region assignment."
            ),
        )

    add_operational_diagnostics(network, region_map, add)

    result = pd.DataFrame(records, columns=COLUMNS)

    return result.sort_values(
        "severity",
        key=lambda values: values.map({"warning": 0, "info": 1}),
    ).reset_index(drop=True)


if __name__ == "__main__":
    configure_logging(snakemake)

    network = pypsa.Network(snakemake.input["network_path"])

    corridors = pd.read_csv(snakemake.input["corridors"])
    capacity = pd.read_csv(snakemake.input["capacity"])
    mapping = pd.read_csv(snakemake.input["osm_mapping"], dtype=str)

    region_map = pd.read_csv(snakemake.input["bus_region_map"], dtype=str).set_index(
        "bus"
    )["region_id"]

    result = build_diagnostics(network, corridors, capacity, mapping, region_map)

    result.to_csv(snakemake.output["diagnostics"], index=False)

    for row in result.itertuples(index=False):
        log = logger.warning if row.severity == "warning" else logger.info

        log(
            "%s [%s - %s]: %s Value: %s %s. Check: %s",
            row.category,
            row.bus0,
            row.bus1,
            row.description,
            row.value,
            row.unit,
            row.parameters_to_check,
        )
