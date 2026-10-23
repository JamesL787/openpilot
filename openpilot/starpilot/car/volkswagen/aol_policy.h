#pragma once
#include "selfdrive/pandad/aol_protocol.h"
inline bool volkswagen_stock_aol_param(uint16_t param) {
  return (param == 8U) || (param == 24U);
}
inline bool volkswagen_long_aol_param(uint16_t param) {
  return (param == 9U) || (param == 25U);
}
inline constexpr AolSafetyProfile VOLKSWAGEN_LONG_AOL_PROFILE{15U, volkswagen_long_aol_param, true};
inline constexpr AolSafetyProfile VOLKSWAGEN_STOCK_AOL_PROFILE{15U, volkswagen_stock_aol_param, true};
