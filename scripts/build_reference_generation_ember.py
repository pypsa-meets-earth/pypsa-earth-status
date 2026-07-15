# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Build generation mix reference data from Ember.
"""

import os

import country_converter as coco
import pandas as pd
from helpers import configure_logging, read_csv_nafix, to_csv_nafix

cc = coco.CountryConverter()


def clean_generation_ember(df_ember):
    """
    Clean generation data from Ember.
    """
    df = df_ember.copy()

    # Filter to generation by specific fuel subcategory (in TWh)
    df = df[
        (df["Category"] == "Electricity generation")
        & (df["Subcategory"] == "Fuel")
        & (df["Unit"] == "TWh")
    ]

    # Map variables to PyPSA carriers
    mapping = {
        "Bioenergy": "biomass",
        "Coal": "coal",
        "Gas": "CCGT",
        "Hydro": "hydro",
        "Nuclear": "nuclear",
        "Other Fossil": "oil",
        "Other Renewables": "geothermal",
        "Solar": "solar",
        "Wind": "onwind",
    }
    df["Technology"] = df["Variable"].map(mapping)

    # Conversion - already in TWh
    df["generation"] = pd.to_numeric(df["Value"], errors="coerce")

    # Drop unmapped technologies
    df = df.dropna(subset=["Technology"])

    return df


def build_reference_generation_ember(inputs, outputs):
    """
    Retrieve generation mix data from Ember.
    """
    fp_input = inputs["gen_ember"]
    fp_output = outputs["gen_ember"]

    df_ember = read_csv_nafix(fp_input)
    df_ember["region"] = cc.pandas_convert(df_ember["ISO 3 code"], to="ISO2")
    df_ember = clean_generation_ember(df_ember)
    df_ember = df_ember[["region", "Technology", "Year", "generation"]]
    df_ember = df_ember.set_index("region")

    to_csv_nafix(df_ember, fp_output)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_generation_ember")

    configure_logging(snakemake)

    build_reference_generation_ember(snakemake.input, snakemake.output)
