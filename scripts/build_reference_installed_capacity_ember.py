# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Build installed capacity reference data from Ember.
"""

import os

import country_converter as coco
import pandas as pd
from helpers import configure_logging, read_csv_nafix, to_csv_nafix

cc = coco.CountryConverter()


def clean_capacity_ember(df_ember):
    """
    Clean capacity data from Ember.
    """
    df = df_ember.copy()

    # Filter to capacity by specific fuel subcategory
    df = df[(df["Category"] == "Capacity") & (df["Subcategory"] == "Fuel")]

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

    # Convert GW to MW (Ember capacity values are in GW)
    df["p_nom"] = pd.to_numeric(df["Value"], errors="coerce") * 1000.0

    # Drop unmapped technologies
    df = df.dropna(subset=["Technology"])

    return df


def build_reference_installed_capacity_ember(inputs, outputs):
    """
    Retrieve installed capacity data from Ember.
    """
    fp_input = inputs["cap_ember"]
    fp_output = outputs["cap_ember"]

    df_ember = read_csv_nafix(fp_input)
    df_ember["region"] = cc.pandas_convert(df_ember["ISO 3 code"], to="ISO2")
    df_ember = clean_capacity_ember(df_ember)
    df_ember = df_ember[["region", "Technology", "Year", "p_nom"]]
    df_ember = df_ember.set_index("region")

    to_csv_nafix(df_ember, fp_output)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_installed_capacity_ember")

    configure_logging(snakemake)

    build_reference_installed_capacity_ember(snakemake.input, snakemake.output)
