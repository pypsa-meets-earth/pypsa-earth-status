<!--
SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->

# Release notes

## Upcoming release

### New Features and Major Changes

* [Add multi-scenario health status validation reports with ember dataset source PR #61](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/61)

* [Decompose clean_data into carrier-source-specific rules PR #47](https://github.com/SPSUnipi/pypsa2smspp/pull/47)

* [Drop pypsa-earth submodule PR #46](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/46)

* [Add an inventory for data sources available for validation PR #32](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/32)

* [Add `validate_cross_border_capacity` to `network_validation` config so cross-border capacity checks can be disabled when building network validation GeoJSON outputs PR #36](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/33)

* [Add functionality to plot OSM electrical grid network plus circuit values and csv export of osm grid line voltages and their lengths PR #38](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/38)

### Minor Changes and bug-fixing

* [Link year and country parameters to `build_reference_statistics` rule PR #58](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/58)

* [Add Read the Docs badge to README.md PR #35](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/35)

* [Handle empty networks and make validation plots robust to missing data PR #34](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/34)

## Version v0.0.1 - Initial Release

### New Features and Major Changes

* [Include comparison and plotting features PR #1](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/1)
* [Include generation of geojson for network validation PR #3](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/3)
* [Finalize workflow, visualization, add CI and documentation PR #6](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/6)
* [Add documentation with MkDocs style PR #20](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/20)

### Minor Changes and bug-fixing

* [Add PR template PR #25](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/25)
* [Improve README.md PR #27](https://github.com/pypsa-meets-earth/pypsa-earth-status/pull/27)


## Release Process

* Checkout a new release branch ``git checkout -b release-v0.x.x``.

* Finalise release notes at ``doc/release_notes.md``.

* Update version number in ``config.yaml``.

* Open, review and merge pull request for branch ``release-v0.x.x``.
  Make sure to close issues and PRs or the release milestone with it (e.g. closes #X).
  Run ``pre-commit run --all`` locally and fix any issues.

* Update and checkout your local `main` and tag a release with ``git tag v0.x.x``, ``git push``, ``git push --tags``. Include release notes in the tag message using Github UI.

* Send announcement on the `PyPSA-Earth Discord channel <https://discord.gg/AnuJBk23FU>`_.
