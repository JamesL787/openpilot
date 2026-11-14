import contextlib
import importlib.util
import io
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import check_rwd  # noqa: E402
from rwd_format.x5a import x5a  # noqa: E402


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Negative(Exception):
    pass


class Timeout(Exception):
    pass


def dependencies():
    uds = types.ModuleType('opendbc.car.uds')
    uds.UdsClient = Mock()
    uds.NegativeResponseError = Negative
    uds.MessageTimeoutError = Timeout
    for name in ('SESSION_TYPE', 'ACCESS_TYPE', 'ROUTINE_CONTROL_TYPE', 'ROUTINE_IDENTIFIER_TYPE',
                 'DATA_IDENTIFIER_TYPE', 'RESET_TYPE'):
        setattr(uds, name, types.SimpleNamespace(**{key: i for i, key in enumerate((
            'DEFAULT', 'EXTENDED_DIAGNOSTIC', 'PROGRAMMING', 'APPLICATION_SOFTWARE_IDENTIFICATION',
            'VIN', 'REQUEST_SEED', 'SEND_KEY', 'START', 'ERASE_MEMORY', 'CHECK_PROGRAMMING_DEPENDENCIES', 'HARD'))}))
    panda = types.ModuleType('panda')
    panda.Panda = Mock()
    structs = types.ModuleType('opendbc.car.structs')
    structs.CarParams = types.SimpleNamespace(SafetyModel=types.SimpleNamespace(elm327=1))
    return {'panda': panda, 'opendbc': types.ModuleType('opendbc'),
            'opendbc.car': types.ModuleType('opendbc.car'), 'opendbc.car.uds': uds,
            'opendbc.car.structs': structs, 'tqdm': types.SimpleNamespace(tqdm=Mock())}


def image(length=0x4c000, key=b'\x01\x02\x03', ids=1, secrets=1):
    inverse = {v: k for k, v in check_rwd.DECRYPT_LOOKUP.items()}
    payload = bytes([inverse[0]]) * length
    # Six headers: target ECU, matching software ID, seed secret, encryption key.
    header = (b'\x00\x00\x01\x01\x30' + bytes([ids]) + b'\x01A' * ids +
              bytes([secrets]) + (b'\x06' + b'\x00' * 6) * secrets + b'\x01\x03' + key)
    body = b'\x5a\x0d\x0a' + header + struct.pack('!II', 0x10000, length) + payload
    return body + struct.pack('<I', sum(body) & 0xffffffff)


def rom_crc_image(software_id=b'39990-TJB,A220', start=0xc000, length=0x74000, stale=False):
    """A THR/TJB-shaped image whose checksums are right and ROM CRCs right unless stale."""
    app = bytearray(length)
    for region_start, region_end, slot in check_rwd.ROM_CRC_REGIONS:
        app[region_start - start + 7] = 0x5a  # some content to CRC
        crc = check_rwd.crc32_bzip2(app[region_start - start:region_end - start])
        app[slot - start:slot - start + 4] = struct.pack('!I', crc ^ (1 if stale else 0))
    for func, offset, _label in check_rwd.checksum_definitions(length):
        words = struct.unpack(f'!{offset // 2}H', app[:offset])
        app[offset:offset + 2] = struct.pack('!H', (sum(words) * (-1 if func else 1)) & 0xffff)
    inverse = {v: k for k, v in check_rwd.DECRYPT_LOOKUP.items()}
    header = (b'\x00\x00\x01\x01\x30\x01' + bytes([len(software_id)]) + software_id +
              b'\x01\x06' + b'\x00' * 6 + b'\x01\x03\x01\x02\x03')
    body = b'\x5a\x0d\x0a' + header + struct.pack('!II', start, length) + bytes(inverse[b] for b in app)
    return body + struct.pack('<I', sum(body) & 0xffffffff)


class ValidationTests(unittest.TestCase):
    def test_parser_rejects_malformed(self):
        good = image()
        for raw in (b'', b'\x5a', good[:12], good[:-6], good[:-1], good + b'x', b'\x31' + good[1:]):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                x5a(raw)

    def test_checker_and_cli(self):
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            good = Path(folder) / 'good.rwd'
            bad = Path(folder) / 'bad.rwd'
            unknown = Path(folder) / 'unknown.rwd'
            good.write_bytes(image())
            raw = bytearray(image())
            raw[-5] ^= 1
            raw[-4:] = struct.pack('<I', sum(raw[:-4]))
            bad.write_bytes(raw)
            unknown.write_bytes(image(8))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertTrue(check_rwd.check(good))
                self.assertFalse(check_rwd.check(bad))
                self.assertFalse(check_rwd.check(unknown))
            self.assertIn('too short', output.getvalue())
            for optimized in (False, True):
                bad.write_bytes(raw)
                command = [sys.executable] + (['-O'] if optimized else []) + [str(TOOLS / 'check_rwd.py')]
                self.assertEqual(subprocess.run(command + [str(good)], capture_output=True).returncode, 0)
                self.assertNotEqual(subprocess.run(command + [str(good), str(bad)], capture_output=True).returncode, 0)
                self.assertNotEqual(subprocess.run(command + [str(unknown)], capture_output=True).returncode, 0)
                bad.write_bytes(b'')
                self.assertNotEqual(subprocess.run(command + [str(bad)], capture_output=True).returncode, 0)

    def test_every_image_gets_the_standard_checks(self):
        raw = bytearray(image())
        raw[-5] ^= 1
        raw[-4:] = struct.pack('<I', sum(raw[:-4]))
        # Lengths and keys outside the TLA/Clarity images are still validated, not skipped.
        cases = ((image(), True), (image(0x1000), True), (image(key=b'xyz'), True),
                 (image(8), False), (image(0x1001), False), (bytes(raw), False),
                 (image(secrets=2), False), (image(ids=0, secrets=0), False), (b'', False))
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            path = Path(folder) / 'image.rwd'
            for raw, expected in cases:
                path.write_bytes(raw)
                with self.subTest(length=len(raw), expected=expected), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(check_rwd.check(path), expected)

    def test_thr_tjb_rom_crcs(self):
        # Odyssey THR and RDX TJB images must also carry valid runtime ROM CRCs;
        # other software IDs are not held to them.
        cases = ((rom_crc_image(), True), (rom_crc_image(b'39990-THR-A020'), True),
                 (rom_crc_image(stale=True), False), (rom_crc_image(b'39990-THR,A020', stale=True), False),
                 (rom_crc_image(start=0x4000), False), (rom_crc_image(b'39990-TLA-A040', stale=True), True))
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            path = Path(folder) / 'image.rwd'
            for raw, expected in cases:
                path.write_bytes(raw)
                with self.subTest(expected=expected), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(check_rwd.check(path), expected)
                if not expected:
                    self.assertTrue('ROM CRC failed' in output.getvalue() or 'THR/TJB image' in output.getvalue())

    def test_known_lengths_match_published_offsets(self):
        # Offsets the per-vehicle tables used before validation was generalized, including
        # the RDX TJB entry carried in the Honda PTM openpilot copy.
        known = {0x4c000: (0x4bf80, 0x4bffe), 0x6c000: (0x6bf80, 0x6bffe), 0x74000: (0x73f80, 0x73ffe)}
        for length, (sum_offset, negative_offset) in known.items():
            with self.subTest(length=hex(length)):
                self.assertEqual(check_rwd.checksum_definitions(length),
                                 [(0, sum_offset, "sum"), (1, negative_offset, "negative-sum")])
                with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
                    path = Path(folder) / 'image.rwd'
                    path.write_bytes(image(length))
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertTrue(check_rwd.check(path))

    def test_x31_bytes_and_validation(self):
        from rwd_format.x31 import x31
        headers = b''
        for identity in (ord('!'), ord('"'), ord('#'), ord('$'), ord('%'), ord('&')):
            delimiter = bytes([identity]) + b'\r\n'
            value = b'010203\r\n' if identity == ord('&') else b''
            headers += delimiter + value + delimiter
        body = b'1\r\n' + headers + b'\x00\x00' + bytes(128)
        raw = body + struct.pack('<I', sum(body))
        self.assertEqual(x31(raw).firmware_blocks, [{"start": 0, "length": 128}])
        for invalid in (b'', raw[:-5], raw[:-4] + bytes(4)):
            with self.assertRaises(ValueError):
                x31(invalid)

    def test_manual_flashing_blocks_unknown_and_malformed(self):
        for raw, flags in ((image(8), []), (b'', []), (image(secrets=2), [])):
            modules = dependencies()
            with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
                path = Path(folder) / 'image.rwd'
                path.write_bytes(raw)
                with patch.dict(sys.modules, modules), \
                     patch.object(sys, 'argv', ['eps-update.py', str(path), '--danger', *flags]), \
                     contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as status:
                    runpy.run_path(str(TOOLS / 'eps-update.py'), run_name='__main__')
                self.assertIn('Image validation failed', str(status.exception))
                modules['panda'].Panda.assert_not_called()

    def test_optimized_parser_checksum_and_length(self):
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            path = Path(folder) / 'bad.rwd'
            command = [sys.executable, '-O', '-c',
                       'from rwd_format.x5a import x5a; import sys; x5a(open(sys.argv[1], "rb").read())', str(path)]
            for raw in (image()[:-4] + b'\x00' * 4, image() + b'x'):
                path.write_bytes(raw)
                self.assertNotEqual(subprocess.run(command, cwd=TOOLS, capture_output=True).returncode, 0)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.deps = patch.dict(sys.modules, dependencies())
        self.deps.start()
        self.addCleanup(self.deps.stop)
        self.diag = load('eps_diag_test', 'eps-diag.py')
        self.panda = Mock()
        self.client = Mock()
        self.client.read_data_by_identifier.return_value = b'LIVE'

    def run_diag(self, args=(), sniff=False):
        with patch.object(self.diag, 'connect_panda', return_value=self.panda), \
             patch.object(self.diag, 'UdsClient', return_value=self.client), \
             patch.object(self.diag, 'passive_sniff', return_value={0: sniff}), \
             patch.object(self.diag, 'car_eps_fw_from_params', return_value='CACHED'), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = self.diag.main(['-b', '0', *args])
        return code, output.getvalue()

    def test_healthy_is_not_recovery(self):
        code, output = self.run_diag()
        self.assertEqual(code, 0)
        self.assertIn('EPS communication confirmed', output)
        self.assertIn('read live: LIVE', output)
        self.assertNotIn('try the flash again', output)
        self.assertNotIn('Recovery troubleshooting', output)
        self.client.diagnostic_session_control.assert_called_with(self.diag.SESSION_TYPE.DEFAULT)
        self.panda.close.assert_called_once()

    def test_negative_response_and_missing_id(self):
        self.client.tester_present.side_effect = Negative('unsupported')
        self.client.diagnostic_session_control.side_effect = Negative('unsupported')
        self.client.read_data_by_identifier.side_effect = Negative('unsupported')
        code, output = self.run_diag()
        self.assertEqual(code, 0)
        self.assertIn('software ID read=False', output)
        self.assertIn('Cached CarParams', output)
        self.assertIn('default session accepted=False', output)
        self.assertNotIn('stuck', output)
        self.panda.close.assert_called_once()

    def test_timeout_and_passive_only(self):
        self.client.tester_present.side_effect = Timeout()
        self.client.diagnostic_session_control.side_effect = Timeout()
        self.client.read_data_by_identifier.side_effect = Timeout()
        code, output = self.run_diag()
        self.assertEqual(code, 1)
        self.assertIn('not confirmed', output)
        self.assertNotIn('bricked', output)
        self.assertNotIn('Cleanup:', output)
        self.assertEqual(self.client.diagnostic_session_control.call_count, 2)  # default + extended, no cleanup
        self.assertEqual(self.run_diag(['--sniff-only'])[0], 1)
        self.assertEqual(self.run_diag(['--sniff-only'], sniff=True)[0], 0)

    def test_session_acceptance_is_not_id_success(self):
        self.client.tester_present.side_effect = Timeout()
        self.client.read_data_by_identifier.side_effect = Negative('ID unsupported')
        code, output = self.run_diag()
        self.assertEqual(code, 0)
        self.assertIn('default session accepted=True', output)
        self.assertIn('software ID read=False', output)
        self.assertIn('Cached CarParams', output)

    def test_scan_without_responses(self):
        self.client.tester_present.side_effect = Timeout()
        self.assertEqual(self.run_diag(['--scan'])[0], 1)
        self.panda.close.assert_called_once()

    def test_recovery_is_explicit(self):
        code, output = self.run_diag(['--recovery'])
        self.assertEqual(code, 0)
        self.assertIn('Recovery troubleshooting', output)
        self.assertNotIn('try the flash again', output)

    def test_connection_failure(self):
        with patch.object(self.diag, 'connect_panda', side_effect=OSError('USB unavailable')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.diag.main([]), 2)
        self.assertIn('check could not run', output.getvalue())

    def test_runtime_and_cleanup_failure(self):
        self.client.tester_present.side_effect = RuntimeError('USB lost')
        self.client.diagnostic_session_control.side_effect = RuntimeError('USB lost')
        self.panda.close.side_effect = RuntimeError('close failed')
        code, output = self.run_diag()
        self.assertEqual(code, 2)
        self.assertIn('Cleanup:', output)

    def test_scan_negative_response(self):
        self.client.tester_present.side_effect = Negative('unsupported')
        code, output = self.run_diag(['--scan'])
        self.assertEqual(code, 0)
        self.assertIn('not necessarily EPS', output)
        self.panda.close.assert_called_once()


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.flash = load('eps_flash_test', 'flash.py')

    def test_optional_check_preserves_target_and_recovery(self):
        for success in (True, False):
            with patch('builtins.input', side_effect=['1', 'q']), \
                 patch.object(self.flash.subprocess, 'run') as run, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.flash.post_flash_menu({}, 1, eps_addr=0x18da30f1, flash_succeeded=success)
            command = run.call_args.args[0]
            self.assertIn('Optional EPS communication sanity check', output.getvalue())
            self.assertEqual(command[2:6], ['-b', '1', '--addr', '0x18da30f1'])
            self.assertEqual('--recovery' in command, not success)

    def test_dry_run_requires_success_status_and_markers(self):
        markers = self.flash.REAL_CLIENT_MARKER + '\n' + self.flash.DRY_RUN_OK_MARKER
        for rc, text, accepted in ((0, markers, True), (1, markers, False),
                                   (0, self.flash.DRY_RUN_OK_MARKER, False),
                                   (0, self.flash.REAL_CLIENT_MARKER, False)):
            with patch.object(self.flash, 'run_and_tee', return_value=(rc, text)), \
                 patch.object(self.flash, 'exit_with_op_stopped', side_effect=SystemExit(1)), \
                 contextlib.redirect_stdout(io.StringIO()):
                if accepted:
                    self.flash.run_dry_run('test.rwd', 1, {}, 'test')
                else:
                    with self.assertRaises(SystemExit):
                        self.flash.run_dry_run('test.rwd', 1, {}, 'test')

    def test_main_preserves_failed_flash_status(self):
        for rc in (0, 1):
            with patch.object(sys, 'argv', ['flash.py']), \
                 patch.object(self.flash, 'find_images', return_value=['test.rwd']), \
                 patch.object(self.flash, 'car_eps_fw', return_value=None), \
                 patch.object(self.flash, 'validate', return_value=True), \
                 patch('builtins.input', side_effect=['1', 'yes', '', 'FLASH']), \
                 patch.object(self.flash, 'stop_openpilot'), \
                 patch.object(self.flash, 'resolve_bus', return_value=1), \
                 patch.object(self.flash, 'rwd_can_address', return_value=0x18da30f1), \
                 patch.object(self.flash, 'choose_dry_run', return_value=False), \
                 patch.object(self.flash, 'run_real_flash', return_value=rc), \
                 patch.object(self.flash, 'flash_failure_menu', return_value=rc), \
                 patch.object(self.flash, 'post_flash_menu') as menu, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exit_status:
                    self.flash.main()
                self.assertEqual(exit_status.exception.code, rc)
                self.assertEqual(menu.call_args.kwargs['flash_succeeded'], rc == 0)
                self.assertEqual('Firmware programming completed.' in output.getvalue(), rc == 0)

    def run_main_with_status(self, status):
        with patch.object(sys, 'argv', ['flash.py']), \
             patch.object(self.flash, 'find_images', return_value=['test.rwd']), \
             patch.object(self.flash, 'car_eps_fw', return_value=None), \
             patch.object(self.flash, 'validate', return_value=status), \
             patch('builtins.input', side_effect=['1', 'yes', '', 'FLASH']), \
             patch.object(self.flash, 'stop_openpilot') as stop, \
             patch.object(self.flash, 'resolve_bus', return_value=1), \
             patch.object(self.flash, 'rwd_can_address', return_value=0x18da30f1), \
             patch.object(self.flash, 'choose_dry_run', return_value=False), \
             patch.object(self.flash, 'run_real_flash', return_value=0) as flash, \
             patch.object(self.flash, 'post_flash_menu'), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_status:
            self.flash.main()
        return exit_status.exception.code, stop, flash

    def test_failed_image_is_refused_before_stopping_openpilot(self):
        code, stop, flash = self.run_main_with_status(False)
        self.assertIn('refusing to flash', code)
        stop.assert_not_called()
        flash.assert_not_called()

    def test_manual_flashing_has_no_checksum_bypass(self):
        # The removed flag must be rejected by argparse before any image or Panda is touched.
        modules = dependencies()
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            path = Path(folder) / 'image.rwd'
            path.write_bytes(image(8))
            with patch.dict(sys.modules, modules), \
                 patch.object(sys, 'argv', ['eps-update.py', str(path), '--danger', '--skip-checksum']), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err, \
                 self.assertRaises(SystemExit) as status:
                runpy.run_path(str(TOOLS / 'eps-update.py'), run_name='__main__')
            self.assertEqual(status.exception.code, 2)
            self.assertIn('--skip-checksum', err.getvalue())
            modules['panda'].Panda.assert_not_called()
        for name in ('eps-update.py', 'flash.py'):
            self.assertNotIn('skip_checksum', (TOOLS / name).read_text())

    def test_valid_image_never_skips_checksum(self):
        code, stop, flash = self.run_main_with_status(True)
        self.assertEqual(code, 0)
        flash.assert_called_once()
        self.assertNotIn('--skip-checksum', self.flash.run_eps_update('test.rwd', 1, danger=True))

    def test_eps_update_requires_panda_unless_mock(self):
        modules = dependencies()
        modules['panda'].Panda.side_effect = OSError('no panda')
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            path = Path(folder) / 'test.rwd'
            path.write_bytes(image())
            with patch.dict(sys.modules, modules), \
                 patch.object(sys, 'argv', ['eps-update.py', str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as status:
                runpy.run_path(str(TOOLS / 'eps-update.py'), run_name='__main__')
        self.assertIn('Could not open the Panda', str(status.exception))
        self.assertNotIn('Using mock client', output.getvalue())

    def test_eps_update_rejects_unusable_block_length(self):
        modules = dependencies()
        client = Mock()
        client.read_data_by_identifier.return_value = b'A'
        client.security_access.return_value = b'\x00\x01'
        client.request_download.return_value = 2
        # A plain namespace, so eps-update's mock-client guard doesn't trip.
        modules['opendbc.car.uds'].UdsClient.return_value = types.SimpleNamespace(**{
            name: getattr(client, name) for name in ('read_data_by_identifier', 'security_access', 'tester_present',
            'diagnostic_session_control', 'routine_control', 'write_data_by_identifier', 'request_download', 'transfer_data')})
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            path = Path(folder) / 'test.rwd'
            path.write_bytes(image())
            with patch.dict(sys.modules, modules), \
                 patch.object(sys, 'argv', ['eps-update.py', str(path), '--danger']), \
                 patch('time.sleep'), contextlib.redirect_stdout(io.StringIO()) as output, \
                 self.assertRaises(SystemExit) as status:
                runpy.run_path(str(TOOLS / 'eps-update.py'), run_name='__main__')
        self.assertEqual(status.exception.code, 1)
        self.assertIn('unusable max block length', output.getvalue())
        client.transfer_data.assert_not_called()

    def test_eps_update_dry_run_no_traceback_or_erase(self):
        modules = dependencies()
        client = Mock()
        client.read_data_by_identifier.return_value = b'A'
        client.security_access.return_value = b'\x00\x01'
        modules['opendbc.car.uds'].UdsClient.return_value = types.SimpleNamespace(**{
            name: getattr(client, name) for name in ('read_data_by_identifier', 'security_access',
            'tester_present', 'diagnostic_session_control', 'routine_control', 'transfer_data')})
        with tempfile.TemporaryDirectory(dir=TOOLS / 'tests') as folder:
            path = Path(folder) / 'test.rwd'
            path.write_bytes(image())
            with patch.dict(sys.modules, modules), \
                 patch.object(sys, 'argv', ['eps-update.py', str(path)]), \
                 patch('time.sleep'), contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as status:
                    runpy.run_path(str(TOOLS / 'eps-update.py'), run_name='__main__')
                self.assertEqual(status.exception.code, 0)
        self.assertIn(self.flash.DRY_RUN_OK_MARKER, output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())
        client.routine_control.assert_not_called()
        client.transfer_data.assert_not_called()
        client.diagnostic_session_control.assert_called_with(modules['opendbc.car.uds'].SESSION_TYPE.DEFAULT)


if __name__ == '__main__':
    unittest.main()
