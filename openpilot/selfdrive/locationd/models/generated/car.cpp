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
void err_fun(double *nom_x, double *delta_x, double *out_7493683132655164884) {
   out_7493683132655164884[0] = delta_x[0] + nom_x[0];
   out_7493683132655164884[1] = delta_x[1] + nom_x[1];
   out_7493683132655164884[2] = delta_x[2] + nom_x[2];
   out_7493683132655164884[3] = delta_x[3] + nom_x[3];
   out_7493683132655164884[4] = delta_x[4] + nom_x[4];
   out_7493683132655164884[5] = delta_x[5] + nom_x[5];
   out_7493683132655164884[6] = delta_x[6] + nom_x[6];
   out_7493683132655164884[7] = delta_x[7] + nom_x[7];
   out_7493683132655164884[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_4749075189989820222) {
   out_4749075189989820222[0] = -nom_x[0] + true_x[0];
   out_4749075189989820222[1] = -nom_x[1] + true_x[1];
   out_4749075189989820222[2] = -nom_x[2] + true_x[2];
   out_4749075189989820222[3] = -nom_x[3] + true_x[3];
   out_4749075189989820222[4] = -nom_x[4] + true_x[4];
   out_4749075189989820222[5] = -nom_x[5] + true_x[5];
   out_4749075189989820222[6] = -nom_x[6] + true_x[6];
   out_4749075189989820222[7] = -nom_x[7] + true_x[7];
   out_4749075189989820222[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_38424272915726002) {
   out_38424272915726002[0] = 1.0;
   out_38424272915726002[1] = 0.0;
   out_38424272915726002[2] = 0.0;
   out_38424272915726002[3] = 0.0;
   out_38424272915726002[4] = 0.0;
   out_38424272915726002[5] = 0.0;
   out_38424272915726002[6] = 0.0;
   out_38424272915726002[7] = 0.0;
   out_38424272915726002[8] = 0.0;
   out_38424272915726002[9] = 0.0;
   out_38424272915726002[10] = 1.0;
   out_38424272915726002[11] = 0.0;
   out_38424272915726002[12] = 0.0;
   out_38424272915726002[13] = 0.0;
   out_38424272915726002[14] = 0.0;
   out_38424272915726002[15] = 0.0;
   out_38424272915726002[16] = 0.0;
   out_38424272915726002[17] = 0.0;
   out_38424272915726002[18] = 0.0;
   out_38424272915726002[19] = 0.0;
   out_38424272915726002[20] = 1.0;
   out_38424272915726002[21] = 0.0;
   out_38424272915726002[22] = 0.0;
   out_38424272915726002[23] = 0.0;
   out_38424272915726002[24] = 0.0;
   out_38424272915726002[25] = 0.0;
   out_38424272915726002[26] = 0.0;
   out_38424272915726002[27] = 0.0;
   out_38424272915726002[28] = 0.0;
   out_38424272915726002[29] = 0.0;
   out_38424272915726002[30] = 1.0;
   out_38424272915726002[31] = 0.0;
   out_38424272915726002[32] = 0.0;
   out_38424272915726002[33] = 0.0;
   out_38424272915726002[34] = 0.0;
   out_38424272915726002[35] = 0.0;
   out_38424272915726002[36] = 0.0;
   out_38424272915726002[37] = 0.0;
   out_38424272915726002[38] = 0.0;
   out_38424272915726002[39] = 0.0;
   out_38424272915726002[40] = 1.0;
   out_38424272915726002[41] = 0.0;
   out_38424272915726002[42] = 0.0;
   out_38424272915726002[43] = 0.0;
   out_38424272915726002[44] = 0.0;
   out_38424272915726002[45] = 0.0;
   out_38424272915726002[46] = 0.0;
   out_38424272915726002[47] = 0.0;
   out_38424272915726002[48] = 0.0;
   out_38424272915726002[49] = 0.0;
   out_38424272915726002[50] = 1.0;
   out_38424272915726002[51] = 0.0;
   out_38424272915726002[52] = 0.0;
   out_38424272915726002[53] = 0.0;
   out_38424272915726002[54] = 0.0;
   out_38424272915726002[55] = 0.0;
   out_38424272915726002[56] = 0.0;
   out_38424272915726002[57] = 0.0;
   out_38424272915726002[58] = 0.0;
   out_38424272915726002[59] = 0.0;
   out_38424272915726002[60] = 1.0;
   out_38424272915726002[61] = 0.0;
   out_38424272915726002[62] = 0.0;
   out_38424272915726002[63] = 0.0;
   out_38424272915726002[64] = 0.0;
   out_38424272915726002[65] = 0.0;
   out_38424272915726002[66] = 0.0;
   out_38424272915726002[67] = 0.0;
   out_38424272915726002[68] = 0.0;
   out_38424272915726002[69] = 0.0;
   out_38424272915726002[70] = 1.0;
   out_38424272915726002[71] = 0.0;
   out_38424272915726002[72] = 0.0;
   out_38424272915726002[73] = 0.0;
   out_38424272915726002[74] = 0.0;
   out_38424272915726002[75] = 0.0;
   out_38424272915726002[76] = 0.0;
   out_38424272915726002[77] = 0.0;
   out_38424272915726002[78] = 0.0;
   out_38424272915726002[79] = 0.0;
   out_38424272915726002[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_8006930805773121944) {
   out_8006930805773121944[0] = state[0];
   out_8006930805773121944[1] = state[1];
   out_8006930805773121944[2] = state[2];
   out_8006930805773121944[3] = state[3];
   out_8006930805773121944[4] = state[4];
   out_8006930805773121944[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8100000000000005*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_8006930805773121944[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_8006930805773121944[7] = state[7];
   out_8006930805773121944[8] = state[8];
}
void F_fun(double *state, double dt, double *out_8761604196310819941) {
   out_8761604196310819941[0] = 1;
   out_8761604196310819941[1] = 0;
   out_8761604196310819941[2] = 0;
   out_8761604196310819941[3] = 0;
   out_8761604196310819941[4] = 0;
   out_8761604196310819941[5] = 0;
   out_8761604196310819941[6] = 0;
   out_8761604196310819941[7] = 0;
   out_8761604196310819941[8] = 0;
   out_8761604196310819941[9] = 0;
   out_8761604196310819941[10] = 1;
   out_8761604196310819941[11] = 0;
   out_8761604196310819941[12] = 0;
   out_8761604196310819941[13] = 0;
   out_8761604196310819941[14] = 0;
   out_8761604196310819941[15] = 0;
   out_8761604196310819941[16] = 0;
   out_8761604196310819941[17] = 0;
   out_8761604196310819941[18] = 0;
   out_8761604196310819941[19] = 0;
   out_8761604196310819941[20] = 1;
   out_8761604196310819941[21] = 0;
   out_8761604196310819941[22] = 0;
   out_8761604196310819941[23] = 0;
   out_8761604196310819941[24] = 0;
   out_8761604196310819941[25] = 0;
   out_8761604196310819941[26] = 0;
   out_8761604196310819941[27] = 0;
   out_8761604196310819941[28] = 0;
   out_8761604196310819941[29] = 0;
   out_8761604196310819941[30] = 1;
   out_8761604196310819941[31] = 0;
   out_8761604196310819941[32] = 0;
   out_8761604196310819941[33] = 0;
   out_8761604196310819941[34] = 0;
   out_8761604196310819941[35] = 0;
   out_8761604196310819941[36] = 0;
   out_8761604196310819941[37] = 0;
   out_8761604196310819941[38] = 0;
   out_8761604196310819941[39] = 0;
   out_8761604196310819941[40] = 1;
   out_8761604196310819941[41] = 0;
   out_8761604196310819941[42] = 0;
   out_8761604196310819941[43] = 0;
   out_8761604196310819941[44] = 0;
   out_8761604196310819941[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_8761604196310819941[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_8761604196310819941[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_8761604196310819941[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_8761604196310819941[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_8761604196310819941[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_8761604196310819941[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_8761604196310819941[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_8761604196310819941[53] = -9.8100000000000005*dt;
   out_8761604196310819941[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_8761604196310819941[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_8761604196310819941[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8761604196310819941[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8761604196310819941[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_8761604196310819941[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_8761604196310819941[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_8761604196310819941[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8761604196310819941[62] = 0;
   out_8761604196310819941[63] = 0;
   out_8761604196310819941[64] = 0;
   out_8761604196310819941[65] = 0;
   out_8761604196310819941[66] = 0;
   out_8761604196310819941[67] = 0;
   out_8761604196310819941[68] = 0;
   out_8761604196310819941[69] = 0;
   out_8761604196310819941[70] = 1;
   out_8761604196310819941[71] = 0;
   out_8761604196310819941[72] = 0;
   out_8761604196310819941[73] = 0;
   out_8761604196310819941[74] = 0;
   out_8761604196310819941[75] = 0;
   out_8761604196310819941[76] = 0;
   out_8761604196310819941[77] = 0;
   out_8761604196310819941[78] = 0;
   out_8761604196310819941[79] = 0;
   out_8761604196310819941[80] = 1;
}
void h_25(double *state, double *unused, double *out_6303836805314891079) {
   out_6303836805314891079[0] = state[6];
}
void H_25(double *state, double *unused, double *out_987545194944208211) {
   out_987545194944208211[0] = 0;
   out_987545194944208211[1] = 0;
   out_987545194944208211[2] = 0;
   out_987545194944208211[3] = 0;
   out_987545194944208211[4] = 0;
   out_987545194944208211[5] = 0;
   out_987545194944208211[6] = 1;
   out_987545194944208211[7] = 0;
   out_987545194944208211[8] = 0;
}
void h_24(double *state, double *unused, double *out_656755319644127702) {
   out_656755319644127702[0] = state[4];
   out_656755319644127702[1] = state[5];
}
void H_24(double *state, double *unused, double *out_4545470793746531347) {
   out_4545470793746531347[0] = 0;
   out_4545470793746531347[1] = 0;
   out_4545470793746531347[2] = 0;
   out_4545470793746531347[3] = 0;
   out_4545470793746531347[4] = 1;
   out_4545470793746531347[5] = 0;
   out_4545470793746531347[6] = 0;
   out_4545470793746531347[7] = 0;
   out_4545470793746531347[8] = 0;
   out_4545470793746531347[9] = 0;
   out_4545470793746531347[10] = 0;
   out_4545470793746531347[11] = 0;
   out_4545470793746531347[12] = 0;
   out_4545470793746531347[13] = 0;
   out_4545470793746531347[14] = 1;
   out_4545470793746531347[15] = 0;
   out_4545470793746531347[16] = 0;
   out_4545470793746531347[17] = 0;
}
void h_30(double *state, double *unused, double *out_6158316981094236108) {
   out_6158316981094236108[0] = state[4];
}
void H_30(double *state, double *unused, double *out_3540151135183399987) {
   out_3540151135183399987[0] = 0;
   out_3540151135183399987[1] = 0;
   out_3540151135183399987[2] = 0;
   out_3540151135183399987[3] = 0;
   out_3540151135183399987[4] = 1;
   out_3540151135183399987[5] = 0;
   out_3540151135183399987[6] = 0;
   out_3540151135183399987[7] = 0;
   out_3540151135183399987[8] = 0;
}
void h_26(double *state, double *unused, double *out_7286753824954469863) {
   out_7286753824954469863[0] = state[7];
}
void H_26(double *state, double *unused, double *out_2753958123929848013) {
   out_2753958123929848013[0] = 0;
   out_2753958123929848013[1] = 0;
   out_2753958123929848013[2] = 0;
   out_2753958123929848013[3] = 0;
   out_2753958123929848013[4] = 0;
   out_2753958123929848013[5] = 0;
   out_2753958123929848013[6] = 0;
   out_2753958123929848013[7] = 1;
   out_2753958123929848013[8] = 0;
}
void h_27(double *state, double *unused, double *out_6159983429088518784) {
   out_6159983429088518784[0] = state[3];
}
void H_27(double *state, double *unused, double *out_5714914446983824898) {
   out_5714914446983824898[0] = 0;
   out_5714914446983824898[1] = 0;
   out_5714914446983824898[2] = 0;
   out_5714914446983824898[3] = 1;
   out_5714914446983824898[4] = 0;
   out_5714914446983824898[5] = 0;
   out_5714914446983824898[6] = 0;
   out_5714914446983824898[7] = 0;
   out_5714914446983824898[8] = 0;
}
void h_29(double *state, double *unused, double *out_6946559856729284945) {
   out_6946559856729284945[0] = state[1];
}
void H_29(double *state, double *unused, double *out_3029919790869007803) {
   out_3029919790869007803[0] = 0;
   out_3029919790869007803[1] = 1;
   out_3029919790869007803[2] = 0;
   out_3029919790869007803[3] = 0;
   out_3029919790869007803[4] = 0;
   out_3029919790869007803[5] = 0;
   out_3029919790869007803[6] = 0;
   out_3029919790869007803[7] = 0;
   out_3029919790869007803[8] = 0;
}
void h_28(double *state, double *unused, double *out_2245673390555707869) {
   out_2245673390555707869[0] = state[0];
}
void H_28(double *state, double *unused, double *out_1066289519303681552) {
   out_1066289519303681552[0] = 1;
   out_1066289519303681552[1] = 0;
   out_1066289519303681552[2] = 0;
   out_1066289519303681552[3] = 0;
   out_1066289519303681552[4] = 0;
   out_1066289519303681552[5] = 0;
   out_1066289519303681552[6] = 0;
   out_1066289519303681552[7] = 0;
   out_1066289519303681552[8] = 0;
}
void h_31(double *state, double *unused, double *out_8007617932175328889) {
   out_8007617932175328889[0] = state[8];
}
void H_31(double *state, double *unused, double *out_3380166226163199489) {
   out_3380166226163199489[0] = 0;
   out_3380166226163199489[1] = 0;
   out_3380166226163199489[2] = 0;
   out_3380166226163199489[3] = 0;
   out_3380166226163199489[4] = 0;
   out_3380166226163199489[5] = 0;
   out_3380166226163199489[6] = 0;
   out_3380166226163199489[7] = 0;
   out_3380166226163199489[8] = 1;
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
void car_err_fun(double *nom_x, double *delta_x, double *out_7493683132655164884) {
  err_fun(nom_x, delta_x, out_7493683132655164884);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4749075189989820222) {
  inv_err_fun(nom_x, true_x, out_4749075189989820222);
}
void car_H_mod_fun(double *state, double *out_38424272915726002) {
  H_mod_fun(state, out_38424272915726002);
}
void car_f_fun(double *state, double dt, double *out_8006930805773121944) {
  f_fun(state,  dt, out_8006930805773121944);
}
void car_F_fun(double *state, double dt, double *out_8761604196310819941) {
  F_fun(state,  dt, out_8761604196310819941);
}
void car_h_25(double *state, double *unused, double *out_6303836805314891079) {
  h_25(state, unused, out_6303836805314891079);
}
void car_H_25(double *state, double *unused, double *out_987545194944208211) {
  H_25(state, unused, out_987545194944208211);
}
void car_h_24(double *state, double *unused, double *out_656755319644127702) {
  h_24(state, unused, out_656755319644127702);
}
void car_H_24(double *state, double *unused, double *out_4545470793746531347) {
  H_24(state, unused, out_4545470793746531347);
}
void car_h_30(double *state, double *unused, double *out_6158316981094236108) {
  h_30(state, unused, out_6158316981094236108);
}
void car_H_30(double *state, double *unused, double *out_3540151135183399987) {
  H_30(state, unused, out_3540151135183399987);
}
void car_h_26(double *state, double *unused, double *out_7286753824954469863) {
  h_26(state, unused, out_7286753824954469863);
}
void car_H_26(double *state, double *unused, double *out_2753958123929848013) {
  H_26(state, unused, out_2753958123929848013);
}
void car_h_27(double *state, double *unused, double *out_6159983429088518784) {
  h_27(state, unused, out_6159983429088518784);
}
void car_H_27(double *state, double *unused, double *out_5714914446983824898) {
  H_27(state, unused, out_5714914446983824898);
}
void car_h_29(double *state, double *unused, double *out_6946559856729284945) {
  h_29(state, unused, out_6946559856729284945);
}
void car_H_29(double *state, double *unused, double *out_3029919790869007803) {
  H_29(state, unused, out_3029919790869007803);
}
void car_h_28(double *state, double *unused, double *out_2245673390555707869) {
  h_28(state, unused, out_2245673390555707869);
}
void car_H_28(double *state, double *unused, double *out_1066289519303681552) {
  H_28(state, unused, out_1066289519303681552);
}
void car_h_31(double *state, double *unused, double *out_8007617932175328889) {
  h_31(state, unused, out_8007617932175328889);
}
void car_H_31(double *state, double *unused, double *out_3380166226163199489) {
  H_31(state, unused, out_3380166226163199489);
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
