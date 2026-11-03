# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Build electricity generation reference data from IRENA.
"""

import os

import country_converter as coco
import pandas as pd
from helpers import (
    IRENA_GENERATION_EXCLUDED_TECHNOLOGIES,
    IRENA_TECHNOLOGY_MAPPING,
    configure_logging,
    read_csv_nafix,
    to_csv_nafix,
)

cc = coco.CountryConverter()


def clean_generation_irena(df_irena):
    """
    Clean electricity generation data from IRENA.

    Generation values are expressed in GWh. Aggregate technology rows and
    pumped-storage generation are excluded.
    """
    df = df_irena.copy()

    required_columns = {
        "Country/area",
        "Technology",
        "Data Type",
        "Grid connection",
        "Year",
        "Electricity generation statistics",
    }
    missing_columns = required_columns.difference(df.columns)

    if missing_columns:
        raise ValueError(
            "Missing expected columns in IRENA generation data: "
            f"{sorted(missing_columns)}. "
            f"Available columns: {df.columns.tolist()}"
        )

    data_type = df["Data Type"].astype(str).str.strip().str.casefold()
    df = df[data_type == "electricity generation (gwh)".casefold()]

    grid_connection = df["Grid connection"].astype(str).str.strip().str.casefold()
    df = df[grid_connection == "all"]

    technology_normalized = df["Technology"].astype(str).str.strip().str.casefold()

    df = df[~technology_normalized.isin(IRENA_GENERATION_EXCLUDED_TECHNOLOGIES)]

    df["Technology"] = df["Technology"].replace(IRENA_TECHNOLOGY_MAPPING)

    df["Year"] = pd.to_numeric(
        df["Year"],
        errors="coerce",
    )
    df["generation"] = pd.to_numeric(
        df["Electricity generation statistics"],
        errors="coerce",
    )

    df["region"] = cc.pandas_convert(
        df["Country/area"],
        to="ISO2",
    )

    df = df.dropna(
        subset=[
            "region",
            "Technology",
            "Year",
            "generation",
        ]
    )

    df = df[df["region"].astype(str).str.len() == 2]

    return df


def build_reference_generation_irena(inputs, outputs):
    """
    Build clean electricity generation reference data from IRENA.
    """
    fp_input = inputs["generation_irena"]
    fp_output = outputs["generation_irena"]

    df_irena = read_csv_nafix(
        fp_input,
        skiprows=2,
        encoding="latin-1",
    )

    df_irena = clean_generation_irena(df_irena)

    df_irena = df_irena[
        [
            "region",
            "Technology",
            "Year",
            "generation",
        ]
    ].set_index("region")

    to_csv_nafix(df_irena, fp_output)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_generation_irena")

    configure_logging(snakemake)

    build_reference_generation_irena(
        snakemake.input,
        snakemake.output,
    )
