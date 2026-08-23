#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_6947624313872495524);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_6870382180897404022);
void pose_H_mod_fun(double *state, double *out_7211163890878107353);
void pose_f_fun(double *state, double dt, double *out_6340326609391524869);
void pose_F_fun(double *state, double dt, double *out_7393239063929808405);
void pose_h_4(double *state, double *unused, double *out_5952459838685677664);
void pose_H_4(double *state, double *unused, double *out_8035170281729974239);
void pose_h_10(double *state, double *unused, double *out_3472976061268600135);
void pose_H_10(double *state, double *unused, double *out_3986091875956058549);
void pose_h_13(double *state, double *unused, double *out_4496303610004593389);
void pose_H_13(double *state, double *unused, double *out_8599772201411818343);
void pose_h_14(double *state, double *unused, double *out_7353773663794788489);
void pose_H_14(double *state, double *unused, double *out_4952381849434601943);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}