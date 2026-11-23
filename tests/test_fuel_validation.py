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


def test_reference_keeps_old_observations_and_warns(caplog):
    rows = unsd_rows(
        [
            ("Motor Gasoline", "Consumption by road", 2022, 400.0),
            # Last reported six years before the model year: kept, with a warning.
            ("Fuel oil", "Consumption by road", 2017, 30.0),
        ]
    )
    with caplog.at_level("WARNING", logger=ref.logger.name):
        table = ref.aggregate(
            rows, OIL_FUELS, 2023, shift_coal_to_elec=False, stale_warning_years=5
        )

    assert table.iloc[0].reference_twh == pytest.approx(400.0 + 30.0)
    assert table.iloc[0].reference_year == 2022

    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == 1
    assert "Fuel oil - Consumption by road" in warnings[0]
    assert "2017" in warnings[0] and "6 years" in warnings[0]


def test_reference_does_not_warn_within_threshold(caplog):
    rows = unsd_rows([("Motor Gasoline", "Consumption by road", 2018, 400.0)])
    with caplog.at_level("WARNING", logger=ref.logger.name):
        ref.aggregate(
            rows, OIL_FUELS, 2023, shift_coal_to_elec=False, stale_warning_years=5
        )

    assert not caplog.records


def test_reference_shifts_residential_and_services_coal_to_electricity():
    rows = pd.DataFrame(
        [
            {
                "country": "JP",
                "sector": sector,
                "Commodity": "Hard coal",
                "Commodity - Transaction": f"Hard coal - {sector}",
                "Year": 2022,
                "Quantity_TWh": 1.0,
            }
            for sector in ["residential", "services", "industry"]
        ]
    )
    fuels = {"Hard coal": "coal"}

    shifted = ref.aggregate(rows, fuels, 2023, shift_coal_to_elec=True)
    pairs = set(zip(shifted.sector, shifted.fuel))

    assert pairs == {
        ("residential", "electricity"),
        ("services", "electricity"),
        ("industry", "coal"),
    }


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


def make_industry_transport_network():
    """PyPSA-Earth industry and transport components, without sector metadata."""
    n = pypsa.Network()
    n.set_snapshots(range(N_SNAPSHOTS))
    n.snapshot_weightings.loc[:, :] = HOURS / N_SNAPSHOTS

    buses = {
        "elec": "AC",
        "low voltage": "low voltage",
        "gas": "gas",
        "gas for industry": "gas for industry",
        "biomass": "biomass",
        "solid biomass for industry": "solid biomass for industry",
        "oil": "oil",
        "H2": "H2",
        "EV battery": "Li ion",
    }
    for name, carrier in buses.items():
        n.add("Bus", name, carrier=carrier)
    n.buses["country"] = "JP"

    loads = {
        "gas for industry": ("gas for industry", 5.0),
        "solid biomass for industry": ("solid biomass for industry", 2.0),
        "naphtha for industry": ("oil", 3.0),
        "H2 for industry": ("H2", 1.0),
        "land transport fuel cell": ("H2", 0.5),
        "land transport EV": ("EV battery", 4.0),
    }
    for carrier, (bus, p_set) in loads.items():
        n.add("Load", carrier, bus=bus, carrier=carrier, p_set=p_set)

    # Transfer Links share their carrier name with the industry loads. They move
    # fuel between buses and are not final consumption.
    links = {
        "gas for industry": ("gas", "gas for industry", 5.0),
        "solid biomass for industry": ("biomass", "solid biomass for industry", 2.0),
        "BEV charger": ("low voltage", "EV battery", 4.0 / 0.9),
    }
    for carrier, (bus0, bus1, p0) in links.items():
        n.add("Link", carrier + " link", bus0=bus0, bus1=bus1, carrier=carrier)
    n.links_t.p0 = pd.DataFrame(
        {name + " link": p0 for name, (_, _, p0) in links.items()}, index=n.snapshots
    )
    n.links_t.p1 = -n.links_t.p0
    return n


def test_carrier_fallback_covers_industry_and_transport_carriers():
    n = make_industry_transport_network()
    detail, _ = stats.build_statistics(n, 2023, MAPPING)
    rows = detail.set_index("asset")

    expected = {
        "gas for industry": ("industry", "gas", 5.0),
        "solid biomass for industry": ("industry", "biomass", 2.0),
        "naphtha for industry": ("industry", "oil", 3.0),
        "H2 for industry": ("industry", "hydrogen", 1.0),
        "land transport fuel cell": ("transport", "hydrogen", 0.5),
        # The EV load sits on the battery bus; the charger input is counted.
        "BEV charger link": ("transport", "electricity", 4.0 / 0.9),
    }
    for asset, (sector, fuel, mw) in expected.items():
        assert rows.loc[asset, "sector"] == sector, asset
        assert rows.loc[asset, "fuel"] == fuel, asset
        assert rows.loc[asset, "consumption_twh"] == pytest.approx(twh(mw)), asset

    assert stats.UNCLASSIFIED not in set(detail.sector)


def test_transfer_links_are_not_final_consumption():
    n = make_industry_transport_network()
    detail, _ = stats.build_statistics(n, 2023, MAPPING)

    # Same carrier as the industry loads, but only fuel transfers between buses.
    assert "gas for industry link" not in set(detail.asset)
    assert "solid biomass for industry link" not in set(detail.asset)
    # The EV demand is covered by the charger input, not counted a second time.
    assert "land transport EV" not in set(detail.asset)


def make_heat_network():
    """CHPs, district heating and a heat bus shared by services and industry."""
    n = pypsa.Network()
    n.set_snapshots(range(N_SNAPSHOTS))
    n.snapshot_weightings.loc[:, :] = HOURS / N_SNAPSHOTS

    buses = {
        "elec": "AC",
        "gas": "gas",
        "co2 atmosphere": "co2 atmosphere",
        "central heat": "urban central heat",
        "res heat": "residential urban decentral heat",
        "ser heat": "services urban decentral heat",
    }
    for name, carrier in buses.items():
        n.add("Bus", name, carrier=carrier)
    n.buses["country"] = "JP"

    loads = {
        # District heating: residential and services together, as in PyPSA-Earth.
        "urban central heat": ("central heat", 6.0),
        "industry heat central": ("central heat", 2.0),
        "residential urban decentral heat": ("res heat", 5.0),
        # A services heat bus also supplying industrial low-temperature heat.
        "services urban decentral heat": ("ser heat", 3.0),
        "industry heat decentral": ("ser heat", 1.0),
    }
    for name, (bus, p_set) in loads.items():
        carrier = "low-temperature heat for industry" if "industry" in name else name
        n.add("Load", name, bus=bus, carrier=carrier, p_set=p_set)

    # name: (carrier, bus0, {port: (bus, output MW)}, input MW)
    links = {
        "central CHP": (
            "urban central gas CHP",
            "gas",
            {1: ("elec", 4.0), 2: ("central heat", 4.0), 3: ("co2 atmosphere", 2.0)},
            10.0,
        ),
        "central boiler": (
            "urban central gas boiler",
            "gas",
            {1: ("central heat", 4.0)},
            4.0 / 0.9,
        ),
        # Micro CHP: 3 MW electricity to the grid and 5 MW heat to the household.
        "micro CHP": (
            "residential urban decentral micro gas CHP",
            "gas",
            {1: ("elec", 3.0), 2: ("res heat", 5.0), 3: ("co2 atmosphere", 2.0)},
            10.0,
        ),
        "services boiler": (
            "services urban decentral gas boiler",
            "gas",
            {1: ("ser heat", 4.0)},
            4.0 / 0.9,
        ),
    }
    flows = {port: {} for port in range(4)}
    for name, (carrier, bus0, outputs, p0) in links.items():
        ports = {f"bus{port}": bus for port, (bus, _) in outputs.items()}
        n.add("Link", name, bus0=bus0, carrier=carrier, **ports)
        flows[0][name] = p0
        for port, (_, mw) in outputs.items():
            # The CO2 port is drawn into the atmosphere bus (negative = injected).
            flows[port][name] = -mw
    for port, values in flows.items():
        n.links_t[f"p{port}"] = pd.DataFrame(values, index=n.snapshots)
    return n


@pytest.fixture
def heat_statistics():
    return stats.build_statistics(make_heat_network(), 2023, MAPPING)[0]


def test_district_heating_is_counted_as_delivered_heat(heat_statistics):
    detail = heat_statistics

    # Fuel burned in central CHPs and boilers is an energy transformation.
    assert "central CHP" not in set(detail.asset)
    assert "central boiler" not in set(detail.asset)

    heat = detail[detail.fuel.eq("heat")].set_index("asset")
    assert heat.loc["industry heat central", "sector"] == "industry"
    assert heat.loc["industry heat central", "consumption_twh"] == pytest.approx(
        twh(2.0)
    )
    # The combined residential and services load cannot be split: unclassified.
    assert heat.loc["urban central heat", "sector"] == stats.UNCLASSIFIED
    assert set(heat.consumption_source) == {"load_district_heat"}


def test_multi_output_link_counts_only_the_end_use_share(heat_statistics):
    detail = heat_statistics
    micro = detail[detail.asset.eq("micro CHP")]

    # 10 MW of gas gives 3 MW electricity and 5 MW heat (CO2 is not an output):
    # only the heat share of the gas is final consumption in the household.
    assert len(micro) == 1
    assert micro.iloc[0].sector == "residential"
    assert micro.iloc[0].fuel == "gas"
    assert micro.iloc[0].consumption_twh == pytest.approx(twh(10.0 * 5.0 / 8.0))


def test_shared_heat_bus_is_split_by_load_sector(heat_statistics):
    detail = heat_statistics
    boiler = detail[detail.asset.eq("services boiler")].set_index("sector")

    gas_in = twh(4.0 / 0.9)
    # Services heat 3 MW and industrial heat 1 MW on the same bus.
    assert set(boiler.index) == {"services", "industry"}
    assert boiler.loc["services", "consumption_twh"] == pytest.approx(gas_in * 0.75)
    assert boiler.loc["industry", "consumption_twh"] == pytest.approx(gas_in * 0.25)
    assert set(boiler.fuel) == {"gas"}


def test_dedicated_load_shedding_reduces_final_consumption():
    n, _ = make_network()
    n.add("Bus", "industry biomass", carrier="solid biomass for industry")
    n.buses.at["industry biomass", "country"] = "JP"
    n.add(
        "Load",
        "dedicated biomass demand",
        bus="industry biomass",
        carrier="solid biomass for industry",
        p_set=10.0,
    )
    n.add(
        "Generator",
        "biomass shedding",
        bus="industry biomass",
        carrier="load shedding",
        p_nom=10.0,
    )
    shedding_mw = pd.Series([2.0, 0.0, 4.0, 1.0], index=n.snapshots)
    n.generators_t.p = pd.DataFrame({"biomass shedding": shedding_mw})

    detail, _ = stats.build_statistics(n, 2023, MAPPING)
    row = detail.loc[detail.asset.eq("dedicated biomass demand")].iloc[0]
    expected = (10.0 * HOURS - shedding_mw.sum() * HOURS / N_SNAPSHOTS) * TWH
    assert row.sector == "industry"
    assert row.fuel == "biomass"
    assert row.consumption_twh == pytest.approx(expected)

    shedding = stats.load_shedding_statistics(
        n,
        2023,
        stats.snapshot_weights(n),
        stats.apply_sector_coupled_fallback(n, MAPPING),
    )
    assert shedding.unserved_twh.sum() == pytest.approx(
        shedding_mw.sum() * HOURS / N_SNAPSHOTS * TWH
    )
    assert shedding.iloc[0].sector == "industry"
    assert shedding.iloc[0].fuel == "biomass"


def test_shared_bus_shedding_is_unclassified_and_not_subtracted():
    n, _ = make_network()
    n.add("Bus", "shared low voltage", carrier="low voltage")
    n.buses.at["shared low voltage", "country"] = "JP"
    n.add(
        "Load",
        "shared industry",
        bus="shared low voltage",
        carrier="industry electricity",
        p_set=3.0,
    )
    n.add(
        "Load",
        "shared services",
        bus="shared low voltage",
        carrier="services electricity",
        p_set=4.0,
    )
    n.add(
        "Generator",
        "shared shedding",
        bus="shared low voltage",
        carrier="load shedding",
        p_nom=10.0,
    )
    n.generators_t.p = pd.DataFrame(
        {"shared shedding": [1.0, 2.0, 0.0, 1.0]}, index=n.snapshots
    )

    detail, _ = stats.build_statistics(n, 2023, MAPPING)
    assert detail.loc[detail.asset.eq("shared industry"), "consumption_twh"].iloc[
        0
    ] == pytest.approx(twh(3.0))
    assert detail.loc[detail.asset.eq("shared services"), "consumption_twh"].iloc[
        0
    ] == pytest.approx(twh(4.0))

    shedding = stats.load_shedding_statistics(
        n,
        2023,
        stats.snapshot_weights(n),
        stats.apply_sector_coupled_fallback(n, MAPPING),
    )
    assert set(shedding.sector) == {stats.UNCLASSIFIED}
    assert set(shedding.fuel) == {"electricity"}
    assert shedding.unserved_twh.sum() == pytest.approx(twh(1.0))


def test_decentralized_solar_thermal_is_counted_but_central_is_not():
    n, _ = make_network()
    n.add("Bus", "district heat", carrier="urban central heat")
    n.buses.at["district heat", "country"] = "JP"
    n.add(
        "Load",
        "central heat load",
        bus="district heat",
        carrier="urban central heat",
        p_set=2.0,
    )
    n.add(
        "Generator",
        "res solar thermal",
        bus="res heat",
        carrier="residential rural solar thermal",
        p_nom=5.0,
    )
    n.add(
        "Generator",
        "central solar thermal",
        bus="district heat",
        carrier="urban central solar thermal",
        p_nom=5.0,
    )
    n.generators_t.p = pd.DataFrame(
        {
            "res solar thermal": [1.0] * N_SNAPSHOTS,
            "central solar thermal": [2.0] * N_SNAPSHOTS,
        },
        index=n.snapshots,
    )

    detail, _ = stats.build_statistics(n, 2023, MAPPING)
    solar = detail.loc[detail.consumption_source.eq("direct_solar_thermal")]
    assert set(solar.asset) == {"res solar thermal"}
    assert solar.consumption_twh.sum() == pytest.approx(twh(1.0))
    central = detail.loc[detail.asset.eq("central heat load")]
    assert central.consumption_twh.sum() == pytest.approx(twh(2.0))
    assert set(central.consumption_source) == {"load_district_heat"}


def test_electricity_only_plot_accepts_empty_shedding(tmp_path):
    from plot_fuel_comparison import plot_comparison
    from plot_fuel_consumption import plot_by_sector

    n = pypsa.Network()
    n.set_snapshots(range(N_SNAPSHOTS))
    n.snapshot_weightings.loc[:, :] = HOURS / N_SNAPSHOTS
    n.add("Carrier", "AC")
    n.add("Bus", "electricity", carrier="AC")
    n.buses["country"] = "DE"
    n.add("Load", "total electricity", bus="electricity", carrier="AC", p_set=3.0)

    detail, _ = stats.build_statistics(n, 2023, MAPPING)
    shedding = stats.load_shedding_statistics(
        n, 2023, stats.snapshot_weights(n), MAPPING
    )
    assert shedding.empty
    assert set(detail.sector) == {stats.UNCLASSIFIED}

    output = tmp_path / "electricity_only.png"
    plot_by_sector(detail, output, shedding)
    assert output.is_file()
    assert output.stat().st_size > 0

    empty_comparison = pd.DataFrame(
        columns=[
            "region",
            "sector",
            "fuel",
            "model_year",
            "reference_year",
            "network_twh",
            "reference_twh",
            "status",
        ]
    )
    comparison_output = tmp_path / "electricity_only_comparison.png"
    plot_comparison(empty_comparison, comparison_output, shedding)
    assert comparison_output.is_file()
    assert comparison_output.stat().st_size > 0
