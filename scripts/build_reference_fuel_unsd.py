# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build historical UNSD final energy consumption by country, sector and fuel."""

import argparse
import ast
import logging
import os
import types
from pathlib import Path

import country_converter as coco
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REFERENCE_SOURCE = "UNSD"

OUTPUT_COLUMNS = [
    "region",
    "sector",
    "fuel",
    "model_year",
    "reference_year",
    "reference_twh",
    "reference_source",
]

# Output sector -> substrings matched in the lowercased 'Commodity - Transaction'.
ENERGY_SECTORS = {
    "residential": ["consumption by households"],
    "services": ["services"],
    "agriculture": ["agriculture"],
    "transport": ["road", "rail"],
}
COAL_SHIFT_SECTORS = {"residential", "services"}
INDUSTRY_OTHER_COLUMN = "other"
# A commodity may lag this many years behind the latest year of its fuel group.
MAX_SERIES_LAG_YEARS = 2


def import_pypsa_earth_helpers(pypsa_earth_path):
    """Load only the needed functions from PyPSA-Earth's _helpers.py.

    The module is not imported because it pulls in many unrelated dependencies.
    The source of aggregate_fuels, get_conv_factors and read_csv_nafix (and the
    constants they use) is extracted and executed in an isolated namespace.
    """
    source_file = Path(pypsa_earth_path) / "scripts" / "_helpers.py"
    if not source_file.exists():
        raise FileNotFoundError(f"PyPSA-Earth _helpers.py not found: {source_file}")

    source = source_file.read_text()
    tree = ast.parse(source)

    wanted_functions = {"aggregate_fuels", "get_conv_factors", "read_csv_nafix"}
    wanted_constants = {"NA_VALUES"}

    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in wanted_constants for t in node.targets
        ):
            nodes.append(node)

    found = {n.name for n in nodes if isinstance(n, ast.FunctionDef)}
    if missing := wanted_functions - found:
        raise ImportError(f"Functions not found in {source_file}: {sorted(missing)}")

    namespace = {
        "pd": pd,
        "np": np,
        "os": os,
        "logging": logging,
        "Path": Path,
        "logger": logger,
        "_logger": logger,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, str(source_file), "exec"), namespace)

    return types.SimpleNamespace(**{name: namespace[name] for name in wanted_functions})


def load_unsd(unsd_dir, helpers):
    """Read the raw UNSD files and add commodity, transaction and ISO2 country."""
    files = sorted(Path(unsd_dir).glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"No UNSD .txt files found in {unsd_dir}")

    df = pd.concat(
        (helpers.read_csv_nafix(f, encoding="utf8", sep=";") for f in files),
        ignore_index=True,
    )
    df[["Commodity", "Transaction", "extra"]] = df["Commodity - Transaction"].str.split(
        " - ", expand=True
    )
    df = df.loc[~df["Commodity - Transaction"].isin(["Footnote", "Estimate"])]

    # Rows without a country name (footnotes) cannot be assigned to a country.
    df = df.dropna(subset=["Country or Area"])

    # Convert each distinct name once instead of every row.
    logging.getLogger("country_converter").setLevel(logging.ERROR)
    names = sorted(df["Country or Area"].astype(str).unique())
    converter = coco.CountryConverter()
    iso2, failed = {}, []
    for name in names:
        try:
            code = converter.convert(names=name, to="ISO2", not_found="not found")
        except (AttributeError, TypeError, ValueError):
            failed.append(name)
            code = "not found"
        iso2[name] = ",".join(map(str, code)) if isinstance(code, list) else str(code)
    if failed:
        logger.warning(
            "Country names that could not be converted and are skipped: %s", failed
        )
    df["country"] = df["Country or Area"].astype(str).map(iso2)
    # Drop former countries and areas that map to several ISO2 codes.
    df = df[df["country"].ne("not found") & ~df["country"].str.contains(",", na=False)]

    return df.reset_index(drop=True)


def to_twh(df, conversion):
    """Convert UNSD quantities to TWh, as in the PyPSA-Earth base totals scripts."""
    df = df.copy()
    quantity = pd.to_numeric(df["Quantity"], errors="coerce")
    factor = df["Commodity"].map(conversion)

    twh = pd.Series(float("nan"), index=df.index)
    mass_or_volume = df["Unit"].isin(
        ["Metric tons,  thousand", "Cubic metres, thousand"]
    )
    twh[mass_or_volume] = quantity[mass_or_volume] * factor[mass_or_volume]
    kwh = df["Unit"].eq("Kilowatt-hours, million")
    twh[kwh] = quantity[kwh] / 1e3
    tj = df["Unit"].eq("Terajoules")
    twh[tj] = quantity[tj] / 3600

    df["Quantity_TWh"] = twh

    unconverted = df["Quantity_TWh"].isna()
    if unconverted.any():
        logger.warning(
            "%s UNSD rows could not be converted to TWh (units: %s).",
            unconverted.sum(),
            sorted(df.loc[unconverted, "Unit"].dropna().unique())[:5],
        )

    return df.loc[~unconverted]


def fuel_mapping(helpers):
    """Map UNSD commodities to the PyPSA fuel categories."""
    gas, oil, biomass, coal, heat, electricity = helpers.aggregate_fuels("industry")
    return {
        commodity: fuel
        for fuel, commodities in [
            ("gas", gas),
            ("oil", oil),
            ("biomass", biomass),
            ("coal", coal),
            ("heat", heat),
            ("electricity", electricity),
        ]
        for commodity in commodities
    }


def select_latest_year(df, model_year):
    """Keep observations not later than the model year.

    The latest year is chosen later, per commodity series, because UNSD
    reports the commodities of one sector up to different years.
    """
    return df[df["Year"] <= model_year]


def energy_sector_rows(df, model_year):
    """Select the energy-statistics rows of the residential, services,
    agriculture and transport sectors."""
    text = df["Commodity - Transaction"].str.lower()
    frames = []
    for sector, patterns in ENERGY_SECTORS.items():
        mask = pd.Series(False, index=df.index)
        for pattern in patterns:
            mask |= text.str.contains(pattern, na=False)
        selected = df.loc[mask].copy()
        selected["sector"] = sector
        frames.append(selected)

    rows = pd.concat(frames)
    overlap = rows.index.duplicated().sum()
    if overlap:
        logger.warning("%s UNSD rows match more than one sector.", overlap)

    return select_latest_year(rows, model_year)


def industry_rows(df, transactions, model_year, include_other):
    """Select industry rows using the PyPSA-Earth industry transactions list."""
    data = df[df["Commodity"].ne("Other bituminous coal")].copy()
    data["Transaction"] = data["Transaction"].fillna("NA").str.lower()

    names = transactions.set_index("Transaction")["clean_name"].to_dict()
    data = data[data["Transaction"].isin(names)]
    data["clean_name"] = data["Transaction"].map(names)

    if not include_other:
        data = data[data["clean_name"].ne(INDUSTRY_OTHER_COLUMN)]

    data["sector"] = "industry"
    return select_latest_year(data, model_year)


def aggregate(rows, fuels, model_year, shift_coal_to_elec):
    """Sum TWh by country, sector, fuel; keep the reference year used."""
    rows = rows.copy()
    rows["fuel"] = rows["Commodity"].map(fuels)

    unmapped = rows["fuel"].isna()
    if unmapped.any():
        logger.warning(
            "Ignoring %.3f TWh of UNSD commodities with no fuel category: %s",
            rows.loc[unmapped, "Quantity_TWh"].sum(),
            sorted(rows.loc[unmapped, "Commodity"].unique())[:8],
        )
        rows = rows.loc[~unmapped]

    # UNSD reports the commodities of one fuel up to different years (e.g. diesel
    # one year behind gasoline). Take the latest observation of every series, so
    # that a lagging commodity is not dropped from the fuel total.
    series = ["country", "sector", "Commodity - Transaction"]
    rows = rows[rows["Year"].eq(rows.groupby(series)["Year"].transform("max"))]

    # Series that stopped long before the others of the same fuel are treated as
    # discontinued, not as lagging.
    latest = rows.groupby(["country", "sector", "fuel"])["Year"].transform("max")
    rows = rows[rows["Year"].ge(latest - MAX_SERIES_LAG_YEARS)]

    if shift_coal_to_elec:
        shift = rows["fuel"].eq("coal") & rows["sector"].isin(COAL_SHIFT_SECTORS)
        rows.loc[shift, "fuel"] = "electricity"

    table = (
        rows.groupby(["country", "sector", "fuel"], as_index=False)
        .agg(reference_year=("Year", "max"), reference_twh=("Quantity_TWh", "sum"))
        .rename(columns={"country": "region"})
    )
    table["model_year"] = int(model_year)
    table["reference_source"] = REFERENCE_SOURCE

    return table[OUTPUT_COLUMNS].sort_values(["region", "sector", "fuel"])


def build_reference(args, countries):
    """Build the reference table; empty when the UNSD inputs are unavailable."""
    empty = pd.DataFrame(columns=OUTPUT_COLUMNS)

    # The UNSD statistics live in a PyPSA-Earth checkout. Without it the fuel
    # reference is unavailable, which must not stop the rest of the validation.
    required = [
        Path(args.pypsa_earth_path) / "scripts" / "_helpers.py",
        Path(args.unsd_path),
        Path(args.transactions_path),
    ]
    if missing := [str(path) for path in required if not path.exists()]:
        logger.warning(
            "UNSD fuel reference unavailable; PyPSA-Earth inputs not found: %s",
            missing,
        )
        return empty

    helpers = import_pypsa_earth_helpers(args.pypsa_earth_path)

    df = load_unsd(args.unsd_path, helpers)
    df = df[df["country"].isin(countries)]

    for country in sorted(set(countries) - set(df["country"])):
        logger.warning("No UNSD data at all for country %s.", country)

    if df.empty or not (df["Year"] <= args.year).any():
        logger.warning("No UNSD observations up to model year %s.", args.year)
        return empty

    transactions = helpers.read_csv_nafix(args.transactions_path, sep=";")
    conversion = helpers.get_conv_factors("industry")

    energy = energy_sector_rows(df, args.year)
    industry = industry_rows(df, transactions, args.year, args.include_other_industries)
    rows = to_twh(pd.concat([energy, industry], ignore_index=True), conversion)

    return aggregate(rows, fuel_mapping(helpers), args.year, args.shift_coal_to_elec)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pypsa-earth-path", required=True)
    parser.add_argument("--unsd-path", required=True)
    parser.add_argument("--transactions-path", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--countries", nargs="+", required=True)
    parser.add_argument("--shift-coal-to-elec", action="store_true")
    parser.add_argument("--include-other-industries", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    countries = [c.upper() for c in args.countries]
    table = build_reference(args, countries)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output, index=False)

    if not table.empty:
        logger.info(
            "UNSD reference years used:\n%s",
            table.groupby(["region", "sector"])["reference_year"].max().to_string(),
        )


if __name__ == "__main__":
    main()
