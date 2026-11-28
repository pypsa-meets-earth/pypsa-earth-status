# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build historical UNSD final energy consumption by country, sector and fuel."""

import argparse
import logging
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import yaml
from download_unsd_sdmx import country_to_unsd_area

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
# UNSD transaction codes of the unspecified industry (1214O) and of the totals
# that include it: manufacturing, construction and non-fuel industry (121) and
# other manufacturing, construction and non-fuel industry (1214).
INDUSTRY_OTHER_CODES = {"121", "1214", "1214O"}
# Warn when a commodity's latest observation is older than this many years,
# relative to the model year. The observation is still used.
STALE_OBSERVATION_WARNING_YEARS = 5


def read_sdmx_labels(root, codelist_id):
    """Map official SDMX codes to their English descriptions."""
    ns = {
        "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
        "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    }

    codelist = root.find(
        f".//s:Codelist[@id='{codelist_id}']",
        ns,
    )

    if codelist is None:
        raise ValueError(f"Missing UNSD codelist: {codelist_id}")

    return {
        code.get("id"): code.findtext("c:Name", namespaces=ns)
        for code in codelist.findall("s:Code", ns)
    }


def load_unsd(unsd_dir, countries):
    """Read cached SDMX observations using the official UNSD classifications."""
    root = ET.parse(Path(unsd_dir) / "structure.xml").getroot()

    commodities = read_sdmx_labels(root, "CL_COMMODITY_NRG")
    transactions = read_sdmx_labels(root, "CL_TRANSACTION_NRG")

    frames = []

    for country in countries:
        code = country_to_unsd_area(country)
        source = Path(unsd_dir) / f"{code}.csv"

        df = pd.read_csv(
            source,
            dtype={
                "COMMODITY": str,
                "TRANSACTION": str,
            },
            low_memory=False,
        )

        df = df[df["FREQ"].eq("A")].copy()

        df["country"] = country
        df["Commodity"] = df["COMMODITY"].map(commodities)

        # Normalize SDMX labels to the existing PyPSA-Earth fuel mapping.
        commodity_aliases = {
            "7000": "Electricity",
            "4680": "Fuel oil",
            "0100": "Hard coal",
            "0200": "Brown coal",
            "4630": "Liquefied petroleum gas (LPG)",
            "5140": "Black Liquor",
            "5150": "Vegetal waste",
            "0379": "Recovered gases",
        }

        df["Commodity"] = df["COMMODITY"].map(commodity_aliases).fillna(df["Commodity"])
        df["Transaction"] = df["TRANSACTION"].map(transactions)
        df["transaction_code"] = df["TRANSACTION"]
        df["Year"] = pd.to_numeric(df["TIME_PERIOD"], errors="coerce")

        # Apply the SDMX unit multiplier before unit conversion.
        multiplier = pd.to_numeric(df["UNIT_MULT"], errors="coerce")
        value = pd.to_numeric(df["OBS_VALUE"], errors="coerce")

        df["Quantity"] = value * (10.0**multiplier)

        unit = df["UNIT_MEASURE"].astype(str).str.upper()

        units = {
            "TN": "Metric tons,  thousand",
            "M3": "Cubic metres, thousand",
            "TJ": "Terajoules",
            "GWHR": "Kilowatt-hours, million",
            "KWH": "Kilowatt-hours, million",
            "MWH": "Kilowatt-hours, million",
            "GWH": "Kilowatt-hours, million",
        }

        df["Unit"] = unit.map(units)

        # PyPSA-Earth conversion factors are expressed per thousand tonnes
        # or thousand cubic metres.
        mass_or_volume = unit.isin(["TN", "M3"])
        df.loc[mass_or_volume, "Quantity"] /= 1000

        # Normalize electricity observations to million kWh.
        df.loc[unit.eq("KWH"), "Quantity"] /= 1e6
        df.loc[unit.eq("MWH"), "Quantity"] /= 1e3

        df["Commodity - Transaction"] = (
            df["Commodity"].astype(str) + " - " + df["Transaction"].astype(str)
        )

        df = df.dropna(subset=["Commodity", "Transaction", "Year"])

        df["Year"] = df["Year"].astype(int)

        frames.append(df)

    return pd.concat(frames, ignore_index=True)


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


def fuel_mapping(mapping):
    """Return the locally maintained UNSD commodity-to-fuel mapping."""
    return mapping["fuels"]


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
    """Select industrial consumption using UNSD transaction codes."""
    data = df[df["Commodity"].ne("Other bituminous coal")].copy()

    names = transactions.copy()
    names["Transaction"] = names["Transaction"].fillna("").str.strip().str.lower()
    name_mapping = names.set_index("Transaction")["clean_name"].to_dict()

    transaction_names = data["Transaction"].fillna("").str.strip().str.lower()

    data["clean_name"] = transaction_names.map(name_mapping)

    # The 121 hierarchy covers manufacturing, construction and
    # non-fuel industry, including all its detailed subsectors.
    if "transaction_code" in data.columns:
        code = data["transaction_code"].fillna("")
        industrial = code.str.startswith("121")
    else:
        code = pd.Series("", index=data.index)
        industrial = pd.Series(False, index=data.index)

    selected = industrial | data["clean_name"].notna()
    data = data.loc[selected].copy()

    data["sector"] = "industry"
    data = select_latest_year(data, model_year)

    if not include_other:
        data = exclude_other_industries(data)

    return data


def exclude_other_industries(rows, transaction_parents=None):
    """Exclude unspecified industry without reviving obsolete subsectors."""
    unspecified = rows["clean_name"].eq(INDUSTRY_OTHER_COLUMN)

    if "transaction_code" not in rows.columns:
        return rows.loc[~unspecified]

    unspecified |= rows["transaction_code"].isin(INDUSTRY_OTHER_CODES)

    discarded = set()

    if transaction_parents:
        for _, group in rows.groupby(["country", "COMMODITY"]):
            latest_years = group.groupby("transaction_code")["Year"].max()

            for code, observations in group.groupby("transaction_code"):
                ancestor = transaction_parents.get(code)
                visited = set()

                while ancestor and ancestor not in visited:
                    visited.add(ancestor)

                    if (
                        ancestor in INDUSTRY_OTHER_CODES
                        and ancestor in latest_years.index
                    ):
                        older = observations["Year"].lt(latest_years.loc[ancestor])
                        discarded.update(observations.index[older])

                    ancestor = transaction_parents.get(ancestor)

    if discarded:
        logger.info(
            "Excluded %s historical industrial observations superseded "
            "by newer UNSD transaction aggregates.",
            len(discarded),
        )

    return rows.loc[~unspecified].drop(index=list(discarded), errors="ignore")


def read_transaction_parents(structure_path):
    """Read the UNSD transaction hierarchy from the official SDMX structure."""
    root = ET.parse(structure_path).getroot()

    ns = {
        "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    }

    codes = root.findall(
        ".//s:Codelist[@id='CL_TRANSACTION_NRG']/s:Code",
        ns,
    )

    if not codes:
        raise ValueError("UNSD transaction codelist not found")

    parents = {}

    for code in codes:
        parent = code.find("./s:Parent/Ref", ns)

        if parent is not None:
            parents[code.get("id")] = parent.get("id")

    return parents


def read_commodity_parents(structure_path):
    """Read the commodity hierarchy from the official UNSD SDMX structure."""
    root = ET.parse(structure_path).getroot()

    ns = {
        "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    }

    codes = root.findall(
        ".//s:Codelist[@id='CL_COMMODITY_NRG']/s:Code",
        ns,
    )

    if not codes:
        raise ValueError("UNSD commodity codelist not found")

    parents = {}

    for code in codes:
        parent = code.find("./s:Parent/Ref", ns)

        if parent is not None:
            parents[code.get("id")] = parent.get("id")

    return parents


def reconcile_commodity_hierarchy(rows, parents):
    """Prevent double counting of aggregate commodities and descendants."""
    if not parents or not {"COMMODITY", "transaction_code"}.issubset(rows):
        return rows

    discarded = set()

    for (country, sector, transaction), group in rows.groupby(
        ["country", "sector", "transaction_code"]
    ):
        available = set(group["COMMODITY"].dropna())

        for index, row in group.iterrows():
            code = row["COMMODITY"]
            ancestor = parents.get(code)
            visited = set()

            while ancestor and ancestor not in visited:
                visited.add(ancestor)

                if ancestor in available:
                    parent_year = group.loc[
                        group["COMMODITY"].eq(ancestor), "Year"
                    ].max()

                    if row["Year"] > parent_year:
                        logger.warning(
                            "UNSD commodity hierarchy %s / %s / %s: "
                            "aggregate %s (%s) is older than "
                            "subcategory %s (%s); retaining the aggregate "
                            "to avoid double counting.",
                            country,
                            sector,
                            transaction,
                            ancestor,
                            int(parent_year),
                            code,
                            int(row["Year"]),
                        )

                    discarded.add(index)
                    break

                ancestor = parents.get(ancestor)

    if discarded:
        logger.info(
            "Excluded %s overlapping UNSD commodity observations.",
            len(discarded),
        )

    return rows.drop(index=list(discarded))


def reconcile_transaction_hierarchy(rows, parents):
    """Avoid double-counting UNSD aggregates and their descendants."""
    if not parents or "transaction_code" not in rows.columns:
        return rows

    def is_descendant(code, ancestor):
        visited = set()

        while code in parents and code not in visited:
            visited.add(code)
            code = parents[code]

            if code == ancestor:
                return True

        return False

    discarded = set()

    for (country, sector, commodity), group in rows.groupby(
        ["country", "sector", "Commodity"]
    ):
        codes = set(group["transaction_code"].dropna())

        for parent_code in codes:
            descendants = {
                code
                for code in codes
                if code != parent_code and is_descendant(code, parent_code)
            }

            if not descendants:
                continue

            parent_rows = group[group["transaction_code"].eq(parent_code)]
            child_rows = group[group["transaction_code"].isin(descendants)]

            parent_year = parent_rows["Year"].max()
            child_year = child_rows["Year"].max()

            if parent_year >= child_year:
                discarded.update(child_rows.index)
                selected = parent_code
            else:
                discarded.update(parent_rows.index)
                selected = "newer subcategories"

            logger.info(
                "UNSD hierarchy: %s / %s / %s: "
                "using %s instead of overlapping transactions.",
                country,
                sector,
                commodity,
                selected,
            )

    return rows.drop(index=list(discarded))


def warn_stale_observations(rows, model_year, warning_years):
    """Log the commodities whose latest observation is old; they are kept."""
    stale = rows[rows["Year"] < model_year - warning_years]
    for _, row in stale.sort_values(["country", "sector", "Year"]).iterrows():
        logger.warning(
            "UNSD %s / %s / %s: latest observation is %s, %s years before the "
            "model year %s (%.3f TWh). It is kept in the reference.",
            row["country"],
            row["sector"],
            row["Commodity - Transaction"],
            int(row["Year"]),
            int(model_year - row["Year"]),
            model_year,
            row["Quantity_TWh"],
        )


def aggregate(
    rows,
    fuels,
    model_year,
    shift_coal_to_elec,
    stale_warning_years=STALE_OBSERVATION_WARNING_YEARS,
    transaction_parents=None,
    commodity_parents=None,
):
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
    # one year behind gasoline), and an old last observation may only be a
    # reporting gap. Take the latest observation of every series and keep it,
    # warning when it is old.
    series = ["country", "sector", "Commodity - Transaction"]
    rows = rows[rows["Year"].eq(rows.groupby(series)["Year"].transform("max"))]
    rows = reconcile_transaction_hierarchy(rows, transaction_parents)
    rows = reconcile_commodity_hierarchy(rows, commodity_parents)
    warn_stale_observations(rows, model_year, stale_warning_years)

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
    """Build the UNSD reference from locally cached SDMX observations."""
    empty = pd.DataFrame(columns=OUTPUT_COLUMNS)

    directory = Path(args.unsd_path)
    mapping_path = Path(
        getattr(args, "fuel_mapping_path", "config/unsd/fuel_mapping.yaml")
    )

    required = [
        directory / "structure.xml",
        Path(args.transactions_path),
        mapping_path,
    ]

    required.extend(
        directory / f"{country_to_unsd_area(country)}.csv" for country in countries
    )

    missing = [str(source) for source in required if not source.exists()]

    if missing:
        logger.warning(
            "UNSD reference unavailable; missing inputs: %s",
            missing,
        )
        return empty

    mapping = yaml.safe_load(mapping_path.read_text())

    df = load_unsd(directory, countries)

    if df.empty or not (df["Year"] <= args.year).any():
        logger.warning("No UNSD observations up to year %s.", args.year)
        return empty

    transactions = pd.read_csv(
        args.transactions_path,
        sep=";",
        keep_default_na=False,
    )

    energy = energy_sector_rows(df, args.year)
    industry = industry_rows(
        df,
        transactions,
        args.year,
        include_other=True,
    )

    rows = pd.concat([energy, industry], ignore_index=True)

    rows = to_twh(
        rows,
        mapping["conversion_factors"],
    )

    parents = read_transaction_parents(directory / "structure.xml")

    if not args.include_other_industries:
        industrial = rows["sector"].eq("industry")
        rows = pd.concat(
            [
                rows.loc[~industrial],
                exclude_other_industries(rows.loc[industrial], parents),
            ]
        )

    return aggregate(
        rows,
        fuel_mapping(mapping),
        args.year,
        args.shift_coal_to_elec,
        args.stale_warning_years,
        transaction_parents=parents,
        commodity_parents=read_commodity_parents(directory / "structure.xml"),
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--unsd-path",
        default="data/unsd_sdmx",
    )
    parser.add_argument(
        "--transactions-path",
        default="config/unsd/industry_transactions.csv",
    )
    parser.add_argument(
        "--fuel-mapping-path",
        default="config/unsd/fuel_mapping.yaml",
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--countries", nargs="+", required=True)
    parser.add_argument("--shift-coal-to-elec", action="store_true")
    parser.add_argument("--include-other-industries", action="store_true")
    parser.add_argument(
        "--stale-warning-years",
        type=int,
        default=STALE_OBSERVATION_WARNING_YEARS,
    )
    parser.add_argument("--output", required=True)

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    table = build_reference(
        args,
        [country.upper() for country in args.countries],
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output, index=False)

    if not table.empty:
        logger.info(
            "UNSD reference years used:\\n%s",
            table.groupby(["region", "sector"])["reference_year"].max().to_string(),
        )


if __name__ == "__main__":
    main()
