<!--
SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->

# Installation

This page describes how to install **PyPSA-Earth-Status** and its dependencies.

PyPSA-Earth-Status provides its own Conda environment file with the dependencies needed to run the workflow.

## Prerequisites

Before installing PyPSA-Earth-Status, make sure you have:

- **Git**
- **Conda** (recommended: Miniconda)

## Clone the repository

First, clone the repository:

```bash
git clone https://github.com/pypsa-meets-earth/pypsa-earth-status.git
cd pypsa-earth-status
```

## Create the Conda environment

1. Make sure you are in the project folder:

    ```bash
    cd pypsa-earth-status
    ```

2. Create the Conda environment using the repository environment file:

    ```bash
    conda env create -f envs/environment.yaml
    ```

3. Activate the environment:

    ```bash
    conda activate pypsa-earth
    ```

4. Quick sanity check (optional):

    ```bash
    snakemake --help
    ```

    If you see the Snakemake help text, the environment is ready.
