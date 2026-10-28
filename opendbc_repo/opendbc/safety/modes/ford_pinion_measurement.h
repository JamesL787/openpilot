#pragma once
#define FORD_PINION_GEOMETRY_COUNT 12U
static const AngleSteeringParams *ford_pinion_geometry_at(uint16_t index) {
  static const AngleSteeringParams ford_pinion_geometry[FORD_PINION_GEOMETRY_COUNT + 1U] = {
    {.slip_factor = 0.0f, .steer_ratio = 1.0f, .wheelbase = 1.0f},                  // 0: invalid
    {.slip_factor = -0.00062819555f, .steer_ratio = 17.7f, .wheelbase = 2.670f},    // 1: FORD_BRONCO_SPORT_MK1
    {.slip_factor = -0.00061892325f, .steer_ratio = 16.7f, .wheelbase = 2.710f},    // 2: FORD_ESCAPE_MK4
    {.slip_factor = -0.00061892325f, .steer_ratio = 16.7f, .wheelbase = 2.710f},    // 3: FORD_ESCAPE_MK4_5
    {.slip_factor = -0.00045454798f, .steer_ratio = 17.0f, .wheelbase = 3.690f},    // 4: FORD_EXPEDITION_MK4
    {.slip_factor = -0.00055447339f, .steer_ratio = 16.8f, .wheelbase = 3.025f},    // 5: FORD_EXPLORER_MK6
    {.slip_factor = -0.00062121569f, .steer_ratio = 15.0f, .wheelbase = 2.700f},    // 6: FORD_FOCUS_MK4
    {.slip_factor = -0.00045331952f, .steer_ratio = 16.9f, .wheelbase = 3.700f},    // 7: FORD_F_150_LIGHTNING_MK1
    {.slip_factor = -0.00042037149f, .steer_ratio = 17.0f, .wheelbase = 3.990f},    // 8: FORD_F_150_MK14
    {.slip_factor = -0.00054528036f, .steer_ratio = 17.0f, .wheelbase = 3.076f},    // 9: FORD_MAVERICK_MK1
    {.slip_factor = -0.00058852001f, .steer_ratio = 14.8f, .wheelbase = 2.850f},    // 10: FORD_MONDEO_MK5
    {.slip_factor = -0.00056209187f, .steer_ratio = 17.0f, .wheelbase = 2.984f},    // 11: FORD_MUSTANG_MACH_E_MK1
    {.slip_factor = -0.00051293030f, .steer_ratio = 17.0f, .wheelbase = 3.270f},    // 12: FORD_RANGER_MK2
  };
  return &ford_pinion_geometry[index];
}

static bool ford_pinion_enabled = false;
static const AngleSteeringParams *ford_pinion_params = NULL;
