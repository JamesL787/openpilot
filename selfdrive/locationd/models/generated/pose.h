#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_7324534072166343284);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_4093192572736199915);
void pose_H_mod_fun(double *state, double *out_829763465388208705);
void pose_f_fun(double *state, double dt, double *out_6925502751931868556);
void pose_F_fun(double *state, double dt, double *out_5096874786388754966);
void pose_h_4(double *state, double *unused, double *out_2729563795634279142);
void pose_H_4(double *state, double *unused, double *out_75602463333496098);
void pose_h_10(double *state, double *unused, double *out_8200253958922815090);
void pose_H_10(double *state, double *unused, double *out_2124391000687077810);
void pose_h_13(double *state, double *unused, double *out_7771148490220590299);
void pose_H_13(double *state, double *unused, double *out_3136671361998836703);
void pose_h_14(double *state, double *unused, double *out_7607766202558535283);
void pose_H_14(double *state, double *unused, double *out_3158390895628868394);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}