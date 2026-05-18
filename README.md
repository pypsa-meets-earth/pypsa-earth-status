<!--
SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->

# PyPSA-Earth-Status: validating any PyPSA network on Earth

## Development Status: **under development**

[![Test workflows](https://github.com/pypsa-meets-earth/pypsa-earth-status/actions/workflows/test.yaml/badge.svg)](https://github.com/pypsa-meets-earth/pypsa-earth/actions/workflows/test.yaml)
![Size](https://img.shields.io/github/repo-size/pypsa-meets-earth/pypsa-earth-status)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Discord](https://img.shields.io/discord/911692131440148490?logo=discord)](https://discord.gg/AnuJBk23FU)
[![Google Drive](https://img.shields.io/badge/Google%20Drive-4285F4?style=flat&logo=googledrive&logoColor=white)](https://drive.google.com/drive/folders/13Z8Y9zgsh5IZaDNkkRyo1wkoMgbdUxT5?usp=sharing)
[![Documentation Status](https://readthedocs.org/projects/pypsa-earth-status/badge/?version=latest)](https://pypsa-earth-status.readthedocs.io/en/latest/?badge=latest)

**Enabling accurate and reproducible energy system modelling for every region of the world**

💡 Any modeling is only as good as the underlying data and assumptions allow. For energy systems modelling it [translates](https://pypsa-earth.readthedocs.io/en/latest/customization_validation.html) into the need to quantify accuracy of modelling inputs and validating optimisation outputs against real-world data.

**PyPSA-Earth-Status** is a collaborative project aims to make that process faster, easier, and more consistent across PyPSA-meets-Earth community. The workflow is designed to validate PyPSA networks against available energy system statistics in an automated way. It provides automated procedures to compare user-provided PyPSA networks with state-of-the-art databases from authoritative sources such as IRENA, IEA, and others.

By streamlining the validation process, PyPSA-Earth-Status helps modelers enhance the credibility, transparency, and quality of their modeling results saving time and allowing them to focus on what matters most: developing better energy system models.

## Contributing

🤝 We warmly welcome contributions to expand the capabilities of PyPSA-Earth-Status and to build a shared foundation for model validation in open energy system research worldwide.

Regional and domain expertise is crucial for interpreting energy statistics and ensure reference validation procedures make sense. We are very interested in experience in energy system modelling and the use of openly available energy system data sources for countries worldwide.

### Ways to contribute

1. Flag existing validation needs by opening issues and joining discussions in [PyPSA-meets-Earth Discord](https://discord.gg/AnuJBk23FU)
2. Suggest improvements by opening issues and pull requests to this repository
3. Contribute non-code insights filling out [this form](https://docs.google.com/forms/d/e/1FAIpQLScfMw1MY1h3lOqU74j7RMcEFWuw1lWrbu6bKQYB3GsxKDasig/viewform)

## Functionality

🔍 Automated validation covers the following points for which accurate representation is crucial to ensure energy system optimisation outputs are relevant:

- **Installed capacities**: `p_nom` of generators and storage units
- **Optimized capacities**: `p_nom_opt` of generators and storage units
- **Transmission capacities**: `s_nom` of power lines
- **Demand**: comparison with real-world consumption data. Currently, electricity only is covered while in future we are planning to also include sector-coupled capabilities

Additionally, we are working to add validation of the energy mix modelled for a reference state of an energy system, such past years.

## Features

- Automated validation of PyPSA networks against real-world data
- Creation of reference statistics from leading reference databases
- Generation of tables and visualizations for easy interpretation of results

... and we are aiming for more features with your help!

Currently, the following datasets are supported:

- Installed capacities from IRENA and IEA
- Cross-border line capacities from [Global Transmission Database](https://zenodo.org/records/15527469)
- Comparison of network data with reference statistics
- Demand data from Our World in Data

The following repositories provide more reference data:

- [Awesome-Electrical-Grid-Mapping](https://github.com/open-energy-transition/Awesome-Electrical-Grid-Mapping) on datasets and documents related to power grid topology, capacity and development plans
- [Awesome-Electricity-Demand](https://github.com/open-energy-transition/Awesome-Electricity-Demand) collects datasets on electricity demand in hourly resolution

Improving coverage with regionally focused datasets is of high interest for this project. If you see any datasets relevant for your study, feel free to open an issue to flag them, and we can develop an approach to accommodate it into PyPSA-Earth-Status together.

## Installation

To install PyPSA-Earth-Status, simply clone the repository:

```bash
    git clone https://github.com/pypsa-meets-earth/pypsa-earth-status
```

The Python dependencies required to run the scripts are defined in this repository.
We recommend using the provided Conda environment file.

Create the environment as follows:

```bash
    cd pypsa-earth-status
    conda env create -f envs/environment.yaml
```

## Tutorial

To validate a first PyPSA network, you can run the following command in your terminal from the `pypsa-earth-status` folder:

```bash
    conda activate pypsa-earth
    snakemake -j 1 visualize_data
```

This command will:

1. Create the sample network scigrid_de from PyPSA
2. Save it as `resources/example_DE.nc` with minimal changes
3. Execute the typical validation procedure to produre tables and visualizations in the folder `results/` for easy inspection

## Execute your first custom validation

If you want to validate your own PyPSA network, you can:

1. Open the file `config.yaml` in the `pypsa-earth-status` folder
2. Specify the path to the network you want to validate in the field `network_path` under `network_validation`
3. Adapt the list of countries you want to validate in the field `countries` under `network_validation` using 2-letter code naming convention; please keep at least two neighbouring countries in the list, e.g. ['DE', 'FR'] for the tutorial case for Germany.
4. Execute:

    ```bash
        snakemake -j 1 visualize_data
    ```

5. Check the results in the `results/` folder
