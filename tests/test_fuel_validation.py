# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests of the fuel consumption validation on a small synthetic network."""

import argparse
import sys
from pathlib import Path

import pandas as pd
import pypsa
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_network_fuel_statistics as stats  # noqa: E402
import build_reference_fuel_unsd as ref  # noqa: E402
import compare_fuel_consumption as comp  # noqa: E402

MAPPING_FILE = ROOT / "config" / "fuel_sector_mapping.yaml"
MAPPING = stats.load_mapping(MAPPING_FILE)
RAW_MAPPING = yaml.safe_load(MAPPING_FILE.read_text())

HOURS = 8760
N_SNAPSHOTS = 4
TWH = 1e-6  # MW * h -> TWh


def twh(mw):
    """Annual energy in TWh of a constant power in MW."""
    return mw * HOURS * TWH


def make_network():
    """Residential electricity and gas heat, industry gas, transport oil."""
    n = pypsa.Network()
    n.set_snapshots(range(N_SNAPSHOTS))
    n.snapshot_weightings.loc[:, :] = HOURS / N_SNAPSHOTS

    for carrier in ["AC", "gas", "oil", "residential rural heat"]:
        n.add("Carrier", carrier)

    n.add("Bus", "elec", carrier="AC")
    n.add("Bus", "gas", carrier="gas")
    n.add("Bus", "oil", carrier="oil")
    n.add("Bus", "res heat", carrier="residential rural heat")
    n.buses["country"] = "JP"

    # Demand on fuel buses: counted.
    n.add("Load", "res elec", bus="elec", carrier="residential electricity", p_set=10.0)
    n.add("Load", "ind gas", bus="gas", carrier="gas for industry", p_set=5.0)
    n.add("Load", "transport oil", bus="oil", carrier="land transport oil", p_set=4.0)
    # Demand on an end-use bus: supplied by the boiler link, must be skipped.
    n.add(
        "Load", "res heat", bus="res heat", carrier="residential rural heat", p_set=6.0
    )

    n.loads["sector"] = pd.Series(
        {
            "res elec": "residential",
            "ind gas": "industry",
            "transport oil": "transport",
            "res heat": "residential",
        }
    )

    # Gas boiler supplies the heat load: its gas input is the final consumption.
    n.add(
        "Link",
        "res gas boiler",
        bus0="gas",
        bus1="res heat",
        carrier="residential rural gas boiler",
        efficiency=0.9,
        p_nom=100.0,
    )
    # Power plant: an energy transformation into the grid, never final use.
    n.add(
        "Link",
        "gas power plant",
        bus0="gas",
        bus1="elec",
        carrier="CCGT",
        efficiency=0.5,
        p_nom=100.0,
    )
    n.links["sector"] = pd.Series(
        {"res gas boiler": "residential", "gas power plant": ""}
    )

    boiler_in = 6.0 / 0.9
    p0 = pd.DataFrame(
        {"res gas boiler": boiler_in, "gas power plant": 10.0}, index=n.snapshots
    )
    n.links_t.p0 = p0
    n.links_t.p1 = pd.DataFrame(
        {"res gas boiler": -6.0, "gas power plant": -5.0}, index=n.snapshots
    )
    return n, boiler_in


@pytest.fixture
def statistics():
    n, boiler_in = make_network()
    detail, summary = stats.build_statistics(n, 2023, MAPPING)
    return n, boiler_in, detail, summary


def pair(detail, sector, fuel):
    rows = detail[detail.sector.eq(sector) & detail.fuel.eq(fuel)]
    return rows.consumption_twh.sum()


def test_annual_consumption_and_fuel_classification(statistics):
    _, boiler_in, detail, _ = statistics

    assert pair(detail, "residential", "electricity") == pytest.approx(twh(10.0))
    assert pair(detail, "residential", "gas") == pytest.approx(twh(boiler_in))
    assert pair(detail, "industry", "gas") == pytest.approx(twh(5.0))
    assert pair(detail, "transport", "oil") == pytest.approx(twh(4.0))
    assert set(detail.region) == {"JP"}
    assert set(detail.model_year) == {2023}


def test_no_double_counting_of_intermediate_flows(statistics):
    _, boiler_in, detail, _ = statistics

    # Neither the heat demand nor the power plant is final consumption.
    assert "res heat" not in set(detail.asset)
    assert "gas power plant" not in set(detail.asset)

    expected = twh(10.0) + twh(boiler_in) + twh(5.0) + twh(4.0)
    assert detail.consumption_twh.sum() == pytest.approx(expected)


def test_missing_sector_metadata_is_unclassified_not_guessed():
    n, _ = make_network()
    n.loads.loc["ind gas", "sector"] = ""
    n.loads.loc["ind gas", "carrier"] = "unmapped demand"
    detail, summary = stats.build_statistics(n, 2023, MAPPING)

    row = detail[detail.asset.eq("ind gas")].iloc[0]
    assert row.sector == stats.UNCLASSIFIED
    assert row.fuel == "gas"
    assert summary.consumption_twh.sum() == pytest.approx(detail.consumption_twh.sum())


def test_network_without_consumption_does_not_fail():
    n = pypsa.Network()
    n.set_snapshots(range(N_SNAPSHOTS))
    n.snapshot_weightings.loc[:, :] = HOURS / N_SNAPSHOTS
    n.add("Carrier", "AC")
    n.add("Bus", "elec", carrier="AC")

    detail, summary = stats.build_statistics(n, 2023, MAPPING)
    assert detail.empty and summary.empty


def reference_table():
    rows = [
        # sector, fuel, year, TWh
        ("residential", "electricity", 2021, 0.09),
        ("residential", "gas", 2022, 0.06),
        ("transport", "oil", 2022, 0.04),
        ("transport", "electricity", 2021, 0.02),  # model has none
        ("agriculture", "electricity", 2021, 0.01),  # sector absent in model
        # no UNSD observation for industry gas
    ]
    return pd.DataFrame(
        [
            {
                "region": "JP",
                "sector": s,
                "fuel": f,
                "reference_year": y,
                "reference_twh": v,
                "reference_source": "UNSD",
            }
            for s, f, y, v in rows
        ]
    )


def test_comparison_handles_absent_sectors_and_missing_observations(statistics):
    _, boiler_in, detail, _ = statistics
    model = comp.prepare_model(detail)
    result = comp.compare_consumption(model, reference_table(), RAW_MAPPING)

    status = result.set_index(["sector", "fuel"])["status"].to_dict()
    assert status[("residential", "electricity")] == "compared"
    assert status[("residential", "gas")] == "compared"
    assert status[("transport", "oil")] == "compared"
    assert status[("industry", "gas")] == "reference_unavailable"
    assert status[("transport", "electricity")] == "model_missing"
    # A sector absent from the model is not treated as zero consumption.
    assert "agriculture" not in set(result.sector)

    row = result.set_index(["sector", "fuel"]).loc[("residential", "electricity")]
    assert row.difference == pytest.approx(twh(10.0) - 0.09)
    assert row.relative_difference_pct == pytest.approx(100 * (twh(10.0) - 0.09) / 0.09)
    assert row.reference_year == 2021 and row.model_year == 2023


def test_aggregates_are_consistent_with_comparable_national_total(statistics):
    _, boiler_in, detail, _ = statistics
    model = comp.prepare_model(detail)
    result = comp.compare_consumption(model, reference_table(), RAW_MAPPING)
    compared = result[result.status.eq("compared")]

    by_sector = comp.sector_table(model, result)
    by_fuel = comp.fuel_table(result)
    national = comp.national_table(model, result).iloc[0]

    assert by_sector.network_twh.sum() == pytest.approx(compared.network_twh.sum())
    assert by_fuel.network_twh.sum() == pytest.approx(compared.network_twh.sum())
    assert national.network_twh == pytest.approx(compared.network_twh.sum())
    assert national.reference_twh == pytest.approx(compared.reference_twh.sum())

    model_total = twh(10.0) + twh(boiler_in) + twh(5.0) + twh(4.0)
    compared_total = twh(10.0) + twh(boiler_in) + twh(4.0)
    assert national.model_total_twh == pytest.approx(model_total)
    assert national.comparison_coverage_pct == pytest.approx(
        100 * compared_total / model_total
    )
    assert national.status == "partial"


def test_carrier_fallback_when_sector_metadata_is_empty():
    n, _ = make_network()
    n.loads.loc["transport oil", "sector"] = ""
    detail, _ = stats.build_statistics(n, 2023, MAPPING)

    row = detail[detail.asset.eq("transport oil")].iloc[0]
    assert row.sector == "transport"


def unsd_rows(observations):
    """UNSD-like rows from (commodity, transaction, year, TWh) tuples."""
    return pd.DataFrame(
        [
            {
                "country": "JP",
                "sector": "transport",
                "Commodity": commodity,
                "Commodity - Transaction": f"{commodity} - {transaction}",
                "Year": year,
                "Quantity_TWh": value,
            }
            for commodity, transaction, year, value in observations
        ]
    )


OIL_FUELS = {"Motor Gasoline": "oil", "Gas Oil/ Diesel Oil": "oil", "Fuel oil": "oil"}


def test_reference_keeps_commodities_reported_in_an_earlier_year():
    rows = unsd_rows(
        [
            ("Motor Gasoline", "Consumption by road", 2021, 390.0),
            ("Motor Gasoline", "Consumption by road", 2022, 400.0),
            # Diesel lags one year behind gasoline: it must not be dropped.
            ("Gas Oil/ Diesel Oil", "Consumption by road", 2020, 240.0),
            ("Gas Oil/ Diesel Oil", "Consumption by road", 2021, 250.0),
        ]
    )
    table = ref.aggregate(rows, OIL_FUELS, 2023, shift_coal_to_elec=False)

    row = table.iloc[0]
    assert len(table) == 1
    assert row.reference_twh == pytest.approx(400.0 + 250.0)
    assert row.reference_year == 2022


def test_reference_drops_discontinued_commodities():
    stale_year = 2022 - ref.MAX_SERIES_LAG_YEARS - 1
    rows = unsd_rows(
        [
            ("Motor Gasoline", "Consumption by road", 2022, 400.0),
            ("Fuel oil", "Consumption by road", stale_year, 30.0),
        ]
    )
    table = ref.aggregate(rows, OIL_FUELS, 2023, shift_coal_to_elec=False)

    assert table.iloc[0].reference_twh == pytest.approx(400.0)


def unsd_rows(observations):
    """UNSD-like rows from (commodity, transaction, year, TWh) tuples."""
    return pd.DataFrame(
        [
            {
                "country": "JP",
                "sector": "transport",
                "Commodity": commodity,
                "Commodity - Transaction": f"{commodity} - {transaction}",
                "Year": year,
                "Quantity_TWh": value,
            }
            for commodity, transaction, year, value in observations
        ]
    )


OIL_FUELS = {"Motor Gasoline": "oil", "Gas Oil/ Diesel Oil": "oil", "Fuel oil": "oil"}


def test_reference_keeps_commodities_reported_in_an_earlier_year():
    rows = unsd_rows(
        [
            ("Motor Gasoline", "Consumption by road", 2021, 390.0),
            ("Motor Gasoline", "Consumption by road", 2022, 400.0),
            # Diesel lags one year behind gasoline: it must not be dropped.
            ("Gas Oil/ Diesel Oil", "Consumption by road", 2020, 240.0),
            ("Gas Oil/ Diesel Oil", "Consumption by road", 2021, 250.0),
        ]
    )
    table = ref.aggregate(rows, OIL_FUELS, 2023, shift_coal_to_elec=False)

    row = table.iloc[0]
    assert len(table) == 1
    assert row.reference_twh == pytest.approx(400.0 + 250.0)
    assert row.reference_year == 2022


def test_reference_drops_discontinued_commodities():
    stale_year = 2022 - ref.MAX_SERIES_LAG_YEARS - 1
    rows = unsd_rows(
        [
            ("Motor Gasoline", "Consumption by road", 2022, 400.0),
            ("Fuel oil", "Consumption by road", stale_year, 30.0),
        ]
    )
    table = ref.aggregate(rows, OIL_FUELS, 2023, shift_coal_to_elec=False)

    assert table.iloc[0].reference_twh == pytest.approx(400.0)


def test_reference_industry_other_is_optional():
    df = pd.DataFrame(
        {
            "Commodity": ["Fuel oil", "Fuel oil"],
            "Transaction": ["Consumption by iron and steel", "Consumption by other"],
            "Year": [2022, 2022],
        }
    )
    transactions = pd.DataFrame(
        {
            "Transaction": ["consumption by iron and steel", "consumption by other"],
            "clean_name": ["iron and steel", "other"],
        }
    )

    with_other = ref.industry_rows(df, transactions, 2023, include_other=True)
    without_other = ref.industry_rows(df, transactions, 2023, include_other=False)

    assert set(with_other.clean_name) == {"iron and steel", "other"}
    assert set(without_other.clean_name) == {"iron and steel"}


def test_reference_is_empty_when_pypsa_earth_is_missing(tmp_path):
    args = argparse.Namespace(
        pypsa_earth_path=str(tmp_path / "pypsa-earth"),
        unsd_path=str(tmp_path / "pypsa-earth" / "unsd"),
        transactions_path=str(tmp_path / "pypsa-earth" / "transactions.csv"),
        year=2023,
        shift_coal_to_elec=False,
        include_other_industries=True,
    )
    table = ref.build_reference(args, ["JP"])

    assert table.empty
    assert list(table.columns) == ref.OUTPUT_COLUMNS


def test_ac_load_is_residential_only_in_sector_coupled_networks():
    n, _ = make_network()
    n.add("Load", "remaining elec", bus="elec", carrier="AC", p_set=3.0)
    detail, _ = stats.build_statistics(n, 2023, MAPPING)
    assert detail[detail.asset.eq("remaining elec")].iloc[0].sector == "residential"

    # Electricity-only network: the AC load is the total demand, not residential.
    n = pypsa.Network()
    n.set_snapshots(range(N_SNAPSHOTS))
    n.snapshot_weightings.loc[:, :] = HOURS / N_SNAPSHOTS
    n.add("Carrier", "AC")
    n.add("Bus", "elec", carrier="AC")
    n.add("Load", "total elec", bus="elec", carrier="AC", p_set=3.0)
    detail, _ = stats.build_statistics(n, 2023, MAPPING)
    assert detail.iloc[0].sector == stats.UNCLASSIFIED
