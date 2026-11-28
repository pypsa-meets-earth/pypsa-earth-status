# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compare model CO2 emissions to EDGAR for sectors present in the model."""

import argparse
import logging
from pathlib import Path

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

COMPARISON_COLUMNS = [
    "region",
    "sector",
    "model_year",
    "reference_year",
    "network_emissions",
    "reference_emissions",
    "difference",
    "absolute_difference",
    "relative_difference_pct",
    "reference_source",
]
SUMMARY_COLUMNS = [
    "region",
    "model_year",
    "status",
    "model_total",
    "classified_total",
    "compared_total",
    "unclassified_emissions",
    "classification_coverage_pct",
    "comparison_coverage_pct",
]


def compare_emissions(model, reference, mappings, return_matched_assets=False):
    """Match modeled emitting assets only to explicitly mapped EDGAR sectors."""
    required_model = {
        "region",
        "sector",
        "carrier",
        "component",
        "model_year",
        "network_emissions",
    }
    required_reference = {
        "region",
        "sector",
        "reference_year",
        "reference_emissions",
        "reference_source",
    }
    if missing := required_model - set(model.columns):
        raise ValueError(f"Missing model columns: {sorted(missing)}")
    if missing := required_reference - set(reference.columns):
        raise ValueError(f"Missing reference columns: {sorted(missing)}")
    if not mappings:
        raise ValueError("At least one sector mapping is required.")
    if reference.duplicated(["region", "sector"]).any():
        raise ValueError("Multiple EDGAR rows for one country and sector.")

    model = model.reset_index(drop=True).copy()
    results = []
    used_assets = set()
    used_output_sectors = set()
    used_reference_sectors = set()
    available_sectors = set(model["sector"].dropna().astype(str).str.strip()) - {""}

    for mapping in mappings:
        sector = mapping["sector"]
        reference_sector = mapping["reference_sector"]
        if sector == "total" or sector in used_output_sectors:
            raise ValueError(f"Invalid or duplicated output sector: {sector}")
        used_output_sectors.add(sector)
        if reference_sector in used_reference_sectors:
            raise ValueError(f"EDGAR reference sector mapped twice: {reference_sector}")
        used_reference_sectors.add(reference_sector)

        # A missing sector is not equivalent to zero modeled emissions.
        if not (set(mapping["model_sectors"]) & available_sectors):
            logger.info("Skipping absent modeled sector: %s", sector)
            continue

        mask = model["sector"].isin(mapping["model_sectors"])
        if "components" in mapping:
            mask &= model["component"].isin(mapping["components"])
        if "include_carriers" in mapping:
            mask &= model["carrier"].isin(mapping["include_carriers"])
        selected = model.loc[mask]
        if selected.empty:
            logger.warning("No eligible emitting assets for sector %s", sector)
            continue

        overlap = used_assets.intersection(selected.index)
        if overlap:
            raise ValueError(f"Overlapping model assets for {sector}.")
        used_assets.update(selected.index)

        model_totals = selected.groupby(["region", "model_year"], as_index=False)[
            "network_emissions"
        ].sum()
        reference_selected = reference.loc[
            reference["sector"].eq(reference_sector),
            ["region", "reference_year", "reference_emissions", "reference_source"],
        ]
        comparison = model_totals.merge(
            reference_selected,
            on="region",
            how="left",
            validate="many_to_one",
            indicator=True,
        )
        if (comparison["_merge"] != "both").any():
            missing_regions = comparison.loc[
                comparison["_merge"] != "both", "region"
            ].tolist()
            raise ValueError(f"Missing EDGAR reference for {sector}: {missing_regions}")
        if comparison["reference_emissions"].isna().any():
            raise ValueError(f"Missing EDGAR emissions values for {sector}")
        comparison = comparison.drop(columns="_merge")
        comparison["sector"] = sector
        results.append(comparison)

    if not results:
        logger.warning("No model sectors can be compared with EDGAR.")
        empty = pd.DataFrame(columns=COMPARISON_COLUMNS)
        return (empty, used_assets) if return_matched_assets else empty

    sectors = pd.concat(results, ignore_index=True)
    reference_consistency = sectors.groupby(["region", "model_year"])[
        ["reference_year", "reference_source"]
    ].nunique(dropna=False)
    if (reference_consistency > 1).any().any():
        raise ValueError("Inconsistent EDGAR years or sources across sectors.")

    total = sectors.groupby(
        ["region", "model_year", "reference_year", "reference_source"],
        as_index=False,
        dropna=False,
    )[["network_emissions", "reference_emissions"]].sum()
    total["sector"] = "total"
    output = pd.concat([sectors, total], ignore_index=True)
    output["difference"] = output["network_emissions"] - output["reference_emissions"]
    output["absolute_difference"] = output["difference"].abs()
    output["relative_difference_pct"] = (
        output["difference"]
        .div(output["reference_emissions"].replace(0, float("nan")))
        .mul(100)
    )
    comparison = (
        output[COMPARISON_COLUMNS]
        .sort_values(["region", "model_year", "sector"])
        .reset_index(drop=True)
    )
    return (comparison, used_assets) if return_matched_assets else comparison


def build_comparison_summary(model, comparison, matched_assets):
    """Summarize positive emissions and EDGAR coverage at asset level.

    The comparison itself uses signed net emissions. Coverage is calculated
    from nonnegative emissions of exactly the assets selected for comparison.
    """
    required = {"region", "sector", "model_year", "network_emissions"}
    if missing := required - set(model.columns):
        raise ValueError(f"Missing summary columns: {sorted(missing)}")

    data = model.reset_index(drop=True).copy()
    data["emitted"] = data["network_emissions"].clip(lower=0)
    classified = data["sector"].fillna("").astype(str).str.strip().ne("")
    data["classified_emissions"] = data["emitted"].where(classified, 0)
    data["compared_emissions"] = data["emitted"].where(
        data.index.isin(matched_assets), 0
    )

    grouped = data.groupby(["region", "model_year"], as_index=False)[
        ["emitted", "classified_emissions", "compared_emissions"]
    ].sum()
    grouped = grouped.rename(
        columns={
            "emitted": "model_total",
            "classified_emissions": "classified_total",
            "compared_emissions": "compared_total",
        }
    )
    grouped["unclassified_emissions"] = (
        grouped["model_total"] - grouped["classified_total"]
    ).clip(lower=0)
    grouped["classified_not_compared"] = (
        grouped["classified_total"] - grouped["compared_total"]
    ).clip(lower=0)

    denominator = grouped["model_total"].replace(0, float("nan"))
    grouped["classification_coverage_pct"] = (
        100 * grouped["classified_total"] / denominator
    )
    grouped["comparison_coverage_pct"] = 100 * grouped["compared_total"] / denominator

    pairs = set(zip(comparison["region"], comparison["model_year"]))
    # Small exclusions are recorded without triggering a partial warning.
    coverage_warning_threshold_pct = 99.9
    grouped["status"] = [
        (
            "unavailable"
            if (row.region, row.model_year) not in pairs
            else (
                "partial"
                if row.model_total > 0
                and row.comparison_coverage_pct < coverage_warning_threshold_pct
                else "compared"
            )
        )
        for row in grouped.itertuples()
    ]
    for row in grouped.itertuples():
        message = (
            "CO2 comparison %s for %s (%s): %.4f%% coverage; "
            "%.6f MtCO2 unclassified; %.6f MtCO2 classified but not compared"
        )
        args = (
            row.status,
            row.region,
            row.model_year,
            row.comparison_coverage_pct,
            row.unclassified_emissions,
            row.classified_not_compared,
        )
        if row.status == "compared":
            logger.info(message, *args)
        else:
            logger.warning(message, *args)

    columns = [*SUMMARY_COLUMNS]
    if "classified_not_compared" not in columns:
        columns.append("classified_not_compared")
    return grouped[columns]


def detect_network_type(network, model):
    """Identify sector coupling from sector-specific loads, not generic buses."""
    sector_load_carriers = {
        "industry electricity",
        "land transport oil",
        "shipping oil",
        "kerosene for aviation",
        "residential rural heat",
        "services rural heat",
        "gas for industry",
    }

    load_carriers = set(network.loads.carrier.dropna().astype(str))
    sector_loads = load_carriers & sector_load_carriers

    if sector_loads:
        logger.info(
            "Detected sector-specific load carriers: %s",
            sorted(sector_loads),
        )
        if not model["sector"].notna().any():
            logger.warning("Sector-coupled network lacks sector emission metadata.")
        return "sector_coupled"

    return "electricity_only"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    model = pd.read_csv(args.model)
    reference = pd.read_csv(args.reference)
    with open(args.mapping) as handle:
        mappings = yaml.safe_load(handle)

    import pypsa

    network = pypsa.Network(args.network)
    network_type = detect_network_type(network, model)
    logger.info("Detected network type: %s", network_type)
    comparison, matched_assets = compare_emissions(
        model, reference, mappings[network_type], return_matched_assets=True
    )
    summary = build_comparison_summary(model, comparison, matched_assets)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output, index=False)
    print(comparison.to_string(index=False))

    if args.summary_output:
        summary_output = Path(args.summary_output)
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(summary_output, index=False)
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
