"""Personal branch: wide-FOV students carry their own camera geometry (ONNX model_geometry metadata)."""
import json
import unittest

import numpy as np

from openpilot.common.transformations.model import (MEDMODEL_CY, MEDMODEL_INPUT_SIZE, medmodel_fl, model_frame_corrections,
                                                    sbigmodel_fl)


class TestModelGeometry(unittest.TestCase):
  def test_stock_geometry_needs_no_correction(self):
    self.assertIsNone(model_frame_corrections(None))
    stock = {'road': [medmodel_fl, 0.5 * MEDMODEL_INPUT_SIZE[0], MEDMODEL_CY],
             'wide': [sbigmodel_fl, 0.5 * MEDMODEL_INPUT_SIZE[0], 0.5 * (256 + MEDMODEL_CY)]}
    for geometry in (stock, json.dumps(stock)):
      road, wide = model_frame_corrections(geometry)  # ty: ignore[not-iterable]
      np.testing.assert_allclose(road, np.eye(3), atol=1e-5)
      np.testing.assert_allclose(wide, np.eye(3), atol=1e-5)

  def test_student_geometry_maps_its_centre_to_the_stock_frame(self):
    # The G1b students' metadata: road 768x448 at fl 910, wide at fl 455.
    road, _ = model_frame_corrections({'road': [910.0, 384.0, 239.6], 'wide': [455.0, 384.0, 343.8]})  # ty: ignore[not-iterable]
    centre = road @ np.array([384.0, 239.6, 1.0])  # the student's principal point lands on the stock one
    np.testing.assert_allclose(centre[:2] / centre[2], [0.5 * MEDMODEL_INPUT_SIZE[0], MEDMODEL_CY], atol=1e-3)

  def test_compile_metadata_keeps_geometry(self):
    from types import SimpleNamespace
    from unittest.mock import patch
    from openpilot.starpilot.models import compile as compile_module
    geometry = '{"road": [910.0, 384.0, 239.6], "wide": [455.0, 384.0, 343.8]}'

    class Parser:
      def __init__(self, *args, **kwargs):
        self.reader = SimpleNamespace(len=1, skip_field=lambda wire_type: None)
        self.entries = iter([{'key': 'output_slices', 'value': 'gASVIAAAAAAAAAB9lIwHb3V0cHV0c5SMCGJ1aWx0aW5zlIwFc2xpY2WUk5RLAEsCToeUUpRzLg=='},
                             {'key': 'model_geometry', 'value': geometry}])
      def _parse_message(self, length): return [(14, 2), (14, 2)]
      def _parse_StringStringEntryProto(self): return next(self.entries)

    runner = SimpleNamespace(graph_inputs={'new_img': SimpleNamespace(shape=(2, 6, 224, 384))})
    with patch('tinygrad.nn.onnx.OnnxPBParser', Parser):
      metadata = compile_module.make_metadata_dict('student.onnx', runner)
    self.assertEqual(metadata['model_geometry'], geometry)
