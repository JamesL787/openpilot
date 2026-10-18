#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_6550964315864651157);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_4895562721991879665);
void pose_H_mod_fun(double *state, double *out_2502229566014209319);
void pose_f_fun(double *state, double dt, double *out_7650543638844674851);
void pose_F_fun(double *state, double dt, double *out_3194571375064067580);
void pose_h_4(double *state, double *unused, double *out_5032667598116974010);
void pose_H_4(double *state, double *unused, double *out_1269577643829698253);
void pose_h_10(double *state, double *unused, double *out_1000851722634065522);
void pose_H_10(double *state, double *unused, double *out_1846180802078735142);
void pose_h_13(double *state, double *unused, double *out_2099618547077747222);
void pose_H_13(double *state, double *unused, double *out_4481851469162031054);
void pose_h_14(double *state, double *unused, double *out_3950821452670665122);
void pose_H_14(double *state, double *unused, double *out_5232818500169182782);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}