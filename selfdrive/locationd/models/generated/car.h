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
void car_err_fun(double *nom_x, double *delta_x, double *out_5608493539522686667);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4162846502685365603);
void car_H_mod_fun(double *state, double *out_5442943604186832911);
void car_f_fun(double *state, double dt, double *out_5781972681352711679);
void car_F_fun(double *state, double dt, double *out_5826361519075941134);
void car_h_25(double *state, double *unused, double *out_8515201722301925483);
void car_H_25(double *state, double *unused, double *out_1919962954197341234);
void car_h_24(double *state, double *unused, double *out_6116257956049490393);
void car_H_24(double *state, double *unused, double *out_4092612553202840800);
void car_h_30(double *state, double *unused, double *out_3200593673612940276);
void car_H_30(double *state, double *unused, double *out_4996727387294275521);
void car_h_26(double *state, double *unused, double *out_4980829197856807075);
void car_H_26(double *state, double *unused, double *out_5661466273071397458);
void car_h_27(double *state, double *unused, double *out_2636916234743210395);
void car_H_27(double *state, double *unused, double *out_2821964075493850610);
void car_h_29(double *state, double *unused, double *out_9038992612615990285);
void car_H_29(double *state, double *unused, double *out_1108601348624299577);
void car_h_28(double *state, double *unused, double *out_3082586279679563532);
void car_H_28(double *state, double *unused, double *out_3973797668445230997);
void car_h_31(double *state, double *unused, double *out_124675754416616401);
void car_H_31(double *state, double *unused, double *out_1889316992320380806);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}