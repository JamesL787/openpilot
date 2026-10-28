#pragma once
// Pinion measurement selection adapted from BluePilot PR #145 (fe5b0195).
// See CREDITS.md and THIRD_PARTY_NOTICES.md. No live mode switching.
#define FORD_PINION_ENABLE 0x200U
#define FORD_PINION_MASK 0x3E00U

static bool ford_pinion_word_valid(uint16_t word) {
  bool valid = true;
  if ((word & FORD_PINION_MASK) != 0U) {
    const uint16_t index = (word >> 10U) & 15U;
    const uint16_t base = word & ~(FORD_PINION_MASK | 256U);
    valid = (word & FORD_PINION_ENABLE) != 0U;
    if ((index == 1U) || (index == 2U) || (index == 5U) || (index == 6U) || (index == 9U)) {
      valid &= (base == 32U) || (base == 33U) || (base == 128U) || (base == 129U) || (base == 160U) || (base == 161U);
    } else if ((index == 3U) || (index == 4U) || (index == 7U) || (index == 8U) || (index == 12U)) {
      valid &= (base == 66U) || (base == 67U) || (base == 130U) || (base == 131U) || (base == 194U) || (base == 195U);
    } else if (index == 11U) {
      valid &= (base == 18U) || (base == 19U) || (base == 130U) || (base == 131U) || (base == 146U) || (base == 147U);
    } else if (index == 10U) {
      valid &= (base == 10U) || (base == 11U);
    } else {
      valid = false;
    }
  }
  return valid;
}

static uint16_t ford_pinion_base_word(uint16_t word) {
  return ford_pinion_word_valid(word) ? (word & ~FORD_PINION_MASK) : 0xFFFFU;
}

