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
void car_err_fun(double *nom_x, double *delta_x, double *out_4753656955655394831);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_6511381520186483135);
void car_H_mod_fun(double *state, double *out_6344629559078053291);
void car_f_fun(double *state, double dt, double *out_6337903361942830884);
void car_F_fun(double *state, double dt, double *out_6897557538134524229);
void car_h_25(double *state, double *unused, double *out_7202256902423960093);
void car_H_25(double *state, double *unused, double *out_5839295116877756579);
void car_h_24(double *state, double *unused, double *out_5838782973380870064);
void car_H_24(double *state, double *unused, double *out_736276689713761522);
void car_h_30(double *state, double *unused, double *out_431421676073609157);
void car_H_30(double *state, double *unused, double *out_1077395224613860176);
void car_h_26(double *state, double *unused, double *out_8364887788192387983);
void car_H_26(double *state, double *unused, double *out_8865945637957738813);
void car_h_27(double *state, double *unused, double *out_1860389666537929530);
void car_H_27(double *state, double *unused, double *out_8143397375821421560);
void car_h_29(double *state, double *unused, double *out_2279515350549414497);
void car_H_29(double *state, double *unused, double *out_1587626568928252360);
void car_h_28(double *state, double *unused, double *out_6862062934198775175);
void car_H_28(double *state, double *unused, double *out_3494772448141278214);
void car_h_31(double *state, double *unused, double *out_4254530912068475132);
void car_H_31(double *state, double *unused, double *out_5808649155000796151);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}