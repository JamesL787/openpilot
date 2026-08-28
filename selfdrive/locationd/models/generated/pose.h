#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_1700850028159621162);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_3416595063278262141);
void pose_H_mod_fun(double *state, double *out_2045417260865528734);
void pose_f_fun(double *state, double dt, double *out_1001887333786351958);
void pose_F_fun(double *state, double dt, double *out_7083458297094230765);
void pose_h_4(double *state, double *unused, double *out_8007441403531526269);
void pose_H_4(double *state, double *unused, double *out_989904710527973009);
void pose_h_10(double *state, double *unused, double *out_781128545146885635);
void pose_H_10(double *state, double *unused, double *out_2086425279933156357);
void pose_h_13(double *state, double *unused, double *out_2650077392226112998);
void pose_H_13(double *state, double *unused, double *out_4202178535860305810);
void pose_h_14(double *state, double *unused, double *out_7818811588763480757);
void pose_H_14(double *state, double *unused, double *out_4953145566867457538);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}