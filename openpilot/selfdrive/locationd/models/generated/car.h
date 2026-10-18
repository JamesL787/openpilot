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
void car_err_fun(double *nom_x, double *delta_x, double *out_3951812574315484718);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_8280879471313698008);
void car_H_mod_fun(double *state, double *out_1746727943248549042);
void car_f_fun(double *state, double dt, double *out_5208273484973288522);
void car_F_fun(double *state, double dt, double *out_5844658587001644910);
void car_h_25(double *state, double *unused, double *out_2135686625469080304);
void car_H_25(double *state, double *unused, double *out_6174610089725310763);
void car_h_24(double *state, double *unused, double *out_3417732373940796067);
void car_H_24(double *state, double *unused, double *out_2970256620225566399);
void car_h_30(double *state, double *unused, double *out_2410880687753586193);
void car_H_30(double *state, double *unused, double *out_8692943048232559390);
void car_h_26(double *state, double *unused, double *out_1807564803077108676);
void car_H_26(double *state, double *unused, double *out_2433106770851254539);
void car_h_27(double *state, double *unused, double *out_468718695339617347);
void car_H_27(double *state, double *unused, double *out_6518179736432134479);
void car_h_29(double *state, double *unused, double *out_7447700704151124015);
void car_H_29(double *state, double *unused, double *out_9203174392546951574);
void car_h_28(double *state, double *unused, double *out_6193850040228263514);
void car_H_28(double *state, double *unused, double *out_4120775375477421000);
void car_h_31(double *state, double *unused, double *out_4019760570371579825);
void car_H_31(double *state, double *unused, double *out_1806898668617903063);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}