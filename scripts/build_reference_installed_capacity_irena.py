# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Build installed capacity reference data from IRENA.

Capacity is aggregated by country, technology, and year, treating ``-`` as missing and
preserving groups with no reported values as missing.
The output is a CSV file with columns
``region`` (ISO2), ``Technology``, ``Year``, and ``p_nom`` (MW).

The IRENA installed capacity data is parsed in agreement with the configuration in
``configs/config_data_harmonization.yaml``.
Use ``installed_capacity.irena`` in ``configs/config_data_harmonization.yaml`` 
to drop technologies, map source labels to target technologies, and override
country labels before ISO2 conversion. Unmapped technologies raise an error when
``fail_on_unmapped_technologies`` is true; otherwise, warn and drop their rows.
"""

import os

import country_converter as coco
import pandas as pd
from helpers import (
    configure_logging,
    drop_rows,
    map_labels,
    read_csv_nafix,
    to_csv_nafix,
)

cc = coco.CountryConverter()

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

    country_codes = pd.Series(converted, index=unique_countries, dtype=object)
    return country_names.map(country_codes)


def clean_capacity_irena(df_irena, cfg_installed_capacity):
    """
    Clean capacity data from IRENA.
    """
    df = drop_rows(
        df_irena, TECHNOLOGY_COLUMN, cfg_installed_capacity.get("drop_technologies", [])
    )
    df[TECHNOLOGY_COLUMN] = map_labels(
        df[TECHNOLOGY_COLUMN],
        cfg_installed_capacity["technology_mapping"],
        fail_on_unmapped=cfg_installed_capacity.get(
            "fail_on_unmapped_technologies", True
        ),
    )
    df = df.dropna(subset=[TECHNOLOGY_COLUMN])
    df[COUNTRY_COLUMN] = df[COUNTRY_COLUMN].replace(
        cfg_installed_capacity.get("country_overrides", {})
    )
    df["region"] = convert_countries_to_iso2(df[COUNTRY_COLUMN])
    df[OUTPUT_VALUE_COLUMN] = pd.to_numeric(df[VALUE_COLUMN].replace("-", float("nan")))
    return df.groupby(
        ["region", TECHNOLOGY_COLUMN, "Year"], as_index=False, sort=False
    )[[OUTPUT_VALUE_COLUMN]].sum(min_count=1)


def build_reference_installed_capacity_irena(inputs, outputs, cfg_installed_capacity):
    """
    Retrieve installed capacity data from IRENA.
    """
    fp_input = inputs["cap_irena"]
    fp_output = outputs["cap_irena"]

    df_irena = read_csv_nafix(fp_input, skiprows=2, encoding="latin-1")
    df_irena = clean_capacity_irena(df_irena, cfg_installed_capacity)
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
        snakemake.params.cfg_installed_capacity,
    )
