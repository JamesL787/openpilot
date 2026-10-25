"""TEA-H020 rev-b (reports 39990-TEA,H020) calibration.

Firmware fields are the tables of the delivered rev-b image (see tools/lateral/h020_firmware_evidence.json); the
vehicle fields (rack, residual trims, most of the column load) are the TGG-A120 donor's, measured on that car and INFERRED on the H020.
The column's stiffness (k0) and Coulomb friction are fitted on LiMing's first H020 route (00000004--a8cb4760f4).
"""
from openpilot.selfdrive.controls.lib.honda_eps_firmware_ff import ColumnLoadModel, EpsFirmwareCalibration, computed_r6
from openpilot.selfdrive.controls.lib.honda_eps_h020_geometry import PROFILE
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import CIVIC_TGG_A120_RACK

R6_CENTRE, R6_BP, R6_GAIN = computed_r6(PROFILE)
# TGG-A120 donor (routes 0000000b-00000010, 73 min, firmware-output units) with k0 and friction from the H020's own route:
# tools/lateral/fit_column_load.py --source e4 on 3.7 min gave k0 -7.83 (halves -5.2 / -7.9), friction -289 (-273 / -268), R^2 0.86;
# the TGG column is about twice as stiff (k0 -15.67) and 30% more frictional (-388.8). k1 and c agree with the TGG's and are kept.
# bias and kroll were not identifiable from that route (bias -25..+75, kroll -6.9..+2.7) and stay the TGG's. The fit assumes the rev-b image.
H020_LOAD = ColumnLoadModel(k0=-7.8, k1=-0.157, c=-5.449, friction=-285.0, bias=75.77, kroll=-0.6084)
H020 = EpsFirmwareCalibration(
  name="civic_tea_h020",
  e4_per_output=3840.0,
  # command map row 0 on H020's native key axis (0x13794 / 0x13812): the TGG rev-b response resampled onto it
  r5_key_bp=(0, 226, 311, 495, 656, 887, 1108, 1552, 1774), r5_v=(0, 3818, 5258, 8378, 11099, 15003, 18747, 26253, 30002), key_clamp=1663,
  # Clarity envelope (0x135E4 / 0x13662): 1774 to 100 km/h, 1330 from 130 km/h
  envelope_bp=(0, 50, 100, 150, 200, 260, 300, 350, 400), envelope_v=(1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330, 1330),
  # P row 0 (0x13AE2 / 0x13B60): the TGG rev-b P table
  kp_key_bp=(0, 237, 473, 709, 946, 1182, 1419, 1655, 1892), kp_v=(117, 148, 184, 220, 245, 257, 263, 265, 265),
  r6_per_deg_s=R6_CENTRE, r6_angle_bp=R6_BP, r6_angle_gain=R6_GAIN,
  load=H020_LOAD, p_scale=(1.15, 1.25, 1.15), i_scale=(0.75, 0.95, 1.0),
  rack=CIVIC_TGG_A120_RACK,
  cmd_delay_s=0.0, cmd_delay_highway_s=0.0, default_on=True,
)

# No delay schedule is injected into res/modeld: its plan floor and timing differ from the source branch.
CALIBRATION_PROVENANCE = {
  "firmware_tables": "rev-b image, row 0: command X/Y 0x13794/0x13812, P X/Y 0x13AE2/0x13B60, envelope 0x135E4/0x13662",
  "command_map": "TGG rev-b response resampled onto H020's native knots (max 2 R5 counts from the TGG image's own map)",
  "envelope": "Clarity limits (1330 from 130 km/h); the TGG rev-b row 0 envelope is flat 1774",
  "live_row": "firmware: all variant records select row 0",
  "r6": "firmware-derived from H020 Table A and NORM1650; not measured on H020",
  "column_load": "TGG-A120 donor, with k0 and friction fitted on LiMing route 00000004--a8cb4760f4 (one 3.7 min route); bias/kroll not identifiable",
  "rack": "transferred: TGG-A120 yaw-fitted rack; H020 A/B tables equal the C020/TGG ones; gearing is a donor assumption",
  "residual_pid": "transferred: TGG-A120/Civic Bosch four-point base PID and P/I trims; not measured on H020",
  "command_delay": "none added: res plan/model pipeline unchanged, pending H020 timing measurement",
  "pre_table_shaping": "unity assumed by the forward model; H020 blend inputs/gate flags unverified",
  "validation": "offline only; no H020 route or vehicle validation",
}

# keyed by the normalized EPS string ('-' for ','), as in the source branch
EPS_FIRMWARE_CALIBRATIONS = {"39990-TEA-H020": (("HONDA_CIVIC_BOSCH",), H020)}
