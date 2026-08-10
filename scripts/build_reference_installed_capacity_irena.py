# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Build installed capacity reference data from IRENA.
"""

import os

import country_converter as coco
import pandas as pd
from helpers import (
    apply_country_overrides,
    configure_logging,
    create_logger,
    find_unmapped_values,
    get_harmonization_sources,
    harmonize_and_aggregate,
    read_csv_nafix,
    to_csv_nafix,
)

cc = coco.CountryConverter()
logger = create_logger(__name__)

HARMONIZATION_SECTION = "irena_installed_capacity"
COUNTRY_COLUMN = "Country/area"
TECHNOLOGY_COLUMN = "Technology"
VALUE_COLUMN = "Electricity statistics (MW/GWh)"
OUTPUT_VALUE_COLUMN = "p_nom"


def convert_countries_to_iso2(country_names):
    """
    Convert country labels to ISO2 with compatibility across country_converter versions.
    """
    if hasattr(cc, "pandas_convert"):
        return cc.pandas_convert(country_names, to="ISO2")

    unique_countries = country_names.dropna().drop_duplicates()
    converted = coco.convert(unique_countries.tolist(), to="ISO2")
    if isinstance(converted, str):
        converted = [converted]

    country_codes = pd.Series(converted, index=unique_countries)
    return country_names.map(country_codes)


def clean_capacity_irena(df_irena, harmonization_config):
    """
    Clean capacity data from IRENA.
    """
    df = df_irena.copy()
    technology_mapping = harmonization_config.get("technology_mapping", {})
    drop_technologies = harmonization_config.get("drop_technologies", [])
    fail_on_unmapped = harmonization_config.get("fail_on_unmapped_technologies", True)

    mapped_technologies = get_harmonization_sources(technology_mapping)
    dropped_technologies = set(drop_technologies)
    overlapping_technologies = sorted(
        mapped_technologies & dropped_technologies,
        key=str,
    )
    if overlapping_technologies:
        raise ValueError(
            "Technologies cannot be both mapped and dropped in "
            f"{HARMONIZATION_SECTION}: {overlapping_technologies}"
        )

    unmapped_technologies = find_unmapped_values(
        df[TECHNOLOGY_COLUMN],
        selected_values=mapped_technologies,
        dropped_values=dropped_technologies,
    )
    if unmapped_technologies:
        message = (
            "Unmapped IRENA technologies found: "
            f"{unmapped_technologies}. Add them to "
            f"{HARMONIZATION_SECTION}.technology_mapping or "
            f"{HARMONIZATION_SECTION}.drop_technologies in "
            "configs/config_data_harmonization.yaml."
        )
        if fail_on_unmapped:
            raise ValueError(message)
        logger.warning("%s They will be dropped.", message)

    selected_rows = df[TECHNOLOGY_COLUMN].isin(mapped_technologies)
    installed_capacity_irena = df.loc[selected_rows].copy()
    installed_capacity_irena[OUTPUT_VALUE_COLUMN] = pd.to_numeric(
        installed_capacity_irena[VALUE_COLUMN],
        errors="coerce",
    )
    installed_capacity_irena = harmonize_and_aggregate(
        installed_capacity_irena,
        TECHNOLOGY_COLUMN,
        harmonization_config,
        aggregate_by=["region", TECHNOLOGY_COLUMN, "Year"],
        aggregate_columns=OUTPUT_VALUE_COLUMN,
    )

    return installed_capacity_irena


def build_reference_installed_capacity_irena(inputs, outputs, harmonization_config):
    """
    Retrieve installed capacity data from IRENA.
    """
    fp_input = inputs["cap_irena"]
    fp_output = outputs["cap_irena"]

    df_irena = read_csv_nafix(fp_input, skiprows=2, encoding="latin-1")
    df_irena = df_irena.iloc[:, [0, 1, 4, 5]]
    df_irena[COUNTRY_COLUMN] = apply_country_overrides(
        df_irena[COUNTRY_COLUMN],
        harmonization_config,
    )
    df_irena["region"] = convert_countries_to_iso2(df_irena[COUNTRY_COLUMN])
    df_irena = clean_capacity_irena(df_irena, harmonization_config)
    df_irena = df_irena[["region", TECHNOLOGY_COLUMN, "Year", OUTPUT_VALUE_COLUMN]]
    df_irena = df_irena.set_index("region")

    to_csv_nafix(df_irena, fp_output)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_installed_capacity_irena")

    configure_logging(snakemake)

    build_reference_installed_capacity_irena(
        snakemake.input,
        snakemake.output,
        snakemake.params.harmonization_config,
    )
