# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


IRENA_2020_SCENARIOS = {
    "AU_2021",
    "BR_2021",
    "CN_2021",
    "CO_2021",
    "DE_2021",
    "IN_2021",
    "IT_2021",
    "MX_2021",
    "NG_2021",
    "US_2021",
    "ZA_2021",
}


def configure_logging(snakemake):
    logging.basicConfig(
        filename=snakemake.log[0],
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )


def compile_docs_tables(snakemake):
    health_status_path = snakemake.input.health_status
    overview_path = snakemake.output.overview
    statistics_path = snakemake.output.statistics

    df = pd.read_csv(health_status_path)

    # 1. Build Overview Grid
    overview_rows = []

    # Group by scenario and country
    groups = df.groupby(
        ["scenario_key", "country_code", "country_name", "pypsa_earth_version", "year"]
    )

    for (scenario, country_code, country_name, version, year), grp in groups:
        # Extract grades per pillar
        # Format: "Grade (Source)" or comma-separated list if multiple
        def format_grades(pillar, metric):
            sub = grp[(grp["pillar"] == pillar) & (grp["metric"] == metric)]
            if sub.empty:
                return "-"
            grades = []
            for _, r in sub.iterrows():
                grade = r["grade"]
                src = r["reference_source"]
                if pd.isna(grade) or grade == "":
                    # For MAE metrics, grade is empty, so we don't list it in overview total grades
                    continue
                grades.append(f"{grade} ({src})")
            return ", ".join(grades) if grades else "-"

        demand_grade = format_grades("demand", "total_demand")
        capacity_grade = format_grades("installed_capacity", "total_capacity")
        generation_grade = format_grades("generation", "total_generation")

        overview_rows.append(
            {
                "Scenario": scenario,
                "Country": f"{country_name} ({country_code})",
                "Demand Grade": demand_grade,
                "Capacity Grade": capacity_grade,
                "Generation Grade": generation_grade,
                "PyPSA-Earth Version": version,
                "Year": year,
            }
        )

    overview_df = pd.DataFrame(overview_rows)

    # Write overview.md
    os.makedirs(os.path.dirname(overview_path), exist_ok=True)
    with open(overview_path, "w") as f:
        f.write(
            "<!--\n"
            "SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors\n\n"
            "SPDX-License-" + "Identifier: CC-BY-4.0\n"
            "-->\n"
            "# Validation Overview\n\n"
        )
        f.write(
            "A summary of validation grades across all analyzed countries and scenarios. Grades assess the percentage deviation between model outputs and historical reference statistics (Ember, IRENA, OWID).\n\n"
        )
        f.write(overview_df.to_markdown(index=False))
        f.write("\n")
    logger.info(f"Successfully generated overview table at {overview_path}")

    # 2. Build Detailed Statistics Report
    os.makedirs(os.path.dirname(statistics_path), exist_ok=True)
    with open(statistics_path, "w") as f:
        f.write(
            "<!--\n"
            "SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors\n\n"
            "SPDX-License-" + "Identifier: CC-BY-4.0\n"
            "-->\n"
            "# Detailed Validation Statistics\n\n"
        )
        f.write(
            "Detailed comparisons of active validation scenarios. Metrics are grouped by country and pillar.\n\n"
        )

        # Group by country
        for (scenario, country_code, country_name, version, year), grp in groups:
            f.write(f"## {country_name} ({country_code}) — Scenario `{scenario}`\n\n")
            f.write(f"* **Model Year:** {year}\n")
            f.write(f"* **PyPSA-Earth Version:** `{version}`\n\n")

            if scenario in IRENA_2020_SCENARIOS:
                f.write(
                    '!!! note "Validation Baseline Caveat"\n'
                    '    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).\n'
                    "    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.\n\n"
                )

            # Sub-table for Demand
            demand_sub = grp[grp["pillar"] == "demand"]
            if not demand_sub.empty:
                f.write("### 1. Electricity Demand\n\n")
                tbl = demand_sub[
                    [
                        "reference_source",
                        "pypsa_value",
                        "reference_value",
                        "deviation_pct",
                        "grade",
                    ]
                ].copy()
                tbl.columns = [
                    "Source",
                    "Model Value (TWh)",
                    "Reference Value (TWh)",
                    "Deviation (%)",
                    "Grade",
                ]
                # Round columns for readability
                tbl["Model Value (TWh)"] = tbl["Model Value (TWh)"].round(2)
                tbl["Reference Value (TWh)"] = tbl["Reference Value (TWh)"].round(2)
                tbl["Deviation (%)"] = (
                    tbl["Deviation (%)"]
                    .round(2)
                    .map(lambda val: f"{val:+.2f}%" if not pd.isna(val) else "-")
                )
                f.write(tbl.to_markdown(index=False))
                f.write("\n\n")

            # Sub-table for Capacity
            capacity_sub = grp[grp["pillar"] == "installed_capacity"]
            if not capacity_sub.empty:
                f.write("### 2. Installed Capacity\n\n")

                # Total capacity rows
                total_cap = capacity_sub[
                    capacity_sub["metric"] == "total_capacity"
                ].copy()
                if not total_cap.empty:
                    tbl = total_cap[
                        [
                            "reference_source",
                            "pypsa_value",
                            "reference_value",
                            "deviation_pct",
                            "grade",
                        ]
                    ].copy()
                    tbl.columns = [
                        "Source",
                        "Model Value (MW)",
                        "Reference Value (MW)",
                        "Deviation (%)",
                        "Grade",
                    ]
                    tbl["Model Value (MW)"] = tbl["Model Value (MW)"].round(2)
                    tbl["Reference Value (MW)"] = tbl["Reference Value (MW)"].round(2)
                    tbl["Deviation (%)"] = (
                        tbl["Deviation (%)"]
                        .round(2)
                        .map(lambda val: f"{val:+.2f}%" if not pd.isna(val) else "-")
                    )
                    f.write("**Total Installed Capacity Comparison:**\n\n")
                    f.write(tbl.to_markdown(index=False))
                    f.write("\n\n")

                # MAE rows
                mae_cap = capacity_sub[
                    capacity_sub["metric"] == "capacity_mae_pct"
                ].copy()
                if not mae_cap.empty:
                    f.write("**Distribution Mean Absolute Error (MAE):**\n\n")
                    for _, r in mae_cap.iterrows():
                        f.write(
                            f"- **MAE vs. {r['reference_source'].upper()}:** {r['pypsa_value']:.2f}% of total capacity\n"
                        )
                    f.write("\n")

            # Sub-table for Generation
            generation_sub = grp[grp["pillar"] == "generation"]
            if not generation_sub.empty:
                f.write("### 3. Electricity Generation\n\n")

                # Total generation rows
                total_gen = generation_sub[
                    generation_sub["metric"] == "total_generation"
                ].copy()
                if not total_gen.empty:
                    tbl = total_gen[
                        [
                            "reference_source",
                            "pypsa_value",
                            "reference_value",
                            "deviation_pct",
                            "grade",
                        ]
                    ].copy()
                    tbl.columns = [
                        "Source",
                        "Model Value (TWh)",
                        "Reference Value (TWh)",
                        "Deviation (%)",
                        "Grade",
                    ]
                    tbl["Model Value (TWh)"] = tbl["Model Value (TWh)"].round(2)
                    tbl["Reference Value (TWh)"] = tbl["Reference Value (TWh)"].round(2)
                    tbl["Deviation (%)"] = (
                        tbl["Deviation (%)"]
                        .round(2)
                        .map(lambda val: f"{val:+.2f}%" if not pd.isna(val) else "-")
                    )
                    f.write("**Total Generation Comparison:**\n\n")
                    f.write(tbl.to_markdown(index=False))
                    f.write("\n\n")

                # MAE rows
                mae_gen = generation_sub[
                    generation_sub["metric"] == "generation_share_mae"
                ].copy()
                if not mae_gen.empty:
                    f.write("**Distribution Mean Absolute Error (MAE):**\n\n")
                    for _, r in mae_gen.iterrows():
                        f.write(
                            f"- **MAE vs. {r['reference_source'].upper()}:** {r['pypsa_value']:.2f}% of total generation\n"
                        )
                    f.write("\n")

            f.write("---\n\n")

    logger.info(
        f"Successfully generated detailed statistics report at {statistics_path}"
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from helpers import mock_snakemake

        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        snakemake = mock_snakemake("build_docs_tables")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)
    compile_docs_tables(snakemake)
