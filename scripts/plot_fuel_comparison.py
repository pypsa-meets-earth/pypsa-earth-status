# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plot model and UNSD final energy consumption by sector and fuel."""

import argparse
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def year_label(years):
    """Format one year or a year range."""
    years = sorted(int(y) for y in pd.Series(years).dropna().unique())
    if not years:
        return "n/a"
    return str(years[0]) if len(years) == 1 else f"{years[0]}–{years[-1]}"


def shedding_note(shedding):
    """Format a separate unmet-demand note, never added to fuel totals."""
    if shedding is None or shedding.empty:
        return ""
    active = shedding.loc[shedding["unserved_twh"].gt(0.001)].copy()
    if active.empty:
        return ""
    grouped = (
        active.groupby(["sector", "fuel"], dropna=False)["unserved_twh"]
        .sum()
        .sort_values(ascending=False)
    )
    items = [
        f"{('Unassigned sector' if sector == 'unclassified' else str(sector).title())}: "
        f"{value:.2f} TWh {fuel}"
        for (sector, fuel), value in grouped.items()
    ]
    return "Unserved demand (not included in bars): " + "; ".join(items)


def plot_comparison(table, output, shedding=None):
    """Show UNSD comparison and separately identified load shedding on model bars.

    Load shedding is not part of final energy consumption or the UNSD difference.
    Rows with shedding but no matched UNSD observation are shown without a
    reference bar, instead of silently hiding that shedding.
    """
    required = {
        "region",
        "sector",
        "fuel",
        "model_year",
        "reference_year",
        "network_twh",
        "reference_twh",
        "status",
    }
    if missing := required - set(table.columns):
        raise ValueError(f"Missing comparison columns: {sorted(missing)}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    data = table.copy()
    for column in ("region", "sector", "fuel"):
        data[column] = data[column].fillna("").astype(str).str.strip()
    for column in ("network_twh", "reference_twh"):
        data[column] = pd.to_numeric(data[column], errors="coerce")

    compared = data.loc[data["status"].eq("compared")].copy()
    compared["load_shedding_twh"] = 0.0
    rows = compared.copy()

    if shedding is not None and not shedding.empty:
        requested = {"region", "sector", "fuel", "unserved_twh"}
        if missing := requested - set(shedding.columns):
            raise ValueError(f"Missing load shedding columns: {sorted(missing)}")
        active = shedding.copy()
        for column in ("region", "sector", "fuel"):
            active[column] = active[column].fillna("").astype(str).str.strip()
        active["unserved_twh"] = pd.to_numeric(
            active["unserved_twh"], errors="coerce"
        ).fillna(0.0)
        active = active.loc[active["unserved_twh"].gt(0.001)]

        if not active.empty:
            grouped = active.groupby(["region", "sector", "fuel"], as_index=False)[
                "unserved_twh"
            ].sum()
            rows = rows.merge(grouped, on=["region", "sector", "fuel"], how="left")
            rows["load_shedding_twh"] = rows.pop("unserved_twh").fillna(0.0)

            # Append shedding-only rows that have no comparable UNSD observation.
            matched = set(zip(rows.region, rows.sector, rows.fuel))
            missing_keys = grouped.loc[
                ~grouped.apply(
                    lambda r: (r.region, r.sector, r.fuel) in matched, axis=1
                )
            ]
            extra_rows = []
            for key in missing_keys.itertuples(index=False):
                possibilities = data.loc[
                    data.region.eq(key.region)
                    & data.sector.eq(key.sector)
                    & data.fuel.eq(key.fuel)
                ]
                record = (
                    possibilities.iloc[0].to_dict() if not possibilities.empty else {}
                )
                record.update(
                    region=key.region,
                    sector=key.sector,
                    fuel=key.fuel,
                    network_twh=record.get("network_twh", 0.0),
                    reference_twh=float("nan"),
                    reference_year=float("nan"),
                    status="not_compared",
                    load_shedding_twh=float(key.unserved_twh),
                )
                if pd.isna(record["network_twh"]):
                    record["network_twh"] = 0.0
                extra_rows.append(record)
            if extra_rows:
                rows = pd.concat([rows, pd.DataFrame(extra_rows)], ignore_index=True)

    if rows.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(
            0.5,
            0.5,
            "Fuel comparison unavailable: no matched UNSD observations",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.suptitle("Final energy consumption by sector and fuel", fontsize=16)
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    rows["network_twh"] = pd.to_numeric(rows["network_twh"], errors="coerce").fillna(
        0.0
    )
    rows["load_shedding_twh"] = pd.to_numeric(
        rows["load_shedding_twh"], errors="coerce"
    ).fillna(0.0)
    # Display fuel names on each row and sector names once per group.
    rows["fuel_label"] = rows["fuel"].str.replace("_", " ").str.title()
    has_shedding = rows["load_shedding_twh"].gt(0.001)
    rows.loc[has_shedding, "fuel_label"] += " (load shedding)"
    regions = sorted(rows["region"].unique())

    # Horizontal bars: row zero is at the bottom, so Unclassified is below Agriculture.
    sector_order = {
        "unclassified": 0,
        "agriculture": 1,
        "aviation": 2,
        "industry": 3,
        "navigation": 4,
        "residential": 5,
        "services": 6,
        "transport": 7,
    }
    rows["sector_sort"] = rows["sector"].map(sector_order).fillna(8)
    rows = rows.sort_values(["region", "sector_sort", "sector", "fuel"]).reset_index(
        drop=True
    )

    # Leave a gap between sectors, keeping Unclassified below Agriculture.
    group_keys = list(zip(rows["region"], rows["sector"]))
    new_group = np.array(
        [i == 0 or key != group_keys[i - 1] for i, key in enumerate(group_keys)]
    )
    gap = 0.8
    positions = np.arange(len(rows), dtype=float) + gap * (new_group.cumsum() - 1)
    height = 0.34
    fig, ax = plt.subplots(
        figsize=(19, max(6, len(rows) * 0.85 + new_group.sum() * 0.5 + 3.0))
    )
    model_y = positions - height / 2
    reference_y = positions + height / 2
    model_values = rows["network_twh"].to_numpy()
    shedding_values = rows["load_shedding_twh"].to_numpy()

    ax.barh(model_y, model_values, height, color="#F4C430", label="Model", zorder=3)
    has_shedding = shedding_values > 0.001
    if has_shedding.any():
        ax.barh(
            model_y[has_shedding],
            shedding_values[has_shedding],
            height,
            left=model_values[has_shedding],
            color="#F4C430",
            zorder=3,
        )

    has_reference = rows["reference_twh"].notna().to_numpy()
    if has_reference.any():
        ax.barh(
            reference_y[has_reference],
            rows.loc[has_reference, "reference_twh"].to_numpy(),
            height,
            color="#EB6834",
            label="UNSD",
            zorder=3,
        )

    # Labels keep actual model consumption separate from the diagnostic segment.
    for i, (model, shed) in enumerate(zip(model_values, shedding_values)):
        value = f"{model:.1f}"
        if shed > 0.001:
            value += f" + {shed:.2f} LS"
        ax.text(model + shed, model_y[i], f" {value}", va="center", fontsize=8)
        if has_reference[i]:
            reference = float(rows.iloc[i]["reference_twh"])
            ax.text(
                reference, reference_y[i], f" {reference:.1f}", va="center", fontsize=8
            )

    ax.set_yticks(positions)
    ax.set_yticklabels(rows["fuel_label"])
    ax.tick_params(axis="y", length=0, pad=10)

    # Center the sector name vertically across its fuel rows. Position sector
    # labels in an independent left column, without repeating them per fuel.
    for (region, sector), part in rows.groupby(["region", "sector"], sort=False):
        indices = part.index.to_numpy()
        sector_center = (positions[indices[0]] + positions[indices[-1]]) / 2
        sector_label = sector.replace("_", " ").title()
        if len(regions) > 1:
            sector_label = f"{region} / {sector_label}"
        ax.text(
            -0.23,
            sector_center,
            sector_label,
            transform=ax.get_yaxis_transform(),
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            clip_on=False,
        )

    for index in np.flatnonzero(new_group)[1:]:
        separator = (positions[index - 1] + positions[index]) / 2
        ax.axhline(separator, color="#c4c4c4", linewidth=0.8, zorder=1)

    ax.set_xlabel("Energy consumption (TWh/year)")
    ax.grid(axis="x", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    max_ref = float(rows["reference_twh"].max()) if has_reference.any() else 0.0
    max_value = max(max_ref, float((model_values + shedding_values).max()), 1.0)
    ax.set_xlim(0, max_value * 1.08)

    model_year = year_label(rows["model_year"])
    reference_name = (
        str(compared["reference_source"].dropna().iloc[0])
        if "reference_source" in compared.columns
        and compared["reference_source"].notna().any()
        else "UNSD"
    )
    fig.suptitle(
        "Final energy consumption by sector and fuel",
        fontsize=16,
        fontweight="bold",
        y=0.98,
    )
    title = f"{', '.join(regions)} ({model_year})"
    if compared.empty:
        title += " - UNSD comparison unavailable"
    ax.set_title(title, fontsize=11, pad=12)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        labels = [
            (
                f"Model ({model_year})"
                if x == "Model"
                else (
                    f"{reference_name} ({year_label(compared['reference_year'])})"
                    if x == "UNSD"
                    else x
                )
            )
            for x in labels
        ]
        fig.legend(
            handles,
            labels,
            loc="lower center",
            bbox_to_anchor=(0.5, 0.06),
            ncol=min(3, len(labels)),
            frameon=False,
            fontsize=10,
        )

    # Reserve fixed space for the sector and fuel label columns.
    fig.subplots_adjust(left=0.22, right=0.98, bottom=0.16, top=0.92)
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--shedding")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    shedding = pd.read_csv(args.shedding) if args.shedding else None
    plot_comparison(pd.read_csv(args.input), args.output, shedding)


if __name__ == "__main__":
    main()
