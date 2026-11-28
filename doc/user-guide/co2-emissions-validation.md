<!--
SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->

# CO₂ emissions validation

PyPSA-Earth-Status calculates annual direct CO₂ emissions from solved PyPSA networks and compares them against the **EDGAR 2025 fossil CO₂** dataset. The workflow supports electricity-only and sector-coupled networks and provides diagnostics for emissions that cannot be assigned to a comparable EDGAR sector.

## Run the workflow

The CO₂ validation is a dependency of the standard `visualize_data` target:

```bash
snakemake -j 1 visualize_data
```

For an isolated CO₂ validation, without running the other reference-data workflows:

```bash
snakemake -j 1 validate_co2_comparison
```

The workflow uses the configured network and countries in `network_validation`. The EDGAR reference year is inferred from the network planning horizon when available. For future horizons, the latest year available in the downloaded EDGAR workbook is selected. An optional `sector_emissions.comparison_year` provides a fallback when the planning horizon cannot be determined.

The EDGAR sector mapping is maintained internally in `config/co2_sector_mapping.yaml`; users do not need to supply a mapping file.

## Comparison scope

Electricity-only networks are compared with EDGAR's mapped power-generation sector. For sector-coupled networks, the comparison includes the sectors represented by eligible, classified emitting assets; sectors that are absent from the model emission statistics are not assumed to have zero emissions.

A modeled sector with eligible emitting assets and zero annual emissions can appear in the comparison with a zero model value. Model emissions are compared with the corresponding EDGAR values by country. The comparison includes a `total` row, computed as the sum of **the sectors included in the comparison**, rather than the national total of all EDGAR sectors.

Missing or incomplete sector classification is reported with warnings and coverage diagnostics. If no sectors can be compared, the comparison is marked `unavailable` rather than reporting an invented zero comparison. Invalid data or contradictory sector mappings remain errors.

## Output files

Files are written under `results/<validation_name>/`.

| Output | Description |
| --- | --- |
| `tables/co2_emissions_by_asset.csv` | Annual direct model emissions by asset, including source and sector metadata when available. |
| `tables/co2_emissions_by_carrier.csv` | Aggregated annual direct model emissions by carrier and other classifications. |
| `tables/co2_emissions_reference.csv` | Selected EDGAR reference emissions. |
| `tables/co2_emissions_comparison.csv` | Model–EDGAR sector comparison and comparable total, including absolute and relative differences. |
| `tables/co2_emissions_validation_summary.csv` | Classification status, emissions coverage, and quantities not included in the comparison. |
| `figures/co2_emissions_by_carrier.png` | Model emissions by carrier. |
| `figures/co2_emissions_comparison.png` | Model versus EDGAR, or an explanation if no comparison is available. |

## Interpreting coverage and status

The validation summary contains:

- `model_total`: total positive direct model emissions, in MtCO₂, before subtracting removal flows.
- `classified_total`: positive emissions assigned to a model sector.
- `compared_total`: positive emissions from assets selected for the EDGAR comparison.
- `unclassified_emissions`: positive emissions without a model sector assignment.
- `classified_not_compared`: classified positive emissions outside the EDGAR comparison scope.
- `classification_coverage_pct`: `100 × classified_total / model_total`.
- `comparison_coverage_pct`: `100 × compared_total / model_total`.
- `status`: `compared`, `partial`, or `unavailable`.

The comparison uses **signed net emissions** per sector. Coverage calculations instead use **positive emissions at the asset level**; negative removal flows do not reduce the coverage denominator. Consequently, the comparable signed total in the comparison table need not equal `compared_total` in the validation summary.

`compared` indicates that a comparison was available and its emission coverage met the implementation tolerance; it does **not** mean that modeled emissions agree with EDGAR. `partial` means some modeled emissions were not covered by the comparison; `unavailable` means no sector comparison could be produced.

The `total` comparison is a **like-for-like subtotal for the mapped sectors**. Do not interpret it as the complete national emissions inventory if other model or EDGAR sectors are excluded.

## Scope and limitations

- The metric is annual **direct CO₂ emissions**, not a full lifecycle greenhouse-gas inventory.
- The comparison is only as complete as the asset sector metadata and the explicitly supported EDGAR sector mapping.
- The model-versus-EDGAR comparison figure reports unavailable comparisons when no comparable sector metadata are present.
- A successful Snakemake run does not imply that every country and sector was comparable; inspect `status` and coverage in the validation summary.
- The standard `visualize_data` workflow also depends on other reference data, including Ember. Failures in those independent workflows can prevent `visualize_data` from completing even when CO₂ validation succeeds.
