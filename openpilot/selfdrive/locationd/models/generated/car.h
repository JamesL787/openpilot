#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_err_fun(double *nom_x, double *delta_x, double *out_7493683132655164884);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4749075189989820222);
void car_H_mod_fun(double *state, double *out_38424272915726002);
void car_f_fun(double *state, double dt, double *out_8006930805773121944);
void car_F_fun(double *state, double dt, double *out_8761604196310819941);
void car_h_25(double *state, double *unused, double *out_6303836805314891079);
void car_H_25(double *state, double *unused, double *out_987545194944208211);
void car_h_24(double *state, double *unused, double *out_656755319644127702);
void car_H_24(double *state, double *unused, double *out_4545470793746531347);
void car_h_30(double *state, double *unused, double *out_6158316981094236108);
void car_H_30(double *state, double *unused, double *out_3540151135183399987);
void car_h_26(double *state, double *unused, double *out_7286753824954469863);
void car_H_26(double *state, double *unused, double *out_2753958123929848013);
void car_h_27(double *state, double *unused, double *out_6159983429088518784);
void car_H_27(double *state, double *unused, double *out_5714914446983824898);
void car_h_29(double *state, double *unused, double *out_6946559856729284945);
void car_H_29(double *state, double *unused, double *out_3029919790869007803);
void car_h_28(double *state, double *unused, double *out_2245673390555707869);
void car_H_28(double *state, double *unused, double *out_1066289519303681552);
void car_h_31(double *state, double *unused, double *out_8007617932175328889);
void car_H_31(double *state, double *unused, double *out_3380166226163199489);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}