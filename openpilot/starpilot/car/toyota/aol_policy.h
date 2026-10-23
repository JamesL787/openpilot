#pragma once

#include "selfdrive/pandad/aol_protocol.h"

inline bool toyota_aol_param(uint16_t param) {
  return (param == 73U) || (param == 585U) || (param == 4169U) || (param == 4681U) || (param == 2121U) || (param == 0x9049U) || (param == 0x9249U) || (param == 0x2049U) || (param == 0x2249U) || (param == 0x424DU) || (param == 0x449U) || (param == 0x649U) || (param == 0x1449U) || (param == 0x1649U) || (param == 0x8049U) || (param == 0x8249U) || (param == 0x8449U) || (param == 0x8649U);
}

inline constexpr AolSafetyProfile TOYOTA_AOL_PROFILE{2U, toyota_aol_param, true};
