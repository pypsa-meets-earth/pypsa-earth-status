# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compare modeled final energy consumption to UNSD for comparable categories."""

import argparse
import logging
from pathlib import Path

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

UNCLASSIFIED = "unclassified"
COVERAGE_WARNING_THRESHOLD_PCT = 99.9

SECTOR_COUPLED_LOAD_CARRIERS = {
    "industry electricity",
    "land transport oil",
    "shipping oil",
    "kerosene for aviation",
    "residential rural heat",
    "services rural heat",
    "gas for industry",
}

DETAIL_COLUMNS = [
    "region",
    "sector",
    "fuel",
    "model_year",
    "reference_year",
    "network_twh",
    "reference_twh",
    "difference",
    "absolute_difference",
    "relative_difference_pct",
    "status",
    "reference_source",
]
SECTOR_COLUMNS = [
    "region",
    "sector",
    "model_year",
    "reference_year",
    "n_fuels_compared",
    "network_twh",
    "reference_twh",
    "difference",
    "absolute_difference",
    "relative_difference_pct",
    "sector_model_total_twh",
    "sector_coverage_pct",
    "reference_source",
]
FUEL_COLUMNS = [
    "region",
    "fuel",
    "model_year",
    "reference_year",
    "n_sectors_compared",
    "network_twh",
    "reference_twh",
    "difference",
    "absolute_difference",
    "relative_difference_pct",
    "reference_source",
]
NATIONAL_COLUMNS = [
    "region",
    "model_year",
    "reference_year",
    "status",
    "model_total_twh",
    "classified_total_twh",
    "compared_total_twh",
    "unclassified_twh",
    "network_twh",
    "reference_twh",
    "reference_scope_twh",
    "difference",
    "absolute_difference",
    "relative_difference_pct",
    "classification_coverage_pct",
    "comparison_coverage_pct",
    "reference_coverage_pct",
]


def prepare_model(model):
    """Validate and normalize the asset-level model table."""
    required = {"region", "sector", "fuel", "model_year", "consumption_twh"}
    if missing := required - set(model.columns):
        raise ValueError(f"Missing model columns: {sorted(missing)}")

    data = model.copy()
    data["region"] = data["region"].fillna("").astype(str).str.strip()
    for column in ("sector", "fuel"):
        data[column] = (
            data[column].fillna("").astype(str).str.strip().replace("", UNCLASSIFIED)
        )
    data["consumption_twh"] = pd.to_numeric(data["consumption_twh"], errors="coerce")

    if data.groupby("region")["model_year"].nunique().gt(1).any():
        raise ValueError("Multiple model years for one region.")

    return data


def add_differences(table, model_col="network_twh", reference_col="reference_twh"):
    """Add absolute and relative differences."""
    table["difference"] = table[model_col] - table[reference_col]
    table["absolute_difference"] = table["difference"].abs()
    table["relative_difference_pct"] = (
        table["difference"].div(table[reference_col].replace(0, float("nan"))).mul(100)
    )
    return table


def warn_unknown_categories(model, mapping):
    """Warn about sectors or fuels outside the mapping vocabulary."""
    if not mapping:
        return
    known = {
        "sector": set(mapping.get("sectors", {})),
        "fuel": set(mapping.get("fuels", {})),
    }
    for column, names in known.items():
        unknown = set(model[column]) - names - {UNCLASSIFIED}
        if unknown:
            logger.warning("Model %s outside the mapping: %s", column, sorted(unknown))


def compare_consumption(model, reference, mapping=None):
    """Match modeled sector-fuel pairs to UNSD pairs present in both tables."""
    required_reference = {
        "region",
        "sector",
        "fuel",
        "reference_year",
        "reference_twh",
        "reference_source",
    }
    if missing := required_reference - set(reference.columns):
        raise ValueError(f"Missing reference columns: {sorted(missing)}")
    if reference.duplicated(["region", "sector", "fuel"]).any():
        raise ValueError("Multiple UNSD rows for one country, sector and fuel.")

    warn_unknown_categories(model, mapping)

    classified = model[
        model["sector"].ne(UNCLASSIFIED) & model["fuel"].ne(UNCLASSIFIED)
    ]
    if classified.empty:
        logger.warning("No classified model consumption can be compared with UNSD.")
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    year_by_region = model.groupby("region")["model_year"].first()

    modeled = (
        classified.groupby(["region", "sector", "fuel"], as_index=False)[
            "consumption_twh"
        ]
        .sum(min_count=1)
        .rename(columns={"consumption_twh": "network_twh"})
    )

    # A sector absent from the model is not zero consumption: drop its UNSD rows.
    present = set(zip(modeled["region"], modeled["sector"]))
    in_scope = [
        (r, s) in present for r, s in zip(reference["region"], reference["sector"])
    ]
    scoped = reference.loc[
        in_scope,
        [
            "region",
            "sector",
            "fuel",
            "reference_year",
            "reference_twh",
            "reference_source",
        ],
    ]
    skipped = len(reference) - len(scoped)
    if skipped:
        logger.info("Ignored %s UNSD rows for sectors absent in the model.", skipped)

    merged = modeled.merge(
        scoped, on=["region", "sector", "fuel"], how="outer", indicator=True
    )
    merged["model_year"] = merged["region"].map(year_by_region)
    merged["status"] = merged["_merge"].map(
        {
            "both": "compared",
            "left_only": "reference_unavailable",
            "right_only": "model_missing",
        }
    )
    merged.loc[
        merged["status"].eq("compared") & merged["reference_twh"].isna(), "status"
    ] = "reference_unavailable"

    comparable = merged["status"].eq("compared")
    for status, group in merged.groupby("status"):
        if status != "compared":
            logger.warning(
                "%s sector-fuel pairs excluded from comparison (%s): %s",
                len(group),
                status,
                sorted(
                    set(zip(group["region"], group["sector"], group["fuel"])),
                )[:10],
            )

    difference_columns = [
        "difference",
        "absolute_difference",
        "relative_difference_pct",
    ]
    for column in difference_columns:
        merged[column] = float("nan")
    differences = add_differences(merged.loc[comparable].copy())
    merged.loc[comparable, difference_columns] = differences[difference_columns]

    return (
        merged[DETAIL_COLUMNS]
        .sort_values(["region", "sector", "fuel"])
        .reset_index(drop=True)
    )


def _aggregate(compared, keys, count_name, count_of):
    """Aggregate compared rows over the given keys."""
    if compared.empty:
        return pd.DataFrame()

    grouped = compared.groupby(keys + ["model_year"], as_index=False).agg(
        reference_year=("reference_year", "max"),
        network_twh=("network_twh", "sum"),
        reference_twh=("reference_twh", "sum"),
        reference_source=(
            "reference_source",
            lambda s: ";".join(sorted(set(map(str, s)))),
        ),
        **{count_name: (count_of, "nunique")},
    )

    if compared.groupby(keys + ["model_year"])["reference_year"].nunique().gt(1).any():
        logger.warning("UNSD reference years differ within an aggregate; using latest.")

    return add_differences(grouped)


def sector_table(model, detail):
    """Total comparable consumption by sector."""
    compared = detail[detail["status"].eq("compared")]
    table = _aggregate(compared, ["region", "sector"], "n_fuels_compared", "fuel")
    if table.empty:
        return pd.DataFrame(columns=SECTOR_COLUMNS)

    classified = model[
        model["sector"].ne(UNCLASSIFIED) & model["fuel"].ne(UNCLASSIFIED)
    ]
    totals = (
        classified.groupby(["region", "sector"])["consumption_twh"]
        .sum()
        .rename("sector_model_total_twh")
        .reset_index()
    )
    table = table.merge(totals, on=["region", "sector"], how="left")
    table["sector_coverage_pct"] = (
        100
        * table["network_twh"]
        / table["sector_model_total_twh"].replace(0, float("nan"))
    )
    return table[SECTOR_COLUMNS]


def fuel_table(detail):
    """National consumption by fuel across comparable sectors."""
    compared = detail[detail["status"].eq("compared")]
    table = _aggregate(compared, ["region", "fuel"], "n_sectors_compared", "sector")
    return (
        table[FUEL_COLUMNS] if not table.empty else pd.DataFrame(columns=FUEL_COLUMNS)
    )


def national_table(model, detail):
    """National totals restricted to comparable categories, with coverage."""
    keys = ["region", "model_year"]

    totals = (
        model.groupby(keys, as_index=False)["consumption_twh"]
        .sum()
        .rename(columns={"consumption_twh": "model_total_twh"})
    )
    classified = model[
        model["sector"].ne(UNCLASSIFIED) & model["fuel"].ne(UNCLASSIFIED)
    ]
    classified_totals = (
        classified.groupby(keys, as_index=False)["consumption_twh"]
        .sum()
        .rename(columns={"consumption_twh": "classified_total_twh"})
    )
    compared = (
        detail[detail["status"].eq("compared")]
        .groupby(keys, as_index=False)
        .agg(
            reference_year=("reference_year", "max"),
            network_twh=("network_twh", "sum"),
            reference_twh=("reference_twh", "sum"),
        )
    )
    scope = (
        detail[detail["status"].isin(["compared", "model_missing"])]
        .groupby(keys, as_index=False)["reference_twh"]
        .sum()
        .rename(columns={"reference_twh": "reference_scope_twh"})
    )

    table = (
        totals.merge(classified_totals, on=keys, how="left")
        .merge(compared, on=keys, how="left")
        .merge(scope, on=keys, how="left")
    )
    table["classified_total_twh"] = table["classified_total_twh"].fillna(0.0)
    table["compared_total_twh"] = table["network_twh"].fillna(0.0)
    table["unclassified_twh"] = table["model_total_twh"] - table["classified_total_twh"]

    table = add_differences(table)

    model_total = table["model_total_twh"].replace(0, float("nan"))
    table["classification_coverage_pct"] = (
        100 * table["classified_total_twh"] / model_total
    )
    table["comparison_coverage_pct"] = 100 * table["compared_total_twh"] / model_total
    table["reference_coverage_pct"] = (
        100
        * table["reference_twh"]
        / table["reference_scope_twh"].replace(0, float("nan"))
    )

    table["status"] = [
        (
            "unavailable"
            if pd.isna(row.network_twh)
            else (
                "partial"
                if row.comparison_coverage_pct < COVERAGE_WARNING_THRESHOLD_PCT
                else "compared"
            )
        )
        for row in table.itertuples()
    ]

    for row in table.itertuples():
        message = (
            "Fuel comparison %s for %s (%s): %.2f%% of model consumption compared; "
            "%.4f TWh unclassified"
        )
        args = (
            row.status,
            row.region,
            row.model_year,
            (
                0.0
                if pd.isna(row.comparison_coverage_pct)
                else row.comparison_coverage_pct
            ),
            row.unclassified_twh,
        )
        (logger.info if row.status == "compared" else logger.warning)(message, *args)

    return table[NATIONAL_COLUMNS]


def check_sector_coupled(network):
    """Warn when the network has no sector-specific loads."""
    found = (
        set(network.loads.carrier.dropna().astype(str)) & SECTOR_COUPLED_LOAD_CARRIERS
    )
    if not found:
        logger.warning(
            "No sector-specific load carriers found: the network does not look "
            "sector-coupled and most sectors will be unavailable."
        )
    else:
        logger.info("Detected sector-specific load carriers: %s", sorted(found))


def write(table, path):
    """Write a table, creating parent folders."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sector-output", required=True)
    parser.add_argument("--fuel-output", required=True)
    parser.add_argument("--national-output", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    model = prepare_model(pd.read_csv(args.model))
    reference = pd.read_csv(args.reference)
    with open(args.mapping) as handle:
        mapping = yaml.safe_load(handle)

    import pypsa

    check_sector_coupled(pypsa.Network(args.network))

    detail = compare_consumption(model, reference, mapping)

    write(detail, args.output)
    write(sector_table(model, detail), args.sector_output)
    write(fuel_table(detail), args.fuel_output)
    national = national_table(model, detail)
    write(national, args.national_output)

    print(detail.to_string(index=False))
    print(national.to_string(index=False))


if __name__ == "__main__":
    main()
