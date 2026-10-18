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
void car_err_fun(double *nom_x, double *delta_x, double *out_1495263378523690277);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_2358391450812481082);
void car_H_mod_fun(double *state, double *out_1304167992607751194);
void car_f_fun(double *state, double dt, double *out_7182131393785703688);
void car_F_fun(double *state, double dt, double *out_8516390100549633734);
void car_h_25(double *state, double *unused, double *out_1389136709106931389);
void car_H_25(double *state, double *unused, double *out_6207859817792416034);
void car_h_24(double *state, double *unused, double *out_7393409419771565291);
void car_H_24(double *state, double *unused, double *out_2654499043591743305);
void car_h_30(double *state, double *unused, double *out_5198691217369363774);
void car_H_30(double *state, double *unused, double *out_8726192776299664661);
void car_h_26(double *state, double *unused, double *out_7906185620454157279);
void car_H_26(double *state, double *unused, double *out_8934358286156334981);
void car_h_27(double *state, double *unused, double *out_3993542029915629040);
void car_H_27(double *state, double *unused, double *out_6551429464499239750);
void car_h_29(double *state, double *unused, double *out_8246379588679342197);
void car_H_29(double *state, double *unused, double *out_9210319953095494771);
void car_h_28(double *state, double *unused, double *out_3390226145239151523);
void car_H_28(double *state, double *unused, double *out_4154025103544526271);
void car_h_31(double *state, double *unused, double *out_1231950040755802244);
void car_H_31(double *state, double *unused, double *out_8886177685319865159);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}