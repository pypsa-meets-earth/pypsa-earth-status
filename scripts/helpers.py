# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
import logging
import os
import sys
from pathlib import Path

import country_converter as coco
import geopandas as gpd
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# Keep NA/na available for country codes such as Namibia.
NA_VALUES = ["NULL", "", "N/A", "NAN", "NaN", "nan", "Nan", "n/a", "null"]
REGIONS_CONFIG = "regions_definition_config.yaml"


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Customize error tracebacks written through the workflow logger.
    """
    tb = exc_traceback
    while tb.tb_next:
        tb = tb.tb_next
    filename = tb.tb_frame.f_globals.get("__file__")
    function = tb.tb_frame.f_code.co_name

    if issubclass(exc_type, KeyboardInterrupt):
        logger.error(
            "Manual interruption %r, function %r: %s", filename, function, exc_value
        )
    else:
        logger.error(
            "An error happened in module %r, function %r: %s",
            filename,
            function,
            exc_value,
            exc_info=(exc_type, exc_value, exc_traceback),
        )


def create_logger(logger_name, level=logging.INFO):
    """
    Create a logger and register the workflow exception hook.
    """
    module_logger = logging.getLogger(logger_name)
    module_logger.setLevel(level)
    module_logger.addHandler(logging.StreamHandler(stream=sys.stdout))
    sys.excepthook = handle_exception
    return module_logger


def _repository_root():
    return Path(__file__).resolve().parents[1]


def read_osm_config(*args):
    """
    Read values from the optional regions definition config.
    """
    config_path = _repository_root() / "configs" / REGIONS_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"Regions config not found: {config_path}")

    with open(config_path, "r") as f:
        osm_config = yaml.safe_load(f)

    if len(args) == 0:
        return osm_config
    if len(args) == 1:
        return osm_config[args[0]]
    return tuple(osm_config[arg] for arg in args)


def configure_logging(snakemake, skip_handlers=False):
    """
    Configure logging for scripts executed by Snakemake or manually.
    """
    kwargs = snakemake.config.get("logging", {}).copy()
    kwargs.setdefault("level", "INFO")

    if skip_handlers is False:
        fallback_path = _repository_root() / "logs" / f"{snakemake.rule}.log"
        logfile = snakemake.log.get(
            "python", snakemake.log[0] if snakemake.log else fallback_path
        )
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        kwargs.update(
            {
                "handlers": [
                    logging.FileHandler(logfile),
                    logging.StreamHandler(),
                ]
            }
        )

    logging.basicConfig(**kwargs, force=True)


def progress_retrieve(
    url, file, data=None, headers=None, disable_progress=False, roundto=1.0
):
    """
    Download a URL to a file while showing a progress bar.
    """
    import urllib.parse
    import urllib.request

    from tqdm import tqdm

    pbar = tqdm(total=100, disable=disable_progress)

    def dl_progress(count, block_size, total_size, roundto=roundto):
        if total_size <= 0:
            return
        pbar.n = round(count * block_size * 100 / total_size / roundto) * roundto
        pbar.refresh()

    if data is not None:
        data = urllib.parse.urlencode(data).encode()

    try:
        if headers:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request) as response:
                with open(file, "wb") as f:
                    f.write(response.read())
        else:
            urllib.request.urlretrieve(url, file, reporthook=dl_progress, data=data)
    finally:
        pbar.close()


def mock_snakemake(rulename, configfile=None, **wildcards):
    """
    Build a Snakemake object for running a rule script directly.
    """
    import snakemake as sm

    try:
        from pypsa.descriptors import Dict
    except ImportError:
        from pypsa.definitions.structures import Dict
    from snakemake.script import Snakemake

    script_dir = Path(__file__).parent.resolve()
    root_dir = script_dir.parent
    original_cwd = Path.cwd()

    if Path.cwd().resolve() == script_dir:
        os.chdir(root_dir)
    elif Path.cwd().resolve() != root_dir:
        raise RuntimeError(
            "mock_snakemake has to be run from the repository root "
            f"{root_dir} or scripts directory {script_dir}"
        )

    try:
        snakefile = None
        for candidate in sm.SNAKEFILE_CHOICES:
            if os.path.exists(candidate):
                snakefile = candidate
                break
        if snakefile is None:
            raise FileNotFoundError("No Snakefile found in repository root")

        overwrite_config = configfile
        if isinstance(configfile, str):
            with open(configfile, "r") as f:
                overwrite_config = yaml.safe_load(f)

        workflow = sm.Workflow(
            snakefile,
            overwrite_configfiles=[],
            rerun_triggers=[],
            overwrite_config=overwrite_config,
        )
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
        job = sm.jobs.Job(rule, dag, Dict(wildcards))

        def make_accessible(*ios):
            for io in ios:
                for i in range(len(io)):
                    io[i] = os.path.abspath(io[i])

        make_accessible(job.input, job.output, job.log)
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

        for path in list(snakemake.log) + list(snakemake.output):
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        return snakemake
    finally:
        os.chdir(original_cwd)


def three_2_two_digits_country(three_code_country):
    """
    Convert an ISO alpha-3 country code to ISO alpha-2.
    """
    if three_code_country == "SEN-GMB":
        return (
            f"{three_2_two_digits_country('SEN')}-{three_2_two_digits_country('GMB')}"
        )
    return coco.convert(three_code_country, to="ISO2")


def two_digits_2_name_country(two_code_country, nocomma=False, remove_start_words=None):
    """
    Convert an ISO alpha-2 country code to its short country name.
    """
    if two_code_country == "SN-GM":
        return f"{two_digits_2_name_country('SN')}-{two_digits_2_name_country('GM')}"

    full_name = coco.convert(two_code_country, to="name_short")

    if nocomma:
        parts = full_name.split(", ")
        parts.reverse()
        full_name = " ".join(parts)

    if remove_start_words:
        for word in remove_start_words:
            if full_name.startswith(word):
                full_name = full_name.replace(word, "", 1).strip()

    return full_name


def country_name_2_two_digits(country_name):
    """
    Convert a country name to ISO alpha-2.
    """
    senegal_gambia = (
        f"{two_digits_2_name_country('SN')}-{two_digits_2_name_country('GM')}"
    )
    if country_name == senegal_gambia:
        return "SN-GM"

    return coco.convert(country_name, to="ISO2")


def read_csv_nafix(file, **kwargs):
    """
    Read a CSV while keeping country-code-like values from being parsed as NA.
    """
    kwargs.setdefault("keep_default_na", False)
    kwargs.setdefault("na_values", NA_VALUES)

    if os.stat(file).st_size > 0:
        return pd.read_csv(file, **kwargs)
    return pd.DataFrame()


def to_csv_nafix(df, path, **kwargs):
    """
    Write a CSV with a consistent NA representation.
    """
    kwargs.pop("na_rep", None)
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    if not df.empty or not df.columns.empty:
        return df.to_csv(path, **kwargs, na_rep=NA_VALUES[0])

    with open(path, "w"):
        pass
    return None


def save_to_geojson(df, fn):
    """
    Write a GeoDataFrame to GeoJSON, creating an empty file for empty data.
    """
    if os.path.exists(fn):
        os.unlink(fn)

    Path(fn).parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        with open(fn, "w"):
            pass
    else:
        df.to_file(fn, driver="GeoJSON")


def read_geojson(fn, cols=None, dtype=None, crs="EPSG:4326"):
    """
    Read a GeoJSON file, returning an empty GeoDataFrame for empty files.
    """
    if cols is None:
        cols = []

    if os.path.getsize(fn) > 0:
        return gpd.read_file(fn)

    df = gpd.GeoDataFrame(columns=cols, geometry=[], crs=crs)
    if isinstance(dtype, dict):
        for column, kind in dtype.items():
            df[column] = df[column].astype(kind)
    return df


def create_country_list(input, iso_coding=True):
    """
    Create a de-duplicated list of country codes.
    """
    cc = coco.CountryConverter()
    full_codes_list = []

    data = getattr(cc, "data", pd.DataFrame())
    for value in input:
        if value == "Earth" and "ISO2" in data:
            codes = data["ISO2"].dropna().astype(str).tolist()
        elif not data.empty and "ISO2" in data:
            matches = pd.Series(dtype=object)
            for column in ["continent", "UNregion", "name_short", "ISO2", "ISO3"]:
                if column in data:
                    column_matches = data[
                        data[column].astype(str).str.casefold() == str(value).casefold()
                    ]["ISO2"]
                    matches = pd.concat([matches, column_matches])
            codes = matches.dropna().astype(str).tolist()
        else:
            codes = []

        if not codes:
            converted = coco.convert(value, to="ISO2", not_found=None)
            if isinstance(converted, str) and converted != "not found":
                codes = [converted]
            else:
                codes = [value]

        full_codes_list.extend(codes)

    if iso_coding:
        full_codes_list = [code for code in full_codes_list if len(code) == 2]

    return sorted(set(full_codes_list))


def harmonize_carrier_names(series):
    return series.str.lower().replace(
        {
            "solar": "pv",
            "csp": "pv",
            "wind": "wind",
            "onwind": "wind",
            "offwind": "wind",
            "ror": "hydro",
            "run of river": "hydro",
            "storage hydro": "hydro",
            "pumped hydro": "hydro",
            "phs": "hydro",
            "wind onshore": "wind",
            "onshore": "wind",
            "wind offshore": "wind",
            "offwind-dc": "wind",
            "offwind-ac": "wind",
            "hard coal": "coal",
            "lignite": "coal",
            "brown coal": "coal",
            "gas": "ccgt",
            "ocgt": "ccgt",
            "multiple": "other",
        }
    )
