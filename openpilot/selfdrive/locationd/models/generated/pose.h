#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_6021173093259519341);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_3203995659568275494);
void pose_H_mod_fun(double *state, double *out_128560542949297932);
void pose_f_fun(double *state, double dt, double *out_7884286617494058224);
void pose_F_fun(double *state, double dt, double *out_2375412256629136437);
void pose_h_4(double *state, double *unused, double *out_5426853226755395774);
void pose_H_4(double *state, double *unused, double *out_1069386938933600172);
void pose_h_10(double *state, double *unused, double *out_9020263373970964705);
void pose_H_10(double *state, double *unused, double *out_1175983645882290527);
void pose_h_13(double *state, double *unused, double *out_7873459457849635199);
void pose_H_13(double *state, double *unused, double *out_4281660764265932973);
void pose_h_14(double *state, double *unused, double *out_3056352778676871730);
void pose_H_14(double *state, double *unused, double *out_2013401493361772124);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}