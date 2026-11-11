# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calculate annual direct CO2 emissions from solved PyPSA networks."""

import argparse
import logging
from pathlib import Path

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

ELECTRICITY_SECTOR = "power_and_heat_generation"
TONNES_TO_MEGATONNES = 1e-6

DETAIL_COLUMNS = [
    "region",
    "sector",
    "subsector",
    "carrier",
    "component",
    "asset",
    "model_year",
    "generation_mwh",
    "input_mwh",
    "network_emissions",
    "emissions_source",
]

GROUP_COLUMNS = [
    "region",
    "sector",
    "subsector",
    "carrier",
    "component",
    "model_year",
    "emissions_source",
]

SUMMARY_COLUMNS = GROUP_COLUMNS + [
    "generation_mwh",
    "input_mwh",
    "network_emissions",
]


def snapshot_weights(n):
    """Return generator snapshot weights, validating their completeness."""
    weights = n.snapshot_weightings.generators.reindex(n.snapshots)

    if weights.isna().any() or (weights < 0).any():
        raise ValueError("Invalid generator snapshot weights.")

    return weights


def network_country(n):
    """Return the unique network country, or an empty string."""
    if "country" not in n.buses.columns:
        return ""

    countries = n.buses.country.fillna("").astype(str).str.strip().str.upper()

    countries = countries[countries.ne("")].unique()

    return countries[0] if len(countries) == 1 else ""


def component_regions(n, components, component_type):
    """Assign countries using component metadata and physical buses."""
    regions = pd.Series("", index=components.index, dtype=str)

    if "country" in components.columns:
        regions = components.country.fillna("").astype(str).str.strip().str.upper()

    if component_type in {"Generator", "Link"}:
        bus_column = "bus" if component_type == "Generator" else "bus0"

        missing = regions.eq("")

        if "country" in n.buses.columns:
            regions.loc[missing] = (
                components.loc[missing, bus_column]
                .map(n.buses.country)
                .fillna("")
                .astype(str)
                .str.strip()
                .str.upper()
            )

    fallback = network_country(n)

    if fallback:
        regions = regions.replace("", fallback)

    return regions


def metadata_column(components, column):
    """Return a normalized metadata column without inferring missing sectors."""
    if column not in components.columns:
        return pd.Series("", index=components.index, dtype=str)

    return components[column].fillna("").astype(str).str.strip()


def create_detail(
    n,
    components,
    component_type,
    emissions,
    model_year,
    generation=None,
    input_energy=None,
    emissions_source="",
):
    """Convert component emissions into a common asset-level table."""
    index = components.index

    detail = pd.DataFrame(index=index)

    detail["region"] = component_regions(n, components, component_type)

    if component_type == "Generator" and "co2 atmosphere" not in n.buses.index:
        detail["sector"] = ELECTRICITY_SECTOR
    else:
        detail["sector"] = metadata_column(components, "sector")

    detail["subsector"] = metadata_column(components, "subsector")
    detail["carrier"] = components.carrier.fillna("")
    detail["component"] = component_type
    detail["asset"] = index
    detail["model_year"] = int(model_year)

    detail["generation_mwh"] = (
        generation.reindex(index) if generation is not None else float("nan")
    )

    detail["input_mwh"] = (
        input_energy.reindex(index) if input_energy is not None else float("nan")
    )

    detail["network_emissions"] = emissions.reindex(index) * TONNES_TO_MEGATONNES

    detail["emissions_source"] = emissions_source

    return detail[DETAIL_COLUMNS].reset_index(drop=True)


def generator_emissions(n, model_year, weights):
    """Calculate generator emissions from dispatch and carrier CO2 factors."""
    if n.generators.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    if "co2_emissions" not in n.carriers.columns:
        logger.warning(
            "Network carriers have no CO2 emission factors; "
            "generator CO2 emissions are unavailable."
        )
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    generators = n.generators.copy()
    factors = generators.carrier.map(n.carriers.co2_emissions)

    if factors.notna().sum() == 0:
        logger.warning(
            "No generator CO2 emission factors are available; "
            "generator CO2 emissions are unavailable."
        )
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    if factors.isna().any():
        missing = sorted(generators.loc[factors.isna(), "carrier"].unique())
        raise ValueError(f"Missing generator CO2 emission factors: {missing}")

    efficiencies = pd.to_numeric(generators.efficiency, errors="coerce")
    emitting = factors.ne(0)

    invalid = emitting & (efficiencies.isna() | efficiencies.le(0))

    if invalid.any():
        raise ValueError(
            "Invalid efficiencies for emitting generators: "
            + ", ".join(generators.index[invalid].astype(str))
        )

    dispatch = n.generators_t.p.reindex(
        index=n.snapshots,
        columns=generators.index,
    )

    if dispatch.isna().any().any():
        raise ValueError("Missing generator dispatch.")

    generation = dispatch.mul(weights, axis=0).sum(axis=0)

    intensity = factors.div(efficiencies.where(emitting, 1.0))
    emissions = generation.mul(intensity)

    return create_detail(
        n,
        generators,
        "Generator",
        emissions,
        model_year,
        generation=generation,
        emissions_source="generator_carrier_factor",
    )


def atmospheric_link_factors(n):
    """Calculate direct atmospheric CO2 factors using KINETICS conventions."""
    factors = pd.Series(0.0, index=n.links.index)

    bus_columns = sorted(
        (
            column
            for column in n.links.columns
            if column.startswith("bus")
            and column[3:].isdigit()
            and int(column[3:]) >= 1
        ),
        key=lambda column: int(column[3:]),
    )

    for bus_column in bus_columns:
        port = int(bus_column[3:])
        efficiency_column = "efficiency" if port == 1 else f"efficiency{port}"

        mask = n.links[bus_column].eq("co2 atmosphere")

        if not mask.any():
            continue

        if efficiency_column not in n.links.columns:
            raise ValueError(f"Missing {efficiency_column} for atmospheric Links.")

        factors.loc[mask] += n.links.loc[mask, efficiency_column].fillna(0.0)

    return factors


def link_emissions(n, model_year, weights):
    """Calculate emissions through atmospheric Link ports."""
    factors = atmospheric_link_factors(n)
    names = factors.index[factors.ne(0)]

    if names.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    links = n.links.loc[names].copy()

    dispatch = n.links_t.p0.reindex(
        index=n.snapshots,
        columns=names,
    )

    if dispatch.isna().any().any():
        raise ValueError("Missing atmospheric Link dispatch.")

    input_energy = dispatch.mul(weights, axis=0).sum(axis=0)
    emissions = input_energy.mul(factors.loc[names])

    return create_detail(
        n,
        links,
        "Link",
        emissions,
        model_year,
        input_energy=input_energy,
        emissions_source="link_atmosphere",
    )


def load_emissions(n, model_year, weights):
    """Calculate atmospheric Load emissions from static or dynamic p_set."""
    names = n.loads.index[n.loads.bus.eq("co2 atmosphere")]

    if names.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    loads = n.loads.loc[names].copy()

    # Static values are the fallback when no time series exists.
    dispatch = pd.DataFrame(
        {
            name: (
                n.loads_t.p_set[name]
                if name in n.loads_t.p_set.columns
                else pd.Series(n.loads.at[name, "p_set"], index=n.snapshots)
            )
            for name in names
        },
        index=n.snapshots,
    )

    if dispatch.isna().any().any():
        raise ValueError("Missing atmospheric Load profiles.")

    emissions = -dispatch.mul(weights, axis=0).sum(axis=0)

    return create_detail(
        n,
        loads,
        "Load",
        emissions,
        model_year,
        emissions_source="load_atmosphere",
    )


def build_statistics(n, model_year):
    """Build asset-level and aggregated CO2 statistics."""
    weights = snapshot_weights(n)

    frames = [generator_emissions(n, model_year, weights)]

    if "co2 atmosphere" in n.buses.index:
        frames.extend(
            [
                link_emissions(n, model_year, weights),
                load_emissions(n, model_year, weights),
            ]
        )

    detail = pd.concat(frames, ignore_index=True)

    summary = (
        detail.groupby(GROUP_COLUMNS, dropna=False)[
            ["generation_mwh", "input_mwh", "network_emissions"]
        ]
        .sum(min_count=1)
        .reset_index()
    )

    missing_region = detail.region.eq("") & detail.network_emissions.abs().gt(1e-9)

    if missing_region.any():
        logger.warning(
            "%s emitting components have no country assignment.",
            missing_region.sum(),
        )

    missing_sector = detail.sector.eq("") & detail.network_emissions.abs().gt(1e-9)

    if missing_sector.any():
        logger.warning(
            "%s emitting components have no sector assignment. "
            "Sectoral validation is not complete.",
            missing_sector.sum(),
        )

    return detail[DETAIL_COLUMNS], summary[SUMMARY_COLUMNS]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--detail-output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    n = pypsa.Network(args.network)
    detail, summary = build_statistics(n, args.year)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output, index=False)

    if args.detail_output:
        detail_output = Path(args.detail_output)
        detail_output.parent.mkdir(parents=True, exist_ok=True)
        detail.to_csv(detail_output, index=False)

    totals = summary.groupby("region")["network_emissions"].sum()

    logger.info(
        "Annual CO2 emissions by region [MtCO2]:\n%s",
        totals.to_string(),
    )


if __name__ == "__main__":
    main()
