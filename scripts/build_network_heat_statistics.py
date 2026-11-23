# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calculate annual heating sector statistics from solved PyPSA networks."""

import argparse
import logging
from pathlib import Path

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

HEAT_BUS_KEYWORDS = ("heat", "water tanks", "water pits")
STORAGE_KEYWORDS = ("water tanks", "water pits")

COLUMNS = [
    "carrier",
    "component",
    "category",
    "capacity_mw",
    "heat_output_mwh",
    "input_mwh",
    "efficiency",
]


def snapshot_weights(n):
    """Return generator snapshot weights, validating their completeness."""
    weights = n.snapshot_weightings.generators.reindex(n.snapshots)

    if weights.isna().any() or (weights < 0).any():
        raise ValueError("Invalid generator snapshot weights.")

    return weights


def is_heat_carrier(carrier):
    """Return True if a bus carrier belongs to the heating sector."""
    return any(keyword in str(carrier) for keyword in HEAT_BUS_KEYWORDS)


def heat_category(carrier):
    """Classify a heating carrier as thermal storage or heat production."""
    if any(keyword in carrier for keyword in STORAGE_KEYWORDS):
        return "storage"
    return "production"


def link_heat_statistics(n, weights):
    """Annual heat output, input and capacity of links that feed heat buses."""
    bus_carrier = n.buses.carrier
    output_port = pd.Series(index=n.links.index, dtype=object)

    # The heat output port is the first output bus (bus1, bus2, ...) on a heat bus
    for port in sorted(col[3:] for col in n.links.columns if col.startswith("bus")):
        if port == "0":
            continue
        buses = n.links[f"bus{port}"]
        on_heat_bus = buses.map(bus_carrier).map(is_heat_carrier)
        output_port = output_port.where(output_port.notna() | ~on_heat_bus, port)

    output_port = output_port.dropna()

    if output_port.empty:
        return pd.DataFrame(columns=COLUMNS)

    heat_output = pd.Series(
        {
            link: -(getattr(n.links_t, f"p{port}")[link] * weights).sum()
            for link, port in output_port.items()
        }
    )
    links = output_port.index
    energy_input = n.links_t.p0[links].mul(weights, axis=0).sum()

    table = pd.DataFrame(
        {
            "carrier": n.links.loc[links, "carrier"],
            "component": "Link",
            "capacity_mw": n.links.loc[links, "p_nom_opt"],
            "heat_output_mwh": heat_output,
            "input_mwh": energy_input,
        }
    )
    return table


def generator_heat_statistics(n, weights):
    """Annual heat output and capacity of generators on heat buses (solar thermal)."""
    on_heat_bus = n.generators.bus.map(n.buses.carrier).map(is_heat_carrier)
    generators = n.generators.index[on_heat_bus.fillna(False).astype(bool)]
    generators = generators[n.generators.loc[generators, "carrier"] != "load shedding"]

    if generators.empty:
        return pd.DataFrame(columns=COLUMNS)

    table = pd.DataFrame(
        {
            "carrier": n.generators.loc[generators, "carrier"],
            "component": "Generator",
            "capacity_mw": n.generators.loc[generators, "p_nom_opt"],
            "heat_output_mwh": n.generators_t.p[generators].mul(weights, axis=0).sum(),
            "input_mwh": float("nan"),
        }
    )
    return table


def build_statistics(n):
    """Return annual heating statistics aggregated by carrier."""
    weights = snapshot_weights(n)

    assets = pd.concat(
        [link_heat_statistics(n, weights), generator_heat_statistics(n, weights)]
    )

    if assets.empty:
        logger.warning("No heating components found in the network.")
        return pd.DataFrame(columns=COLUMNS)

    table = (
        assets.groupby(["carrier", "component"], as_index=False)[
            ["capacity_mw", "heat_output_mwh", "input_mwh"]
        ]
        .sum(min_count=1)
        .sort_values("heat_output_mwh", ascending=False)
    )
    table["category"] = table["carrier"].map(heat_category)
    # Annual average efficiency (COP for heat pumps) = heat output / energy input
    table["efficiency"] = table["heat_output_mwh"] / table["input_mwh"]

    return table[COLUMNS].reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    n = pypsa.Network(args.network)
    table = build_statistics(n)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output, index=False)

    production = table[table["category"] == "production"]
    logger.info(
        "Annual heat production by carrier [TWh]:\n%s",
        (production.set_index("carrier")["heat_output_mwh"] / 1e6).to_string(),
    )


if __name__ == "__main__":
    main()
