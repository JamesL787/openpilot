"""Reproducible offline image construction/execution; no hardware/network interfaces."""

import hashlib
import json
from pathlib import Path
import struct
import zipfile

import numpy as np
import pytest

from openpilot.tools.eps.h020_revb import build as builder, rwd_codec as codec, verify
from openpilot.tools.eps.h020_revb.sh2a import CPU, EmuError
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import H020, H020_REVB, REQUIRED_PTM_BUILDS, calibration_for_build

FOLDER = Path(__file__).resolve().parents[1] / 'eps/h020_revb'


@pytest.fixture(scope='module')
def inputs():
  manifest = json.loads((FOLDER / 'SOURCES.json').read_text())
  with zipfile.ZipFile(FOLDER / 'testdata/inputs.zip') as archive:
    data = {name: archive.read(name) for name in manifest['inputs']}
  assert all(hashlib.sha256(value).hexdigest() == manifest['inputs'][name]['sha256'] for name, value in data.items())
  return data


@pytest.fixture(scope='module')
def candidates(inputs):
  return {
    tracker: builder.build(
      inputs['stock.bin'], inputs[f'parent-{tracker}.bin'], inputs[f'parent-{tracker}.rwd'], inputs['tgg-revb.bin'], tracker, inputs['clarity.bin'], 'tgg'
    )
    for tracker in [4250, 3200]
  }


@pytest.mark.parametrize('tracker', [4250, 3200])
def test_revb_exact_bytes_limits_calibration_and_provenance(inputs, candidates, tracker):
  image, rwd, report = candidates[tracker]
  result = verify.structural(image, rwd, inputs[f'parent-{tracker}.bin'], inputs['stock.bin'], inputs['tgg-revb.bin'], inputs['clarity.bin'], 'tgg')
  assert result['changed_bytes'] == 270
  build = REQUIRED_PTM_BUILDS[report['build_id']]
  assert build['image_sha256'] == builder.sha(image) and build['rwd_sha256'] == builder.sha(rwd)
  cal = calibration_for_build(report['build_id'])
  assert cal is H020_REVB and cal is not H020
  for key, values in report['row0'].items():
    assert tuple(values) == getattr(cal, key)
  assert cal.load is H020.load and cal.rack is H020.rack
  for name in ['r6_per_deg_s', 'r6_angle_bp', 'r6_angle_gain', 'p_scale', 'i_scale', 'cmd_delay_s', 'cmd_delay_highway_s', 'key_clamp']:
    assert getattr(cal, name) == getattr(H020, name)
  assert cal.r5_v != H020.r5_v and cal.kp_key_bp != H020.kp_key_bp
  for kmh in range(201):
    clarity_limit = min(1663, np.interp(kmh * 2, builder.words(inputs['clarity.bin'], 0x13660), builder.words(inputs['clarity.bin'], 0x136DE)))
    assert cal.key_ceiling(kmh / 3.6) == pytest.approx(clarity_limit)
  assert builder.words(image, 0x13890, 3) == (7373, 1774, 9000)
  assert struct.unpack_from('>H', image, 0x1378E)[0] == tracker
  assert codec.parse(rwd)[2] == image[0x4000:0x50000]


def test_revb_actual_rom_map_pd_wrapper_and_target_response(candidates, inputs):
  result = verify.execute(candidates[4250][0], inputs['tgg-revb.bin'], 'tgg')
  assert result['max_R5_difference_counts'] == 2
  assert result['target_comparison_keys'] == 3327 and len(result['rows']) == 7
  assert all(row == {'map_cases': 3605, 'PD_cases': 635, 'full_wrapper_cases': 200} for row in result['rows'].values())


@pytest.mark.parametrize('tracker', [4250, 3200])
def test_revb_actual_loader_accepts_range_and_decrypts_all_bytes(candidates, tracker):
  assert verify.loader_checks(candidates[tracker][0])['loader_decrypt_0x50a00_cases'] == 256


def test_revb_trackers_differ_only_in_tracker_and_checksums(candidates):
  diff = {i for i, (a, b) in enumerate(zip(candidates[4250][0], candidates[3200][0], strict=True)) if a != b}
  assert diff <= {0x1378E, 0x1378F, 0x4FF80, 0x4FF81, 0x4FFFE, 0x4FFFF}


@pytest.mark.parametrize('key', ['stock.bin', 'parent-4250.bin', 'parent-4250.rwd', 'tgg-revb.bin', 'clarity.bin'])
def test_revb_builder_refuses_unpinned_inputs(inputs, key):
  broken = dict(inputs)
  broken[key] = bytes([broken[key][0] ^ 1]) + broken[key][1:]
  with pytest.raises(ValueError, match='unexpected'):
    builder.build(broken['stock.bin'], broken['parent-4250.bin'], broken['parent-4250.rwd'], broken['tgg-revb.bin'], 4250, broken['clarity.bin'], 'tgg')


def test_revb_builder_refuses_unknown_response(inputs):
  with pytest.raises(ValueError, match='unknown response'):
    builder.build(inputs['stock.bin'], inputs['parent-4250.bin'], inputs['parent-4250.rwd'], inputs['tgg-revb.bin'], 4250, inputs['clarity.bin'], 'unknown')


@pytest.mark.parametrize('kind', ['truncated', 'checksum', 'extra-block', 'header'])
def test_revb_rwd_parser_refuses_invalid_container(inputs, kind):
  raw = inputs['parent-4250.rwd']
  if kind == 'truncated':
    raw = raw[:20]
  elif kind == 'checksum':
    raw = raw[:-1] + bytes([raw[-1] ^ 1])
  elif kind == 'extra-block':
    raw += b'\0'
  else:
    raw = b'BAD' + raw[3:]
  with pytest.raises(ValueError):
    codec.parse(raw)


def test_revb_strict_emulator_refuses_unknown_opcode_rom_write_and_unmodeled_memory(inputs):
  c = CPU(inputs['stock.bin'])
  with pytest.raises(EmuError, match='write to ROM'):
    c.set16(0x4000, 0)
  with pytest.raises(EmuError, match='outside modeled memory'):
    c.set16(0xFFFF0000, 0)
  with pytest.raises(EmuError):
    c.call(0x7FFF2)


def test_revb_cli_refuses_overwriting_existing_output(tmp_path, monkeypatch):
  import sys

  monkeypatch.setattr(sys, 'argv', ['build.py', '--inputs', str(tmp_path / 'unused'), '--output', str(tmp_path), '--response', 'tgg'])
  with pytest.raises(ValueError, match='output directory already exists'):
    builder.main()
