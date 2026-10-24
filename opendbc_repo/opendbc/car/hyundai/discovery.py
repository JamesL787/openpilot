import time


NORMAL_BUS_LAYOUT = {(2, 0x110): 32, (2, 0x362): 32, (1, 0x35): 32,
                     (1, 0xEA): 24, (1, 0xA0): 24, (1, 0x1A0): 32,
                     (1, 0x1CF): 8, (0, 0x3A5): 24}


# Classic HKG steering, chassis and stock SCC are already visible on normal
# harness wiring. This selects a diagnostic query family, never a vehicle or
# control profile. Fresh firmware and CAN fingerprinting still own identity.
CLASSIC_NORMAL_BUS_LAYOUT = {(0, 0x251): 8, (0, 0x386): 8, (0, 0x394): 8,
                            (0, 0x4F1): 4, (2, 0x340): 8, (0, 0x420): 8, (0, 0x421): 8}


def normal_bus_topology(can_recv, *, clock=time.monotonic):
  deadline = clock() + .12
  layouts = (NORMAL_BUS_LAYOUT, CLASSIC_NORMAL_BUS_LAYOUT)
  observed = [{} for _ in layouts]
  for _ in range(24):
    if clock() >= deadline:
      break
    for packet in can_recv(wait_for_one=True):
      for frame in packet:
        key = (frame.src, frame.address)
        for layout, received in zip(layouts, observed, strict=True):
          if key in layout:
            length = len(frame.dat)
            if length != layout[key]:
              return False
            received[key] = length
    if any(received == layout for layout, received in zip(layouts, observed, strict=True)):
      return True
  return False
