from openpilot.starpilot.common import connect_server
from openpilot.starpilot.common.connect_server import sync_konik_dongle_id


class FakeParams:
  def __init__(self, **kw):
    self.d = dict(kw)

  def get(self, key, *a, **k):
    return self.d.get(key)

  def put(self, key, val, *a, **k):
    self.d[key] = val


class TestSyncKonikDongleId:
  def test_unreachable_server_leaves_konik_id_unset(self, mocker):
    mocker.patch.object(connect_server, "use_konik_server", return_value=True)
    reg = mocker.patch.object(connect_server, "register", return_value=None)
    params = FakeParams(DongleId="stock123", StockDongleId="stock123")
    sync_konik_dongle_id(params)
    reg.assert_called_once_with(show_spinner=True, register_konik=True)
    assert params.get("KonikDongleId") is None
    assert params.get("DongleId") == "stock123"

  def test_registered_id_is_adopted(self, mocker):
    mocker.patch.object(connect_server, "use_konik_server", return_value=True)
    mocker.patch.object(connect_server, "register", return_value="konik456")
    params = FakeParams(DongleId="stock123", StockDongleId="stock123")
    sync_konik_dongle_id(params)
    assert params.get("KonikDongleId") == "konik456"
    assert params.get("DongleId") == "konik456"
