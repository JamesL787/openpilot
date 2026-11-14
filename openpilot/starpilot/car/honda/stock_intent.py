from opendbc.car import structs
from openpilot.selfdrive.car.cruise import CRUISE_LONG_PRESS
from openpilot.starpilot.aol.intent import AolCardIntent, AOL_TOGGLE, ButtonType


class HondaStockCardIntent(AolCardIntent):
  observe_stock_engagement = True

  def __init__(self, cp, settings):
    super().__init__(settings, explicit_latch=True)
    self.main_seen = False
    self.main_available = False
    self.main_neutral = False
    self.main_pulse = False
    self.cancel_held = False
    self.cancel_ticks = 0
    self.auto_main = settings.lkas_action != AOL_TOGGLE and settings.main_action != AOL_TOGGLE

  def cancel_action(self, action):
    if action == AOL_TOGGLE and self.settings.enabled:
      self.allowed_latch = not self.allowed_latch
      if self.allowed_latch:
        self.pause_lateral = False
    else:
      self._perform(action)

  def update(self, CS, **kwargs):
    state = CS
    events = []
    for event in CS.buttonEvents:
      if event.type == ButtonType.cancel:
        if event.pressed:
          self.cancel_held = True
          self.cancel_ticks = 0
        else:
          if self.cancel_held and 0 < self.cancel_ticks < CRUISE_LONG_PRESS:
            self.cancel_action(self.settings.cancel_actions[0])
          self.cancel_held = False
          self.cancel_ticks = 0
      elif event.type in (ButtonType.mainCruise, ButtonType.lkas):
        action = self.settings.main_action if event.type == ButtonType.mainCruise else self.settings.lkas_action
        if action == AOL_TOGGLE:
          events.append(structs.CarState.ButtonEvent(**event.to_dict()))
        elif event.pressed:
          self._perform(action)
      else:
        events.append(structs.CarState.ButtonEvent(**event.to_dict()))
    available = bool(CS.cruiseState.available)
    healthy = CS.canValid and not CS.canTimeout
    if healthy:
      if self.main_pulse:
        events.append(structs.CarState.ButtonEvent(type=ButtonType.mainCruise, pressed=False))
        self.main_pulse = False
      # route 000000ac--138f4b8bb4 segment 0: main was already on before the first
      # canValid frame (avail=True at 6.25s, canValid True only at 6.26s), so the
      # off->on edge openpilot normally pulses on never happens and AOL stays
      # unarmed until a full cruise engage. Treat the first healthy frame as
      # neutral/not-available so the pulse can fire on the next healthy frame if
      # main is still on, but not on this frame itself: intent.py needs one
      # non-held frame first to set _gesture_neutral_seen, or the pulse is ignored.
      # Never synthesize the pulse while standard cruise is enabled: intent.py reads a
      # mainCruise press during engagement as the driver toggling lateral off (seen
      # when openpilot starts, or restarts, with cruise already engaged). Full
      # engagement arms AOL on its own in that case.
      first = not self.main_seen
      engaged = bool(kwargs.get('standard_enabled', False))
      if not available or first:
        self.main_neutral = True
      elif self.auto_main and self.main_neutral and not self.main_available and not engaged:
        events.append(structs.CarState.ButtonEvent(type=ButtonType.mainCruise, pressed=True))
        self.main_pulse = True
        self.main_neutral = False
      self.main_seen = True
      self.main_available = available and not first
    else:
      self.cancel_held = False
      self.cancel_ticks = 0
      self.main_neutral = False
    if events or len(CS.buttonEvents):
      # Copy only when button events are rewritten; most frames have none.
      state = structs.CarState(**CS.to_dict())
      state.buttonEvents = events
      CS = state.as_reader()
    super().update(CS, **kwargs)
    if not available:
      self.allowed_latch = False
    if self.cancel_held:
      self.cancel_ticks += 1
      if self.cancel_ticks == CRUISE_LONG_PRESS:
        self.cancel_action(self.settings.cancel_actions[1])
      elif self.cancel_ticks == CRUISE_LONG_PRESS * 5:
        self.cancel_action(self.settings.cancel_actions[2])
