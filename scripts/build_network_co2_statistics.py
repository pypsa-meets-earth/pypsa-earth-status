# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calculate direct CO2 emissions from solved electricity-only networks."""

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
    "network_emissions",
]

SUMMARY_COLUMNS = [
    "region",
    "sector",
    "subsector",
    "carrier",
    "component",
    "model_year",
    "generation_mwh",
    "network_emissions",
]


def calculate_generator_emissions(n, model_year):
    """Calculate annual generator emissions and retain component metadata."""
    if "co2 atmosphere" in n.buses.index:
        raise ValueError(
            "Sector-coupled networks are not supported by this implementation."
        )

    if n.generators.empty:
        raise ValueError("Network contains no generators.")

    generators = n.generators.copy()

    if "co2_emissions" not in n.carriers.columns:
        raise ValueError("Network carriers lack CO2 emission factors.")

    factors = generators.carrier.map(n.carriers.co2_emissions)

    if factors.isna().any():
        missing = sorted(generators.loc[factors.isna(), "carrier"].unique())
        raise ValueError(f"Missing CO2 emission factors: {missing}")

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

    if dispatch.empty or dispatch.isna().any().any():
        raise ValueError("Missing or incomplete generator dispatch.")

    weights = n.snapshot_weightings.generators.reindex(n.snapshots)

    if weights.isna().any():
        raise ValueError("Missing snapshot weights.")

    annual_generation = dispatch.mul(weights, axis=0).sum()

    intensity = factors.div(efficiencies.where(emitting, 1.0))

    emissions = annual_generation.mul(intensity)

    if "country" in generators.columns:
        regions = generators.country.fillna("").astype(str).str.strip()
    else:
        regions = pd.Series("", index=generators.index)

    missing_regions = regions.eq("")

    regions.loc[missing_regions] = (
        generators.loc[missing_regions, "bus"]
        .map(n.buses.country)
        .fillna("")
        .astype(str)
        .str.strip()
    )

    regions = regions.str.upper()

    missing_regions = regions.eq("") & emissions.ne(0)

    if missing_regions.any():
        raise ValueError(
            "Missing country for emitting generators: "
            + ", ".join(generators.index[missing_regions].astype(str))
        )

    detail = pd.DataFrame(index=generators.index)

    detail["region"] = regions
    detail["sector"] = ELECTRICITY_SECTOR
    detail["subsector"] = ""
    detail["carrier"] = generators.carrier
    detail["component"] = "Generator"
    detail["asset"] = generators.index
    detail["model_year"] = int(model_year)
    detail["generation_mwh"] = annual_generation
    detail["network_emissions"] = emissions * TONNES_TO_MEGATONNES

    detail = detail.loc[detail.region.ne("")]

    return detail[DETAIL_COLUMNS].reset_index(drop=True)


def aggregate_emissions(detail):
    """Aggregate emissions while retaining sector and carrier information."""
    group_columns = [
        "region",
        "sector",
        "subsector",
        "carrier",
        "component",
        "model_year",
    ]

    summary = (
        detail.groupby(group_columns, dropna=False)[
            ["generation_mwh", "network_emissions"]
        ]
        .sum()
        .reset_index()
    )

    return summary[SUMMARY_COLUMNS]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--detail-output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    n = pypsa.Network(args.network)

    detail = calculate_generator_emissions(n, args.year)
    summary = aggregate_emissions(detail)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output, index=False)

    if args.detail_output:
        detail_output = Path(args.detail_output)
        detail_output.parent.mkdir(parents=True, exist_ok=True)
        detail.to_csv(detail_output, index=False)

    totals = summary.groupby("region")["network_emissions"].sum()

    logger.info("CO2 emissions by region [MtCO2]:\n%s", totals.to_string())


if __name__ == "__main__":
    main()
