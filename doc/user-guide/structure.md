<!--
SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->

# Project structure

PyPSA-Earth-Status is organized around a **Snakemake workflow** that turns raw reference datasets and a user-provided **PyPSA network** into **comparison tables** and **diagnostic figures**.

The workflow is designed to be:

- **Reproducible**: all steps are explicit rules with defined inputs/outputs
- **Modular**: reference statistics, network statistics, comparisons, and plots are separated
- **Extensible**: you can add new datasets, metrics, and plots by extending rules and scripts

## High-level workflow

At a high level, the workflow does three major actions:

1. **Create reference statistics** from raw datasets. This section includes data downloading, cleaning and harmonization.
2. **Extract network statistics** from the user-provided model. This includes reading the input model and parsing the information to numeric inputs that can be compared to the reference data.
3. **Compare** the reference vs network statistics and generate visualizations.

## Workflow

The default entry point is the Snakemake target:

```bash
snakemake -j 1 visualize_data
```

This command triggers the full workflow, starting from raw data cleaning to final figure generation.
The example described in the quick start guide uses a minimal PyPSA network based on the `scigrid_de` example provided by PyPSA, which is created by the `create_example_DE` rule. The workflow that is being executed is visualized below, where each block denotes a specific Snakemake rule and arrows indicate data dependencies between them.

![PyPSA-Earth-Status workflow DAG](../workflow_dag.png)

The actions mentioned above are implemented through the following Snakemake rules:

1. **Create reference statistics**

    - `create_example_DE` (for the example workflow only)
    - `build_reference_demand_ourworldindata`
    - `build_reference_installed_capacity_irena`
    - `build_reference_statistics`

2. **Extract network statistics**

    - `build_network_statistics`
    - `build_network_geojson`

3. **Compare and visualize**

    - `make_comparison`
    - `visualize_data`

The detailed description of the rules is provided below.

## Rules and their roles

### `create_example_DE`

This rule generates a minimal example PyPSA network based on the `scigrid_de` example provided by PyPSA.
It is primarily intended for tutorials and quick-start demonstrations.

**Output:**

- `resources/example_DE.nc`

### Source-specific reference builders

These rules clean and harmonize raw external datasets so they can be used consistently throughout the workflow.
Each rule follows the `build_reference_{category}_{source}` naming pattern.

**Typical inputs:**

- Electricity demand data from Our World in Data
- Installed capacity data from IRENA
- Other optional reference sources

**Outputs:**

- Cleaned demand data in `resources/clean/owid_demand_data.csv`
- Cleaned capacity data in `resources/clean/irena_capacity_data.csv`

The corresponding processing logic is implemented in:

- `scripts/build_reference_demand_ourworldindata.py`
- `scripts/build_reference_installed_capacity_irena.py`

### `build_reference_statistics`

This rule constructs authoritative reference statistics representing real-world energy systems for the selected countries.

**Inputs:**

- Cleaned demand and capacity datasets

**Outputs:**

- Reference demand statistics
- Reference installed capacity statistics

All outputs are written to `resources/reference_statistics/`.

### `build_network_statistics`

This rule extracts statistics directly from the user-provided PyPSA network.

**Inputs:**

- A PyPSA network file (`.nc`) specified in `config.yaml`

**Outputs:**

- Demand statistics derived from the network
- Installed capacity statistics
- Optimized capacity statistics

All outputs are stored in `resources/network_statistics/`.

### `build_network_geojson`

This rule creates geographic representations of transmission networks to support spatial comparison and inspection.

It combines:

- The topology of the user’s PyPSA network
- Reference transmission datasets from the Global Transmission Database

**Outputs:**

- GeoJSON layers for existing and planned reference networks
- A GeoJSON representation of the modeled network

These files are written to `resources/reference_statistics/` and `resources/network_statistics/`.

### `make_comparison`

This rule aligns and compares reference statistics with network-derived statistics.

**Inputs:**

- Reference demand and capacity statistics
- Network demand, capacity, and topology statistics

**Outputs:**

- Comparison tables for demand, installed capacity, and optimized capacity
- A GeoJSON file highlighting network differences

Comparison results are written to the `results/` directory.

### `visualize_data`

This is the final stage of the workflow and the main user-facing entry point.

It converts comparison tables into figures that highlight discrepancies between the model and real-world data.

**Outputs:**

- Demand comparison plots
- Installed capacity comparison plots
- Capacity mix and grid-related figures

All figures are stored in `results/figures/`.

## Directory overview

- `data/`
  Raw external datasets as downloaded from original sources

- `resources/clean/`
  Cleaned intermediate datasets

- `resources/reference_statistics/`
  Reference (“ground truth”) statistics

- `resources/network_statistics/`
  Statistics derived from the PyPSA network

- `results/tables/`
  Final comparison tables

- `results/figures/`
  Final visual outputs

- `scripts/`
  Python scripts executed by Snakemake rules

- `logs/`
  Log files produced during workflow execution

## Configuration-driven behavior

The workflow is controlled by `config.yaml`, which defines:

- The path to the PyPSA network to validate
- The list of countries included in the validation
- Optional geographic inputs (e.g. shapefiles)
- Which reference datasets are enabled

Changing the configuration modifies the scope and content of the validation, while the overall workflow structure remains unchanged.
