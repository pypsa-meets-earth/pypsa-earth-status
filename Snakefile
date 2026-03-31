# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys

sys.path.append("./scripts")

from os.path import normpath, exists, isdir
from shutil import copyfile, move

from helpers import create_country_list


configfile: "config.yaml"


rule clean:
    run:
        try:
            shell("snakemake -j 1 visualize_data --delete-all-output")
        except:
            pass


rule clean_data:
    input:
        demand_owid="data/electricity_demand/owid-energy-data.csv",  # from https://nyc3.digitaloceanspaces.com/owid-public/data/energy/owid-energy-data.csv
        demand_iea="data/WEO2023_AnnexA_Free_Dataset_Regions.csv",  # from https://www.iea.org/data-and-statistics/data-product/world-energy-outlook-2023-free-dataset-2
        cap_irena="data/installed_capacity/ELECSTAT_20240808-144258.csv",  # IRENA capacity data from https://pxweb.irena.org/pxweb/en/IRENASTAT/IRENASTAT__Power%20Capacity%20and%20Generation/Country_ELECSTAT_2024_H2.px/
        # other sources
    output:
        demand_owid="resources/clean/owid_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
    log:
        "logs/clean_data.log",
    params:
        datasets=config["datasets"],
    script:
        "scripts/clean_data.py"


rule build_network_geojson:
    input:
        buscodes="data/electricity_transmission/Input - Center points.csv",
        lineexist="data/electricity_transmission/GTD-v1.1_regional_existing.csv",
        lineplan="data/electricity_transmission/GTD-v1.1_regional_planned.csv",
        network_path=config["network_validation"]["network_path"],
    output:
        network_existing="resources/reference_statistics/network_exist.geojson",
        network_planned="resources/reference_statistics/network_planned.geojson",
        network_model="resources/network_statistics/network_model.geojson",
    log:
        "logs/build_network_geojson.log",
    params:
        countries=config["network_validation"]["countries"],
        shapefile=config["network_validation"].get("shapefile", False),
        validate_cross_border_capacity=config["network_validation"].get(
            "validate_cross_border_capacity", True
        ),
    script:
        "scripts/build_network_geojson.py"


rule build_reference_statistics:
    input:
        demand_owid="resources/clean/owid_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        # other sources
    output:
        demand="resources/reference_statistics/demand.csv",
        installed_capacity="resources/reference_statistics/installed_capacity.csv",
        # energy_dispatch="resources/reference_statistics/energy_dispatch.geojson"
    log:
        "logs/build_reference_statistics.log",
    params:
        datasets=config["datasets"],
    script:
        "scripts/build_reference_statistics.py"


rule build_network_statistics:
    input:
        network_path=config["network_validation"]["network_path"],
        # other sources
    output:
        demand="resources/network_statistics/demand.csv",
        installed_capacity="resources/network_statistics/installed_capacity.csv",
        optimal_capacity="resources/network_statistics/optimal_capacity.csv",
        # energy_dispatch="resources/network_statistics/energy_dispatch.csv",
        # network="resources/network_statistics/network.geojson",
    log:
        "logs/build_network_statistics.log",
    params:
        network=config["network_validation"],
    script:
        "scripts/build_network_statistics.py"


rule make_comparison:
    input:
        demand_network="resources/network_statistics/demand.csv",
        installed_capacity_network="resources/network_statistics/installed_capacity.csv",
        optimal_capacity_network="resources/network_statistics/optimal_capacity.csv",
        # energy_dispatch_network="resources/network_statistics/energy_dispatch.csv",
        # network_network="resources/network_statistics/network.geojson",
        network_geojson_network="resources/network_statistics/network_model.geojson",
        demand_reference="resources/reference_statistics/demand.csv",
        installed_capacity_reference="resources/reference_statistics/installed_capacity.csv",
        # energy_dispatch_reference="resources/reference_statistics/energy_dispatch.geojson"
        network_geojson_reference="resources/reference_statistics/network_exist.geojson",
    output:
        demand_comparison="results/tables/demand.csv",
        installed_capacity_comparison="results/tables/installed_capacity.csv",
        optimal_capacity_comparison="results/tables/optimal_capacity.csv",
        network_comparison_geojson="results/network_comparison.geojson",
        # energy_dispatch_comparison="results/tables/energy_dispatch.geojson"
        # network_comparison="results/tables/network.geojson"
    log:
        "logs/make_comparison.log",
    script:
        "scripts/make_comparison.py"


rule visualize_data:
    input:
        demand_comparison="results/tables/demand.csv",
        installed_capacity_comparison="results/tables/installed_capacity.csv",
        optimal_capacity_comparison="results/tables/optimal_capacity.csv",
        # energy_dispatch_comparison="results/tables/energy_dispatch.geojson"
        # network_comparison="results/tables/network.geojson"
    output:
        plot_demand="results/figures/demand_comparison.png",
        plot_installed_capacity="results/figures/installed_capacity_comparison.png",
        plot_capacity_mix="results/figures/capacity_mix_comparison.png",
        plot_capacity_grid="results/figures/capacity_grid_comparison.png",
    log:
        "logs/visualize_data.log",
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
