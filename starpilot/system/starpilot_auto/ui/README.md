# Starpilot Auto UI ownership

The car screen owns its screens here. `settings.py` is its settings shell;
`settings_panels/` owns the Device, Network, Bluetooth, Software, Developer, Toggles and StarPilot
panel layouts, including the Aether tiles, breadcrumbs and icons. Simplify or
rearrange these files without editing `selfdrive/ui/layouts/settings/`, which
belongs to the native device UI. `starpilot_settings.py`, `navigation.py` and
`offline_maps.py` compose the car-specific navigation pages.

Settings still write the same Params and use the same backend services. Changing
a setting can therefore affect the device's behavior; changing a car panel's
layout must not alter the native screen. Fonts, primitive widgets, rendering
utilities, network/Bluetooth managers and stable settings route types remain
shared. Pairing reuses the QR/auth lifecycle with car-owned drawing methods.

`nav_map.py` is the car map renderer. Its tests live alongside the other car UI
tests in `../tests/`. Main and onroad factories select car widgets before child
registration, rather than constructing and replacing native widgets.
