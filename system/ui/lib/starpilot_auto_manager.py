import threading
import time

from openpilot.starpilot.system.starpilot_auto.protocol import StarpilotAutoClient


class StarpilotAutoManager:
  """Polls starpilot_autod off the render thread; every action runs in a worker."""

  def __init__(self, client: StarpilotAutoClient | None = None):
    self._client = client or StarpilotAutoClient()
    self._lock = threading.Lock()
    self._status: dict = {}
    self._devices: list[dict] = []
    self._error = ""
    self._busy = False
    self._active = False
    self._exit = False
    self._thread = threading.Thread(target=self._poll, daemon=True)
    self._thread.start()

  @property
  def status(self) -> dict:
    with self._lock:
      return self._status

  @property
  def devices(self) -> list[dict]:
    with self._lock:
      return list(self._devices)

  @property
  def busy(self) -> bool:
    return self._busy

  def set_active(self, active: bool) -> None:
    self._active = active

  def stop(self) -> None:
    self._exit = True

  def consume_error(self) -> str:
    with self._lock:
      error, self._error = self._error, ""
      return error

  def _poll(self) -> None:
    while not self._exit:
      if self._active:
        try:
          status = self._client.status() if self._client.available else {}
        except Exception:
          status = {}
        with self._lock:
          self._status = status
      time.sleep(1.0 if self._active else 2.0)

  def _run(self, fn, *args) -> None:
    if self._busy:
      return
    self._busy = True

    def worker():
      try:
        fn(*args)
      except Exception as error:
        with self._lock:
          self._error = str(error)
      finally:
        self._busy = False
    threading.Thread(target=worker, daemon=True).start()

  def start(self) -> None:
    self._run(self._client.start)

  def stop_projection(self) -> None:
    self._run(self._client.stop)

  def prepare_pairing(self) -> None:
    self._run(self._client.prepare_pairing)

  def set_view(self, view: str) -> None:
    self._run(self._client.set_view, view)

  def set_connection(self, connection: str) -> None:
    self._run(self._client.set_connection, connection)

  def set_auto_connect(self, enabled: bool) -> None:
    self._run(self._client.set_auto_connect, enabled)

  def select_receiver(self, address: str, name: str) -> None:
    self._run(self._client.select_receiver, address, name)

  def refresh_devices(self) -> None:
    def fetch():
      devices = self._client.devices()
      with self._lock:
        self._devices = devices
    self._run(fetch)
