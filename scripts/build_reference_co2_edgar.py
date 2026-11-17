# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Extract country-level fossil CO2 emissions from EDGAR."""

import argparse
import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

SHEET_NAME = "fossil_CO2_by_sector_country_su"

REFERENCE_COLUMNS = [
    "region",
    "sector",
    "reference_year",
    "reference_emissions",
    "reference_source",
]


def network_planning_horizon(network_path):
    """Identify the actual planning horizon from network metadata or filename."""
    if not network_path:
        return None

    import pypsa

    network = pypsa.Network(network_path)

    metadata = network.meta or {}
    wildcards = metadata.get("wildcards", {}) or {}

    wildcard_year = wildcards.get("planning_horizons")

    if wildcard_year is not None:
        try:
            wildcard_year = int(wildcard_year)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid planning horizon in network metadata: {wildcard_year}"
            ) from exc

    filename = Path(network_path).stem

    # Match the planning horizon in PyPSA-Earth sector network filenames.
    match = re.search(r"_(20\\d{2})_[0-9]+(?:\\.[0-9]+)?$", filename)
    filename_year = int(match.group(1)) if match else None

    if (
        wildcard_year is not None
        and filename_year is not None
        and wildcard_year != filename_year
    ):
        raise ValueError(
            f"Conflicting planning horizons: metadata={wildcard_year}, "
            f"filename={filename_year}"
        )

    return wildcard_year if wildcard_year is not None else filename_year


def select_reference_year(
    available_years,
    network_path=None,
    comparison_year=None,
):
    """Select the EDGAR year, prioritizing the network planning horizon."""
    years = sorted({int(year) for year in available_years})

    if not years:
        raise ValueError("No reference years are available.")

    planning_horizon = network_planning_horizon(network_path)

    requested_year = (
        planning_horizon if planning_horizon is not None else comparison_year
    )

    if requested_year is None or requested_year == 0:
        selected = years[-1]
    elif requested_year > years[-1]:
        selected = years[-1]
        logger.warning(
            "Requested year %s exceeds EDGAR coverage. "
            "Using latest available year %s.",
            requested_year,
            selected,
        )
    elif requested_year not in years:
        raise ValueError(
            f"Requested reference year {requested_year} is unavailable. "
            f"Available years: {years[0]}-{years[-1]}."
        )
    else:
        selected = requested_year

    logger.info(
        "CO2 reference year: %s (network horizon: %s, configured: %s)",
        selected,
        planning_horizon,
        comparison_year,
    )

    return selected


def build_reference_edgar(
    path,
    country_map,
    network_path=None,
    comparison_year=None,
):
    """Extract EDGAR fossil CO2 emissions in MtCO2/year."""
    df = pd.read_excel(path, sheet_name=SHEET_NAME)

    required = {"Sector", "EDGAR Country Code"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing EDGAR columns: {sorted(missing)}")

    available_years = [
        column
        for column in df.columns
        if isinstance(column, int) and 1900 <= column <= 2100
    ]

    year = select_reference_year(
        available_years,
        network_path=network_path,
        comparison_year=comparison_year,
    )

    rows = []

    for region, edgar_code in country_map.items():
        selected = df.loc[
            df["EDGAR Country Code"].eq(edgar_code),
            ["Sector", year],
        ].copy()

        if selected.empty:
            raise ValueError(f"No EDGAR data found for {region} ({edgar_code}).")

        selected[year] = pd.to_numeric(
            selected[year],
            errors="raise",
        )

        if selected[year].isna().any():
            raise ValueError(f"Missing EDGAR emissions for {region}, {year}.")

        selected = selected.rename(
            columns={
                "Sector": "sector",
                year: "reference_emissions",
            }
        )

        selected["region"] = region
        selected["reference_year"] = year
        selected["reference_source"] = "EDGAR"

        if selected["sector"].duplicated().any():
            raise ValueError(f"Duplicate EDGAR sectors for {region}, {year}.")

        rows.append(selected[REFERENCE_COLUMNS])

    return pd.concat(rows, ignore_index=True)


def build_country_map(countries):
    """Convert configured ISO2 country codes to EDGAR ISO3 codes."""
    import country_converter as coco

    country_map = {}

    for region in countries:
        region = str(region).upper()
        country = coco.convert(names=region, to="ISO3")

        if not isinstance(country, str) or len(country) != 3:
            raise ValueError(f"Cannot determine EDGAR country code for {region}.")

        country_map[region] = country

    return country_map


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--network")
    parser.add_argument("--comparison-year", type=int, default=0)
    parser.add_argument(
        "--year",
        type=int,
        help="Deprecated alias for --comparison-year.",
    )
    parser.add_argument(
        "--countries",
        nargs="+",
        required=True,
        help="ISO2 country codes, e.g. JP DE US",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.year is not None and args.comparison_year:
        parser.error("Use either --year or --comparison-year.")

    comparison_year = args.year if args.year is not None else args.comparison_year

    country_map = build_country_map(args.countries)

    reference = build_reference_edgar(
        args.input,
        country_map,
        network_path=args.network,
        comparison_year=comparison_year,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    reference.to_csv(output, index=False)

    logger.info(
        "EDGAR reference totals [MtCO2]:\n%s",
        reference.groupby(["region", "reference_year"])["reference_emissions"]
        .sum()
        .to_string(),
    )


if __name__ == "__main__":
    main()
