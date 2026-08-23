#include "car.h"

namespace {
#define DIM 9
#define EDIM 9
#define MEDIM 9
typedef void (*Hfun)(double *, double *, double *);

double mass;

void set_mass(double x){ mass = x;}

double rotational_inertia;

void set_rotational_inertia(double x){ rotational_inertia = x;}

double center_to_front;

void set_center_to_front(double x){ center_to_front = x;}

double center_to_rear;

void set_center_to_rear(double x){ center_to_rear = x;}

double stiffness_front;

void set_stiffness_front(double x){ stiffness_front = x;}

double stiffness_rear;

void set_stiffness_rear(double x){ stiffness_rear = x;}
const static double MAHA_THRESH_25 = 3.8414588206941227;
const static double MAHA_THRESH_24 = 5.991464547107981;
const static double MAHA_THRESH_30 = 3.8414588206941227;
const static double MAHA_THRESH_26 = 3.8414588206941227;
const static double MAHA_THRESH_27 = 3.8414588206941227;
const static double MAHA_THRESH_29 = 3.8414588206941227;
const static double MAHA_THRESH_28 = 3.8414588206941227;
const static double MAHA_THRESH_31 = 3.8414588206941227;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_5608493539522686667) {
   out_5608493539522686667[0] = delta_x[0] + nom_x[0];
   out_5608493539522686667[1] = delta_x[1] + nom_x[1];
   out_5608493539522686667[2] = delta_x[2] + nom_x[2];
   out_5608493539522686667[3] = delta_x[3] + nom_x[3];
   out_5608493539522686667[4] = delta_x[4] + nom_x[4];
   out_5608493539522686667[5] = delta_x[5] + nom_x[5];
   out_5608493539522686667[6] = delta_x[6] + nom_x[6];
   out_5608493539522686667[7] = delta_x[7] + nom_x[7];
   out_5608493539522686667[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_4162846502685365603) {
   out_4162846502685365603[0] = -nom_x[0] + true_x[0];
   out_4162846502685365603[1] = -nom_x[1] + true_x[1];
   out_4162846502685365603[2] = -nom_x[2] + true_x[2];
   out_4162846502685365603[3] = -nom_x[3] + true_x[3];
   out_4162846502685365603[4] = -nom_x[4] + true_x[4];
   out_4162846502685365603[5] = -nom_x[5] + true_x[5];
   out_4162846502685365603[6] = -nom_x[6] + true_x[6];
   out_4162846502685365603[7] = -nom_x[7] + true_x[7];
   out_4162846502685365603[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_5442943604186832911) {
   out_5442943604186832911[0] = 1.0;
   out_5442943604186832911[1] = 0.0;
   out_5442943604186832911[2] = 0.0;
   out_5442943604186832911[3] = 0.0;
   out_5442943604186832911[4] = 0.0;
   out_5442943604186832911[5] = 0.0;
   out_5442943604186832911[6] = 0.0;
   out_5442943604186832911[7] = 0.0;
   out_5442943604186832911[8] = 0.0;
   out_5442943604186832911[9] = 0.0;
   out_5442943604186832911[10] = 1.0;
   out_5442943604186832911[11] = 0.0;
   out_5442943604186832911[12] = 0.0;
   out_5442943604186832911[13] = 0.0;
   out_5442943604186832911[14] = 0.0;
   out_5442943604186832911[15] = 0.0;
   out_5442943604186832911[16] = 0.0;
   out_5442943604186832911[17] = 0.0;
   out_5442943604186832911[18] = 0.0;
   out_5442943604186832911[19] = 0.0;
   out_5442943604186832911[20] = 1.0;
   out_5442943604186832911[21] = 0.0;
   out_5442943604186832911[22] = 0.0;
   out_5442943604186832911[23] = 0.0;
   out_5442943604186832911[24] = 0.0;
   out_5442943604186832911[25] = 0.0;
   out_5442943604186832911[26] = 0.0;
   out_5442943604186832911[27] = 0.0;
   out_5442943604186832911[28] = 0.0;
   out_5442943604186832911[29] = 0.0;
   out_5442943604186832911[30] = 1.0;
   out_5442943604186832911[31] = 0.0;
   out_5442943604186832911[32] = 0.0;
   out_5442943604186832911[33] = 0.0;
   out_5442943604186832911[34] = 0.0;
   out_5442943604186832911[35] = 0.0;
   out_5442943604186832911[36] = 0.0;
   out_5442943604186832911[37] = 0.0;
   out_5442943604186832911[38] = 0.0;
   out_5442943604186832911[39] = 0.0;
   out_5442943604186832911[40] = 1.0;
   out_5442943604186832911[41] = 0.0;
   out_5442943604186832911[42] = 0.0;
   out_5442943604186832911[43] = 0.0;
   out_5442943604186832911[44] = 0.0;
   out_5442943604186832911[45] = 0.0;
   out_5442943604186832911[46] = 0.0;
   out_5442943604186832911[47] = 0.0;
   out_5442943604186832911[48] = 0.0;
   out_5442943604186832911[49] = 0.0;
   out_5442943604186832911[50] = 1.0;
   out_5442943604186832911[51] = 0.0;
   out_5442943604186832911[52] = 0.0;
   out_5442943604186832911[53] = 0.0;
   out_5442943604186832911[54] = 0.0;
   out_5442943604186832911[55] = 0.0;
   out_5442943604186832911[56] = 0.0;
   out_5442943604186832911[57] = 0.0;
   out_5442943604186832911[58] = 0.0;
   out_5442943604186832911[59] = 0.0;
   out_5442943604186832911[60] = 1.0;
   out_5442943604186832911[61] = 0.0;
   out_5442943604186832911[62] = 0.0;
   out_5442943604186832911[63] = 0.0;
   out_5442943604186832911[64] = 0.0;
   out_5442943604186832911[65] = 0.0;
   out_5442943604186832911[66] = 0.0;
   out_5442943604186832911[67] = 0.0;
   out_5442943604186832911[68] = 0.0;
   out_5442943604186832911[69] = 0.0;
   out_5442943604186832911[70] = 1.0;
   out_5442943604186832911[71] = 0.0;
   out_5442943604186832911[72] = 0.0;
   out_5442943604186832911[73] = 0.0;
   out_5442943604186832911[74] = 0.0;
   out_5442943604186832911[75] = 0.0;
   out_5442943604186832911[76] = 0.0;
   out_5442943604186832911[77] = 0.0;
   out_5442943604186832911[78] = 0.0;
   out_5442943604186832911[79] = 0.0;
   out_5442943604186832911[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_5781972681352711679) {
   out_5781972681352711679[0] = state[0];
   out_5781972681352711679[1] = state[1];
   out_5781972681352711679[2] = state[2];
   out_5781972681352711679[3] = state[3];
   out_5781972681352711679[4] = state[4];
   out_5781972681352711679[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8100000000000005*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_5781972681352711679[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_5781972681352711679[7] = state[7];
   out_5781972681352711679[8] = state[8];
}
void F_fun(double *state, double dt, double *out_5826361519075941134) {
   out_5826361519075941134[0] = 1;
   out_5826361519075941134[1] = 0;
   out_5826361519075941134[2] = 0;
   out_5826361519075941134[3] = 0;
   out_5826361519075941134[4] = 0;
   out_5826361519075941134[5] = 0;
   out_5826361519075941134[6] = 0;
   out_5826361519075941134[7] = 0;
   out_5826361519075941134[8] = 0;
   out_5826361519075941134[9] = 0;
   out_5826361519075941134[10] = 1;
   out_5826361519075941134[11] = 0;
   out_5826361519075941134[12] = 0;
   out_5826361519075941134[13] = 0;
   out_5826361519075941134[14] = 0;
   out_5826361519075941134[15] = 0;
   out_5826361519075941134[16] = 0;
   out_5826361519075941134[17] = 0;
   out_5826361519075941134[18] = 0;
   out_5826361519075941134[19] = 0;
   out_5826361519075941134[20] = 1;
   out_5826361519075941134[21] = 0;
   out_5826361519075941134[22] = 0;
   out_5826361519075941134[23] = 0;
   out_5826361519075941134[24] = 0;
   out_5826361519075941134[25] = 0;
   out_5826361519075941134[26] = 0;
   out_5826361519075941134[27] = 0;
   out_5826361519075941134[28] = 0;
   out_5826361519075941134[29] = 0;
   out_5826361519075941134[30] = 1;
   out_5826361519075941134[31] = 0;
   out_5826361519075941134[32] = 0;
   out_5826361519075941134[33] = 0;
   out_5826361519075941134[34] = 0;
   out_5826361519075941134[35] = 0;
   out_5826361519075941134[36] = 0;
   out_5826361519075941134[37] = 0;
   out_5826361519075941134[38] = 0;
   out_5826361519075941134[39] = 0;
   out_5826361519075941134[40] = 1;
   out_5826361519075941134[41] = 0;
   out_5826361519075941134[42] = 0;
   out_5826361519075941134[43] = 0;
   out_5826361519075941134[44] = 0;
   out_5826361519075941134[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_5826361519075941134[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_5826361519075941134[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_5826361519075941134[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_5826361519075941134[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_5826361519075941134[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_5826361519075941134[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_5826361519075941134[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_5826361519075941134[53] = -9.8100000000000005*dt;
   out_5826361519075941134[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_5826361519075941134[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_5826361519075941134[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5826361519075941134[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5826361519075941134[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_5826361519075941134[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_5826361519075941134[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_5826361519075941134[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5826361519075941134[62] = 0;
   out_5826361519075941134[63] = 0;
   out_5826361519075941134[64] = 0;
   out_5826361519075941134[65] = 0;
   out_5826361519075941134[66] = 0;
   out_5826361519075941134[67] = 0;
   out_5826361519075941134[68] = 0;
   out_5826361519075941134[69] = 0;
   out_5826361519075941134[70] = 1;
   out_5826361519075941134[71] = 0;
   out_5826361519075941134[72] = 0;
   out_5826361519075941134[73] = 0;
   out_5826361519075941134[74] = 0;
   out_5826361519075941134[75] = 0;
   out_5826361519075941134[76] = 0;
   out_5826361519075941134[77] = 0;
   out_5826361519075941134[78] = 0;
   out_5826361519075941134[79] = 0;
   out_5826361519075941134[80] = 1;
}
void h_25(double *state, double *unused, double *out_8515201722301925483) {
   out_8515201722301925483[0] = state[6];
}
void H_25(double *state, double *unused, double *out_1919962954197341234) {
   out_1919962954197341234[0] = 0;
   out_1919962954197341234[1] = 0;
   out_1919962954197341234[2] = 0;
   out_1919962954197341234[3] = 0;
   out_1919962954197341234[4] = 0;
   out_1919962954197341234[5] = 0;
   out_1919962954197341234[6] = 1;
   out_1919962954197341234[7] = 0;
   out_1919962954197341234[8] = 0;
}
void h_24(double *state, double *unused, double *out_6116257956049490393) {
   out_6116257956049490393[0] = state[4];
   out_6116257956049490393[1] = state[5];
}
void H_24(double *state, double *unused, double *out_4092612553202840800) {
   out_4092612553202840800[0] = 0;
   out_4092612553202840800[1] = 0;
   out_4092612553202840800[2] = 0;
   out_4092612553202840800[3] = 0;
   out_4092612553202840800[4] = 1;
   out_4092612553202840800[5] = 0;
   out_4092612553202840800[6] = 0;
   out_4092612553202840800[7] = 0;
   out_4092612553202840800[8] = 0;
   out_4092612553202840800[9] = 0;
   out_4092612553202840800[10] = 0;
   out_4092612553202840800[11] = 0;
   out_4092612553202840800[12] = 0;
   out_4092612553202840800[13] = 0;
   out_4092612553202840800[14] = 1;
   out_4092612553202840800[15] = 0;
   out_4092612553202840800[16] = 0;
   out_4092612553202840800[17] = 0;
}
void h_30(double *state, double *unused, double *out_3200593673612940276) {
   out_3200593673612940276[0] = state[4];
}
void H_30(double *state, double *unused, double *out_4996727387294275521) {
   out_4996727387294275521[0] = 0;
   out_4996727387294275521[1] = 0;
   out_4996727387294275521[2] = 0;
   out_4996727387294275521[3] = 0;
   out_4996727387294275521[4] = 1;
   out_4996727387294275521[5] = 0;
   out_4996727387294275521[6] = 0;
   out_4996727387294275521[7] = 0;
   out_4996727387294275521[8] = 0;
}
void h_26(double *state, double *unused, double *out_4980829197856807075) {
   out_4980829197856807075[0] = state[7];
}
void H_26(double *state, double *unused, double *out_5661466273071397458) {
   out_5661466273071397458[0] = 0;
   out_5661466273071397458[1] = 0;
   out_5661466273071397458[2] = 0;
   out_5661466273071397458[3] = 0;
   out_5661466273071397458[4] = 0;
   out_5661466273071397458[5] = 0;
   out_5661466273071397458[6] = 0;
   out_5661466273071397458[7] = 1;
   out_5661466273071397458[8] = 0;
}
void h_27(double *state, double *unused, double *out_2636916234743210395) {
   out_2636916234743210395[0] = state[3];
}
void H_27(double *state, double *unused, double *out_2821964075493850610) {
   out_2821964075493850610[0] = 0;
   out_2821964075493850610[1] = 0;
   out_2821964075493850610[2] = 0;
   out_2821964075493850610[3] = 1;
   out_2821964075493850610[4] = 0;
   out_2821964075493850610[5] = 0;
   out_2821964075493850610[6] = 0;
   out_2821964075493850610[7] = 0;
   out_2821964075493850610[8] = 0;
}
void h_29(double *state, double *unused, double *out_9038992612615990285) {
   out_9038992612615990285[0] = state[1];
}
void H_29(double *state, double *unused, double *out_1108601348624299577) {
   out_1108601348624299577[0] = 0;
   out_1108601348624299577[1] = 1;
   out_1108601348624299577[2] = 0;
   out_1108601348624299577[3] = 0;
   out_1108601348624299577[4] = 0;
   out_1108601348624299577[5] = 0;
   out_1108601348624299577[6] = 0;
   out_1108601348624299577[7] = 0;
   out_1108601348624299577[8] = 0;
}
void h_28(double *state, double *unused, double *out_3082586279679563532) {
   out_3082586279679563532[0] = state[0];
}
void H_28(double *state, double *unused, double *out_3973797668445230997) {
   out_3973797668445230997[0] = 1;
   out_3973797668445230997[1] = 0;
   out_3973797668445230997[2] = 0;
   out_3973797668445230997[3] = 0;
   out_3973797668445230997[4] = 0;
   out_3973797668445230997[5] = 0;
   out_3973797668445230997[6] = 0;
   out_3973797668445230997[7] = 0;
   out_3973797668445230997[8] = 0;
}
void h_31(double *state, double *unused, double *out_124675754416616401) {
   out_124675754416616401[0] = state[8];
}
void H_31(double *state, double *unused, double *out_1889316992320380806) {
   out_1889316992320380806[0] = 0;
   out_1889316992320380806[1] = 0;
   out_1889316992320380806[2] = 0;
   out_1889316992320380806[3] = 0;
   out_1889316992320380806[4] = 0;
   out_1889316992320380806[5] = 0;
   out_1889316992320380806[6] = 0;
   out_1889316992320380806[7] = 0;
   out_1889316992320380806[8] = 1;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_25, H_25, NULL, in_z, in_R, in_ea, MAHA_THRESH_25);
}
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<2, 3, 0>(in_x, in_P, h_24, H_24, NULL, in_z, in_R, in_ea, MAHA_THRESH_24);
}
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_30, H_30, NULL, in_z, in_R, in_ea, MAHA_THRESH_30);
}
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_26, H_26, NULL, in_z, in_R, in_ea, MAHA_THRESH_26);
}
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_27, H_27, NULL, in_z, in_R, in_ea, MAHA_THRESH_27);
}
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_29, H_29, NULL, in_z, in_R, in_ea, MAHA_THRESH_29);
}
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_28, H_28, NULL, in_z, in_R, in_ea, MAHA_THRESH_28);
}
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_31, H_31, NULL, in_z, in_R, in_ea, MAHA_THRESH_31);
}
void car_err_fun(double *nom_x, double *delta_x, double *out_5608493539522686667) {
  err_fun(nom_x, delta_x, out_5608493539522686667);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4162846502685365603) {
  inv_err_fun(nom_x, true_x, out_4162846502685365603);
}
void car_H_mod_fun(double *state, double *out_5442943604186832911) {
  H_mod_fun(state, out_5442943604186832911);
}
void car_f_fun(double *state, double dt, double *out_5781972681352711679) {
  f_fun(state,  dt, out_5781972681352711679);
}
void car_F_fun(double *state, double dt, double *out_5826361519075941134) {
  F_fun(state,  dt, out_5826361519075941134);
}
void car_h_25(double *state, double *unused, double *out_8515201722301925483) {
  h_25(state, unused, out_8515201722301925483);
}
void car_H_25(double *state, double *unused, double *out_1919962954197341234) {
  H_25(state, unused, out_1919962954197341234);
}
void car_h_24(double *state, double *unused, double *out_6116257956049490393) {
  h_24(state, unused, out_6116257956049490393);
}
void car_H_24(double *state, double *unused, double *out_4092612553202840800) {
  H_24(state, unused, out_4092612553202840800);
}
void car_h_30(double *state, double *unused, double *out_3200593673612940276) {
  h_30(state, unused, out_3200593673612940276);
}
void car_H_30(double *state, double *unused, double *out_4996727387294275521) {
  H_30(state, unused, out_4996727387294275521);
}
void car_h_26(double *state, double *unused, double *out_4980829197856807075) {
  h_26(state, unused, out_4980829197856807075);
}
void car_H_26(double *state, double *unused, double *out_5661466273071397458) {
  H_26(state, unused, out_5661466273071397458);
}
void car_h_27(double *state, double *unused, double *out_2636916234743210395) {
  h_27(state, unused, out_2636916234743210395);
}
void car_H_27(double *state, double *unused, double *out_2821964075493850610) {
  H_27(state, unused, out_2821964075493850610);
}
void car_h_29(double *state, double *unused, double *out_9038992612615990285) {
  h_29(state, unused, out_9038992612615990285);
}
void car_H_29(double *state, double *unused, double *out_1108601348624299577) {
  H_29(state, unused, out_1108601348624299577);
}
void car_h_28(double *state, double *unused, double *out_3082586279679563532) {
  h_28(state, unused, out_3082586279679563532);
}
void car_H_28(double *state, double *unused, double *out_3973797668445230997) {
  H_28(state, unused, out_3973797668445230997);
}
void car_h_31(double *state, double *unused, double *out_124675754416616401) {
  h_31(state, unused, out_124675754416616401);
}
void car_H_31(double *state, double *unused, double *out_1889316992320380806) {
  H_31(state, unused, out_1889316992320380806);
}
void car_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
void car_set_mass(double x) {
  set_mass(x);
}
void car_set_rotational_inertia(double x) {
  set_rotational_inertia(x);
}
void car_set_center_to_front(double x) {
  set_center_to_front(x);
}
void car_set_center_to_rear(double x) {
  set_center_to_rear(x);
}
void car_set_stiffness_front(double x) {
  set_stiffness_front(x);
}
void car_set_stiffness_rear(double x) {
  set_stiffness_rear(x);
}
}

const EKF car = {
  .name = "car",
  .kinds = { 25, 24, 30, 26, 27, 29, 28, 31 },
  .feature_kinds = {  },
  .f_fun = car_f_fun,
  .F_fun = car_F_fun,
  .err_fun = car_err_fun,
  .inv_err_fun = car_inv_err_fun,
  .H_mod_fun = car_H_mod_fun,
  .predict = car_predict,
  .hs = {
    { 25, car_h_25 },
    { 24, car_h_24 },
    { 30, car_h_30 },
    { 26, car_h_26 },
    { 27, car_h_27 },
    { 29, car_h_29 },
    { 28, car_h_28 },
    { 31, car_h_31 },
  },
  .Hs = {
    { 25, car_H_25 },
    { 24, car_H_24 },
    { 30, car_H_30 },
    { 26, car_H_26 },
    { 27, car_H_27 },
    { 29, car_H_29 },
    { 28, car_H_28 },
    { 31, car_H_31 },
  },
  .updates = {
    { 25, car_update_25 },
    { 24, car_update_24 },
    { 30, car_update_30 },
    { 26, car_update_26 },
    { 27, car_update_27 },
    { 29, car_update_29 },
    { 28, car_update_28 },
    { 31, car_update_31 },
  },
  .Hes = {
  },
  .sets = {
    { "mass", car_set_mass },
    { "rotational_inertia", car_set_rotational_inertia },
    { "center_to_front", car_set_center_to_front },
    { "center_to_rear", car_set_center_to_rear },
    { "stiffness_front", car_set_stiffness_front },
    { "stiffness_rear", car_set_stiffness_rear },
  },
  .extra_routines = {
  },
};

ekf_lib_init(car)
