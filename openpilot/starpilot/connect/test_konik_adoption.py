import base64

from openpilot.starpilot.connect import provider as p
from openpilot.starpilot.connect.konik_adoption import adopt_vfn_konik_identity

KONIK, COMMA = 'aa72d9572459015c', '0123456789abcdef'


class ParamsFiles:
  """vfn's keys are not in 7.0's registry, so the adoption reads and the test writes their files directly."""
  def __init__(self, root):
    self.root = root
    root.mkdir()

  def get_param_path(self, key):
    return str(self.root / key)

  def put(self, key, value, block=True):
    (self.root / key).write_bytes(value.encode() if isinstance(value, str) else value)

  def remove(self, key):
    (self.root / key).unlink(missing_ok=True)

  def get(self, key):
    path = self.root / key
    return path.read_text() if path.exists() else None


def setup(tmp_path, *, konik=True, key=True):
  # not named params: these are vfn's raw files, not registered 7.0 keys (the params-registry audit keys on that name)
  files = ParamsFiles(tmp_path / 'files')
  persist = tmp_path / 'persist'
  (persist / 'comma').mkdir(parents=True)
  (persist / 'comma' / 'dongle_id').write_text(COMMA + '\n')
  if key:
    (persist / 'comma' / 'id_rsa').write_text('FACTORY PRIVATE')
    (persist / 'comma' / 'id_rsa.pub').write_text('FACTORY PUBLIC')
  files.put('DongleId', KONIK if konik else COMMA)   # vfn kept DongleId on the active server's id
  if konik:
    files.put('KonikDongleId', KONIK)
    files.put('StockDongleId', COMMA)
  files.put('PrimeType', '0')
  return files, tmp_path / 'cloud', persist


def test_a_vfn_konik_device_keeps_its_konik_identity(tmp_path):
  params, root, persist = setup(tmp_path)
  assert adopt_vfn_konik_identity(params, root=root, persist=persist) == 'adopted'
  assert params.get('DongleId') == KONIK and params.get('ConnectProvider') == 'konik'
  assert params.get('PrimeType') is None
  assert p._read(root / 'konik' / 'identity.json') == {'private': 'FACTORY PRIVATE', 'public': 'FACTORY PUBLIC'}
  assert base64.b64decode(p._read(root / 'comma' / 'params.json')['DongleId']).decode() == COMMA
  # 7.0's boot then keeps Konik and the adopted id, and signs with the factory key
  p.activate_at_boot(params, root=root, boot=lambda: 'boot')
  assert params.get('DongleId') == KONIK
  assert p.configuration(root)['active'] == 'konik'


def test_runs_once(tmp_path):
  params, root, persist = setup(tmp_path)
  adopt_vfn_konik_identity(params, root=root, persist=persist)
  params.put('DongleId', 'fedcba9876543210')
  assert adopt_vfn_konik_identity(params, root=root, persist=persist) == 'existing'
  assert params.get('DongleId') == 'fedcba9876543210'


def test_a_comma_device_registers_with_konik_fresh(tmp_path):
  params, root, persist = setup(tmp_path, konik=False)
  assert adopt_vfn_konik_identity(params, root=root, persist=persist) == 'fresh'
  assert params.get('DongleId') is None   # the comma id is never sent to Konik
  assert not (root / 'konik' / 'identity.json').exists()   # Konik gets its own new key
  assert base64.b64decode(p._read(root / 'comma' / 'params.json')['DongleId']).decode() == COMMA


def test_without_the_factory_key_the_konik_id_cannot_be_kept(tmp_path):
  params, root, persist = setup(tmp_path, key=False)
  assert adopt_vfn_konik_identity(params, root=root, persist=persist) == 'fresh'
  assert params.get('DongleId') is None
