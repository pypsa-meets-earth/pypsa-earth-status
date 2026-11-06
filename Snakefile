# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append("./scripts")

from os.path import normpath, exists, isdir
from shutil import copyfile, move

from helpers import create_country_list

# Create a temporary backup of the validation results before Snakemake deletes it
if exists("results/health_status.csv"):
    copyfile("results/health_status.csv", "results/health_status.csv.tmp")


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


rule download_ember_data:
    input:
        ember_data=storage.HTTP(
            "https://storage.googleapis.com/emb-prod-bkt-publicdata/"
            "public-downloads/yearly_full_release_long_format.csv"
        ),
    output:
        ember_data="data/ember/yearly_full_release_long_format.csv",
    run:
        os.makedirs(
            os.path.dirname(output.ember_data),
            exist_ok=True,
        )
        copyfile(
            input.ember_data,
            output.ember_data,
        )


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
        demand_ourworldindata="resources/clean/owid_demand_data.csv",
        demand_ember="resources/clean/ember_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        cap_ember="resources/clean/ember_capacity_data.csv",
        gen_ember="resources/clean/ember_generation_data.csv",
        gen_irena="resources/clean/irena_generation_data.csv",
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
    params:
        datasets=config["datasets"],
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
        co2_by_asset=f"{results_dir}/tables/co2_emissions_by_asset.csv",
        co2_by_carrier=f"{results_dir}/tables/co2_emissions_by_carrier.csv",
        co2_reference=f"{results_dir}/tables/co2_emissions_reference.csv",
        co2_comparison=f"{results_dir}/tables/co2_emissions_comparison.csv",
        co2_validation_summary=f"{results_dir}/tables/co2_emissions_validation_summary.csv",
        co2_carrier_plot=f"{results_dir}/figures/co2_emissions_by_carrier.png",
        co2_comparison_plot=f"{results_dir}/figures/co2_emissions_comparison.png",
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


rule build_network_co2_statistics:
    input:
        network=network_path,
        script="scripts/build_network_co2_statistics.py",
    output:
        summary=f"{results_dir}/tables/co2_emissions_by_carrier.csv",
        detail=f"{results_dir}/tables/co2_emissions_by_asset.csv",
    params:
        year=years[0],
    shell:
        """
        python {input.script:q} \\
        --network {input.network:q} \\
        --year {params.year} \\
        --output {output.summary:q} \\
        --detail-output {output.detail:q}
        """


rule plot_network_co2_emissions:
    input:
        statistics=f"{results_dir}/tables/co2_emissions_by_carrier.csv",
        script="scripts/plot_co2_emissions.py",
    output:
        figure=f"{results_dir}/figures/co2_emissions_by_carrier.png",
    shell:
        """
        python {input.script:q} \\
        --input {input.statistics:q} \\
        --output {output.figure:q} \\
        --groupby carrier
        """


rule validate_co2:
    input:
        f"{results_dir}/tables/co2_emissions_by_asset.csv",
        f"{results_dir}/figures/co2_emissions_by_carrier.png",


rule retrieve_co2_edgar:
    output:
        "resources/clean/edgar_2025_fossilCO2.xlsx",
    params:
        url=(
            "https://edgar.jrc.ec.europa.eu/booklet/"
            "EDGAR_2025_GHG_booklet_2025_fossilCO2only.xlsx"
        ),
    shell:
        """
        curl -fL --retry 3 \
            --output {output:q} \
            {params.url:q}
        """


rule build_reference_co2_edgar:
    input:
        workbook="resources/clean/edgar_2025_fossilCO2.xlsx",
        network=network_path,
        script="scripts/build_reference_co2_edgar.py",
    output:
        reference=f"{results_dir}/tables/co2_emissions_reference.csv",
    params:
        countries=config["network_validation"]["countries"],
        comparison_year=config.get("sector_emissions", {}).get("comparison_year", 0),
    shell:
        """
        python {input.script:q} \\
        --input {input.workbook:q} \\
        --network {input.network:q} \\
        --comparison-year {params.comparison_year} \\
        --countries {params.countries} \\
        --output {output.reference:q}
        """


rule compare_co2_emissions:
    input:
        model=f"{results_dir}/tables/co2_emissions_by_asset.csv",
        reference=f"{results_dir}/tables/co2_emissions_reference.csv",
        mapping="config/co2_sector_mapping.yaml",
        network=network_path,
        script="scripts/compare_co2_emissions.py",
    output:
        comparison=f"{results_dir}/tables/co2_emissions_comparison.csv",
        summary=f"{results_dir}/tables/co2_emissions_validation_summary.csv",
    shell:
        """
        python {input.script:q} \
            --model {input.model:q} \
            --reference {input.reference:q} \
            --mapping {input.mapping:q} \
            --network {input.network:q} \
            --output {output.comparison:q} \
            --summary-output {output.summary:q}
        """


rule plot_co2_comparison:
    input:
        comparison=f"{results_dir}/tables/co2_emissions_comparison.csv",
        script="scripts/plot_co2_comparison.py",
    output:
        figure=f"{results_dir}/figures/co2_emissions_comparison.png",
    shell:
        """
        python {input.script:q} \
            --input {input.comparison:q} \
            --output {output.figure:q}
        """


rule validate_co2_comparison:
    input:
        f"{results_dir}/tables/co2_emissions_by_asset.csv",
        f"{results_dir}/figures/co2_emissions_by_carrier.png",
        f"{results_dir}/tables/co2_emissions_reference.csv",
        f"{results_dir}/tables/co2_emissions_comparison.csv",
        f"{results_dir}/tables/co2_emissions_validation_summary.csv",
        f"{results_dir}/figures/co2_emissions_comparison.png",


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
        demand_ourworldindata="resources/clean/owid_demand_data.csv",
        demand_ember="resources/clean/ember_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        cap_ember="resources/clean/ember_capacity_data.csv",
        gen_ember="resources/clean/ember_generation_data.csv",
        gen_irena="resources/clean/irena_generation_data.csv",
    output:
        health_status="results/health_status.csv",
    log:
        "logs/build_health_status.log",
    params:
        networks=config["network_validation"].get("networks", {}),
        year=config["network_validation"]["year"],
        datasets=config.get("datasets", {}),
        fallback_pypsa_earth_version=config["network_validation"].get(
            "fallback_pypsa_earth_version", ""
        ),
    script:
        "scripts/build_health_status.py"
