# Starpilot Auto settings

The independent car UI uses one section sidebar and a flat row of page tabs.
**All Pages** lists every page in the selected section. On narrow screens,
**Sections** opens the same navigation as a drawer. Back returns from a choice
or detail page before closing Settings.

| Section | Contents |
| --- | --- |
| Car Display | Layout, status slots, driving widgets, road/path appearance, visibility and metrics |
| Navigation | Routes, offline maps and map labels |
| Driving | General controls, gas/brake, personalities, speed limits, curve speed, drive modes and steering |
| Sounds | Volumes and alerts |
| Connections | Wi-Fi, Bluetooth pairing and Starpilot Auto connection controls |
| Vehicle | Vehicle identity and supported vehicle preferences |
| System | Device information, preferences, power, backups, maintenance, software and developer tools |

Galaxy exposes the Starpilot Auto enable switch, live connection controls, Layout
and Status Widgets controls, certificate setup and diagnostics at
`/#/settings/starpilot-auto`. The Connection section uses `starpilot_autod` for the
same Connect status, Car, Auto Connect, Link Type, Display, pairing, Setup Help
and Last Error settings as the comma menu. Layout and Status Widgets use the
same labels and settings as the car UI. Controls that do not apply to the
selected layout are hidden. Layout also holds Show Current Speed and the comma
display's sleep and wake choices; Status Widgets also places the status column
per layout (left or right, or between the driving view and the map when split).

Car-only display preferences live in the existing `car_screen.json`, separate
from comma display preferences. Both interfaces merge partial updates under a
shared file lock before saving atomically. Legacy driving and device controls
retain their existing Params and action handlers; shared pages identify their
scope beneath the tabs.

The car's responsive row renderer measures text before placing controls. Values
stack below labels on narrow screens, toggles retain a reserved control column,
and long pages scroll vertically. Dialog bodies scroll independently of their
confirmation buttons. Bluetooth and Wi-Fi retain their existing managers,
pairing prompts, authentication and connection flows.

## Validation

Run native checks through the isolated host runtime on macOS:

```sh
./dev pytest -q -c /dev/null --confcutdir=starpilot/system/starpilot_auto/tests \
  starpilot/system/starpilot_auto/tests/test_settings_redesign.py \
  starpilot/system/starpilot_auto/tests/test_car_ui_screens.py \
  starpilot/system/starpilot_auto/tests/test_ui_ownership.py \
  starpilot/system/starpilot_auto/tests/test_offline_maps_panel.py \
  starpilot/system/starpilot_auto/tests/test_car_ui_nav.py
node --test \
  starpilot/system/the_galaxy/tests/test_starpilot_auto_connection_panel.mjs \
  starpilot/system/the_galaxy/tests/test_starpilot_auto_car_screen_panel.mjs
```

Run the Galaxy API tests in a separate Python process: their existing import
stubs conflict with the native UI suite when collected together.

The browser test uses synthetic API responses and local assets, with no device
connection. It checks widths from 320 to 1920 pixels, navigation, layout
dependencies, saving and rollback. Supply `PLAYWRIGHT_MODULE` and
`CHROMIUM_EXECUTABLE` if Playwright or Chromium are not available by default:

```sh
node starpilot/system/the_galaxy/tests/test_starpilot_auto_settings_dom.cjs
```

Native geometry tests cover short landscape, wide landscape and portrait
screens. Physical receiver pairing, touch scaling and on-device performance
still require a hardware check.
