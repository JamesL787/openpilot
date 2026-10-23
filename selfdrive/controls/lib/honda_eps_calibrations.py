"""H020 PTM calibration: firmware fields verified; vehicle fields remain inferred pending H020 rlogs.

Do not label the Civic sibling's load, rack or timing as measured on the H020.
"""
from dataclasses import replace
from opendbc.sunnypilot.car.honda.h020_builds import PTM_BUILDS
from openpilot.selfdrive.controls.lib.honda_eps_firmware_ff import ColumnLoadModel, EpsFirmwareCalibration, computed_r6
from openpilot.selfdrive.controls.lib.honda_eps_h020_geometry import PROFILE
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import CIVIC_TGG_A120_RACK

R6_CENTRE, R6_BP, R6_GAIN = computed_r6(PROFILE)
# TGG-A120 donor: measured on its owner's routes 0000000b-00000010 (73 min).
# Transferred in firmware-output units; inferred on H020, including donor bias/roll terms.
H020_LOAD = ColumnLoadModel(k0=-15.67, k1=-0.157, c=-5.449, friction=-388.8, bias=75.77, kroll=-0.6084)
H020 = EpsFirmwareCalibration(
  name="civic_tea_h020",
  e4_per_output=3840.0,
  r5_key_bp=(0, 226, 311, 495, 656, 887, 1108, 1552, 1774), r5_v=(0, 1926, 4938, 8455, 12036, 15926, 20138, 26955, 30000), key_clamp=1663,
  envelope_bp=(0, 50, 100, 150, 200, 240, 300, 321, 400), envelope_v=(1774, 1774, 1774, 1774, 1774, 1552, 1219, 1108, 1108),
  kp_key_bp=(3, 173, 441, 665, 887, 1104, 1317, 1610, 1774), kp_v=(117, 148, 184, 220, 245, 257, 263, 265, 265),
  r6_per_deg_s=R6_CENTRE, r6_angle_bp=R6_BP, r6_angle_gain=R6_GAIN,
  load=H020_LOAD, p_scale=(1.15, 1.25, 1.15), i_scale=(0.75, 0.95, 1.0),
  rack=CIVIC_TGG_A120_RACK,  # TGG yaw-fitted donor; inferred on H020
  cmd_delay_s=0.0, cmd_delay_highway_s=0.0, default_on=False,
)

# No delay schedule is injected into res/modeld: its plan floor and timing differ from the source branch.
CALIBRATION_PROVENANCE = {
  "firmware_tables": "H020 PTM image, row 0, X 0x13794, R5 0x13812, P X/Y 0x13AE2/0x13B60",
  "live_row": "firmware: all five searched variant records at 0x4B418 + n*0x59 have selector byte +0x0F == 0",
  "r6": "firmware-derived from H020 Table A and NORM1650; not measured on H020",
  "column_load": "transferred: TGG-A120 owner routes 83ccc6a9a4e14d0b/0000000b-00000010; measured on TGG, inferred on H020",
  "rack": "transferred: TGG-A120 yaw-fitted rack; A/B tables match H020 byte-for-byte; mechanical gearing remains a donor assumption",
  "residual_pid": "transferred: TGG-A120/Civic Bosch four-point base PID plus its P/I trims; not measured on H020",
  "command_delay": "none added: res plan/model pipeline unchanged, pending H020 timing measurement",
  "model_delay": "existing res model pipeline unchanged",
  "validation": "offline only; no H020 route or vehicle validation available",
  "pre_table_shaping": "unity assumed by the forward model; H020 blend inputs/gate flags remain unverified",
  "command_map": "original H020 PTM row retained; R5/key slope 35.435 on key 226-311 versus 18.04 linear reference; residual PID gain not validated",
}

# Rev-b maps are extracted from the verified generated image, not borrowed blindly from the TGG axes.
H020_REVB = replace(
  H020, name="civic_tea_h02b_tgg_claritylimits",
  r5_key_bp=(0, 226, 311, 495, 656, 887, 1108, 1552, 1774),
  r5_v=(0, 3818, 5258, 8378, 11099, 15003, 18747, 26253, 30002),
  kp_key_bp=(0, 237, 473, 709, 946, 1182, 1419, 1655, 1892),
  kp_v=(117, 148, 184, 220, 245, 257, 263, 265, 265),
  envelope_bp=(0, 50, 100, 150, 200, 260, 300, 350, 400),
  envelope_v=(1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330, 1330),
)

REQUIRED_PTM_BUILDS = PTM_BUILDS


def calibration_for_build(build_id):
  profile = PTM_BUILDS[build_id]["profile"]
  return {"legacy": H020, "revb-tgg-claritylimits": H020_REVB}[profile]


def provenance_for_build(build_id):
  profile = calibration_for_build(build_id)
  return {**CALIBRATION_PROVENANCE, "profile": profile.name, "build": PTM_BUILDS[build_id],
          "command_map": (CALIBRATION_PROVENANCE["command_map"] if profile is H020 else
                          "rev-b: corrected TGG response resampled on native H020 knots; Clarity envelope and limits; offline ROM execution checked"),
          "firmware_tables": (CALIBRATION_PROVENANCE["firmware_tables"] if profile is H020 else
                              "H02B generated image: command X/Y 0x13794/0x13812, P X/Y 0x13AE2/0x13B60; Clarity envelope at 0x135E4/0x13662")}


EPS_FIRMWARE_CALIBRATIONS = {
  "39990-TEA-H020": (("HONDA_CIVIC_BOSCH",), H020),
  "39990-TEA-H02B": (("HONDA_CIVIC_BOSCH",), H020_REVB),
}
