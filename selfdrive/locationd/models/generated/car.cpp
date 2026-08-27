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
void err_fun(double *nom_x, double *delta_x, double *out_6921687248411021200) {
   out_6921687248411021200[0] = delta_x[0] + nom_x[0];
   out_6921687248411021200[1] = delta_x[1] + nom_x[1];
   out_6921687248411021200[2] = delta_x[2] + nom_x[2];
   out_6921687248411021200[3] = delta_x[3] + nom_x[3];
   out_6921687248411021200[4] = delta_x[4] + nom_x[4];
   out_6921687248411021200[5] = delta_x[5] + nom_x[5];
   out_6921687248411021200[6] = delta_x[6] + nom_x[6];
   out_6921687248411021200[7] = delta_x[7] + nom_x[7];
   out_6921687248411021200[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_1531609997203188998) {
   out_1531609997203188998[0] = -nom_x[0] + true_x[0];
   out_1531609997203188998[1] = -nom_x[1] + true_x[1];
   out_1531609997203188998[2] = -nom_x[2] + true_x[2];
   out_1531609997203188998[3] = -nom_x[3] + true_x[3];
   out_1531609997203188998[4] = -nom_x[4] + true_x[4];
   out_1531609997203188998[5] = -nom_x[5] + true_x[5];
   out_1531609997203188998[6] = -nom_x[6] + true_x[6];
   out_1531609997203188998[7] = -nom_x[7] + true_x[7];
   out_1531609997203188998[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_67042187713662319) {
   out_67042187713662319[0] = 1.0;
   out_67042187713662319[1] = 0.0;
   out_67042187713662319[2] = 0.0;
   out_67042187713662319[3] = 0.0;
   out_67042187713662319[4] = 0.0;
   out_67042187713662319[5] = 0.0;
   out_67042187713662319[6] = 0.0;
   out_67042187713662319[7] = 0.0;
   out_67042187713662319[8] = 0.0;
   out_67042187713662319[9] = 0.0;
   out_67042187713662319[10] = 1.0;
   out_67042187713662319[11] = 0.0;
   out_67042187713662319[12] = 0.0;
   out_67042187713662319[13] = 0.0;
   out_67042187713662319[14] = 0.0;
   out_67042187713662319[15] = 0.0;
   out_67042187713662319[16] = 0.0;
   out_67042187713662319[17] = 0.0;
   out_67042187713662319[18] = 0.0;
   out_67042187713662319[19] = 0.0;
   out_67042187713662319[20] = 1.0;
   out_67042187713662319[21] = 0.0;
   out_67042187713662319[22] = 0.0;
   out_67042187713662319[23] = 0.0;
   out_67042187713662319[24] = 0.0;
   out_67042187713662319[25] = 0.0;
   out_67042187713662319[26] = 0.0;
   out_67042187713662319[27] = 0.0;
   out_67042187713662319[28] = 0.0;
   out_67042187713662319[29] = 0.0;
   out_67042187713662319[30] = 1.0;
   out_67042187713662319[31] = 0.0;
   out_67042187713662319[32] = 0.0;
   out_67042187713662319[33] = 0.0;
   out_67042187713662319[34] = 0.0;
   out_67042187713662319[35] = 0.0;
   out_67042187713662319[36] = 0.0;
   out_67042187713662319[37] = 0.0;
   out_67042187713662319[38] = 0.0;
   out_67042187713662319[39] = 0.0;
   out_67042187713662319[40] = 1.0;
   out_67042187713662319[41] = 0.0;
   out_67042187713662319[42] = 0.0;
   out_67042187713662319[43] = 0.0;
   out_67042187713662319[44] = 0.0;
   out_67042187713662319[45] = 0.0;
   out_67042187713662319[46] = 0.0;
   out_67042187713662319[47] = 0.0;
   out_67042187713662319[48] = 0.0;
   out_67042187713662319[49] = 0.0;
   out_67042187713662319[50] = 1.0;
   out_67042187713662319[51] = 0.0;
   out_67042187713662319[52] = 0.0;
   out_67042187713662319[53] = 0.0;
   out_67042187713662319[54] = 0.0;
   out_67042187713662319[55] = 0.0;
   out_67042187713662319[56] = 0.0;
   out_67042187713662319[57] = 0.0;
   out_67042187713662319[58] = 0.0;
   out_67042187713662319[59] = 0.0;
   out_67042187713662319[60] = 1.0;
   out_67042187713662319[61] = 0.0;
   out_67042187713662319[62] = 0.0;
   out_67042187713662319[63] = 0.0;
   out_67042187713662319[64] = 0.0;
   out_67042187713662319[65] = 0.0;
   out_67042187713662319[66] = 0.0;
   out_67042187713662319[67] = 0.0;
   out_67042187713662319[68] = 0.0;
   out_67042187713662319[69] = 0.0;
   out_67042187713662319[70] = 1.0;
   out_67042187713662319[71] = 0.0;
   out_67042187713662319[72] = 0.0;
   out_67042187713662319[73] = 0.0;
   out_67042187713662319[74] = 0.0;
   out_67042187713662319[75] = 0.0;
   out_67042187713662319[76] = 0.0;
   out_67042187713662319[77] = 0.0;
   out_67042187713662319[78] = 0.0;
   out_67042187713662319[79] = 0.0;
   out_67042187713662319[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_5979571664892016831) {
   out_5979571664892016831[0] = state[0];
   out_5979571664892016831[1] = state[1];
   out_5979571664892016831[2] = state[2];
   out_5979571664892016831[3] = state[3];
   out_5979571664892016831[4] = state[4];
   out_5979571664892016831[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8100000000000005*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_5979571664892016831[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_5979571664892016831[7] = state[7];
   out_5979571664892016831[8] = state[8];
}
void F_fun(double *state, double dt, double *out_4776924826301051446) {
   out_4776924826301051446[0] = 1;
   out_4776924826301051446[1] = 0;
   out_4776924826301051446[2] = 0;
   out_4776924826301051446[3] = 0;
   out_4776924826301051446[4] = 0;
   out_4776924826301051446[5] = 0;
   out_4776924826301051446[6] = 0;
   out_4776924826301051446[7] = 0;
   out_4776924826301051446[8] = 0;
   out_4776924826301051446[9] = 0;
   out_4776924826301051446[10] = 1;
   out_4776924826301051446[11] = 0;
   out_4776924826301051446[12] = 0;
   out_4776924826301051446[13] = 0;
   out_4776924826301051446[14] = 0;
   out_4776924826301051446[15] = 0;
   out_4776924826301051446[16] = 0;
   out_4776924826301051446[17] = 0;
   out_4776924826301051446[18] = 0;
   out_4776924826301051446[19] = 0;
   out_4776924826301051446[20] = 1;
   out_4776924826301051446[21] = 0;
   out_4776924826301051446[22] = 0;
   out_4776924826301051446[23] = 0;
   out_4776924826301051446[24] = 0;
   out_4776924826301051446[25] = 0;
   out_4776924826301051446[26] = 0;
   out_4776924826301051446[27] = 0;
   out_4776924826301051446[28] = 0;
   out_4776924826301051446[29] = 0;
   out_4776924826301051446[30] = 1;
   out_4776924826301051446[31] = 0;
   out_4776924826301051446[32] = 0;
   out_4776924826301051446[33] = 0;
   out_4776924826301051446[34] = 0;
   out_4776924826301051446[35] = 0;
   out_4776924826301051446[36] = 0;
   out_4776924826301051446[37] = 0;
   out_4776924826301051446[38] = 0;
   out_4776924826301051446[39] = 0;
   out_4776924826301051446[40] = 1;
   out_4776924826301051446[41] = 0;
   out_4776924826301051446[42] = 0;
   out_4776924826301051446[43] = 0;
   out_4776924826301051446[44] = 0;
   out_4776924826301051446[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_4776924826301051446[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_4776924826301051446[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_4776924826301051446[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_4776924826301051446[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_4776924826301051446[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_4776924826301051446[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_4776924826301051446[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_4776924826301051446[53] = -9.8100000000000005*dt;
   out_4776924826301051446[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_4776924826301051446[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_4776924826301051446[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4776924826301051446[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4776924826301051446[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_4776924826301051446[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_4776924826301051446[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_4776924826301051446[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4776924826301051446[62] = 0;
   out_4776924826301051446[63] = 0;
   out_4776924826301051446[64] = 0;
   out_4776924826301051446[65] = 0;
   out_4776924826301051446[66] = 0;
   out_4776924826301051446[67] = 0;
   out_4776924826301051446[68] = 0;
   out_4776924826301051446[69] = 0;
   out_4776924826301051446[70] = 1;
   out_4776924826301051446[71] = 0;
   out_4776924826301051446[72] = 0;
   out_4776924826301051446[73] = 0;
   out_4776924826301051446[74] = 0;
   out_4776924826301051446[75] = 0;
   out_4776924826301051446[76] = 0;
   out_4776924826301051446[77] = 0;
   out_4776924826301051446[78] = 0;
   out_4776924826301051446[79] = 0;
   out_4776924826301051446[80] = 1;
}
void h_25(double *state, double *unused, double *out_5600998109952287910) {
   out_5600998109952287910[0] = state[6];
}
void H_25(double *state, double *unused, double *out_9186513660083652060) {
   out_9186513660083652060[0] = 0;
   out_9186513660083652060[1] = 0;
   out_9186513660083652060[2] = 0;
   out_9186513660083652060[3] = 0;
   out_9186513660083652060[4] = 0;
   out_9186513660083652060[5] = 0;
   out_9186513660083652060[6] = 1;
   out_9186513660083652060[7] = 0;
   out_9186513660083652060[8] = 0;
}
void h_24(double *state, double *unused, double *out_2653523787842120254) {
   out_2653523787842120254[0] = state[4];
   out_2653523787842120254[1] = state[5];
}
void H_24(double *state, double *unused, double *out_32165227556704331) {
   out_32165227556704331[0] = 0;
   out_32165227556704331[1] = 0;
   out_32165227556704331[2] = 0;
   out_32165227556704331[3] = 0;
   out_32165227556704331[4] = 1;
   out_32165227556704331[5] = 0;
   out_32165227556704331[6] = 0;
   out_32165227556704331[7] = 0;
   out_32165227556704331[8] = 0;
   out_32165227556704331[9] = 0;
   out_32165227556704331[10] = 0;
   out_32165227556704331[11] = 0;
   out_32165227556704331[12] = 0;
   out_32165227556704331[13] = 0;
   out_32165227556704331[14] = 1;
   out_32165227556704331[15] = 0;
   out_32165227556704331[16] = 0;
   out_32165227556704331[17] = 0;
}
void h_30(double *state, double *unused, double *out_9208296435503241356) {
   out_9208296435503241356[0] = state[4];
}
void H_30(double *state, double *unused, double *out_4658817329956043862) {
   out_4658817329956043862[0] = 0;
   out_4658817329956043862[1] = 0;
   out_4658817329956043862[2] = 0;
   out_4658817329956043862[3] = 0;
   out_4658817329956043862[4] = 1;
   out_4658817329956043862[5] = 0;
   out_4658817329956043862[6] = 0;
   out_4658817329956043862[7] = 0;
   out_4658817329956043862[8] = 0;
}
void h_26(double *state, double *unused, double *out_226327263496400591) {
   out_226327263496400591[0] = state[7];
}
void H_26(double *state, double *unused, double *out_5445010341209595836) {
   out_5445010341209595836[0] = 0;
   out_5445010341209595836[1] = 0;
   out_5445010341209595836[2] = 0;
   out_5445010341209595836[3] = 0;
   out_5445010341209595836[4] = 0;
   out_5445010341209595836[5] = 0;
   out_5445010341209595836[6] = 0;
   out_5445010341209595836[7] = 1;
   out_5445010341209595836[8] = 0;
}
void h_27(double *state, double *unused, double *out_6358848255113106720) {
   out_6358848255113106720[0] = state[3];
}
void H_27(double *state, double *unused, double *out_2484054018155618951) {
   out_2484054018155618951[0] = 0;
   out_2484054018155618951[1] = 0;
   out_2484054018155618951[2] = 0;
   out_2484054018155618951[3] = 1;
   out_2484054018155618951[4] = 0;
   out_2484054018155618951[5] = 0;
   out_2484054018155618951[6] = 0;
   out_2484054018155618951[7] = 0;
   out_2484054018155618951[8] = 0;
}
void h_29(double *state, double *unused, double *out_4206623167842395711) {
   out_4206623167842395711[0] = state[1];
}
void H_29(double *state, double *unused, double *out_5169048674270436046) {
   out_5169048674270436046[0] = 0;
   out_5169048674270436046[1] = 1;
   out_5169048674270436046[2] = 0;
   out_5169048674270436046[3] = 0;
   out_5169048674270436046[4] = 0;
   out_5169048674270436046[5] = 0;
   out_5169048674270436046[6] = 0;
   out_5169048674270436046[7] = 0;
   out_5169048674270436046[8] = 0;
}
void h_28(double *state, double *unused, double *out_873764223772274265) {
   out_873764223772274265[0] = state[0];
}
void H_28(double *state, double *unused, double *out_86649657200905472) {
   out_86649657200905472[0] = 1;
   out_86649657200905472[1] = 0;
   out_86649657200905472[2] = 0;
   out_86649657200905472[3] = 0;
   out_86649657200905472[4] = 0;
   out_86649657200905472[5] = 0;
   out_86649657200905472[6] = 0;
   out_86649657200905472[7] = 0;
   out_86649657200905472[8] = 0;
}
void h_31(double *state, double *unused, double *out_2807806380081144242) {
   out_2807806380081144242[0] = state[8];
}
void H_31(double *state, double *unused, double *out_4818802238976244360) {
   out_4818802238976244360[0] = 0;
   out_4818802238976244360[1] = 0;
   out_4818802238976244360[2] = 0;
   out_4818802238976244360[3] = 0;
   out_4818802238976244360[4] = 0;
   out_4818802238976244360[5] = 0;
   out_4818802238976244360[6] = 0;
   out_4818802238976244360[7] = 0;
   out_4818802238976244360[8] = 1;
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
void car_err_fun(double *nom_x, double *delta_x, double *out_6921687248411021200) {
  err_fun(nom_x, delta_x, out_6921687248411021200);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_1531609997203188998) {
  inv_err_fun(nom_x, true_x, out_1531609997203188998);
}
void car_H_mod_fun(double *state, double *out_67042187713662319) {
  H_mod_fun(state, out_67042187713662319);
}
void car_f_fun(double *state, double dt, double *out_5979571664892016831) {
  f_fun(state,  dt, out_5979571664892016831);
}
void car_F_fun(double *state, double dt, double *out_4776924826301051446) {
  F_fun(state,  dt, out_4776924826301051446);
}
void car_h_25(double *state, double *unused, double *out_5600998109952287910) {
  h_25(state, unused, out_5600998109952287910);
}
void car_H_25(double *state, double *unused, double *out_9186513660083652060) {
  H_25(state, unused, out_9186513660083652060);
}
void car_h_24(double *state, double *unused, double *out_2653523787842120254) {
  h_24(state, unused, out_2653523787842120254);
}
void car_H_24(double *state, double *unused, double *out_32165227556704331) {
  H_24(state, unused, out_32165227556704331);
}
void car_h_30(double *state, double *unused, double *out_9208296435503241356) {
  h_30(state, unused, out_9208296435503241356);
}
void car_H_30(double *state, double *unused, double *out_4658817329956043862) {
  H_30(state, unused, out_4658817329956043862);
}
void car_h_26(double *state, double *unused, double *out_226327263496400591) {
  h_26(state, unused, out_226327263496400591);
}
void car_H_26(double *state, double *unused, double *out_5445010341209595836) {
  H_26(state, unused, out_5445010341209595836);
}
void car_h_27(double *state, double *unused, double *out_6358848255113106720) {
  h_27(state, unused, out_6358848255113106720);
}
void car_H_27(double *state, double *unused, double *out_2484054018155618951) {
  H_27(state, unused, out_2484054018155618951);
}
void car_h_29(double *state, double *unused, double *out_4206623167842395711) {
  h_29(state, unused, out_4206623167842395711);
}
void car_H_29(double *state, double *unused, double *out_5169048674270436046) {
  H_29(state, unused, out_5169048674270436046);
}
void car_h_28(double *state, double *unused, double *out_873764223772274265) {
  h_28(state, unused, out_873764223772274265);
}
void car_H_28(double *state, double *unused, double *out_86649657200905472) {
  H_28(state, unused, out_86649657200905472);
}
void car_h_31(double *state, double *unused, double *out_2807806380081144242) {
  h_31(state, unused, out_2807806380081144242);
}
void car_H_31(double *state, double *unused, double *out_4818802238976244360) {
  H_31(state, unused, out_4818802238976244360);
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
