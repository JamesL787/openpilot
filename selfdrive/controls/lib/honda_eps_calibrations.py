"""H020 PTM calibration: firmware fields verified; vehicle fields remain inferred pending H020 rlogs.

Do not label the Civic sibling's load, rack or timing as measured on the H020.
"""
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
}

REQUIRED_PTM_BUILDS = {'20261011-trk4250': {'rwd_sha256': '9fcd18697938a741771aada9f6a1274b7eada6ae3dc3fb1d7d3771c61f97e537', 'image_sha256': '53427cbcd80e315c237d34f4e41bb7ef62ddedd6166d670e6352acb1d45587a1', 'tracker': 4250, 'file': '39990-TEA,H020-20261011-PTM-FF45-Norm1650-Trk4250-P117to265-D737-Pclamp7373-Dclamp1774-Out9000-SpeedClamp0-A280Flat.rwd'}, '20261011-trk3200': {'rwd_sha256': '56191940003ee614fe1bd18e0a1a67b946c40db5bf69a08109806eca408ade55', 'image_sha256': '5b3ba3061d9259abfa622beca1c460aad03b0e8af9422c3199b72a58749bc080', 'tracker': 3200, 'file': '39990-TEA,H020-20261011-PTM-FF45-Norm1650-Trk3200-P117to265-D737-Pclamp7373-Dclamp1774-Out9000-SpeedClamp0-A280Flat.rwd'}}

EPS_FIRMWARE_CALIBRATIONS = {"39990-TEA-H020": (("HONDA_CIVIC_BOSCH",), H020)}
