# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys

sys.path.append("./scripts")

from os.path import normpath, exists, isdir
from shutil import copyfile, move

from helpers import create_country_list

# Create a temporary backup of the validation results before Snakemake deletes it
if exists("results/health_status.csv"):
    copyfile("results/health_status.csv", "results/health_status.csv.tmp")


configfile: "config.yaml"


rule clean:
    run:
        try:
            shell("snakemake -j 1 visualize_data --delete-all-output")
        except:
            pass


rule download_ember_data:
    output:
        "data/ember/yearly_full_release_long_format.csv",
    log:
        "logs/download_ember_data.log",
    run:
        from helpers import progress_retrieve

        url = "https://storage.googleapis.com/emb-prod-bkt-publicdata/public-downloads/yearly_full_release_long_format.csv"
        progress_retrieve(url, output[0])


rule build_reference_demand_ember:
    input:
        demand_ember="data/ember/yearly_full_release_long_format.csv",
    output:
        demand_ember="resources/clean/ember_demand_data.csv",
    log:
        "logs/build_reference_demand_ember.log",
    script:
        "scripts/build_reference_demand_ember.py"


rule build_reference_installed_capacity_ember:
    input:
        cap_ember="data/ember/yearly_full_release_long_format.csv",
    output:
        cap_ember="resources/clean/ember_capacity_data.csv",
    log:
        "logs/build_reference_installed_capacity_ember.log",
    script:
        "scripts/build_reference_installed_capacity_ember.py"


rule build_reference_generation_ember:
    input:
        gen_ember="data/ember/yearly_full_release_long_format.csv",
    output:
        gen_ember="resources/clean/ember_generation_data.csv",
    log:
        "logs/build_reference_generation_ember.log",
    script:
        "scripts/build_reference_generation_ember.py"


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
    script:
        "scripts/build_reference_installed_capacity_irena.py"


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
        demand_ember="resources/clean/ember_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        cap_ember="resources/clean/ember_capacity_data.csv",
        gen_ember="resources/clean/ember_generation_data.csv",
    output:
        demand="resources/reference_statistics/demand.csv",
        installed_capacity="resources/reference_statistics/installed_capacity.csv",
        generation="resources/reference_statistics/generation.csv",
    log:
        "logs/build_reference_statistics.log",
    params:
        datasets=config["datasets"],
        year=config["network_validation"]["year"],
        countries=config["network_validation"]["countries"],
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
        generation="resources/network_statistics/generation.csv",
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
        generation_network="resources/network_statistics/generation.csv",
        network_geojson_network="resources/network_statistics/network_model.geojson",
        demand_reference="resources/reference_statistics/demand.csv",
        installed_capacity_reference="resources/reference_statistics/installed_capacity.csv",
        generation_reference="resources/reference_statistics/generation.csv",
        network_geojson_reference="resources/reference_statistics/network_exist.geojson",
    output:
        demand_comparison="results/tables/demand.csv",
        installed_capacity_comparison="results/tables/installed_capacity.csv",
        optimal_capacity_comparison="results/tables/optimal_capacity.csv",
        generation_comparison="results/tables/generation.csv",
        network_comparison_geojson="results/network_comparison.geojson",
    log:
        "logs/make_comparison.log",
    params:
        datasets=config["datasets"],
    script:
        "scripts/make_comparison.py"


rule visualize_data:
    input:
        demand_comparison="results/tables/demand.csv",
        installed_capacity_comparison="results/tables/installed_capacity.csv",
        optimal_capacity_comparison="results/tables/optimal_capacity.csv",
        osm_lines=os.path.join(
            config["plot_osm_grid_network"]["grid_path"], "all_clean_lines.geojson"
        ),
        osm_substations=os.path.join(
            config["plot_osm_grid_network"]["grid_path"],
            "all_clean_substations.geojson",
        ),
        # energy_dispatch_comparison="results/tables/energy_dispatch.geojson"
        # network_comparison="results/tables/network.geojson"
    output:
        plot_demand="results/figures/demand_comparison.png",
        plot_installed_capacity="results/figures/installed_capacity_comparison.png",
        plot_capacity_mix="results/figures/capacity_mix_comparison.png",
        plot_capacity_grid="results/figures/capacity_grid_comparison.png",
        plot_grid_network="results/figures/grid_network.png",
        line_length_by_voltage="results/tables/line_length_by_voltage.csv",
    log:
        "logs/visualize_data.log",
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


rule build_health_status:
    input:
        demand_owid="resources/clean/owid_demand_data.csv",
        demand_ember="resources/clean/ember_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        cap_ember="resources/clean/ember_capacity_data.csv",
        gen_ember="resources/clean/ember_generation_data.csv",
    output:
        health_status="results/health_status.csv",
    log:
        "logs/build_health_status.log",
    params:
        networks=config["network_validation"].get("networks", {}),
        year=config["network_validation"]["year"],
        datasets=config.get("datasets", {}),
        fallback_pypsa_earth_version=config["network_validation"].get(
            "fallback_pypsa_earth_version", "unknown"
        ),
    script:
        "scripts/build_health_status.py"


rule build_docs_tables:
    input:
        health_status="results/health_status.csv",
    output:
        overview="doc/validation/overview.md",
        statistics="doc/validation/statistics.md",
    log:
        "logs/build_docs_tables.log",
    script:
        "scripts/build_docs_tables.py"
