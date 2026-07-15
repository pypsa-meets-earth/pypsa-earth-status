# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-


import logging
import os
import shutil

import country_converter as coco
import numpy as np
import pandas as pd
import pypsa
from helpers import configure_logging, harmonize_carrier_names, read_csv_nafix

logger = logging.getLogger(__name__)


def get_grade(deviation_pct):
    if pd.isna(deviation_pct):
        return ""
    val = abs(deviation_pct)
    if val < 5.0:
        return "A"
    elif val < 10.0:
        return "B"
    elif val < 20.0:
        return "C"
    else:
        return "D"


def compile_health_status(snakemake):
    # Year: handle single value or list
    year = snakemake.params.year
    if isinstance(year, list):
        year = year[0]

    # Networks dictionary
    networks = snakemake.params.networks
    if not networks:
        logger.warning("No networks defined in configuration networks list.")
        return

    cc = coco.CountryConverter()

    # Resolve datasets and fallback version configuration from snakemake params
    datasets = snakemake.params.datasets
    fallback_version = snakemake.params.fallback_pypsa_earth_version

    # Preload all configured demand reference sources
    demand_refs = {}
    for src in datasets.get("demand", ["ember"]):
        src = src.lower()
        if src == "ourworldindata":
            df = read_csv_nafix(snakemake.input.demand_owid)
            df = df.rename(columns={"year": "Year", "electricity_demand": "demand"})
        elif src == "ember":
            df = read_csv_nafix(snakemake.input.demand_ember)
        else:
            logger.warning(f"Unknown demand source: {src}, skipping.")
            continue
        demand_refs[src] = df[df["Year"] == year]

    # Preload all configured capacity reference sources
    capacity_refs = {}
    for src in datasets.get("installed_capacity", ["ember"]):
        src = src.lower()
        if src == "irena":
            df = read_csv_nafix(snakemake.input.cap_irena)
        elif src == "ember":
            df = read_csv_nafix(snakemake.input.cap_ember)
        else:
            logger.warning(f"Unknown capacity source: {src}, skipping.")
            continue
        df = df[df["Year"] == year].rename(columns={"Technology": "carrier"})
        df["carrier"] = harmonize_carrier_names(df["carrier"])
        capacity_refs[src] = df

    # Preload all configured generation reference sources
    generation_refs = {}
    for src in datasets.get("generation", ["ember"]):
        src = src.lower()
        if src == "ember":
            df = read_csv_nafix(snakemake.input.gen_ember)
        else:
            logger.warning(f"Unknown generation source: {src}, skipping.")
            continue
        df = df[df["Year"] == year].rename(columns={"Technology": "carrier"})
        df["carrier"] = harmonize_carrier_names(df["carrier"])
        generation_refs[src] = df

    carriers = [
        "pv",
        "wind",
        "hydro",
        "ccgt",
        "coal",
        "nuclear",
        "oil",
        "biomass",
        "geothermal",
        "other",
    ]

    records = []

    for scenario_key, network_info in networks.items():
        if isinstance(network_info, str):
            network_path = network_info
            explicit_countries = None
        else:
            network_path = network_info.get("path")
            explicit_countries = network_info.get("countries")

        logger.info(f"Processing scenario {scenario_key}...")
        logger.info(f"  Using solved network: {network_path}")

        if not network_path or not os.path.exists(network_path):
            logger.warning(
                f"  Warning: Solved network path for {scenario_key} does not exist: {network_path}. Skipping."
            )
            continue

        try:
            n = pypsa.Network(network_path)
        except Exception as e:
            logger.error(f"  Error loading network for {scenario_key}: {e}. Skipping.")
            continue

        # Extract pypsa-earth version from network metadata
        pypsa_earth_version = (
            n.meta.get("version", fallback_version)
            if isinstance(getattr(n, "meta", None), dict)
            else fallback_version
        )

        # Resolve target countries for this scenario
        if explicit_countries is not None:
            target_countries = explicit_countries
        else:
            if "country" in n.buses.columns:
                target_countries = n.buses["country"].dropna().unique().tolist()
                target_countries = [
                    c
                    for c in target_countries
                    if c and isinstance(c, str) and c.strip()
                ]
            else:
                target_countries = []

        target_countries = [c.strip().upper() for c in target_countries]

        if not target_countries:
            logger.warning(
                f"  No target countries resolved for scenario {scenario_key}. Skipping."
            )
            continue

        # Extract common stats for all countries in this network (we will filter per country)
        gen_cap = n.generators[["carrier", "p_nom", "bus"]].copy()
        if "country" in n.buses.columns:
            gen_cap["region"] = (
                n.buses.loc[gen_cap["bus"], "country"].fillna("").astype(str).values
            )
        else:
            gen_cap["region"] = ""

        if not n.storage_units.empty:
            store_cap = n.storage_units[["carrier", "p_nom", "bus"]].copy()
            if "country" in n.buses.columns:
                store_cap["region"] = (
                    n.buses.loc[store_cap["bus"], "country"]
                    .fillna("")
                    .astype(str)
                    .values
                )
            else:
                store_cap["region"] = ""
            installed_capacity = pd.concat([gen_cap, store_cap], axis=0)
        else:
            installed_capacity = gen_cap

        installed_capacity = installed_capacity[
            ~installed_capacity["carrier"].str.lower().isin(["load", "load shedding"])
        ]
        installed_capacity["carrier"] = harmonize_carrier_names(
            installed_capacity["carrier"]
        )

        gen_p_t = n.generators_t.p.multiply(n.snapshot_weightings.objective, axis=0)
        gen_gen_sum = gen_p_t.sum() * 1e-6
        df_gen = pd.DataFrame(
            {
                "generation": gen_gen_sum,
                "carrier": n.generators.carrier,
                "bus": n.generators.bus,
            }
        )
        if "country" in n.buses.columns:
            df_gen["region"] = (
                n.buses.loc[df_gen["bus"], "country"].fillna("").astype(str).values
            )
        else:
            df_gen["region"] = ""

        if not n.storage_units.empty:
            store_p_t = n.storage_units_t.p.multiply(
                n.snapshot_weightings.objective, axis=0
            )
            store_gen_sum = store_p_t.sum() * 1e-6
            df_store = pd.DataFrame(
                {
                    "generation": store_gen_sum,
                    "carrier": n.storage_units.carrier,
                    "bus": n.storage_units.bus,
                }
            )
            if "country" in n.buses.columns:
                df_store["region"] = (
                    n.buses.loc[df_store["bus"], "country"]
                    .fillna("")
                    .astype(str)
                    .values
                )
            else:
                df_store["region"] = ""
            generation = pd.concat([df_gen, df_store], axis=0)
        else:
            generation = df_gen

        generation = generation[
            ~generation["carrier"].str.lower().isin(["load", "load shedding"])
        ]
        generation["carrier"] = harmonize_carrier_names(generation["carrier"])

        # Now loop through target countries
        for country in target_countries:
            country_name = cc.convert(names=country, to="name")
            logger.info(f"  Comparing country {country_name} ({country})...")

            # 1. Compute PyPSA Values (Once per country)
            # Demand
            if "country" in n.buses.columns:
                loads_country = n.loads.bus.map(n.buses.country)
                country_loads = n.loads.index[loads_country == country]
            else:
                country_loads = n.loads.index

            pypsa_demand = (
                n.loads_t.p_set.reindex(columns=country_loads, fill_value=0.0)
                .multiply(n.snapshot_weightings.objective, axis=0)
                .sum()
                .sum()
                * 1e-6
            )

            # Capacity
            installed_capacity_country = installed_capacity[
                installed_capacity["region"].str.upper() == country
            ]
            pypsa_cap_grouped = installed_capacity_country.groupby("carrier")[
                "p_nom"
            ].sum()
            total_installed_capacity_pypsa = pypsa_cap_grouped.reindex(
                carriers, fill_value=0.0
            ).sum()

            # Generation
            generation_country = generation[generation["region"].str.upper() == country]
            pypsa_gen_grouped = generation_country.groupby("carrier")[
                "generation"
            ].sum()
            total_generation_pypsa = pypsa_gen_grouped.reindex(
                carriers, fill_value=0.0
            ).sum()

            # 2. Process Demand Sources
            for demand_src, ref_demand_df in demand_refs.items():
                ref_dem_row = ref_demand_df[ref_demand_df["region"] == country]
                if ref_dem_row.empty:
                    continue
                ref_demand = ref_dem_row["demand"].sum()
                demand_error_pct = (
                    ((pypsa_demand - ref_demand) / ref_demand * 100.0)
                    if ref_demand > 0
                    else np.nan
                )

                records.append(
                    {
                        "scenario_key": scenario_key,
                        "country_code": country,
                        "country_name": country_name,
                        "pillar": "demand",
                        "metric": "total_demand",
                        "carrier": "total",
                        "pypsa_value": pypsa_demand,
                        "reference_value": ref_demand,
                        "reference_source": demand_src,
                        "unit": "TWh",
                        "deviation_pct": demand_error_pct,
                        "grade": get_grade(demand_error_pct),
                        "pypsa_earth_version": pypsa_earth_version,
                        "year": year,
                    }
                )

            # 3. Process Capacity Sources
            for cap_src, ref_capacity_df in capacity_refs.items():
                ref_cap_rows = ref_capacity_df[ref_capacity_df["region"] == country]
                if ref_cap_rows.empty:
                    continue
                ref_cap_grouped = ref_cap_rows.groupby("carrier")["p_nom"].sum()
                total_installed_capacity_ref = ref_cap_grouped.reindex(
                    carriers, fill_value=0.0
                ).sum()

                # MAE
                df_cap = pd.DataFrame(index=carriers)
                df_cap["pypsa"] = pypsa_cap_grouped.reindex(carriers, fill_value=0.0)
                df_cap["ref"] = ref_cap_grouped.reindex(carriers, fill_value=0.0)
                capacity_difference_mae = (df_cap["pypsa"] - df_cap["ref"]).abs().mean()
                capacity_mae_pct = (
                    (capacity_difference_mae / total_installed_capacity_ref * 100.0)
                    if total_installed_capacity_ref > 0
                    else 0.0
                )

                # Capacity Deviation
                cap_dev_pct = (
                    (
                        (total_installed_capacity_pypsa - total_installed_capacity_ref)
                        / total_installed_capacity_ref
                        * 100.0
                    )
                    if total_installed_capacity_ref > 0
                    else np.nan
                )

                # Append total capacity row
                records.append(
                    {
                        "scenario_key": scenario_key,
                        "country_code": country,
                        "country_name": country_name,
                        "pillar": "installed_capacity",
                        "metric": "total_capacity",
                        "carrier": "total",
                        "pypsa_value": total_installed_capacity_pypsa,
                        "reference_value": total_installed_capacity_ref,
                        "reference_source": cap_src,
                        "unit": "MW",
                        "deviation_pct": cap_dev_pct,
                        "grade": get_grade(cap_dev_pct),
                        "pypsa_earth_version": pypsa_earth_version,
                        "year": year,
                    }
                )

                # Append individual capacity carrier rows
                for carrier in carriers:
                    pypsa_val = pypsa_cap_grouped.get(carrier, 0.0)
                    ref_val = ref_cap_grouped.get(carrier, 0.0)
                    dev_pct = (
                        ((pypsa_val - ref_val) / ref_val * 100.0)
                        if ref_val > 0
                        else np.nan
                    )
                    records.append(
                        {
                            "scenario_key": scenario_key,
                            "country_code": country,
                            "country_name": country_name,
                            "pillar": "installed_capacity",
                            "metric": "capacity",
                            "carrier": carrier,
                            "pypsa_value": pypsa_val,
                            "reference_value": ref_val,
                            "reference_source": cap_src,
                            "unit": "MW",
                            "deviation_pct": dev_pct,
                            "grade": "",
                            "pypsa_earth_version": pypsa_earth_version,
                            "year": year,
                        }
                    )

            # 4. Process Generation Sources
            for gen_src, ref_generation_df in generation_refs.items():
                ref_gen_rows = ref_generation_df[ref_generation_df["region"] == country]
                if ref_gen_rows.empty:
                    continue
                ref_gen_grouped = ref_gen_rows.groupby("carrier")["generation"].sum()
                total_generation_ref = ref_gen_grouped.reindex(
                    carriers, fill_value=0.0
                ).sum()

                # MAE
                df_gen_comp = pd.DataFrame(index=carriers)
                df_gen_comp["pypsa"] = pypsa_gen_grouped.reindex(
                    carriers, fill_value=0.0
                )
                df_gen_comp["ref"] = ref_gen_grouped.reindex(carriers, fill_value=0.0)
                generation_difference_mae = (
                    (df_gen_comp["pypsa"] - df_gen_comp["ref"]).abs().mean()
                )
                generation_mae_pct = (
                    (generation_difference_mae / total_generation_ref * 100.0)
                    if total_generation_ref > 0
                    else 0.0
                )

                # Generation Deviation
                gen_dev_pct = (
                    (
                        (total_generation_pypsa - total_generation_ref)
                        / total_generation_ref
                        * 100.0
                    )
                    if total_generation_ref > 0
                    else np.nan
                )

                # Append total generation row
                records.append(
                    {
                        "scenario_key": scenario_key,
                        "country_code": country,
                        "country_name": country_name,
                        "pillar": "generation",
                        "metric": "total_generation",
                        "carrier": "total",
                        "pypsa_value": total_generation_pypsa,
                        "reference_value": total_generation_ref,
                        "reference_source": gen_src,
                        "unit": "TWh",
                        "deviation_pct": gen_dev_pct,
                        "grade": get_grade(gen_dev_pct),
                        "pypsa_earth_version": pypsa_earth_version,
                        "year": year,
                    }
                )

                # Append individual generation carrier rows
                for carrier in carriers:
                    pypsa_val = pypsa_gen_grouped.get(carrier, 0.0)
                    ref_val = ref_gen_grouped.get(carrier, 0.0)
                    dev_pct = (
                        ((pypsa_val - ref_val) / ref_val * 100.0)
                        if ref_val > 0
                        else np.nan
                    )
                    records.append(
                        {
                            "scenario_key": scenario_key,
                            "country_code": country,
                            "country_name": country_name,
                            "pillar": "generation",
                            "metric": "generation",
                            "carrier": carrier,
                            "pypsa_value": pypsa_val,
                            "reference_value": ref_val,
                            "reference_source": gen_src,
                            "unit": "TWh",
                            "deviation_pct": dev_pct,
                            "grade": "",
                            "pypsa_earth_version": pypsa_earth_version,
                            "year": year,
                        }
                    )

    # Save to CSV (with incremental merge)
    health_status_df = pd.DataFrame(records)
    output_path = snakemake.output.health_status

    # Look for existing data to merge, checking both the direct path and the Snakemake temp backup
    existing_path = None
    if os.path.exists(output_path + ".tmp"):
        existing_path = output_path + ".tmp"
    elif os.path.exists(output_path):
        existing_path = output_path

    if existing_path is not None:
        try:
            existing_df = pd.read_csv(existing_path)

            # Identify scenario-country combinations currently being validated
            new_keys = set(
                zip(health_status_df["scenario_key"], health_status_df["country_code"])
            )

            # Filter out existing records matching these new keys
            keep_mask = ~existing_df.apply(
                lambda r: (r["scenario_key"], r["country_code"]) in new_keys, axis=1
            )
            existing_filtered = existing_df[keep_mask]

            # Concatenate remaining records with the new ones
            health_status_df = pd.concat(
                [existing_filtered, health_status_df], ignore_index=True
            )

            # Sort values to keep git diffs deterministic and easy to read
            health_status_df = health_status_df.sort_values(
                by=[
                    "scenario_key",
                    "country_code",
                    "pillar",
                    "metric",
                    "carrier",
                    "reference_source",
                ]
            )
            logger.info(
                f"Successfully merged new results with existing data from {existing_path}."
            )
        except Exception as e:
            logger.warning(
                f"Could not merge with existing CSV: {e}. Overwriting instead."
            )

    # Clean up the temp backup file if it exists
    if os.path.exists(output_path + ".tmp"):
        try:
            os.remove(output_path + ".tmp")
        except Exception as e:
            logger.warning(f"Failed to remove temp backup file: {e}")

    health_status_df.to_csv(output_path, index=False)
    logger.info(f"Successfully compiled health_status.csv to {output_path}!")


if __name__ == "__main__":
    if "snakemake" not in globals():
        from helpers import mock_snakemake

        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        snakemake = mock_snakemake("build_health_status")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    configure_logging(snakemake)
    compile_health_status(snakemake)
