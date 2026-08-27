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
void car_err_fun(double *nom_x, double *delta_x, double *out_6921687248411021200);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_1531609997203188998);
void car_H_mod_fun(double *state, double *out_67042187713662319);
void car_f_fun(double *state, double dt, double *out_5979571664892016831);
void car_F_fun(double *state, double dt, double *out_4776924826301051446);
void car_h_25(double *state, double *unused, double *out_5600998109952287910);
void car_H_25(double *state, double *unused, double *out_9186513660083652060);
void car_h_24(double *state, double *unused, double *out_2653523787842120254);
void car_H_24(double *state, double *unused, double *out_32165227556704331);
void car_h_30(double *state, double *unused, double *out_9208296435503241356);
void car_H_30(double *state, double *unused, double *out_4658817329956043862);
void car_h_26(double *state, double *unused, double *out_226327263496400591);
void car_H_26(double *state, double *unused, double *out_5445010341209595836);
void car_h_27(double *state, double *unused, double *out_6358848255113106720);
void car_H_27(double *state, double *unused, double *out_2484054018155618951);
void car_h_29(double *state, double *unused, double *out_4206623167842395711);
void car_H_29(double *state, double *unused, double *out_5169048674270436046);
void car_h_28(double *state, double *unused, double *out_873764223772274265);
void car_H_28(double *state, double *unused, double *out_86649657200905472);
void car_h_31(double *state, double *unused, double *out_2807806380081144242);
void car_H_31(double *state, double *unused, double *out_4818802238976244360);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}