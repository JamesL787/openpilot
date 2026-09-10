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
void car_err_fun(double *nom_x, double *delta_x, double *out_1730026552285578243);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_5608225427137211498);
void car_H_mod_fun(double *state, double *out_4069150026082258428);
void car_f_fun(double *state, double dt, double *out_2891633532368007403);
void car_F_fun(double *state, double dt, double *out_1948804307455896282);
void car_h_25(double *state, double *unused, double *out_8013558390609820676);
void car_H_25(double *state, double *unused, double *out_3852188006891601377);
void car_h_24(double *state, double *unused, double *out_3530360593846997683);
void car_H_24(double *state, double *unused, double *out_7410113605693924513);
void car_h_30(double *state, double *unused, double *out_1242723164259469740);
void car_H_30(double *state, double *unused, double *out_675508323236006821);
void car_h_26(double *state, double *unused, double *out_3758950103401375905);
void car_H_26(double *state, double *unused, double *out_110684688017545153);
void car_h_27(double *state, double *unused, double *out_6323110555874139716);
void car_H_27(double *state, double *unused, double *out_2850271635036431732);
void car_h_29(double *state, double *unused, double *out_1569828939010383643);
void car_H_29(double *state, double *unused, double *out_165276978921614637);
void car_h_28(double *state, double *unused, double *out_6375022268340547730);
void car_H_28(double *state, double *unused, double *out_5247675995991145211);
void car_h_31(double *state, double *unused, double *out_1858111194769160547);
void car_H_31(double *state, double *unused, double *out_515523414215806323);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}