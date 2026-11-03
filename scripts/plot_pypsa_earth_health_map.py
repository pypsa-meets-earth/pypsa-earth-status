# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Build an interactive world map of PyPSA-Earth validation health.

Reads the long-format ``health_status_actual.csv`` (one row per
country / pillar / metric / reference_source), reshapes it into one row
per country, and renders a Leaflet/folium choropleth where each country
is coloured by its average validation error. Clicking a country's icon
opens a popup with the error % reported by every individual reference
source; hovering a country shows a short summary.
"""

import folium
import geopandas as gpd
import pandas as pd

INPUT_CSV = "../pe_health_status/health_status_actual.csv"
COUNTRIES_SHAPEFILE = "../pe_health_status/ne_110m_admin_0_countries.zip"
OUTPUT_HTML = "country_metrics_map_explore.html"
COUNTRY_COL = "country_name"

# Maps each (pillar, metric) pair found in the input CSV to the short key
# used for that metric throughout this script.
PILLAR_METRIC_TO_KEY = {
    ("installed_capacity", "total_capacity"): "capacity_error_pct",
    ("demand", "total_demand"): "demand_error_pct",
}

# Display label and popup accent colour for each metric.
METRICS = {
    "capacity_error_pct": {
        "label": "Capacity error (%)",
        "colorscale": "Reds",
    },
    "demand_error_pct": {
        "label": "Demand error (%)",
        "colorscale": "Blues",
    },
}
metric_keys = list(METRICS.keys())

# Icon styling for the per-country marker (see make_graph_icon_html).
ICON_COLOR = "#37474f"
ICON_BORDER = "#263238"
MIN_ICON_PX, MAX_ICON_PX = 14, 34


def _darken_hex(hex_color, factor=0.55):
    """
    Return a darker shade of a ``#rrggbb`` color string.

    Parameters
    ----------
    hex_color : str or None
        Color in ``#rrggbb`` form
    factor : float, optional
        Multiplier applied to each RGB channel

    Returns
    -------
    str
        The darkened color in ``#rrggbb`` form.
    """
    if not hex_color:
        return "#333333"
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, int(c * factor)) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken_border(feature):
    """
    folium ``style_function`` hook: border color = a darker shade of this
    feature's own fill color.

    Parameters
    ----------
    feature : dict
        A single GeoJSON feature, as passed by folium/Leaflet to a style_function.

    Returns
    -------
    dict
        A partial Leaflet style dict overriding just the ``color`` (border) key
    """
    return {"color": _darken_hex(feature["properties"].get("__folium_color"))}


def make_table_popup_html(row, source_lookup) -> str:
    """
    Build the click-popup HTML for one country.

    Lists every reference source's error % under each metric heading, e.g.
    "Capacity error (%)" followed by an "irena" row and an "ember" row.

    Parameters
    ----------
    row : pandas.Series
        One row of the merged country GeoDataFrame
    source_lookup : dict
        Mapping of ``country_code -> {metric_key: [(source, value), ...]}``
    Returns
    -------
    str
        Self-contained HTML for use as a folium ``Popup``.
    """
    rows = ""
    sources_by_metric = source_lookup.get(row.name, {})
    for key, meta in METRICS.items():
        rows += f"""
        <tr>
          <td colspan="2" style="padding:6px 0 2px 0; font-weight:600;">{meta['label']}</td>
        </tr>"""
        for source, value in sources_by_metric.get(key, []):
            rows += f"""
        <tr>
          <td style="padding:1px 8px 1px 10px; color:#555;">{source}</td>
          <td style="padding:1px 0; text-align:right;"><b>{value:.2f}%</b></td>
        </tr>"""
    return f"""
    <div style="font-family:sans-serif; width:220px;">
      <div style="font-size:13px; font-weight:600; margin-bottom:8px;">{row[COUNTRY_COL]}</div>
      <table style="font-size:12px; width:100%; border-collapse:collapse;">
        {rows}
      </table>
    </div>"""


def make_graph_icon_html(size: float) -> str:
    """
    Build the DivIcon HTML for a country's marker.

    Renders a small bar-chart glyph inside a circular badge, both sized
    proportionally to ``size`` so larger countries get a larger marker.

    Parameters
    ----------
    size : float
        Marker diameter in pixels (see ``MIN_ICON_PX``/``MAX_ICON_PX``).

    Returns
    -------
    str
        Self-contained HTML for use as a folium ``DivIcon``.
    """
    svg_size = round(size * 0.6)
    return f"""
    <div style="
        width:{size}px; height:{size}px; border-radius:50%;
        background:{ICON_COLOR}; border:1px solid {ICON_BORDER};
        display:flex; align-items:center; justify-content:center;
    ">
      <svg width="{svg_size}" height="{svg_size}" viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg">
        <rect x="1" y="7" width="3" height="6" fill="#ffffff"/>
        <rect x="5.5" y="3" width="3" height="10" fill="#ffffff"/>
        <rect x="10" y="5" width="3" height="8" fill="#ffffff"/>
      </svg>
    </div>
    """


def main():
    """
    Load the validation data, build the map, and write it to OUTPUT_HTML.

    Reads ``INPUT_CSV``, reshapes it into one row per country, joins it
    onto the Natural Earth country geometries, and renders a folium
    choropleth (colored by average error, with per-country marker popups)
    to ``OUTPUT_HTML``. Takes no parameters and returns nothing; all
    inputs/outputs are the module-level constants at the top of this file.
    """
    # --- Load and reshape the validation data -------------------------------
    # health_status_actual.csv is long-format: one row per
    # country/pillar/metric/reference_source. Some (pillar, metric) pairs
    # have multiple reference sources per country (e.g. demand has both
    # ourworldindata and ember) - those are averaged into one value per
    # country.
    raw = pd.read_csv(INPUT_CSV)
    raw["metric_key"] = [
        PILLAR_METRIC_TO_KEY.get(pm) for pm in zip(raw["pillar"], raw["metric"])
    ]
    raw_metrics = raw.dropna(subset=["metric_key"])

    pivot = (
        raw_metrics.groupby(["country_code", "metric_key"])["deviation_pct"]
        .mean()
        .unstack("metric_key")
    )
    country_meta = raw.groupby("country_code").agg(
        country_name=("country_name", "first"),
        pypsa_earth_version=("pypsa_earth_version", "first"),
    )
    df = country_meta.join(pivot)

    # Per-source breakdown (e.g. capacity error per irena vs ember) kept
    # separately so popups can show every data source, not just the average.
    source_lookup = {}
    for (country_code, metric_key), grp in raw_metrics.groupby(
        ["country_code", "metric_key"]
    ):
        source_lookup.setdefault(country_code, {})[metric_key] = list(
            zip(grp["reference_source"], grp["deviation_pct"])
        )

    years = sorted(raw["year"].dropna().unique().tolist())
    year_label = f"{years[0]}" if len(years) == 1 else f"{years[0]}-{years[-1]}"

    # --- Join onto country geometries ----------------------------------------
    gdf_countries = gpd.read_file(COUNTRIES_SHAPEFILE)
    gdf_countries.set_index("ISO_A2", inplace=True)
    gdf_countries_merged = gdf_countries.join(df)

    # Columns that are shown on hover
    popup_cols = ["country_name", "pypsa_earth_version"] + metric_keys

    # All metrics are already % errors, so just average their magnitudes
    # directly into a single "overall error" score used to colour the map.
    gdf_countries_merged["avg_error_score"] = (
        gdf_countries_merged[metric_keys].abs().mean(axis=1).round(2)
    )

    # Hover tooltip content: countries with no entry in
    # health_status_actual.csv still get a name (falling back to the
    # Natural Earth "ADMIN" field) plus an explicit note instead of
    # blank/NaN metric values. Each piece is its own tooltip field so it
    # renders on its own bolded-label row.
    gdf_countries_merged["display_country"] = gdf_countries_merged[
        "country_name"
    ].fillna(gdf_countries_merged["ADMIN"])
    gdf_countries_merged["version_display"] = gdf_countries_merged[
        "pypsa_earth_version"
    ].fillna("Health status not added")
    gdf_countries_merged["avg_error_display"] = gdf_countries_merged[
        "avg_error_score"
    ].apply(lambda v: "N/A" if pd.isna(v) else f"{v}")

    tooltip_cols = ["display_country", "version_display", "avg_error_display"]
    tooltip_aliases = ["Country", "PyPSA-Earth version", "Avg error"]

    if (
        gdf_countries_merged.crs is not None
        and gdf_countries_merged.crs.to_epsg() != 4326
    ):
        gdf_countries_merged = gdf_countries_merged.to_crs(epsg=4326)

    # --- Build the map --------------------------------------------------------
    # Single choropleth layer coloured by the average error across all
    # metrics, fixed to a 0-100 scale so colors are comparable in absolute
    # terms.
    m = gdf_countries_merged.explore(
        column="avg_error_score",
        cmap="jet",
        vmin=0,
        vmax=100,
        tooltip=tooltip_cols,
        tooltip_kwds={"aliases": tooltip_aliases},
        popup=popup_cols,
        legend=True,
        name="Average error",
        legend_kwds={"caption": "Average error (%)"},
        style_kwds={"weight": 1, "style_function": _darken_border},
        no_wrap=True,
        min_zoom=1.5,
    )

    m.options["noWrap"] = True
    m.options["maxBounds"] = [
        [-90, -180],
        [90, 180],
    ]  # Restricts coordinates to global bounds
    m.options["maxBoundsViscosity"] = (
        1.0  # Makes bounds rigid so the map can't be dragged endlessly
    )

    # --- Per-country marker with a click popup table --------------------------
    # Only countries actually present in health_status_actual.csv have data
    # to show, and icon size scales with country area (equal-area
    # projection, sqrt so it tracks linear "size" rather than area itself,
    # else small countries would all collapse to the minimum size).
    has_data = gdf_countries_merged["avg_error_score"].notna()
    gdf_with_data = gdf_countries_merged.loc[has_data]
    centroids = gdf_with_data.geometry.to_crs(epsg=3857).centroid.to_crs(epsg=4326)

    # Calculate icon sizes based on area of the country
    area_measure = gdf_with_data.geometry.to_crs(epsg=6933).area.pow(0.5)
    lo, hi = area_measure.min(), area_measure.max()
    if hi > lo:
        icon_sizes = MIN_ICON_PX + (area_measure - lo) / (hi - lo) * (
            MAX_ICON_PX - MIN_ICON_PX
        )
    else:
        icon_sizes = pd.Series(MIN_ICON_PX, index=area_measure.index)

    for (_, row), point in zip(gdf_with_data.iterrows(), centroids):
        html = make_table_popup_html(row, source_lookup)
        size = icon_sizes[row.name]
        folium.Marker(
            location=[point.y, point.x],
            icon=folium.DivIcon(
                html=make_graph_icon_html(size),
                icon_size=(size, size),
                icon_anchor=(size / 2, size / 2),
            ),
            popup=folium.Popup(html, max_width=260),
        ).add_to(m)

    # --- Page title -------------------------------------------------------------
    page_title = f"PyPSA-Earth-Status health ({year_label})"
    m.get_root().title = page_title
    title_html = f"""
    <div style="
        position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
        z-index: 1000; background: rgba(255,255,255,0.9); padding: 8px 20px;
        border-radius: 6px; font-family: sans-serif; font-size: 18px; font-weight: 600;
        box-shadow: 0 1px 4px rgba(0,0,0,0.3);
    ">
        {page_title}
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    m.save(OUTPUT_HTML)


if __name__ == "__main__":
    main()
