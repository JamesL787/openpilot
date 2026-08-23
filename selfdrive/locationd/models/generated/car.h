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
void car_err_fun(double *nom_x, double *delta_x, double *out_1164787853655705929);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_588229169633882171);
void car_H_mod_fun(double *state, double *out_6595585959729208805);
void car_f_fun(double *state, double dt, double *out_6538394037219821330);
void car_F_fun(double *state, double dt, double *out_6465309767192832359);
void car_h_25(double *state, double *unused, double *out_8352957524314354812);
void car_H_25(double *state, double *unused, double *out_3072605309739717128);
void car_h_24(double *state, double *unused, double *out_5184381584422412044);
void car_H_24(double *state, double *unused, double *out_485320289062606008);
void car_h_30(double *state, double *unused, double *out_3507716244200964423);
void car_H_30(double *state, double *unused, double *out_3844085031751899627);
void car_h_26(double *state, double *unused, double *out_5288593220065032717);
void car_H_26(double *state, double *unused, double *out_6814108628613773352);
void car_h_27(double *state, double *unused, double *out_9111702456059898692);
void car_H_27(double *state, double *unused, double *out_1669321719951474716);
void car_h_29(double *state, double *unused, double *out_1454663753480328809);
void car_H_29(double *state, double *unused, double *out_44041006918076317);
void car_h_28(double *state, double *unused, double *out_4110029188399053047);
void car_H_28(double *state, double *unused, double *out_5126440023987606891);
void car_h_31(double *state, double *unused, double *out_471684873560305627);
void car_H_31(double *state, double *unused, double *out_3041959347862756700);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}