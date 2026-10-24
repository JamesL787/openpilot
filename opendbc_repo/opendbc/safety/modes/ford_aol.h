#pragma once

static bool ford_aol_manual = false;
static bool ford_aol_enabled = false;
static bool ford_aol_token = false;
static bool ford_aol_main_available = false;
static bool ford_aol_token_claimed = false;
static uint32_t ford_aol_token_ts = 0U;
static bool ford_aol_main_neutral = false;
static bool ford_aol_main_previous = false;
static bool ford_aol_button_neutral = false;
static bool ford_aol_button_previous = false;
static bool ford_aol_session = false;
static bool ford_aol_request_seen = false;
static uint16_t ford_aol_param = 0U;
static bool ford_aol_drive = false;
static uint8_t ford_aol_eps = 0U;
static bool ford_aol_lka_ready = false;
// Keep steering and display ownership separate without adding state storage.
#define FORD_AOL_STEERING_OWNED 1U
#define FORD_AOL_DISPLAY_OWNED 2U
static uint8_t ford_aol_owned = 0U;
static uint32_t ford_aol_accepted_ts = 0U;

static void ford_aol_clear(void) {
  // A revoked session stays revoked, but must not repeatedly erase neutral
  // physical input history needed for the next real driver activation.
  ford_aol_session = false;
  ford_aol_token = false;
  ford_aol_token_claimed = false;
  ford_aol_token_ts = 0U;
  ford_aol_main_neutral = false;
  ford_aol_button_neutral = false;
  ford_aol_owned = 0U;
}

static void ford_aol_reset(void) {
  ford_aol_clear();
  ford_aol_enabled = false;
  ford_aol_main_available = false;
  ford_aol_main_previous = false;
  ford_aol_button_previous = false;
  ford_aol_session = false;
  ford_aol_request_seen = false;
  ford_aol_param = 0U;
  ford_aol_drive = false;
  ford_aol_eps = 0U;
  ford_aol_lka_ready = false;
  ford_aol_accepted_ts = 0U;
}

// Fresh physical MAIN/LKAS or ordinary cruise activation begins a new session.
// pandad reads status before writing its request and engagement heartbeat; the
// old session's disengaged heartbeat is not a loss of this unclaimed token.
// Original token expiry and current heartbeat/request/RX guards remain in force.
static void ford_aol_arm(void) {
  ford_aol_token = true;
  ford_aol_token_claimed = false;
  ford_aol_token_ts = microsecond_timer_get();
  ford_aol_session = false;
}

static void ford_aol_host_request(uint8_t mask) {
  ford_aol_request_seen |= mask != 0U;
  if (((ford_aol_param & 0xFFFEU) == 18U) && ((mask & 1U) == 0U)) {
    ford_aol_owned &= FORD_AOL_STEERING_OWNED;
  }
}

static uint8_t ford_aol_request_mask(void) {
  uint8_t result = 0U;
  const bool expired = ford_aol_request_seen &&
    (safety_get_ts_elapsed(microsecond_timer_get(), aol_host_request_ts) > AOL_HOST_REQUEST_TIMEOUT_US);
  const bool token_expired = ford_aol_token && !ford_aol_token_claimed &&
    (safety_get_ts_elapsed(microsecond_timer_get(), ford_aol_token_ts) > AOL_HOST_REQUEST_TIMEOUT_US);
  const bool long_profile = (ford_aol_param & 1U) != 0U;
  const bool lost_session = ford_aol_session && !heartbeat_engaged;
  if (!aol_rx_healthy() || relay_malfunction || expired || lost_session) {
    // Ordinary LONG cannot revive solely because a stale source/host recovers.
    // A fresh real PCM cruise activation is required after this withdrawal.
    if (long_profile) { controls_allowed = false; }
    ford_aol_clear();
  } else {
    if (token_expired) {
      // Expiry of an unclaimed lateral token must not create a LONG grant or
      // invalidate an independent, still-current ordinary LONG activation.
      ford_aol_clear();
    }
    if (heartbeat_engaged) {
      ford_aol_session = true;
      result = aol_host_axis_mask & (long_profile ? 3U : 1U);
      if (ford_aol_token && (((result & 1U) != 0U) || (((result & 2U) != 0U) && controls_allowed))) {
        ford_aol_token_claimed = true;
      }
    }
  }
  return result;
}

static uint8_t ford_aol_permission_mask(void) {
  uint8_t result = 0U;
  if (ford_aol_eps >= 2U) {
    controls_allowed = false;
    ford_aol_clear();
  }
  const uint16_t base = ford_aol_param & 0xFFFEU;
  const bool needs_lka = (base == 10U) || (base == 12U) || (base == 18U) || (base == 66U);
  const uint8_t requested = ford_aol_request_mask();
  if (((requested & 1U) != 0U) && (controls_allowed || ford_aol_token) &&
      ford_aol_main_available && ford_aol_drive && (ford_aol_eps == 0U) && (!needs_lka || ford_aol_lka_ready)) {
    result = 1U;
  }
  if (((requested & 2U) != 0U) && ((ford_aol_param & 1U) != 0U) && controls_allowed &&
      ford_aol_main_available && ford_aol_drive && (ford_aol_eps < 2U) &&
      !brake_pressed && !gas_pressed && !gas_pressed_prev) {
    result |= 2U;
  }
  if ((base == 18U) && ((result & 1U) == 0U)) {
    ford_aol_owned &= FORD_AOL_STEERING_OWNED;
  }
  return result;
}

static void ford_aol_rx(const CANPacket_t *msg) {
  if (ford_aol_enabled && (msg->bus == 0U)) {
    if (msg_matches(msg, 0x165U, 0U, 8U)) {
      const unsigned int state = msg->data[1] & 7U;
      const bool main_available = (state == 3U) || (state == 4U) || (state == 5U);
      ford_aol_main_available = main_available;
      if (!main_available) {
        ford_aol_clear();
        ford_aol_main_neutral = true;
      } else if (ford_aol_main_neutral && !ford_aol_main_previous && (aol_host_axis_mask == 0U)) {
        ford_aol_arm();
      } else {
      }
      ford_aol_main_previous = main_available;
      if ((state == 1U) || (state == 2U)) {
        ford_aol_clear();
      }
    } else if (msg_matches(msg, 0x83U, 0U, 8U)) {
      const bool button = GET_BIT(msg, 40U);
      if (!button) {
        ford_aol_button_neutral = true;
      } else if (ford_aol_button_neutral && !ford_aol_button_previous && (aol_host_axis_mask == 0U)) {
        ford_aol_arm();
      } else {
      }
      ford_aol_button_previous = button;
      if (GET_BIT(msg, 8U) || GET_BIT(msg, 24U)) {
        ford_aol_clear();
      }
    } else if (msg_matches(msg, 0x82U, 0U, 8U)) {
      ford_aol_eps = msg->data[1] & 3U;
      if (ford_aol_eps >= 2U) {
        controls_allowed = false;
        ford_aol_clear();
      }
    } else if (msg_matches(msg, 0x3CCU, 0U, 8U)) {
      const unsigned int state = msg->data[2] & 7U;
      ford_aol_lka_ready = ((ford_aol_param & 0xFFFEU) == 12U) ?
        ((((msg->data[0] >> 4U) & 3U) == 3U) && ((msg->data[0] & 0x40U) == 0U)) :
        ((state == 1U) || (state == 2U) || (state == 3U));
    } else if (ford_aol_manual && msg_matches(msg, 0x3C3U, 0U, 8U)) {
      ford_aol_drive = !GET_BIT(msg, 9U);
    } else if (!ford_aol_manual) {
      const uint16_t base = ford_aol_param & 0xFFFEU;
      const uint16_t gear_addr = (base == 8U) ? 0x230U : ((base == 10U) ? 0x5AU : 0x176U);
      if (msg_matches(msg, gear_addr, 0U, 8U)) {
        const unsigned int gear = (base == 8U) ? ((msg->data[1] >> 1U) & 15U) :
                                  ((base == 10U) ? (msg->data[6] & 15U) : (msg->data[3] & 15U));
        ford_aol_drive = (gear == 3U) || (gear == 4U) || (gear == 5U);
      }
    } else {
      // Manual profiles consume only the dedicated reverse lamp source.
    }
    // A transient physical veto revokes only display ownership, even when a
    // healthy packet follows in the same RX batch. AOL intent is retained.
    if (((ford_aol_param & 0xFFFEU) == 18U) &&
        (!ford_aol_main_available || !ford_aol_drive || (ford_aol_eps != 0U) || !ford_aol_lka_ready)) {
      ford_aol_owned &= FORD_AOL_STEERING_OWNED;
    }
  }
}

// A real ordinary cruise rising edge can arm retained lateral intent without
// requiring a historical MAIN/LKAS cycle. This never grants ordinary controls
// or longitudinal permission; the current request/heartbeat/RX gates still own TX.
// Accelerator override does not erase this lateral intent. The independent
// longitudinal permission mask continues to require released accelerator/brake.
static void ford_aol_full_engagement(bool cruise_rising) {
  if (ford_aol_enabled && cruise_rising && controls_allowed && !brake_pressed &&
      !relay_malfunction && aol_rx_healthy() && ford_aol_main_available && ford_aol_drive && (ford_aol_eps == 0U)) {
    ford_aol_arm();
  }
}

static bool ford_aol_param_valid(uint16_t param) {
  bool result = false;
  switch (param & ~256U) {
    case 8U: case 9U: case 10U: case 12U: case 13U: case 18U: case 32U: case 33U: case 66U:
      result = true;
      break;
    case 146U: case 147U: case 160U: case 161U: case 194U: case 195U:
    case 11U: case 19U: case 67U:
      result = true;
      break;
    default:
      break;
  }
  return result;
}

static void ford_aol_configure(uint16_t param) {
  ford_aol_reset();
  ford_aol_enabled = ford_aol_param_valid(param) && ((unsigned int)alternative_experience == 32U);
  ford_aol_manual = (param & 256U) != 0U;
  ford_aol_param = param & ~(256U | 128U);
  if (ford_aol_enabled) {
    static const AolSafetyPolicy policy = {
      .reset = ford_aol_reset,
      .host_request = ford_aol_host_request,
      .request_mask = ford_aol_request_mask,
      .permission_mask = ford_aol_permission_mask,
      .rx_invalid = ford_aol_clear,
    };
    aol_policy = &policy;
  }
}

static unsigned int ford_aol_replacement(void) {
  const uint16_t base = ford_aol_param & 0xFFFEU;
  return (base == 12U) ? 0x3CAU : (((base == 10U) || (base == 18U) || (base == 66U)) ? 0x3D6U : 0x3D3U);
}

static void ford_aol_tx(const CANPacket_t *msg, bool accepted) {
  if (ford_aol_enabled && (msg->bus == 0U) && (msg->addr == ford_aol_replacement())) {
    const bool active = (msg->addr == 0x3CAU) ? (((msg->data[0] >> 5U) == 2U) || ((msg->data[0] >> 5U) == 4U)) :
                       ((msg->addr == 0x3D3U) ? (((msg->data[4] >> 2U) & 7U) != 0U) :
                                               (((msg->data[0] >> 4U) & 7U) != 0U));
    const bool mache = (ford_aol_param & 0xFFFEU) == 18U;
    const bool retained_display = mache && ((ford_aol_owned & FORD_AOL_DISPLAY_OWNED) != 0U) &&
      (safety_get_ts_elapsed(microsecond_timer_get(), ford_aol_accepted_ts) <= AOL_HOST_REQUEST_TIMEOUT_US);
    const uint8_t permission = (accepted && (active || retained_display)) ? ford_aol_permission_mask() : 0U;
    const bool steering_owned = accepted && active && (permission != 0U) && !relay_malfunction;
    const bool display_owned = steering_owned || (accepted && retained_display && ((permission & 1U) != 0U) && !relay_malfunction);
    ford_aol_owned = (steering_owned ? FORD_AOL_STEERING_OWNED : 0U) | (display_owned ? FORD_AOL_DISPLAY_OWNED : 0U);
    ford_aol_accepted_ts = microsecond_timer_get();
  }
}

static bool ford_aol_fwd(int bus, int addr) {
  bool blocked = false;
  if (ford_aol_enabled && (bus == 2) && (ford_aol_owned != 0U) && (ford_aol_permission_mask() != 0U) &&
      (safety_get_ts_elapsed(microsecond_timer_get(), ford_aol_accepted_ts) <= AOL_HOST_REQUEST_TIMEOUT_US)) {
    const bool display_permitted = ((ford_aol_param & 0xFFFEU) != 18U) || ((ford_aol_permission_mask() & 1U) != 0U);
    blocked = (((ford_aol_owned & FORD_AOL_STEERING_OWNED) != 0U) && (addr == (int)ford_aol_replacement())) ||
      (((ford_aol_owned & FORD_AOL_DISPLAY_OWNED) != 0U) && display_permitted && ((addr == 0x3D8) || (addr == 0x18A)));
  }
  return blocked;
}

// An unowned Mach-E display must remain stock, including a rejected first
// steering command. This cannot grant steering or longitudinal permission.
static bool ford_aol_display_tx_allowed(void) {
  bool allowed = true;
  if (ford_aol_enabled && ((ford_aol_param & 0xFFFEU) == 18U)) {
    allowed = ((ford_aol_owned & FORD_AOL_DISPLAY_OWNED) != 0U) &&
      ((ford_aol_permission_mask() & 1U) != 0U) && !relay_malfunction &&
      (safety_get_ts_elapsed(microsecond_timer_get(), ford_aol_accepted_ts) <= AOL_HOST_REQUEST_TIMEOUT_US);
  }
  return allowed;
}
