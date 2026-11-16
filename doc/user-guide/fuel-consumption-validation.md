<!--
SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->

# Fuel consumption validation

PyPSA-Earth-Status calculates annual final energy consumption by sector and fuel from solved sector-coupled PyPSA-Earth networks and compares it against the historical **UNSD Energy Statistics** shipped with PyPSA-Earth. The comparison is produced by sector and fuel, by sector, by fuel, and as a national total restricted to the categories that can be compared.

## Requirements

The UNSD statistics are not downloaded by this workflow. They are read from a local PyPSA-Earth checkout, together with the fuel groupings and conversion factors defined in its `scripts/_helpers.py`. Point the workflow to that checkout in `config.yaml`:

```yaml
fuel_validation:
  pypsa_earth_path: "../pypsa-earth"
  unsd_path: "../pypsa-earth/data/demand/unsd/data"
  transactions_path: "../pypsa-earth/data/unsd_transactions.csv"
  shift_coal_to_elec: false
  include_other_industries: true
```

| Key | Description |
| --- | --- |
| `pypsa_earth_path` | PyPSA-Earth checkout; `scripts/_helpers.py` is read from it. |
| `unsd_path` | Folder with the raw UNSD `.txt` files. PyPSA-Earth downloads them when it builds the base energy totals. |
| `transactions_path` | PyPSA-Earth list of UNSD industry transactions. |
| `shift_coal_to_elec` | Count residential and services coal as electricity. Must match the `shift_coal_to_elec` option of the PyPSA-Earth run that produced the network. |
| `include_other_industries` | Include the unspecified ("other") industries in the industry reference. Keep `true` unless the network was built without them. |

If any of the three paths is missing, the workflow does not fail: a warning is logged, the reference table is empty and every comparison is reported as `unavailable`.

## Run the workflow

The fuel validation is a dependency of the standard `visualize_data` and `validate_all` targets:

```bash
snakemake -j 1 validate_all
```

For an isolated fuel validation, without running the other reference-data workflows:

```bash
snakemake -j 1 validate_fuel_consumption
```

The workflow uses the network, year and countries configured in `network_validation`. The mapping between model components and UNSD sectors and fuels is maintained in `config/fuel_sector_mapping.yaml`.

## How consumption is calculated

**Model.** Consumption is the snapshot-weighted annual energy, in TWh, of:

- Loads connected to a fuel bus (for example electricity, gas, oil or biomass).
- The input of Links that deliver energy to an end-use bus, such as a gas boiler supplying a heat bus.

Loads on end-use buses (heat, water tanks, vehicle batteries) are skipped, because their supply is already counted at the Link input. Links between fuel buses, such as power plants, are energy transformations and are not counted. This avoids double counting.

The sector is taken from the `sector` metadata of each component. When that is missing, the carrier name is used as a fallback (`carrier_sectors` in the mapping file). In sector-coupled networks the remaining `AC` loads are assigned to the residential sector (`sector_coupled_carrier_sectors`). Components that match none of these are reported as `unclassified` rather than guessed. The fuel is taken from the carrier of the supplying bus.

**Reference.** UNSD quantities are converted to TWh with the PyPSA-Earth conversion factors and grouped into gas, oil, biomass, coal, heat and electricity with the PyPSA-Earth fuel lists. The sectors are residential, services, agriculture, transport (road and rail) and industry. The values are the historical statistics, before any scenario-dependent growth, efficiency or electrification assumption.

**Reference year.** For each commodity, the latest observation not later than the model year is used. UNSD reports the commodities of one fuel up to different years, so a fuel total can combine neighbouring years; `reference_year` gives the most recent one. A commodity whose last observation is more than two years older than the newest of its fuel group is treated as discontinued and left out.

## Output files

Files are written under `results/<validation_name>/`.

| Output | Description |
| --- | --- |
| `tables/fuel_consumption_by_asset.csv` | Annual model consumption of every Load and Link counted, with sector, fuel and source. |
| `tables/fuel_consumption_by_carrier.csv` | Model consumption aggregated by sector, subsector, fuel and bus carrier. |
| `tables/fuel_consumption_reference.csv` | UNSD consumption by country, sector and fuel, with the reference year used. |
| `tables/fuel_consumption_comparison.csv` | Model–UNSD comparison for every sector and fuel pair. |
| `tables/fuel_consumption_comparison_by_sector.csv` | Comparable consumption summed by sector. |
| `tables/fuel_consumption_comparison_by_fuel.csv` | Comparable consumption summed by fuel across sectors. |
| `tables/fuel_consumption_comparison_national.csv` | National comparable total, with coverage indicators. |
| `figures/fuel_consumption_by_sector.png` | Model consumption by sector, stacked by fuel. |
| `figures/fuel_consumption_comparison.png` | Model versus UNSD by sector and fuel, or an explanation if no comparison is available. |

## Interpreting the comparison

All comparison tables contain `network_twh` (model), `reference_twh` (UNSD), `difference` (model minus UNSD), `absolute_difference`, `relative_difference_pct` (difference relative to UNSD), `model_year` and `reference_year`.

Each sector and fuel pair has a `status`:

- `compared`: present in the model and in UNSD. Only these pairs enter the aggregated tables.
- `model_missing`: UNSD reports consumption, but the network has none for this pair although it represents the sector.
- `reference_unavailable`: the network has consumption, but there is no UNSD value for this pair.

A sector that is entirely absent from the network is not treated as zero consumption; its UNSD rows are left out of the comparison.

The national table adds coverage indicators:

- `model_total_twh`: all model consumption found, including unclassified.
- `classified_total_twh`: consumption with both a sector and a fuel assigned.
- `compared_total_twh`: model consumption in `compared` pairs.
- `unclassified_twh`: consumption without a sector or fuel.
- `classification_coverage_pct`: `100 × classified_total_twh / model_total_twh`.
- `comparison_coverage_pct`: `100 × compared_total_twh / model_total_twh`.
- `reference_scope_twh`: UNSD consumption of the `compared` and `model_missing` pairs.
- `reference_coverage_pct`: share of `reference_scope_twh` that is in `compared` pairs.
- `status`: `compared`, `partial`, or `unavailable`.

`compared` indicates that practically all model consumption entered the comparison; it does **not** mean that the model agrees with UNSD. `partial` means some model consumption was not compared; `unavailable` means no pair could be compared.

The national and aggregated values are **like-for-like subtotals of the compared pairs**. Do not interpret them as the complete national final energy consumption.

## Scope and limitations

- The model year and the UNSD reference year usually differ by one or two years, so small deviations are expected.
- In sector-coupled networks the remaining `AC` loads are counted as residential electricity, because PyPSA-Earth scales them to the UNSD residential electricity demand. In electricity-only networks they are the total demand and stay `unclassified`.
- No UNSD reference is built for aviation and navigation; their model consumption is reported as `reference_unavailable`.
- UNSD "heat" has no fuel-bus counterpart in the model. Fuel burned in boilers to supply heat demand is counted under that fuel.
- Electricity-only networks contain no sector-specific loads; the comparison is then `unavailable`.
- A successful Snakemake run does not imply that every sector and fuel was comparable; inspect `status` and the coverage indicators.
