from openpilot.system.hardware.tici import amplifier
from openpilot.system.hardware.tici.amplifier import Amplifier, CONFIGS, config_key


class TestAmplifierConfig:
  def test_tici_uses_tizi_registers(self, mocker):
    mocker.patch.object(amplifier.os.path, "exists", return_value=False)
    assert config_key("tici") == "tizi"
    assert config_key("tizi") == "tizi"

  def test_flag_restores_tici_registers(self, mocker):
    mocker.patch.object(amplifier.os.path, "exists", return_value=True)
    assert config_key("tici") == "tici"

  def test_initialize_writes_tizi_set(self, mocker):
    mocker.patch.object(amplifier.os.path, "exists", return_value=False)
    written = mocker.patch.object(Amplifier, "set_configs", return_value=True)
    assert Amplifier().initialize_configuration("tici")
    cfgs = written.call_args[0][0]
    assert all(c in cfgs for c in CONFIGS["tizi"])
    assert not any(c in cfgs for c in CONFIGS["tici"] if c not in CONFIGS["tizi"])
