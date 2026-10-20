import time


NORMAL_BUS_LAYOUT = {(2, 0x110): 32, (2, 0x362): 32, (1, 0x35): 32,
                     (1, 0xEA): 24, (1, 0xA0): 24, (1, 0x1A0): 32,
                     (1, 0x1CF): 8, (0, 0x3A5): 24}


def normal_bus_topology(can_recv, *, clock=time.monotonic):
  deadline = clock() + .12
  observed = {}
  for _ in range(24):
    if clock() >= deadline:
      break
    for packet in can_recv(wait_for_one=True):
      for frame in packet:
        key = (frame.src, frame.address)
        if key in NORMAL_BUS_LAYOUT:
          length = len(frame.dat)
          if length != NORMAL_BUS_LAYOUT[key]:
            return False
          observed[key] = length
    if observed == NORMAL_BUS_LAYOUT:
      return True
  return False
