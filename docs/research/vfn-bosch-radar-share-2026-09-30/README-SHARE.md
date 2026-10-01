# Bosch Radar Investigation Package

This package contains the current Honda Bosch radar reverse-engineering and
longitudinal-control investigation artifacts.

## Included

- Investigation findings and replay reports
- Candidate patches and design notes
- Replay/evaluation scripts
- JSON analysis outputs
- Relative-observer experiments
- Raw route logs are intentionally omitted from this share package.

## Packaging notes

- Older ZIP bundles were not nested because their contents are already present
  here and nesting them would duplicate data.
- macOS metadata, caches, and temporary files were omitted.
- Local usernames, home-directory paths, and personal identifiers were removed
  from text artifacts where present.
- Raw route logs were omitted at the request of the recipient.
- CSV analysis outputs were omitted at the request of the recipient.

This is an analysis artifact bundle, not a complete openpilot source checkout.
