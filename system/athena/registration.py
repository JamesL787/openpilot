#!/usr/bin/env python3
import time
import json
import jwt
import random
import string
from typing import cast
from pathlib import Path

from datetime import datetime, timedelta, UTC
from openpilot.common.api import api_get, get_key_pair
from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog


UNREGISTERED_DONGLE_ID = "UnregisteredDevice"
IMEI_MAX_ATTEMPTS = 10
KONIK_REGISTER_TIMEOUT_S = 60

def is_registered_device() -> bool:
  dongle = Params().get("DongleId")
  return dongle not in (None, UNREGISTERED_DONGLE_ID)


def register(show_spinner=False, register_konik=False) -> str | None:
  """
  All devices built since March 2024 come with all
  info stored in /persist/. This is kept around
  only for devices built before then.

  With a backend update to take serial number instead
  of dongle ID to some endpoints, this can be removed
  entirely.
  """
  params = Params()

  dongle_id: str | None = params.get("DongleId")
  if dongle_id is None and Path(Paths.persist_root()+"/comma/dongle_id").is_file():
    # not all devices will have this; added early in comma 3X production (2/28/24)
    with open(Paths.persist_root()+"/comma/dongle_id") as f:
      dongle_id = f.read().strip()

  # Create registration token, in the future, this key will make JWTs directly
  jwt_algo, private_key, public_key = get_key_pair()

  if not public_key and not register_konik:
    dongle_id = UNREGISTERED_DONGLE_ID
    cloudlog.warning("missing public key")
  elif dongle_id is None or register_konik:
    # an unreachable Konik server must not hold up manager init, it is retried on the next boot
    konik_deadline = time.monotonic() + KONIK_REGISTER_TIMEOUT_S
    if show_spinner:
      spinner = Spinner()
      spinner.update("registering device")

    # Wait for the imei, but give up after a bounded number of attempts (devices without a modem)
    serial = HARDWARE.get_serial()
    start_time = time.monotonic()
    imei1: str | None = None
    imei2: str | None = None
    imei_attempts = 0
    while imei1 is None and imei2 is None:
      try:
        imei1, imei2 = HARDWARE.get_imei(0), HARDWARE.get_imei(1)
      except Exception:
        imei_attempts += 1
        if imei_attempts >= IMEI_MAX_ATTEMPTS:
          cloudlog.error("Unable to get imei, continuing without it")
          break
        cloudlog.exception("Error getting imei, trying again...")
        time.sleep(1)

      if time.monotonic() - start_time > 60 and show_spinner:
        spinner.update(f"registering device - serial: {serial}, IMEI: ({imei1}, {imei2})")

    backoff = 0
    start_time = time.monotonic()
    while True:
      try:
        register_token = jwt.encode({'register': True, 'exp': datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)},
                                    cast(str, private_key), algorithm=jwt_algo)
        cloudlog.info("getting pilotauth")
        resp = api_get("v2/pilotauth/", method='POST', timeout=15,
                       imei=imei1, imei2=imei2, serial=serial, public_key=public_key, register_token=register_token)

        if resp.status_code in (402, 403):
          cloudlog.info(f"Unable to register device, got {resp.status_code}")
          dongle_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
        else:
          dongleauth = json.loads(resp.text)
          dongle_id = dongleauth["dongle_id"]
        break
      except Exception:
        cloudlog.exception("failed to authenticate")
        backoff = min(backoff + 1, 15)
        if register_konik:
          remaining = konik_deadline - time.monotonic()
          if remaining <= 0:
            cloudlog.error("Konik registration timed out, will retry next boot")
            if show_spinner:
              spinner.close()
            return None
          backoff = min(backoff, remaining)
        time.sleep(backoff)

      if time.monotonic() - start_time > 60 and show_spinner:
        spinner.update(f"registering device - serial: {serial}, IMEI: ({imei1}, {imei2})")

    if show_spinner:
      spinner.close()

  if not register_konik and dongle_id != params.get("KonikDongleId"):
    params.put("DongleId", dongle_id)
    params.put("StockDongleId", dongle_id)
    set_offroad_alert("Offroad_UnregisteredHardware", (dongle_id == UNREGISTERED_DONGLE_ID) and not PC)
  return dongle_id


if __name__ == "__main__":
  print(register())
