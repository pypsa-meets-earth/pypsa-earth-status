# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append("./scripts")

from os.path import normpath, exists, isdir
from shutil import copyfile, move

from helpers import create_country_list, get_harmonization_config


configfile: "configs/config_data_harmonization.yaml"
configfile: "config.yaml"


storage HTTP:
    provider="http",


validation_config = config["network_validation"]

network_path = validation_config["network_path"]
countries = validation_config["countries"]
years = validation_config["year"]

validation_name = validation_config["name"]

reference_statistics_dir = "resources/reference_statistics"
network_statistics_dir = "resources/network_statistics"
results_dir = "results"
logs_dir = "logs"

if validation_name:
    reference_statistics_dir += f"/{validation_name}"
    network_statistics_dir += f"/{validation_name}"
    results_dir += f"/{validation_name}"
    logs_dir += f"/{validation_name}"


rule clean:
    run:
        try:
            shell("snakemake -j 1 visualize_data --delete-all-output")
        except:
            pass


rule build_reference_demand_ourworldindata:
    input:
        demand_owid="data/electricity_demand/owid-energy-data.csv",  # from https://nyc3.digitaloceanspaces.com/owid-public/data/energy/owid-energy-data.csv
    output:
        demand_owid="resources/clean/owid_demand_data.csv",
    log:
        "logs/build_reference_demand_ourworldindata.log",
    script:
        "scripts/build_reference_demand_ourworldindata.py"


rule build_reference_installed_capacity_irena:
    input:
        cap_irena="data/installed_capacity/ELECSTAT_20240808-144258.csv",  # IRENA capacity data from https://pxweb.irena.org/pxweb/en/IRENASTAT/IRENASTAT__Power%20Capacity%20and%20Generation/Country_ELECSTAT_2024_H2.px/
    output:
        cap_irena="resources/clean/irena_capacity_data.csv",
    log:
        "logs/build_reference_installed_capacity_irena.log",
    params:
        harmonization_config=get_harmonization_config(
            config, "irena_installed_capacity"
        ),
    script:
        "scripts/build_reference_installed_capacity_irena.py"


rule retrieve_reference_generation_irena:
    input:
        generation_irena=storage.HTTP(
            "https://raw.githubusercontent.com/"
            "pypsa-meets-earth/temporary_storage/main/"
            "datasets/C-ELECGEN_20260713-113435.csv"
        ),
    output:
        generation_irena="data/electricity_generation/C-ELECGEN_20260713-113435.csv",
    run:
        os.makedirs(
            os.path.dirname(output.generation_irena),
            exist_ok=True,
        )
        copyfile(
            input.generation_irena,
            output.generation_irena,
        )


rule build_reference_generation_irena:
    input:
        # Source: https://pxweb.irena.org/pxweb/en/IRENASTAT/IRENASTAT__Power%20Capacity%20and%20Generation/Country_ELECGEN_2025_H2_v-PX%201.px/
        generation_irena="data/electricity_generation/C-ELECGEN_20260713-113435.csv",
    output:
        generation_irena="resources/clean/irena_generation_data.csv",
    log:
        "logs/build_reference_generation_irena.log",
    script:
        "scripts/build_reference_generation_irena.py"


rule build_network_geojson:
    input:
        buscodes="data/electricity_transmission/Input - Center points.csv",
        lineexist="data/electricity_transmission/GTD-v1.1_regional_existing.csv",
        lineplan="data/electricity_transmission/GTD-v1.1_regional_planned.csv",
        network_path=network_path,
    output:
        network_existing=f"{reference_statistics_dir}/network_exist.geojson",
        network_planned=f"{reference_statistics_dir}/network_planned.geojson",
        network_model=f"{network_statistics_dir}/network_model.geojson",
    log:
        f"{logs_dir}/build_network_geojson.log",
    params:
        countries=countries,
        shapefile=validation_config["shapefile"],
        validate_cross_border_capacity=validation_config[
            "validate_cross_border_capacity"
        ],
    script:
        "scripts/build_network_geojson.py"


rule build_reference_statistics:
    input:
        demand_owid="resources/clean/owid_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        generation_irena="resources/clean/irena_generation_data.csv",
    output:
        demand=f"{reference_statistics_dir}/demand.csv",
        installed_capacity=f"{reference_statistics_dir}/installed_capacity.csv",
        electricity_generation=(
            f"{reference_statistics_dir}/electricity_generation.csv"
        ),
    log:
        f"{logs_dir}/build_reference_statistics.log",
    params:
        datasets=config["datasets"],
        year=years,
        countries=countries,
    script:
        "scripts/build_reference_statistics.py"


rule build_network_statistics:
    input:
        network_path=network_path,
    output:
        demand=f"{network_statistics_dir}/demand.csv",
        installed_capacity=f"{network_statistics_dir}/installed_capacity.csv",
        optimal_capacity=f"{network_statistics_dir}/optimal_capacity.csv",
        electricity_generation=f"{network_statistics_dir}/electricity_generation.csv",
    log:
        f"{logs_dir}/build_network_statistics.log",
    params:
        network_path=network_path,
        year=years,
        countries=countries,
        shapefile=validation_config["shapefile"],
        validate_cross_border_capacity=validation_config[
            "validate_cross_border_capacity"
        ],
        network=validation_config,
    script:
        "scripts/build_network_statistics.py"


rule make_comparison:
    input:
        demand_network=f"{network_statistics_dir}/demand.csv",
        installed_capacity_network=f"{network_statistics_dir}/installed_capacity.csv",
        optimal_capacity_network=f"{network_statistics_dir}/optimal_capacity.csv",
        electricity_generation_network=(
            f"{network_statistics_dir}/electricity_generation.csv"
        ),
        network_geojson_network=f"{network_statistics_dir}/network_model.geojson",
        demand_reference=f"{reference_statistics_dir}/demand.csv",
        installed_capacity_reference=(
            f"{reference_statistics_dir}/installed_capacity.csv"
        ),
        electricity_generation_reference=(
            f"{reference_statistics_dir}/electricity_generation.csv"
        ),
        network_geojson_reference=f"{reference_statistics_dir}/network_exist.geojson",
    output:
        demand_comparison=f"{results_dir}/tables/demand.csv",
        installed_capacity_comparison=f"{results_dir}/tables/installed_capacity.csv",
        optimal_capacity_comparison=f"{results_dir}/tables/optimal_capacity.csv",
        electricity_generation_comparison=(
            f"{results_dir}/tables/electricity_generation.csv"
        ),
        network_comparison_geojson=f"{results_dir}/network_comparison.geojson",
    log:
        f"{logs_dir}/make_comparison.log",
    script:
        "scripts/make_comparison.py"


rule visualize_data:
    input:
        demand_comparison=f"{results_dir}/tables/demand.csv",
        installed_capacity_comparison=f"{results_dir}/tables/installed_capacity.csv",
        optimal_capacity_comparison=f"{results_dir}/tables/optimal_capacity.csv",
        electricity_generation_comparison=(
            f"{results_dir}/tables/electricity_generation.csv"
        ),
        osm_lines=os.path.join(
            config["plot_osm_grid_network"]["grid_path"],
            "all_clean_lines.geojson",
        ),
        osm_substations=os.path.join(
            config["plot_osm_grid_network"]["grid_path"],
            "all_clean_substations.geojson",
        ),
    output:
        plot_demand=f"{results_dir}/figures/demand_comparison.png",
        plot_installed_capacity=(
            f"{results_dir}/figures/installed_capacity_comparison.png"
        ),
        plot_electricity_generation=(
            f"{results_dir}/figures/electricity_generation_comparison.png"
        ),
        plot_capacity_mix=f"{results_dir}/figures/capacity_mix_comparison.png",
        plot_capacity_grid=f"{results_dir}/figures/capacity_grid_comparison.png",
        plot_grid_network=f"{results_dir}/figures/grid_network.png",
        line_length_by_voltage=f"{results_dir}/tables/line_length_by_voltage.csv",
    log:
        f"{logs_dir}/visualize_data.log",
    params:
        line_voltages=config["plot_osm_grid_network"]["line_voltages"],
        voltage_colors=config["plot_osm_grid_network"]["voltage_colors"],
        plot_circuits=config["plot_osm_grid_network"]["plot_circuits"],
    script:
        "scripts/visualize_data.py"


rule create_example_DE:
    output:
        "resources/example_DE.nc",
    log:
        "logs/create_example_DE.log",
    run:
        import pypsa

        n = pypsa.examples.scigrid_de()
        n.buses["country"] = "DE"
        n.export_to_netcdf(output[0])
        print(f"Created example network at {output[0]}")
