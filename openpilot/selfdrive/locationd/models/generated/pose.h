#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_1063797637258796766);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_5886317630058333046);
void pose_H_mod_fun(double *state, double *out_9034902037276537918);
void pose_f_fun(double *state, double dt, double *out_7872094071272015340);
void pose_F_fun(double *state, double dt, double *out_306824247471662228);
void pose_h_4(double *state, double *unused, double *out_8123411127694778865);
void pose_H_4(double *state, double *unused, double *out_546114021891860012);
void pose_h_10(double *state, double *unused, double *out_1547906265708858286);
void pose_H_10(double *state, double *unused, double *out_5776283871331797156);
void pose_h_13(double *state, double *unused, double *out_1149091238389542330);
void pose_H_13(double *state, double *unused, double *out_8156745230208560941);
void pose_h_14(double *state, double *unused, double *out_2710515986937060210);
void pose_H_14(double *state, double *unused, double *out_4509354878231344541);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}