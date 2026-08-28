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
void car_err_fun(double *nom_x, double *delta_x, double *out_6422080531108300975);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_7864631515909799753);
void car_H_mod_fun(double *state, double *out_6107356462735918729);
void car_f_fun(double *state, double dt, double *out_254568429738076035);
void car_F_fun(double *state, double dt, double *out_1044277288594422012);
void car_h_25(double *state, double *unused, double *out_8078961343894996488);
void car_H_25(double *state, double *unused, double *out_3085831763176318508);
void car_h_24(double *state, double *unused, double *out_4387952804543679712);
void car_H_24(double *state, double *unused, double *out_7832341090142827542);
void car_h_30(double *state, double *unused, double *out_1911847303923862185);
void car_H_30(double *state, double *unused, double *out_3830858578315298247);
void car_h_26(double *state, double *unused, double *out_2855357156825524620);
void car_H_26(double *state, double *unused, double *out_218694206584482093);
void car_h_27(double *state, double *unused, double *out_5366109462153709483);
void car_H_27(double *state, double *unused, double *out_1656095266514873336);
void car_h_29(double *state, double *unused, double *out_1728659933899687133);
void car_H_29(double *state, double *unused, double *out_57267460354677697);
void car_h_28(double *state, double *unused, double *out_364436194492863838);
void car_H_28(double *state, double *unused, double *out_5139666477424208271);
void car_h_31(double *state, double *unused, double *out_8917151337185671961);
void car_H_31(double *state, double *unused, double *out_3990843487335498745);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}