from cereal import custom
from openpilot.common.realtime import DT_CTRL

StarPilotEventName = custom.StarPilotOnroadEvent.EventName
AcceleratorState = custom.StarPilotModelDataV2.AcceleratorState
Backend = custom.StarPilotModelDataV2.Backend

# how long each event is raised for, in selfdrived ticks (DT_CTRL = 10 ms)
OFFER_TICKS = round(3. / DT_CTRL)
HANDBACK_TICKS = round(5. / DT_CTRL)
# the no-entry after a swap, and the settling either way: about the 20 frames the large model needs to prove it keeps up
# and the small model needs to refill its history (SETTLE_SECONDS in jetlink_adapter.runner)
SWITCHING_TICKS = round(1. / DT_CTRL)

# Processes whose death costs a feature and never the drive: a dead one is not "processNotRunning". jetlinkd holds the
# USB gadget; the local model keeps driving without it
OPTIONAL_PROCESSES = frozenset({"jetlinkd"})


class JetlinkEvents:
  """Onroad events for an external model that joins and leaves mid-drive.

  Chestnut's native block expects its model loaded before the first modelV2. Jetlink's joins onto a modelV2 the small model
  is already publishing, and can leave and come back, so the driver is told:

  * when it is ready (and nothing yet allows the swap): "Disengage to switch";
  * for a second after any switch (`switching` / `settling`): nothing engages, because the large model is proving it keeps
    up and the small model is refilling its history; the chime at the end says the driver can;
  * when it hands back while the driver is in control: "Jetlink lost, small model is driving". Nothing disengages.

  The status is read from starpilotModelV2, which modeld publishes on every frame it publishes. Stale status neither offers
  a switch nor re-arms the offer; the settling window follows the *published* backend, so it also covers a switch whose
  message was the last before a stall."""

  def __init__(self):
    self.offered = False
    self.remote_running = False
    # ticks left of each event, and of the settling after a switch either way
    self.offer = self.handback = self.switching = self.settle = 0

  @property
  def settling(self) -> bool:
    """Within a second of the large model swapping in or handing back."""
    return self.settle > 0

  def update(self, sm, in_control: bool, starpilot_events) -> None:
    """`in_control`: openpilot or always-on lateral is engaged or armed, i.e. the swap gate in modeld is shut."""
    status = sm['starpilotModelV2']
    fresh = sm.seen['starpilotModelV2'] and sm.alive['starpilotModelV2'] and sm.valid['starpilotModelV2']
    state = status.accelerator
    running = fresh and status.backend == Backend.jetlink

    if fresh:
      if state != AcceleratorState.ready or running:
        # ended by the swap as well as by the link going: an offer still on screen after the switch read as if it had
        # not happened
        self.offered = False
        self.offer = 0
      elif in_control and not self.offered and self.handback == 0:
        # with nothing in control it swaps in at once and jetlinkReady says so. Once per readiness, not at every stop
        self.offered = True
        self.offer = OFFER_TICKS

    if running and not self.remote_running:
      self.switching = SWITCHING_TICKS + 1   # the no-entry, then the chime
      self.settle = SWITCHING_TICKS + 1      # counted down below, this tick included
    elif self.remote_running and not running:
      self.switching = 0
      self.settle = SWITCHING_TICKS + 1
      if in_control:
        self.handback = HANDBACK_TICKS
    self.remote_running = running
    if self.settle > 0:
      self.settle -= 1
    if not in_control:
      self.handback = 0

    if self.offer > 0:
      self.offer -= 1
      starpilot_events.add(StarPilotEventName.jetlinkAvailable)
    if self.handback > 0:
      self.handback -= 1
      starpilot_events.add(StarPilotEventName.jetlinkLinkLost)
    if self.switching > 0:
      self.switching -= 1
      if self.switching:
        starpilot_events.add(StarPilotEventName.jetlinkSwitching)
      else:
        starpilot_events.add(StarPilotEventName.jetlinkReady)
