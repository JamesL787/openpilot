#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_9020563603504726210);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_6858679601398523695);
void pose_H_mod_fun(double *state, double *out_7505068867812799858);
void pose_f_fun(double *state, double dt, double *out_7693532277985119128);
void pose_F_fun(double *state, double dt, double *out_2354363096336885288);
void pose_h_4(double *state, double *unused, double *out_2798176097030080284);
void pose_H_4(double *state, double *unused, double *out_8259229869867512465);
void pose_h_10(double *state, double *unused, double *out_6129012920849367651);
void pose_H_10(double *state, double *unused, double *out_6492774096974950579);
void pose_h_13(double *state, double *unused, double *out_630259235338554445);
void pose_H_13(double *state, double *unused, double *out_2576882995525338222);
void pose_h_14(double *state, double *unused, double *out_5108820496996726073);
void pose_H_14(double *state, double *unused, double *out_5176441437572140169);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}