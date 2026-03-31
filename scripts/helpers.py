# -*- coding: utf-8 -*-
import logging
import os
import sys
from pathlib import Path

sys.path.append("../workflows/pypsa-earth/scripts")
sys.path.append("./workflows/pypsa-earth/scripts")
import _helpers as pe_helpers
import country_converter as coco
import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

# Import helpers from pypsa-earth subworkflow
handle_exception = pe_helpers.handle_exception
create_logger = pe_helpers.create_logger
read_osm_config = pe_helpers.read_osm_config
create_country_list = pe_helpers.create_country_list
# mock_snakemake = pe_helpers.mock_snakemake
progress_retrieve = pe_helpers.progress_retrieve
to_csv_nafix = pe_helpers.to_csv_nafix
read_csv_nafix = pe_helpers.read_csv_nafix
configure_logging = pe_helpers.configure_logging
three_2_two_digits_country = pe_helpers.three_2_two_digits_country
country_name_2_two_digits = pe_helpers.country_name_2_two_digits
two_digits_2_name_country = pe_helpers.two_digits_2_name_country
read_geojson = pe_helpers.read_geojson
save_to_geojson = pe_helpers.save_to_geojson


def mock_snakemake(rulename, **wildcards):
    """
    This function is expected to be executed from the "scripts"-directory of "
    the snakemake project. It returns a snakemake.script.Snakemake object,
    based on the Snakefile.

    If a rule has wildcards, you have to specify them in **wildcards**.

    Parameters
    ----------
    rulename: str
        name of the rule for which the snakemake object should be generated
    wildcards:
        keyword arguments fixing the wildcards. Only necessary if wildcards are
        needed.
    """
    import os

    import snakemake as sm
    from pypsa.descriptors import Dict
    from snakemake.script import Snakemake

    script_dir = Path(__file__).parent.resolve()
    assert (
        Path.cwd().resolve() == script_dir
    ), f"mock_snakemake has to be run from the repository scripts directory {script_dir}"
    os.chdir(script_dir.parent)
    for p in sm.SNAKEFILE_CHOICES:
        if os.path.exists(p):
            snakefile = p
            break
    workflow = sm.Workflow(
        snakefile, overwrite_configfiles=[], rerun_triggers=[]
    )  # overwrite_config=config
    workflow.include(snakefile)
    workflow.global_resources = {}
    try:
        rule = workflow.get_rule(rulename)
    except Exception as exception:
        print(
            exception,
            f"The {rulename} might be a conditional rule in the Snakefile.\n"
            f"Did you enable {rulename} in the config?",
        )
        raise
    dag = sm.dag.DAG(workflow, rules=[rule])
    wc = Dict(wildcards)
    job = sm.jobs.Job(rule, dag, wc)

    def make_accessable(*ios):
        for io in ios:
            for i in range(len(io)):
                io[i] = os.path.abspath(io[i])

    make_accessable(job.input, job.output, job.log)
    snakemake = Snakemake(
        job.input,
        job.output,
        job.params,
        job.wildcards,
        job.threads,
        job.resources,
        job.log,
        job.dag.workflow.config,
        job.rule.name,
        None,
    )
    snakemake.benchmark = job.benchmark

    # create log and output dir if not existent
    for path in list(snakemake.log) + list(snakemake.output):
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    os.chdir(script_dir)
    return snakemake


def harmonize_carrier_names(series):
    return series.str.lower().replace(
        {
            "solar": "pv",
            "wind": "onwind",
            "offwind": "offwind",
            "ror": "hydro",
            "run of river": "hydro",
            "storage hydro": "hydro",
            "wind onshore": "onshore",
            "wind offshore": "offwind",
            "offwind-dc": "offwind",
            "offwind-ac": "offwind",
            "hard coal": "coal",
        }
    )
