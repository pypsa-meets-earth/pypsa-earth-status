# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Build demand reference data from Ember.
"""

import os

import country_converter as coco
import pandas as pd
from helpers import configure_logging, read_csv_nafix, to_csv_nafix

cc = coco.CountryConverter()


def clean_demand_ember(df_ember):
    """
    Clean demand data from Ember.
    """
    df = df_ember.copy()

    # Filter to demand (in TWh)
    df = df[
        (df["Category"] == "Electricity demand")
        & (df["Variable"] == "Demand")
        & (df["Unit"] == "TWh")
    ]

    # Rename Value to demand
    df["demand"] = pd.to_numeric(df["Value"], errors="coerce")

    return df


def build_reference_demand_ember(inputs, outputs):
    """
    Retrieve demand data from Ember.
    """
    fp_input = inputs["demand_ember"]
    fp_output = outputs["demand_ember"]

    df_ember = read_csv_nafix(fp_input)
    df_ember["region"] = cc.pandas_convert(df_ember["ISO 3 code"], to="ISO2")
    df_ember = clean_demand_ember(df_ember)
    df_ember = df_ember[["region", "Year", "demand"]]
    df_ember = df_ember.set_index("region")

    to_csv_nafix(df_ember, fp_output)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_demand_ember")

    configure_logging(snakemake)

    build_reference_demand_ember(snakemake.input, snakemake.output)
