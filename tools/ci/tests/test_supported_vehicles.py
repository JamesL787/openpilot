import unittest

from opendbc.car import supported_brands
from opendbc.car.values import BRANDS
from tools.ci import supported_vehicles
from tools.ci.run_host_tests import pytest_files
from tools.ci.run_vehicle_tests import ROOT, supported_targets_for, targets_for
from tools.ci.supported_vehicles import supported, unsupported_brand

SUITES = ("aol-lifecycle", "interfaces", "safety-debug", "safety-release")


class TestSupportedVehicles(unittest.TestCase):
  def test_ci_scope_is_the_brand_list_the_car_code_enforces(self):
    self.assertEqual(supported_vehicles.SUPPORTED_BRANDS, supported_brands.SUPPORTED_BRANDS)

  def test_every_registered_brand_is_either_supported_or_named_as_unsupported(self):
    registered = {brand.__module__.split(".")[2] for brand in BRANDS}
    self.assertEqual(registered - {"mock"},
                     supported_vehicles.SUPPORTED_BRANDS | supported_vehicles.UNSUPPORTED_BRAND_DIRECTORIES)

  def test_honda_and_acura_always_run(self):
    for target in ("opendbc_repo/opendbc/car/honda/tests/test_bosch_longitudinal.py",
                   "opendbc_repo/opendbc/car/honda/tests/test_gm_shaped_name.py",
                   "opendbc_repo/opendbc/safety/tests/test_honda.py",
                   "openpilot/starpilot/car/honda/tests/test_anything.py",
                   "openpilot/selfdrive/car/tests/test_honda_aol.py",
                   "openpilot/starpilot/tests/test_acura_and_toyota_compared.py"):
      with self.subTest(target=target):
        self.assertTrue(supported(target))

  def test_other_brands_are_recognised_by_directory_and_by_name(self):
    for target, word in (("opendbc_repo/opendbc/car/toyota/tests/test_matrix_filter.py", "toyota"),
                         ("openpilot/starpilot/car/gm/tests/test_gear_events.py", "gm"),
                         ("opendbc_repo/opendbc/safety/tests/test_hyundai_canfd.py", "hyundai"),
                         ("opendbc_repo/opendbc/safety/tests/test_body.py", "body"),
                         ("opendbc_repo/opendbc/bluepilot_lateral/tests/test_core_imports.py", "bluepilot"),
                         ("openpilot/starpilot/aol/tests/test_hkg_angle_limit_warning.py", "hkg"),
                         ("openpilot/selfdrive/car/tests/test_subaru_stock_startup.py", "subaru"),
                         ("opendbc_repo/opendbc/safety/tests/test_toyota.py::TestToyotaStockLongitudinalTorque", "toyota")):
      with self.subTest(target=target):
        self.assertEqual(unsupported_brand(target), word)

  def test_brand_neutral_tests_keep_running(self):
    for target in ("opendbc_repo/opendbc/car/tests/test_car_interfaces.py",
                   "opendbc_repo/opendbc/car/tests/test_supported_brands.py",
                   "opendbc_repo/opendbc/safety/tests/test_defaults.py::TestNoOutput",
                   "openpilot/selfdrive/controls/tests/test_longcontrol.py",
                   "openpilot/system/body/tests/test_not_a_car_brand.py",
                   "tools/ci/tests/test_supported_vehicles.py"):
      with self.subTest(target=target):
        self.assertTrue(supported(target))

  def test_brand_named_cases_inside_neutral_files_are_left_out(self):
    module = "openpilot/starpilot/aol/tests/test_panda_inventory.py"
    self.assertTrue(supported(module))
    self.assertEqual(unsupported_brand(module + "::test_ev6_cancel_rejects_changed_identity_and_continuity[3]"), "ev6")
    self.assertEqual(unsupported_brand(module + "::TestInventory::test_gm_main_response"), "gm")
    self.assertTrue(supported(module + "::test_inventory_keeps_order[toyota-first]"))
    self.assertTrue(supported(module + "::test_honda_matches_gm_layout"))
    self.assertEqual(supported_vehicles.unsupported_test_name("test_volt_cc_engagement"), "volt")
    self.assertIsNone(supported_vehicles.unsupported_test_name("test_main_response"))

  def test_neutral_named_files_that_only_drive_other_brands_are_listed_and_exist(self):
    for file, brand in supported_vehicles.UNSUPPORTED_FILES.items():
      with self.subTest(file=file):
        self.assertTrue((ROOT / file).is_file())
        self.assertEqual(unsupported_brand(file), brand)

  def test_vehicle_suites_keep_honda_and_drop_only_unsupported_brands(self):
    for suite in SUITES:
      with self.subTest(suite=suite):
        everything, selected = targets_for(suite), supported_targets_for(suite)
        self.assertEqual(selected, [target for target in everything if supported(target)])
        self.assertTrue(any("honda" in target for target in selected))
        self.assertFalse([target for target in everything if "/honda/" in target and target not in selected])
        self.assertFalse([target for target in selected if "/car/toyota/" in target or "/car/gm/" in target])

  def test_custom_pytest_catalog_leaves_out_other_brands(self):
    selected = pytest_files()
    self.assertTrue(selected)
    self.assertEqual([path for path in selected if not supported(path)], [])


if __name__ == "__main__":
  unittest.main()
