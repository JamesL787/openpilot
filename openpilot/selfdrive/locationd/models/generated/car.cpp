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
void err_fun(double *nom_x, double *delta_x, double *out_1495263378523690277) {
   out_1495263378523690277[0] = delta_x[0] + nom_x[0];
   out_1495263378523690277[1] = delta_x[1] + nom_x[1];
   out_1495263378523690277[2] = delta_x[2] + nom_x[2];
   out_1495263378523690277[3] = delta_x[3] + nom_x[3];
   out_1495263378523690277[4] = delta_x[4] + nom_x[4];
   out_1495263378523690277[5] = delta_x[5] + nom_x[5];
   out_1495263378523690277[6] = delta_x[6] + nom_x[6];
   out_1495263378523690277[7] = delta_x[7] + nom_x[7];
   out_1495263378523690277[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_2358391450812481082) {
   out_2358391450812481082[0] = -nom_x[0] + true_x[0];
   out_2358391450812481082[1] = -nom_x[1] + true_x[1];
   out_2358391450812481082[2] = -nom_x[2] + true_x[2];
   out_2358391450812481082[3] = -nom_x[3] + true_x[3];
   out_2358391450812481082[4] = -nom_x[4] + true_x[4];
   out_2358391450812481082[5] = -nom_x[5] + true_x[5];
   out_2358391450812481082[6] = -nom_x[6] + true_x[6];
   out_2358391450812481082[7] = -nom_x[7] + true_x[7];
   out_2358391450812481082[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_1304167992607751194) {
   out_1304167992607751194[0] = 1.0;
   out_1304167992607751194[1] = 0.0;
   out_1304167992607751194[2] = 0.0;
   out_1304167992607751194[3] = 0.0;
   out_1304167992607751194[4] = 0.0;
   out_1304167992607751194[5] = 0.0;
   out_1304167992607751194[6] = 0.0;
   out_1304167992607751194[7] = 0.0;
   out_1304167992607751194[8] = 0.0;
   out_1304167992607751194[9] = 0.0;
   out_1304167992607751194[10] = 1.0;
   out_1304167992607751194[11] = 0.0;
   out_1304167992607751194[12] = 0.0;
   out_1304167992607751194[13] = 0.0;
   out_1304167992607751194[14] = 0.0;
   out_1304167992607751194[15] = 0.0;
   out_1304167992607751194[16] = 0.0;
   out_1304167992607751194[17] = 0.0;
   out_1304167992607751194[18] = 0.0;
   out_1304167992607751194[19] = 0.0;
   out_1304167992607751194[20] = 1.0;
   out_1304167992607751194[21] = 0.0;
   out_1304167992607751194[22] = 0.0;
   out_1304167992607751194[23] = 0.0;
   out_1304167992607751194[24] = 0.0;
   out_1304167992607751194[25] = 0.0;
   out_1304167992607751194[26] = 0.0;
   out_1304167992607751194[27] = 0.0;
   out_1304167992607751194[28] = 0.0;
   out_1304167992607751194[29] = 0.0;
   out_1304167992607751194[30] = 1.0;
   out_1304167992607751194[31] = 0.0;
   out_1304167992607751194[32] = 0.0;
   out_1304167992607751194[33] = 0.0;
   out_1304167992607751194[34] = 0.0;
   out_1304167992607751194[35] = 0.0;
   out_1304167992607751194[36] = 0.0;
   out_1304167992607751194[37] = 0.0;
   out_1304167992607751194[38] = 0.0;
   out_1304167992607751194[39] = 0.0;
   out_1304167992607751194[40] = 1.0;
   out_1304167992607751194[41] = 0.0;
   out_1304167992607751194[42] = 0.0;
   out_1304167992607751194[43] = 0.0;
   out_1304167992607751194[44] = 0.0;
   out_1304167992607751194[45] = 0.0;
   out_1304167992607751194[46] = 0.0;
   out_1304167992607751194[47] = 0.0;
   out_1304167992607751194[48] = 0.0;
   out_1304167992607751194[49] = 0.0;
   out_1304167992607751194[50] = 1.0;
   out_1304167992607751194[51] = 0.0;
   out_1304167992607751194[52] = 0.0;
   out_1304167992607751194[53] = 0.0;
   out_1304167992607751194[54] = 0.0;
   out_1304167992607751194[55] = 0.0;
   out_1304167992607751194[56] = 0.0;
   out_1304167992607751194[57] = 0.0;
   out_1304167992607751194[58] = 0.0;
   out_1304167992607751194[59] = 0.0;
   out_1304167992607751194[60] = 1.0;
   out_1304167992607751194[61] = 0.0;
   out_1304167992607751194[62] = 0.0;
   out_1304167992607751194[63] = 0.0;
   out_1304167992607751194[64] = 0.0;
   out_1304167992607751194[65] = 0.0;
   out_1304167992607751194[66] = 0.0;
   out_1304167992607751194[67] = 0.0;
   out_1304167992607751194[68] = 0.0;
   out_1304167992607751194[69] = 0.0;
   out_1304167992607751194[70] = 1.0;
   out_1304167992607751194[71] = 0.0;
   out_1304167992607751194[72] = 0.0;
   out_1304167992607751194[73] = 0.0;
   out_1304167992607751194[74] = 0.0;
   out_1304167992607751194[75] = 0.0;
   out_1304167992607751194[76] = 0.0;
   out_1304167992607751194[77] = 0.0;
   out_1304167992607751194[78] = 0.0;
   out_1304167992607751194[79] = 0.0;
   out_1304167992607751194[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_7182131393785703688) {
   out_7182131393785703688[0] = state[0];
   out_7182131393785703688[1] = state[1];
   out_7182131393785703688[2] = state[2];
   out_7182131393785703688[3] = state[3];
   out_7182131393785703688[4] = state[4];
   out_7182131393785703688[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8100000000000005*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_7182131393785703688[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_7182131393785703688[7] = state[7];
   out_7182131393785703688[8] = state[8];
}
void F_fun(double *state, double dt, double *out_8516390100549633734) {
   out_8516390100549633734[0] = 1;
   out_8516390100549633734[1] = 0;
   out_8516390100549633734[2] = 0;
   out_8516390100549633734[3] = 0;
   out_8516390100549633734[4] = 0;
   out_8516390100549633734[5] = 0;
   out_8516390100549633734[6] = 0;
   out_8516390100549633734[7] = 0;
   out_8516390100549633734[8] = 0;
   out_8516390100549633734[9] = 0;
   out_8516390100549633734[10] = 1;
   out_8516390100549633734[11] = 0;
   out_8516390100549633734[12] = 0;
   out_8516390100549633734[13] = 0;
   out_8516390100549633734[14] = 0;
   out_8516390100549633734[15] = 0;
   out_8516390100549633734[16] = 0;
   out_8516390100549633734[17] = 0;
   out_8516390100549633734[18] = 0;
   out_8516390100549633734[19] = 0;
   out_8516390100549633734[20] = 1;
   out_8516390100549633734[21] = 0;
   out_8516390100549633734[22] = 0;
   out_8516390100549633734[23] = 0;
   out_8516390100549633734[24] = 0;
   out_8516390100549633734[25] = 0;
   out_8516390100549633734[26] = 0;
   out_8516390100549633734[27] = 0;
   out_8516390100549633734[28] = 0;
   out_8516390100549633734[29] = 0;
   out_8516390100549633734[30] = 1;
   out_8516390100549633734[31] = 0;
   out_8516390100549633734[32] = 0;
   out_8516390100549633734[33] = 0;
   out_8516390100549633734[34] = 0;
   out_8516390100549633734[35] = 0;
   out_8516390100549633734[36] = 0;
   out_8516390100549633734[37] = 0;
   out_8516390100549633734[38] = 0;
   out_8516390100549633734[39] = 0;
   out_8516390100549633734[40] = 1;
   out_8516390100549633734[41] = 0;
   out_8516390100549633734[42] = 0;
   out_8516390100549633734[43] = 0;
   out_8516390100549633734[44] = 0;
   out_8516390100549633734[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_8516390100549633734[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_8516390100549633734[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_8516390100549633734[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_8516390100549633734[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_8516390100549633734[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_8516390100549633734[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_8516390100549633734[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_8516390100549633734[53] = -9.8100000000000005*dt;
   out_8516390100549633734[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_8516390100549633734[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_8516390100549633734[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8516390100549633734[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8516390100549633734[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_8516390100549633734[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_8516390100549633734[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_8516390100549633734[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8516390100549633734[62] = 0;
   out_8516390100549633734[63] = 0;
   out_8516390100549633734[64] = 0;
   out_8516390100549633734[65] = 0;
   out_8516390100549633734[66] = 0;
   out_8516390100549633734[67] = 0;
   out_8516390100549633734[68] = 0;
   out_8516390100549633734[69] = 0;
   out_8516390100549633734[70] = 1;
   out_8516390100549633734[71] = 0;
   out_8516390100549633734[72] = 0;
   out_8516390100549633734[73] = 0;
   out_8516390100549633734[74] = 0;
   out_8516390100549633734[75] = 0;
   out_8516390100549633734[76] = 0;
   out_8516390100549633734[77] = 0;
   out_8516390100549633734[78] = 0;
   out_8516390100549633734[79] = 0;
   out_8516390100549633734[80] = 1;
}
void h_25(double *state, double *unused, double *out_1389136709106931389) {
   out_1389136709106931389[0] = state[6];
}
void H_25(double *state, double *unused, double *out_6207859817792416034) {
   out_6207859817792416034[0] = 0;
   out_6207859817792416034[1] = 0;
   out_6207859817792416034[2] = 0;
   out_6207859817792416034[3] = 0;
   out_6207859817792416034[4] = 0;
   out_6207859817792416034[5] = 0;
   out_6207859817792416034[6] = 1;
   out_6207859817792416034[7] = 0;
   out_6207859817792416034[8] = 0;
}
void h_24(double *state, double *unused, double *out_7393409419771565291) {
   out_7393409419771565291[0] = state[4];
   out_7393409419771565291[1] = state[5];
}
void H_24(double *state, double *unused, double *out_2654499043591743305) {
   out_2654499043591743305[0] = 0;
   out_2654499043591743305[1] = 0;
   out_2654499043591743305[2] = 0;
   out_2654499043591743305[3] = 0;
   out_2654499043591743305[4] = 1;
   out_2654499043591743305[5] = 0;
   out_2654499043591743305[6] = 0;
   out_2654499043591743305[7] = 0;
   out_2654499043591743305[8] = 0;
   out_2654499043591743305[9] = 0;
   out_2654499043591743305[10] = 0;
   out_2654499043591743305[11] = 0;
   out_2654499043591743305[12] = 0;
   out_2654499043591743305[13] = 0;
   out_2654499043591743305[14] = 1;
   out_2654499043591743305[15] = 0;
   out_2654499043591743305[16] = 0;
   out_2654499043591743305[17] = 0;
}
void h_30(double *state, double *unused, double *out_5198691217369363774) {
   out_5198691217369363774[0] = state[4];
}
void H_30(double *state, double *unused, double *out_8726192776299664661) {
   out_8726192776299664661[0] = 0;
   out_8726192776299664661[1] = 0;
   out_8726192776299664661[2] = 0;
   out_8726192776299664661[3] = 0;
   out_8726192776299664661[4] = 1;
   out_8726192776299664661[5] = 0;
   out_8726192776299664661[6] = 0;
   out_8726192776299664661[7] = 0;
   out_8726192776299664661[8] = 0;
}
void h_26(double *state, double *unused, double *out_7906185620454157279) {
   out_7906185620454157279[0] = state[7];
}
void H_26(double *state, double *unused, double *out_8934358286156334981) {
   out_8934358286156334981[0] = 0;
   out_8934358286156334981[1] = 0;
   out_8934358286156334981[2] = 0;
   out_8934358286156334981[3] = 0;
   out_8934358286156334981[4] = 0;
   out_8934358286156334981[5] = 0;
   out_8934358286156334981[6] = 0;
   out_8934358286156334981[7] = 1;
   out_8934358286156334981[8] = 0;
}
void h_27(double *state, double *unused, double *out_3993542029915629040) {
   out_3993542029915629040[0] = state[3];
}
void H_27(double *state, double *unused, double *out_6551429464499239750) {
   out_6551429464499239750[0] = 0;
   out_6551429464499239750[1] = 0;
   out_6551429464499239750[2] = 0;
   out_6551429464499239750[3] = 1;
   out_6551429464499239750[4] = 0;
   out_6551429464499239750[5] = 0;
   out_6551429464499239750[6] = 0;
   out_6551429464499239750[7] = 0;
   out_6551429464499239750[8] = 0;
}
void h_29(double *state, double *unused, double *out_8246379588679342197) {
   out_8246379588679342197[0] = state[1];
}
void H_29(double *state, double *unused, double *out_9210319953095494771) {
   out_9210319953095494771[0] = 0;
   out_9210319953095494771[1] = 1;
   out_9210319953095494771[2] = 0;
   out_9210319953095494771[3] = 0;
   out_9210319953095494771[4] = 0;
   out_9210319953095494771[5] = 0;
   out_9210319953095494771[6] = 0;
   out_9210319953095494771[7] = 0;
   out_9210319953095494771[8] = 0;
}
void h_28(double *state, double *unused, double *out_3390226145239151523) {
   out_3390226145239151523[0] = state[0];
}
void H_28(double *state, double *unused, double *out_4154025103544526271) {
   out_4154025103544526271[0] = 1;
   out_4154025103544526271[1] = 0;
   out_4154025103544526271[2] = 0;
   out_4154025103544526271[3] = 0;
   out_4154025103544526271[4] = 0;
   out_4154025103544526271[5] = 0;
   out_4154025103544526271[6] = 0;
   out_4154025103544526271[7] = 0;
   out_4154025103544526271[8] = 0;
}
void h_31(double *state, double *unused, double *out_1231950040755802244) {
   out_1231950040755802244[0] = state[8];
}
void H_31(double *state, double *unused, double *out_8886177685319865159) {
   out_8886177685319865159[0] = 0;
   out_8886177685319865159[1] = 0;
   out_8886177685319865159[2] = 0;
   out_8886177685319865159[3] = 0;
   out_8886177685319865159[4] = 0;
   out_8886177685319865159[5] = 0;
   out_8886177685319865159[6] = 0;
   out_8886177685319865159[7] = 0;
   out_8886177685319865159[8] = 1;
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
void car_err_fun(double *nom_x, double *delta_x, double *out_1495263378523690277) {
  err_fun(nom_x, delta_x, out_1495263378523690277);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_2358391450812481082) {
  inv_err_fun(nom_x, true_x, out_2358391450812481082);
}
void car_H_mod_fun(double *state, double *out_1304167992607751194) {
  H_mod_fun(state, out_1304167992607751194);
}
void car_f_fun(double *state, double dt, double *out_7182131393785703688) {
  f_fun(state,  dt, out_7182131393785703688);
}
void car_F_fun(double *state, double dt, double *out_8516390100549633734) {
  F_fun(state,  dt, out_8516390100549633734);
}
void car_h_25(double *state, double *unused, double *out_1389136709106931389) {
  h_25(state, unused, out_1389136709106931389);
}
void car_H_25(double *state, double *unused, double *out_6207859817792416034) {
  H_25(state, unused, out_6207859817792416034);
}
void car_h_24(double *state, double *unused, double *out_7393409419771565291) {
  h_24(state, unused, out_7393409419771565291);
}
void car_H_24(double *state, double *unused, double *out_2654499043591743305) {
  H_24(state, unused, out_2654499043591743305);
}
void car_h_30(double *state, double *unused, double *out_5198691217369363774) {
  h_30(state, unused, out_5198691217369363774);
}
void car_H_30(double *state, double *unused, double *out_8726192776299664661) {
  H_30(state, unused, out_8726192776299664661);
}
void car_h_26(double *state, double *unused, double *out_7906185620454157279) {
  h_26(state, unused, out_7906185620454157279);
}
void car_H_26(double *state, double *unused, double *out_8934358286156334981) {
  H_26(state, unused, out_8934358286156334981);
}
void car_h_27(double *state, double *unused, double *out_3993542029915629040) {
  h_27(state, unused, out_3993542029915629040);
}
void car_H_27(double *state, double *unused, double *out_6551429464499239750) {
  H_27(state, unused, out_6551429464499239750);
}
void car_h_29(double *state, double *unused, double *out_8246379588679342197) {
  h_29(state, unused, out_8246379588679342197);
}
void car_H_29(double *state, double *unused, double *out_9210319953095494771) {
  H_29(state, unused, out_9210319953095494771);
}
void car_h_28(double *state, double *unused, double *out_3390226145239151523) {
  h_28(state, unused, out_3390226145239151523);
}
void car_H_28(double *state, double *unused, double *out_4154025103544526271) {
  H_28(state, unused, out_4154025103544526271);
}
void car_h_31(double *state, double *unused, double *out_1231950040755802244) {
  h_31(state, unused, out_1231950040755802244);
}
void car_H_31(double *state, double *unused, double *out_8886177685319865159) {
  H_31(state, unused, out_8886177685319865159);
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
