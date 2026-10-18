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
void err_fun(double *nom_x, double *delta_x, double *out_3951812574315484718) {
   out_3951812574315484718[0] = delta_x[0] + nom_x[0];
   out_3951812574315484718[1] = delta_x[1] + nom_x[1];
   out_3951812574315484718[2] = delta_x[2] + nom_x[2];
   out_3951812574315484718[3] = delta_x[3] + nom_x[3];
   out_3951812574315484718[4] = delta_x[4] + nom_x[4];
   out_3951812574315484718[5] = delta_x[5] + nom_x[5];
   out_3951812574315484718[6] = delta_x[6] + nom_x[6];
   out_3951812574315484718[7] = delta_x[7] + nom_x[7];
   out_3951812574315484718[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_8280879471313698008) {
   out_8280879471313698008[0] = -nom_x[0] + true_x[0];
   out_8280879471313698008[1] = -nom_x[1] + true_x[1];
   out_8280879471313698008[2] = -nom_x[2] + true_x[2];
   out_8280879471313698008[3] = -nom_x[3] + true_x[3];
   out_8280879471313698008[4] = -nom_x[4] + true_x[4];
   out_8280879471313698008[5] = -nom_x[5] + true_x[5];
   out_8280879471313698008[6] = -nom_x[6] + true_x[6];
   out_8280879471313698008[7] = -nom_x[7] + true_x[7];
   out_8280879471313698008[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_1746727943248549042) {
   out_1746727943248549042[0] = 1.0;
   out_1746727943248549042[1] = 0.0;
   out_1746727943248549042[2] = 0.0;
   out_1746727943248549042[3] = 0.0;
   out_1746727943248549042[4] = 0.0;
   out_1746727943248549042[5] = 0.0;
   out_1746727943248549042[6] = 0.0;
   out_1746727943248549042[7] = 0.0;
   out_1746727943248549042[8] = 0.0;
   out_1746727943248549042[9] = 0.0;
   out_1746727943248549042[10] = 1.0;
   out_1746727943248549042[11] = 0.0;
   out_1746727943248549042[12] = 0.0;
   out_1746727943248549042[13] = 0.0;
   out_1746727943248549042[14] = 0.0;
   out_1746727943248549042[15] = 0.0;
   out_1746727943248549042[16] = 0.0;
   out_1746727943248549042[17] = 0.0;
   out_1746727943248549042[18] = 0.0;
   out_1746727943248549042[19] = 0.0;
   out_1746727943248549042[20] = 1.0;
   out_1746727943248549042[21] = 0.0;
   out_1746727943248549042[22] = 0.0;
   out_1746727943248549042[23] = 0.0;
   out_1746727943248549042[24] = 0.0;
   out_1746727943248549042[25] = 0.0;
   out_1746727943248549042[26] = 0.0;
   out_1746727943248549042[27] = 0.0;
   out_1746727943248549042[28] = 0.0;
   out_1746727943248549042[29] = 0.0;
   out_1746727943248549042[30] = 1.0;
   out_1746727943248549042[31] = 0.0;
   out_1746727943248549042[32] = 0.0;
   out_1746727943248549042[33] = 0.0;
   out_1746727943248549042[34] = 0.0;
   out_1746727943248549042[35] = 0.0;
   out_1746727943248549042[36] = 0.0;
   out_1746727943248549042[37] = 0.0;
   out_1746727943248549042[38] = 0.0;
   out_1746727943248549042[39] = 0.0;
   out_1746727943248549042[40] = 1.0;
   out_1746727943248549042[41] = 0.0;
   out_1746727943248549042[42] = 0.0;
   out_1746727943248549042[43] = 0.0;
   out_1746727943248549042[44] = 0.0;
   out_1746727943248549042[45] = 0.0;
   out_1746727943248549042[46] = 0.0;
   out_1746727943248549042[47] = 0.0;
   out_1746727943248549042[48] = 0.0;
   out_1746727943248549042[49] = 0.0;
   out_1746727943248549042[50] = 1.0;
   out_1746727943248549042[51] = 0.0;
   out_1746727943248549042[52] = 0.0;
   out_1746727943248549042[53] = 0.0;
   out_1746727943248549042[54] = 0.0;
   out_1746727943248549042[55] = 0.0;
   out_1746727943248549042[56] = 0.0;
   out_1746727943248549042[57] = 0.0;
   out_1746727943248549042[58] = 0.0;
   out_1746727943248549042[59] = 0.0;
   out_1746727943248549042[60] = 1.0;
   out_1746727943248549042[61] = 0.0;
   out_1746727943248549042[62] = 0.0;
   out_1746727943248549042[63] = 0.0;
   out_1746727943248549042[64] = 0.0;
   out_1746727943248549042[65] = 0.0;
   out_1746727943248549042[66] = 0.0;
   out_1746727943248549042[67] = 0.0;
   out_1746727943248549042[68] = 0.0;
   out_1746727943248549042[69] = 0.0;
   out_1746727943248549042[70] = 1.0;
   out_1746727943248549042[71] = 0.0;
   out_1746727943248549042[72] = 0.0;
   out_1746727943248549042[73] = 0.0;
   out_1746727943248549042[74] = 0.0;
   out_1746727943248549042[75] = 0.0;
   out_1746727943248549042[76] = 0.0;
   out_1746727943248549042[77] = 0.0;
   out_1746727943248549042[78] = 0.0;
   out_1746727943248549042[79] = 0.0;
   out_1746727943248549042[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_5208273484973288522) {
   out_5208273484973288522[0] = state[0];
   out_5208273484973288522[1] = state[1];
   out_5208273484973288522[2] = state[2];
   out_5208273484973288522[3] = state[3];
   out_5208273484973288522[4] = state[4];
   out_5208273484973288522[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8100000000000005*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_5208273484973288522[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_5208273484973288522[7] = state[7];
   out_5208273484973288522[8] = state[8];
}
void F_fun(double *state, double dt, double *out_5844658587001644910) {
   out_5844658587001644910[0] = 1;
   out_5844658587001644910[1] = 0;
   out_5844658587001644910[2] = 0;
   out_5844658587001644910[3] = 0;
   out_5844658587001644910[4] = 0;
   out_5844658587001644910[5] = 0;
   out_5844658587001644910[6] = 0;
   out_5844658587001644910[7] = 0;
   out_5844658587001644910[8] = 0;
   out_5844658587001644910[9] = 0;
   out_5844658587001644910[10] = 1;
   out_5844658587001644910[11] = 0;
   out_5844658587001644910[12] = 0;
   out_5844658587001644910[13] = 0;
   out_5844658587001644910[14] = 0;
   out_5844658587001644910[15] = 0;
   out_5844658587001644910[16] = 0;
   out_5844658587001644910[17] = 0;
   out_5844658587001644910[18] = 0;
   out_5844658587001644910[19] = 0;
   out_5844658587001644910[20] = 1;
   out_5844658587001644910[21] = 0;
   out_5844658587001644910[22] = 0;
   out_5844658587001644910[23] = 0;
   out_5844658587001644910[24] = 0;
   out_5844658587001644910[25] = 0;
   out_5844658587001644910[26] = 0;
   out_5844658587001644910[27] = 0;
   out_5844658587001644910[28] = 0;
   out_5844658587001644910[29] = 0;
   out_5844658587001644910[30] = 1;
   out_5844658587001644910[31] = 0;
   out_5844658587001644910[32] = 0;
   out_5844658587001644910[33] = 0;
   out_5844658587001644910[34] = 0;
   out_5844658587001644910[35] = 0;
   out_5844658587001644910[36] = 0;
   out_5844658587001644910[37] = 0;
   out_5844658587001644910[38] = 0;
   out_5844658587001644910[39] = 0;
   out_5844658587001644910[40] = 1;
   out_5844658587001644910[41] = 0;
   out_5844658587001644910[42] = 0;
   out_5844658587001644910[43] = 0;
   out_5844658587001644910[44] = 0;
   out_5844658587001644910[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_5844658587001644910[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_5844658587001644910[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_5844658587001644910[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_5844658587001644910[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_5844658587001644910[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_5844658587001644910[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_5844658587001644910[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_5844658587001644910[53] = -9.8100000000000005*dt;
   out_5844658587001644910[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_5844658587001644910[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_5844658587001644910[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5844658587001644910[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5844658587001644910[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_5844658587001644910[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_5844658587001644910[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_5844658587001644910[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5844658587001644910[62] = 0;
   out_5844658587001644910[63] = 0;
   out_5844658587001644910[64] = 0;
   out_5844658587001644910[65] = 0;
   out_5844658587001644910[66] = 0;
   out_5844658587001644910[67] = 0;
   out_5844658587001644910[68] = 0;
   out_5844658587001644910[69] = 0;
   out_5844658587001644910[70] = 1;
   out_5844658587001644910[71] = 0;
   out_5844658587001644910[72] = 0;
   out_5844658587001644910[73] = 0;
   out_5844658587001644910[74] = 0;
   out_5844658587001644910[75] = 0;
   out_5844658587001644910[76] = 0;
   out_5844658587001644910[77] = 0;
   out_5844658587001644910[78] = 0;
   out_5844658587001644910[79] = 0;
   out_5844658587001644910[80] = 1;
}
void h_25(double *state, double *unused, double *out_2135686625469080304) {
   out_2135686625469080304[0] = state[6];
}
void H_25(double *state, double *unused, double *out_6174610089725310763) {
   out_6174610089725310763[0] = 0;
   out_6174610089725310763[1] = 0;
   out_6174610089725310763[2] = 0;
   out_6174610089725310763[3] = 0;
   out_6174610089725310763[4] = 0;
   out_6174610089725310763[5] = 0;
   out_6174610089725310763[6] = 1;
   out_6174610089725310763[7] = 0;
   out_6174610089725310763[8] = 0;
}
void h_24(double *state, double *unused, double *out_3417732373940796067) {
   out_3417732373940796067[0] = state[4];
   out_3417732373940796067[1] = state[5];
}
void H_24(double *state, double *unused, double *out_2970256620225566399) {
   out_2970256620225566399[0] = 0;
   out_2970256620225566399[1] = 0;
   out_2970256620225566399[2] = 0;
   out_2970256620225566399[3] = 0;
   out_2970256620225566399[4] = 1;
   out_2970256620225566399[5] = 0;
   out_2970256620225566399[6] = 0;
   out_2970256620225566399[7] = 0;
   out_2970256620225566399[8] = 0;
   out_2970256620225566399[9] = 0;
   out_2970256620225566399[10] = 0;
   out_2970256620225566399[11] = 0;
   out_2970256620225566399[12] = 0;
   out_2970256620225566399[13] = 0;
   out_2970256620225566399[14] = 1;
   out_2970256620225566399[15] = 0;
   out_2970256620225566399[16] = 0;
   out_2970256620225566399[17] = 0;
}
void h_30(double *state, double *unused, double *out_2410880687753586193) {
   out_2410880687753586193[0] = state[4];
}
void H_30(double *state, double *unused, double *out_8692943048232559390) {
   out_8692943048232559390[0] = 0;
   out_8692943048232559390[1] = 0;
   out_8692943048232559390[2] = 0;
   out_8692943048232559390[3] = 0;
   out_8692943048232559390[4] = 1;
   out_8692943048232559390[5] = 0;
   out_8692943048232559390[6] = 0;
   out_8692943048232559390[7] = 0;
   out_8692943048232559390[8] = 0;
}
void h_26(double *state, double *unused, double *out_1807564803077108676) {
   out_1807564803077108676[0] = state[7];
}
void H_26(double *state, double *unused, double *out_2433106770851254539) {
   out_2433106770851254539[0] = 0;
   out_2433106770851254539[1] = 0;
   out_2433106770851254539[2] = 0;
   out_2433106770851254539[3] = 0;
   out_2433106770851254539[4] = 0;
   out_2433106770851254539[5] = 0;
   out_2433106770851254539[6] = 0;
   out_2433106770851254539[7] = 1;
   out_2433106770851254539[8] = 0;
}
void h_27(double *state, double *unused, double *out_468718695339617347) {
   out_468718695339617347[0] = state[3];
}
void H_27(double *state, double *unused, double *out_6518179736432134479) {
   out_6518179736432134479[0] = 0;
   out_6518179736432134479[1] = 0;
   out_6518179736432134479[2] = 0;
   out_6518179736432134479[3] = 1;
   out_6518179736432134479[4] = 0;
   out_6518179736432134479[5] = 0;
   out_6518179736432134479[6] = 0;
   out_6518179736432134479[7] = 0;
   out_6518179736432134479[8] = 0;
}
void h_29(double *state, double *unused, double *out_7447700704151124015) {
   out_7447700704151124015[0] = state[1];
}
void H_29(double *state, double *unused, double *out_9203174392546951574) {
   out_9203174392546951574[0] = 0;
   out_9203174392546951574[1] = 1;
   out_9203174392546951574[2] = 0;
   out_9203174392546951574[3] = 0;
   out_9203174392546951574[4] = 0;
   out_9203174392546951574[5] = 0;
   out_9203174392546951574[6] = 0;
   out_9203174392546951574[7] = 0;
   out_9203174392546951574[8] = 0;
}
void h_28(double *state, double *unused, double *out_6193850040228263514) {
   out_6193850040228263514[0] = state[0];
}
void H_28(double *state, double *unused, double *out_4120775375477421000) {
   out_4120775375477421000[0] = 1;
   out_4120775375477421000[1] = 0;
   out_4120775375477421000[2] = 0;
   out_4120775375477421000[3] = 0;
   out_4120775375477421000[4] = 0;
   out_4120775375477421000[5] = 0;
   out_4120775375477421000[6] = 0;
   out_4120775375477421000[7] = 0;
   out_4120775375477421000[8] = 0;
}
void h_31(double *state, double *unused, double *out_4019760570371579825) {
   out_4019760570371579825[0] = state[8];
}
void H_31(double *state, double *unused, double *out_1806898668617903063) {
   out_1806898668617903063[0] = 0;
   out_1806898668617903063[1] = 0;
   out_1806898668617903063[2] = 0;
   out_1806898668617903063[3] = 0;
   out_1806898668617903063[4] = 0;
   out_1806898668617903063[5] = 0;
   out_1806898668617903063[6] = 0;
   out_1806898668617903063[7] = 0;
   out_1806898668617903063[8] = 1;
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
void car_err_fun(double *nom_x, double *delta_x, double *out_3951812574315484718) {
  err_fun(nom_x, delta_x, out_3951812574315484718);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_8280879471313698008) {
  inv_err_fun(nom_x, true_x, out_8280879471313698008);
}
void car_H_mod_fun(double *state, double *out_1746727943248549042) {
  H_mod_fun(state, out_1746727943248549042);
}
void car_f_fun(double *state, double dt, double *out_5208273484973288522) {
  f_fun(state,  dt, out_5208273484973288522);
}
void car_F_fun(double *state, double dt, double *out_5844658587001644910) {
  F_fun(state,  dt, out_5844658587001644910);
}
void car_h_25(double *state, double *unused, double *out_2135686625469080304) {
  h_25(state, unused, out_2135686625469080304);
}
void car_H_25(double *state, double *unused, double *out_6174610089725310763) {
  H_25(state, unused, out_6174610089725310763);
}
void car_h_24(double *state, double *unused, double *out_3417732373940796067) {
  h_24(state, unused, out_3417732373940796067);
}
void car_H_24(double *state, double *unused, double *out_2970256620225566399) {
  H_24(state, unused, out_2970256620225566399);
}
void car_h_30(double *state, double *unused, double *out_2410880687753586193) {
  h_30(state, unused, out_2410880687753586193);
}
void car_H_30(double *state, double *unused, double *out_8692943048232559390) {
  H_30(state, unused, out_8692943048232559390);
}
void car_h_26(double *state, double *unused, double *out_1807564803077108676) {
  h_26(state, unused, out_1807564803077108676);
}
void car_H_26(double *state, double *unused, double *out_2433106770851254539) {
  H_26(state, unused, out_2433106770851254539);
}
void car_h_27(double *state, double *unused, double *out_468718695339617347) {
  h_27(state, unused, out_468718695339617347);
}
void car_H_27(double *state, double *unused, double *out_6518179736432134479) {
  H_27(state, unused, out_6518179736432134479);
}
void car_h_29(double *state, double *unused, double *out_7447700704151124015) {
  h_29(state, unused, out_7447700704151124015);
}
void car_H_29(double *state, double *unused, double *out_9203174392546951574) {
  H_29(state, unused, out_9203174392546951574);
}
void car_h_28(double *state, double *unused, double *out_6193850040228263514) {
  h_28(state, unused, out_6193850040228263514);
}
void car_H_28(double *state, double *unused, double *out_4120775375477421000) {
  H_28(state, unused, out_4120775375477421000);
}
void car_h_31(double *state, double *unused, double *out_4019760570371579825) {
  h_31(state, unused, out_4019760570371579825);
}
void car_H_31(double *state, double *unused, double *out_1806898668617903063) {
  H_31(state, unused, out_1806898668617903063);
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
