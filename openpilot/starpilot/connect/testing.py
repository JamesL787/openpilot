"""Night Star port: upstream's connect tests (athena, registration, uploader, logmessaged) exercise comma's path.
Night Star defaults to Konik, so those tests start from the provider state a comma build leaves: comma active."""
from openpilot.starpilot.connect import provider


def use_comma_provider():
  """Call inside the test's OpenpilotPrefix, before anything reads the provider (a started process included)."""
  provider._write(provider.root_path() / 'provider.json', {'active': 'comma', 'selected': 'comma', 'requestedBoot': ''})
