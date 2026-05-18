# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Build demand reference data from Our World in Data.
"""

import os

import country_converter as coco
from helpers import configure_logging, read_csv_nafix, to_csv_nafix

cc = coco.CountryConverter()


def build_reference_demand_ourworldindata(inputs, outputs):
    """
    Retrieve electricity demand data from Our World in Data.
    """
    fp_input = inputs["demand_owid"]
    fp_output = outputs["demand_owid"]

    df = read_csv_nafix(fp_input)
    df = df.loc[:, ["iso_code", "year", "electricity_demand"]]
    df = df[df["iso_code"].notna()]  # removes Antarctica
    df["region"] = cc.pandas_convert(df["iso_code"], to="ISO2")
    df = df[["region", "year", "electricity_demand"]]
    df = df.set_index("region")

    to_csv_nafix(df, fp_output)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_demand_ourworldindata")

    configure_logging(snakemake)

    build_reference_demand_ourworldindata(snakemake.input, snakemake.output)
