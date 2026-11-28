# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared network capability detection and sector mapping."""

import yaml


def load_mapping(path):
    """Read the sector and fuel mapping."""
    with open(path) as f:
        cfg = yaml.safe_load(f)

    return {
        "sectors": {
            model: unsd for unsd, models in cfg["sectors"].items() for model in models
        },
        "carrier_sectors": {
            carrier: unsd
            for unsd, carriers in cfg.get("carrier_sectors", {}).items()
            for carrier in carriers
        },
        "sector_coupled_carrier_sectors": {
            carrier: unsd
            for unsd, carriers in cfg.get("sector_coupled_carrier_sectors", {}).items()
            for carrier in carriers
        },
        "fuels": {
            carrier: fuel
            for fuel, carriers in cfg["fuels"].items()
            for carrier in carriers
        },
        "end_use": set(cfg.get("end_use_bus_carriers", [])),
        "district_heating": set(cfg.get("district_heating_bus_carriers", [])),
        "excluded": set(cfg.get("excluded_bus_carriers", [])),
    }


def is_sector_coupled(n, mapping):
    """Detect sector-coupled networks from their components."""
    mapped_sectors = set(mapping["sectors"])
    mapped_carriers = set(mapping["carrier_sectors"])

    for components in (n.loads, n.links):
        if components.empty:
            continue

        if "sector" in components.columns:
            sectors = components["sector"].fillna("").astype(str).str.strip()
            if sectors.isin(mapped_sectors).any():
                return True

        if "carrier" in components.columns:
            carriers = components["carrier"].fillna("").astype(str).str.strip()
            if carriers.isin(mapped_carriers).any():
                return True

    return False
