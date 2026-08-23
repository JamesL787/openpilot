#include "pose.h"

namespace {
#define DIM 18
#define EDIM 18
#define MEDIM 18
typedef void (*Hfun)(double *, double *, double *);
const static double MAHA_THRESH_4 = 7.814727903251177;
const static double MAHA_THRESH_10 = 7.814727903251177;
const static double MAHA_THRESH_13 = 7.814727903251177;
const static double MAHA_THRESH_14 = 7.814727903251177;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_6947624313872495524) {
   out_6947624313872495524[0] = delta_x[0] + nom_x[0];
   out_6947624313872495524[1] = delta_x[1] + nom_x[1];
   out_6947624313872495524[2] = delta_x[2] + nom_x[2];
   out_6947624313872495524[3] = delta_x[3] + nom_x[3];
   out_6947624313872495524[4] = delta_x[4] + nom_x[4];
   out_6947624313872495524[5] = delta_x[5] + nom_x[5];
   out_6947624313872495524[6] = delta_x[6] + nom_x[6];
   out_6947624313872495524[7] = delta_x[7] + nom_x[7];
   out_6947624313872495524[8] = delta_x[8] + nom_x[8];
   out_6947624313872495524[9] = delta_x[9] + nom_x[9];
   out_6947624313872495524[10] = delta_x[10] + nom_x[10];
   out_6947624313872495524[11] = delta_x[11] + nom_x[11];
   out_6947624313872495524[12] = delta_x[12] + nom_x[12];
   out_6947624313872495524[13] = delta_x[13] + nom_x[13];
   out_6947624313872495524[14] = delta_x[14] + nom_x[14];
   out_6947624313872495524[15] = delta_x[15] + nom_x[15];
   out_6947624313872495524[16] = delta_x[16] + nom_x[16];
   out_6947624313872495524[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_6870382180897404022) {
   out_6870382180897404022[0] = -nom_x[0] + true_x[0];
   out_6870382180897404022[1] = -nom_x[1] + true_x[1];
   out_6870382180897404022[2] = -nom_x[2] + true_x[2];
   out_6870382180897404022[3] = -nom_x[3] + true_x[3];
   out_6870382180897404022[4] = -nom_x[4] + true_x[4];
   out_6870382180897404022[5] = -nom_x[5] + true_x[5];
   out_6870382180897404022[6] = -nom_x[6] + true_x[6];
   out_6870382180897404022[7] = -nom_x[7] + true_x[7];
   out_6870382180897404022[8] = -nom_x[8] + true_x[8];
   out_6870382180897404022[9] = -nom_x[9] + true_x[9];
   out_6870382180897404022[10] = -nom_x[10] + true_x[10];
   out_6870382180897404022[11] = -nom_x[11] + true_x[11];
   out_6870382180897404022[12] = -nom_x[12] + true_x[12];
   out_6870382180897404022[13] = -nom_x[13] + true_x[13];
   out_6870382180897404022[14] = -nom_x[14] + true_x[14];
   out_6870382180897404022[15] = -nom_x[15] + true_x[15];
   out_6870382180897404022[16] = -nom_x[16] + true_x[16];
   out_6870382180897404022[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_7211163890878107353) {
   out_7211163890878107353[0] = 1.0;
   out_7211163890878107353[1] = 0.0;
   out_7211163890878107353[2] = 0.0;
   out_7211163890878107353[3] = 0.0;
   out_7211163890878107353[4] = 0.0;
   out_7211163890878107353[5] = 0.0;
   out_7211163890878107353[6] = 0.0;
   out_7211163890878107353[7] = 0.0;
   out_7211163890878107353[8] = 0.0;
   out_7211163890878107353[9] = 0.0;
   out_7211163890878107353[10] = 0.0;
   out_7211163890878107353[11] = 0.0;
   out_7211163890878107353[12] = 0.0;
   out_7211163890878107353[13] = 0.0;
   out_7211163890878107353[14] = 0.0;
   out_7211163890878107353[15] = 0.0;
   out_7211163890878107353[16] = 0.0;
   out_7211163890878107353[17] = 0.0;
   out_7211163890878107353[18] = 0.0;
   out_7211163890878107353[19] = 1.0;
   out_7211163890878107353[20] = 0.0;
   out_7211163890878107353[21] = 0.0;
   out_7211163890878107353[22] = 0.0;
   out_7211163890878107353[23] = 0.0;
   out_7211163890878107353[24] = 0.0;
   out_7211163890878107353[25] = 0.0;
   out_7211163890878107353[26] = 0.0;
   out_7211163890878107353[27] = 0.0;
   out_7211163890878107353[28] = 0.0;
   out_7211163890878107353[29] = 0.0;
   out_7211163890878107353[30] = 0.0;
   out_7211163890878107353[31] = 0.0;
   out_7211163890878107353[32] = 0.0;
   out_7211163890878107353[33] = 0.0;
   out_7211163890878107353[34] = 0.0;
   out_7211163890878107353[35] = 0.0;
   out_7211163890878107353[36] = 0.0;
   out_7211163890878107353[37] = 0.0;
   out_7211163890878107353[38] = 1.0;
   out_7211163890878107353[39] = 0.0;
   out_7211163890878107353[40] = 0.0;
   out_7211163890878107353[41] = 0.0;
   out_7211163890878107353[42] = 0.0;
   out_7211163890878107353[43] = 0.0;
   out_7211163890878107353[44] = 0.0;
   out_7211163890878107353[45] = 0.0;
   out_7211163890878107353[46] = 0.0;
   out_7211163890878107353[47] = 0.0;
   out_7211163890878107353[48] = 0.0;
   out_7211163890878107353[49] = 0.0;
   out_7211163890878107353[50] = 0.0;
   out_7211163890878107353[51] = 0.0;
   out_7211163890878107353[52] = 0.0;
   out_7211163890878107353[53] = 0.0;
   out_7211163890878107353[54] = 0.0;
   out_7211163890878107353[55] = 0.0;
   out_7211163890878107353[56] = 0.0;
   out_7211163890878107353[57] = 1.0;
   out_7211163890878107353[58] = 0.0;
   out_7211163890878107353[59] = 0.0;
   out_7211163890878107353[60] = 0.0;
   out_7211163890878107353[61] = 0.0;
   out_7211163890878107353[62] = 0.0;
   out_7211163890878107353[63] = 0.0;
   out_7211163890878107353[64] = 0.0;
   out_7211163890878107353[65] = 0.0;
   out_7211163890878107353[66] = 0.0;
   out_7211163890878107353[67] = 0.0;
   out_7211163890878107353[68] = 0.0;
   out_7211163890878107353[69] = 0.0;
   out_7211163890878107353[70] = 0.0;
   out_7211163890878107353[71] = 0.0;
   out_7211163890878107353[72] = 0.0;
   out_7211163890878107353[73] = 0.0;
   out_7211163890878107353[74] = 0.0;
   out_7211163890878107353[75] = 0.0;
   out_7211163890878107353[76] = 1.0;
   out_7211163890878107353[77] = 0.0;
   out_7211163890878107353[78] = 0.0;
   out_7211163890878107353[79] = 0.0;
   out_7211163890878107353[80] = 0.0;
   out_7211163890878107353[81] = 0.0;
   out_7211163890878107353[82] = 0.0;
   out_7211163890878107353[83] = 0.0;
   out_7211163890878107353[84] = 0.0;
   out_7211163890878107353[85] = 0.0;
   out_7211163890878107353[86] = 0.0;
   out_7211163890878107353[87] = 0.0;
   out_7211163890878107353[88] = 0.0;
   out_7211163890878107353[89] = 0.0;
   out_7211163890878107353[90] = 0.0;
   out_7211163890878107353[91] = 0.0;
   out_7211163890878107353[92] = 0.0;
   out_7211163890878107353[93] = 0.0;
   out_7211163890878107353[94] = 0.0;
   out_7211163890878107353[95] = 1.0;
   out_7211163890878107353[96] = 0.0;
   out_7211163890878107353[97] = 0.0;
   out_7211163890878107353[98] = 0.0;
   out_7211163890878107353[99] = 0.0;
   out_7211163890878107353[100] = 0.0;
   out_7211163890878107353[101] = 0.0;
   out_7211163890878107353[102] = 0.0;
   out_7211163890878107353[103] = 0.0;
   out_7211163890878107353[104] = 0.0;
   out_7211163890878107353[105] = 0.0;
   out_7211163890878107353[106] = 0.0;
   out_7211163890878107353[107] = 0.0;
   out_7211163890878107353[108] = 0.0;
   out_7211163890878107353[109] = 0.0;
   out_7211163890878107353[110] = 0.0;
   out_7211163890878107353[111] = 0.0;
   out_7211163890878107353[112] = 0.0;
   out_7211163890878107353[113] = 0.0;
   out_7211163890878107353[114] = 1.0;
   out_7211163890878107353[115] = 0.0;
   out_7211163890878107353[116] = 0.0;
   out_7211163890878107353[117] = 0.0;
   out_7211163890878107353[118] = 0.0;
   out_7211163890878107353[119] = 0.0;
   out_7211163890878107353[120] = 0.0;
   out_7211163890878107353[121] = 0.0;
   out_7211163890878107353[122] = 0.0;
   out_7211163890878107353[123] = 0.0;
   out_7211163890878107353[124] = 0.0;
   out_7211163890878107353[125] = 0.0;
   out_7211163890878107353[126] = 0.0;
   out_7211163890878107353[127] = 0.0;
   out_7211163890878107353[128] = 0.0;
   out_7211163890878107353[129] = 0.0;
   out_7211163890878107353[130] = 0.0;
   out_7211163890878107353[131] = 0.0;
   out_7211163890878107353[132] = 0.0;
   out_7211163890878107353[133] = 1.0;
   out_7211163890878107353[134] = 0.0;
   out_7211163890878107353[135] = 0.0;
   out_7211163890878107353[136] = 0.0;
   out_7211163890878107353[137] = 0.0;
   out_7211163890878107353[138] = 0.0;
   out_7211163890878107353[139] = 0.0;
   out_7211163890878107353[140] = 0.0;
   out_7211163890878107353[141] = 0.0;
   out_7211163890878107353[142] = 0.0;
   out_7211163890878107353[143] = 0.0;
   out_7211163890878107353[144] = 0.0;
   out_7211163890878107353[145] = 0.0;
   out_7211163890878107353[146] = 0.0;
   out_7211163890878107353[147] = 0.0;
   out_7211163890878107353[148] = 0.0;
   out_7211163890878107353[149] = 0.0;
   out_7211163890878107353[150] = 0.0;
   out_7211163890878107353[151] = 0.0;
   out_7211163890878107353[152] = 1.0;
   out_7211163890878107353[153] = 0.0;
   out_7211163890878107353[154] = 0.0;
   out_7211163890878107353[155] = 0.0;
   out_7211163890878107353[156] = 0.0;
   out_7211163890878107353[157] = 0.0;
   out_7211163890878107353[158] = 0.0;
   out_7211163890878107353[159] = 0.0;
   out_7211163890878107353[160] = 0.0;
   out_7211163890878107353[161] = 0.0;
   out_7211163890878107353[162] = 0.0;
   out_7211163890878107353[163] = 0.0;
   out_7211163890878107353[164] = 0.0;
   out_7211163890878107353[165] = 0.0;
   out_7211163890878107353[166] = 0.0;
   out_7211163890878107353[167] = 0.0;
   out_7211163890878107353[168] = 0.0;
   out_7211163890878107353[169] = 0.0;
   out_7211163890878107353[170] = 0.0;
   out_7211163890878107353[171] = 1.0;
   out_7211163890878107353[172] = 0.0;
   out_7211163890878107353[173] = 0.0;
   out_7211163890878107353[174] = 0.0;
   out_7211163890878107353[175] = 0.0;
   out_7211163890878107353[176] = 0.0;
   out_7211163890878107353[177] = 0.0;
   out_7211163890878107353[178] = 0.0;
   out_7211163890878107353[179] = 0.0;
   out_7211163890878107353[180] = 0.0;
   out_7211163890878107353[181] = 0.0;
   out_7211163890878107353[182] = 0.0;
   out_7211163890878107353[183] = 0.0;
   out_7211163890878107353[184] = 0.0;
   out_7211163890878107353[185] = 0.0;
   out_7211163890878107353[186] = 0.0;
   out_7211163890878107353[187] = 0.0;
   out_7211163890878107353[188] = 0.0;
   out_7211163890878107353[189] = 0.0;
   out_7211163890878107353[190] = 1.0;
   out_7211163890878107353[191] = 0.0;
   out_7211163890878107353[192] = 0.0;
   out_7211163890878107353[193] = 0.0;
   out_7211163890878107353[194] = 0.0;
   out_7211163890878107353[195] = 0.0;
   out_7211163890878107353[196] = 0.0;
   out_7211163890878107353[197] = 0.0;
   out_7211163890878107353[198] = 0.0;
   out_7211163890878107353[199] = 0.0;
   out_7211163890878107353[200] = 0.0;
   out_7211163890878107353[201] = 0.0;
   out_7211163890878107353[202] = 0.0;
   out_7211163890878107353[203] = 0.0;
   out_7211163890878107353[204] = 0.0;
   out_7211163890878107353[205] = 0.0;
   out_7211163890878107353[206] = 0.0;
   out_7211163890878107353[207] = 0.0;
   out_7211163890878107353[208] = 0.0;
   out_7211163890878107353[209] = 1.0;
   out_7211163890878107353[210] = 0.0;
   out_7211163890878107353[211] = 0.0;
   out_7211163890878107353[212] = 0.0;
   out_7211163890878107353[213] = 0.0;
   out_7211163890878107353[214] = 0.0;
   out_7211163890878107353[215] = 0.0;
   out_7211163890878107353[216] = 0.0;
   out_7211163890878107353[217] = 0.0;
   out_7211163890878107353[218] = 0.0;
   out_7211163890878107353[219] = 0.0;
   out_7211163890878107353[220] = 0.0;
   out_7211163890878107353[221] = 0.0;
   out_7211163890878107353[222] = 0.0;
   out_7211163890878107353[223] = 0.0;
   out_7211163890878107353[224] = 0.0;
   out_7211163890878107353[225] = 0.0;
   out_7211163890878107353[226] = 0.0;
   out_7211163890878107353[227] = 0.0;
   out_7211163890878107353[228] = 1.0;
   out_7211163890878107353[229] = 0.0;
   out_7211163890878107353[230] = 0.0;
   out_7211163890878107353[231] = 0.0;
   out_7211163890878107353[232] = 0.0;
   out_7211163890878107353[233] = 0.0;
   out_7211163890878107353[234] = 0.0;
   out_7211163890878107353[235] = 0.0;
   out_7211163890878107353[236] = 0.0;
   out_7211163890878107353[237] = 0.0;
   out_7211163890878107353[238] = 0.0;
   out_7211163890878107353[239] = 0.0;
   out_7211163890878107353[240] = 0.0;
   out_7211163890878107353[241] = 0.0;
   out_7211163890878107353[242] = 0.0;
   out_7211163890878107353[243] = 0.0;
   out_7211163890878107353[244] = 0.0;
   out_7211163890878107353[245] = 0.0;
   out_7211163890878107353[246] = 0.0;
   out_7211163890878107353[247] = 1.0;
   out_7211163890878107353[248] = 0.0;
   out_7211163890878107353[249] = 0.0;
   out_7211163890878107353[250] = 0.0;
   out_7211163890878107353[251] = 0.0;
   out_7211163890878107353[252] = 0.0;
   out_7211163890878107353[253] = 0.0;
   out_7211163890878107353[254] = 0.0;
   out_7211163890878107353[255] = 0.0;
   out_7211163890878107353[256] = 0.0;
   out_7211163890878107353[257] = 0.0;
   out_7211163890878107353[258] = 0.0;
   out_7211163890878107353[259] = 0.0;
   out_7211163890878107353[260] = 0.0;
   out_7211163890878107353[261] = 0.0;
   out_7211163890878107353[262] = 0.0;
   out_7211163890878107353[263] = 0.0;
   out_7211163890878107353[264] = 0.0;
   out_7211163890878107353[265] = 0.0;
   out_7211163890878107353[266] = 1.0;
   out_7211163890878107353[267] = 0.0;
   out_7211163890878107353[268] = 0.0;
   out_7211163890878107353[269] = 0.0;
   out_7211163890878107353[270] = 0.0;
   out_7211163890878107353[271] = 0.0;
   out_7211163890878107353[272] = 0.0;
   out_7211163890878107353[273] = 0.0;
   out_7211163890878107353[274] = 0.0;
   out_7211163890878107353[275] = 0.0;
   out_7211163890878107353[276] = 0.0;
   out_7211163890878107353[277] = 0.0;
   out_7211163890878107353[278] = 0.0;
   out_7211163890878107353[279] = 0.0;
   out_7211163890878107353[280] = 0.0;
   out_7211163890878107353[281] = 0.0;
   out_7211163890878107353[282] = 0.0;
   out_7211163890878107353[283] = 0.0;
   out_7211163890878107353[284] = 0.0;
   out_7211163890878107353[285] = 1.0;
   out_7211163890878107353[286] = 0.0;
   out_7211163890878107353[287] = 0.0;
   out_7211163890878107353[288] = 0.0;
   out_7211163890878107353[289] = 0.0;
   out_7211163890878107353[290] = 0.0;
   out_7211163890878107353[291] = 0.0;
   out_7211163890878107353[292] = 0.0;
   out_7211163890878107353[293] = 0.0;
   out_7211163890878107353[294] = 0.0;
   out_7211163890878107353[295] = 0.0;
   out_7211163890878107353[296] = 0.0;
   out_7211163890878107353[297] = 0.0;
   out_7211163890878107353[298] = 0.0;
   out_7211163890878107353[299] = 0.0;
   out_7211163890878107353[300] = 0.0;
   out_7211163890878107353[301] = 0.0;
   out_7211163890878107353[302] = 0.0;
   out_7211163890878107353[303] = 0.0;
   out_7211163890878107353[304] = 1.0;
   out_7211163890878107353[305] = 0.0;
   out_7211163890878107353[306] = 0.0;
   out_7211163890878107353[307] = 0.0;
   out_7211163890878107353[308] = 0.0;
   out_7211163890878107353[309] = 0.0;
   out_7211163890878107353[310] = 0.0;
   out_7211163890878107353[311] = 0.0;
   out_7211163890878107353[312] = 0.0;
   out_7211163890878107353[313] = 0.0;
   out_7211163890878107353[314] = 0.0;
   out_7211163890878107353[315] = 0.0;
   out_7211163890878107353[316] = 0.0;
   out_7211163890878107353[317] = 0.0;
   out_7211163890878107353[318] = 0.0;
   out_7211163890878107353[319] = 0.0;
   out_7211163890878107353[320] = 0.0;
   out_7211163890878107353[321] = 0.0;
   out_7211163890878107353[322] = 0.0;
   out_7211163890878107353[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_6340326609391524869) {
   out_6340326609391524869[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_6340326609391524869[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_6340326609391524869[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_6340326609391524869[3] = dt*state[12] + state[3];
   out_6340326609391524869[4] = dt*state[13] + state[4];
   out_6340326609391524869[5] = dt*state[14] + state[5];
   out_6340326609391524869[6] = state[6];
   out_6340326609391524869[7] = state[7];
   out_6340326609391524869[8] = state[8];
   out_6340326609391524869[9] = state[9];
   out_6340326609391524869[10] = state[10];
   out_6340326609391524869[11] = state[11];
   out_6340326609391524869[12] = state[12];
   out_6340326609391524869[13] = state[13];
   out_6340326609391524869[14] = state[14];
   out_6340326609391524869[15] = state[15];
   out_6340326609391524869[16] = state[16];
   out_6340326609391524869[17] = state[17];
}
void F_fun(double *state, double dt, double *out_7393239063929808405) {
   out_7393239063929808405[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7393239063929808405[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7393239063929808405[2] = 0;
   out_7393239063929808405[3] = 0;
   out_7393239063929808405[4] = 0;
   out_7393239063929808405[5] = 0;
   out_7393239063929808405[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7393239063929808405[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7393239063929808405[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7393239063929808405[9] = 0;
   out_7393239063929808405[10] = 0;
   out_7393239063929808405[11] = 0;
   out_7393239063929808405[12] = 0;
   out_7393239063929808405[13] = 0;
   out_7393239063929808405[14] = 0;
   out_7393239063929808405[15] = 0;
   out_7393239063929808405[16] = 0;
   out_7393239063929808405[17] = 0;
   out_7393239063929808405[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7393239063929808405[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7393239063929808405[20] = 0;
   out_7393239063929808405[21] = 0;
   out_7393239063929808405[22] = 0;
   out_7393239063929808405[23] = 0;
   out_7393239063929808405[24] = 0;
   out_7393239063929808405[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7393239063929808405[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7393239063929808405[27] = 0;
   out_7393239063929808405[28] = 0;
   out_7393239063929808405[29] = 0;
   out_7393239063929808405[30] = 0;
   out_7393239063929808405[31] = 0;
   out_7393239063929808405[32] = 0;
   out_7393239063929808405[33] = 0;
   out_7393239063929808405[34] = 0;
   out_7393239063929808405[35] = 0;
   out_7393239063929808405[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7393239063929808405[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7393239063929808405[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7393239063929808405[39] = 0;
   out_7393239063929808405[40] = 0;
   out_7393239063929808405[41] = 0;
   out_7393239063929808405[42] = 0;
   out_7393239063929808405[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7393239063929808405[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7393239063929808405[45] = 0;
   out_7393239063929808405[46] = 0;
   out_7393239063929808405[47] = 0;
   out_7393239063929808405[48] = 0;
   out_7393239063929808405[49] = 0;
   out_7393239063929808405[50] = 0;
   out_7393239063929808405[51] = 0;
   out_7393239063929808405[52] = 0;
   out_7393239063929808405[53] = 0;
   out_7393239063929808405[54] = 0;
   out_7393239063929808405[55] = 0;
   out_7393239063929808405[56] = 0;
   out_7393239063929808405[57] = 1;
   out_7393239063929808405[58] = 0;
   out_7393239063929808405[59] = 0;
   out_7393239063929808405[60] = 0;
   out_7393239063929808405[61] = 0;
   out_7393239063929808405[62] = 0;
   out_7393239063929808405[63] = 0;
   out_7393239063929808405[64] = 0;
   out_7393239063929808405[65] = 0;
   out_7393239063929808405[66] = dt;
   out_7393239063929808405[67] = 0;
   out_7393239063929808405[68] = 0;
   out_7393239063929808405[69] = 0;
   out_7393239063929808405[70] = 0;
   out_7393239063929808405[71] = 0;
   out_7393239063929808405[72] = 0;
   out_7393239063929808405[73] = 0;
   out_7393239063929808405[74] = 0;
   out_7393239063929808405[75] = 0;
   out_7393239063929808405[76] = 1;
   out_7393239063929808405[77] = 0;
   out_7393239063929808405[78] = 0;
   out_7393239063929808405[79] = 0;
   out_7393239063929808405[80] = 0;
   out_7393239063929808405[81] = 0;
   out_7393239063929808405[82] = 0;
   out_7393239063929808405[83] = 0;
   out_7393239063929808405[84] = 0;
   out_7393239063929808405[85] = dt;
   out_7393239063929808405[86] = 0;
   out_7393239063929808405[87] = 0;
   out_7393239063929808405[88] = 0;
   out_7393239063929808405[89] = 0;
   out_7393239063929808405[90] = 0;
   out_7393239063929808405[91] = 0;
   out_7393239063929808405[92] = 0;
   out_7393239063929808405[93] = 0;
   out_7393239063929808405[94] = 0;
   out_7393239063929808405[95] = 1;
   out_7393239063929808405[96] = 0;
   out_7393239063929808405[97] = 0;
   out_7393239063929808405[98] = 0;
   out_7393239063929808405[99] = 0;
   out_7393239063929808405[100] = 0;
   out_7393239063929808405[101] = 0;
   out_7393239063929808405[102] = 0;
   out_7393239063929808405[103] = 0;
   out_7393239063929808405[104] = dt;
   out_7393239063929808405[105] = 0;
   out_7393239063929808405[106] = 0;
   out_7393239063929808405[107] = 0;
   out_7393239063929808405[108] = 0;
   out_7393239063929808405[109] = 0;
   out_7393239063929808405[110] = 0;
   out_7393239063929808405[111] = 0;
   out_7393239063929808405[112] = 0;
   out_7393239063929808405[113] = 0;
   out_7393239063929808405[114] = 1;
   out_7393239063929808405[115] = 0;
   out_7393239063929808405[116] = 0;
   out_7393239063929808405[117] = 0;
   out_7393239063929808405[118] = 0;
   out_7393239063929808405[119] = 0;
   out_7393239063929808405[120] = 0;
   out_7393239063929808405[121] = 0;
   out_7393239063929808405[122] = 0;
   out_7393239063929808405[123] = 0;
   out_7393239063929808405[124] = 0;
   out_7393239063929808405[125] = 0;
   out_7393239063929808405[126] = 0;
   out_7393239063929808405[127] = 0;
   out_7393239063929808405[128] = 0;
   out_7393239063929808405[129] = 0;
   out_7393239063929808405[130] = 0;
   out_7393239063929808405[131] = 0;
   out_7393239063929808405[132] = 0;
   out_7393239063929808405[133] = 1;
   out_7393239063929808405[134] = 0;
   out_7393239063929808405[135] = 0;
   out_7393239063929808405[136] = 0;
   out_7393239063929808405[137] = 0;
   out_7393239063929808405[138] = 0;
   out_7393239063929808405[139] = 0;
   out_7393239063929808405[140] = 0;
   out_7393239063929808405[141] = 0;
   out_7393239063929808405[142] = 0;
   out_7393239063929808405[143] = 0;
   out_7393239063929808405[144] = 0;
   out_7393239063929808405[145] = 0;
   out_7393239063929808405[146] = 0;
   out_7393239063929808405[147] = 0;
   out_7393239063929808405[148] = 0;
   out_7393239063929808405[149] = 0;
   out_7393239063929808405[150] = 0;
   out_7393239063929808405[151] = 0;
   out_7393239063929808405[152] = 1;
   out_7393239063929808405[153] = 0;
   out_7393239063929808405[154] = 0;
   out_7393239063929808405[155] = 0;
   out_7393239063929808405[156] = 0;
   out_7393239063929808405[157] = 0;
   out_7393239063929808405[158] = 0;
   out_7393239063929808405[159] = 0;
   out_7393239063929808405[160] = 0;
   out_7393239063929808405[161] = 0;
   out_7393239063929808405[162] = 0;
   out_7393239063929808405[163] = 0;
   out_7393239063929808405[164] = 0;
   out_7393239063929808405[165] = 0;
   out_7393239063929808405[166] = 0;
   out_7393239063929808405[167] = 0;
   out_7393239063929808405[168] = 0;
   out_7393239063929808405[169] = 0;
   out_7393239063929808405[170] = 0;
   out_7393239063929808405[171] = 1;
   out_7393239063929808405[172] = 0;
   out_7393239063929808405[173] = 0;
   out_7393239063929808405[174] = 0;
   out_7393239063929808405[175] = 0;
   out_7393239063929808405[176] = 0;
   out_7393239063929808405[177] = 0;
   out_7393239063929808405[178] = 0;
   out_7393239063929808405[179] = 0;
   out_7393239063929808405[180] = 0;
   out_7393239063929808405[181] = 0;
   out_7393239063929808405[182] = 0;
   out_7393239063929808405[183] = 0;
   out_7393239063929808405[184] = 0;
   out_7393239063929808405[185] = 0;
   out_7393239063929808405[186] = 0;
   out_7393239063929808405[187] = 0;
   out_7393239063929808405[188] = 0;
   out_7393239063929808405[189] = 0;
   out_7393239063929808405[190] = 1;
   out_7393239063929808405[191] = 0;
   out_7393239063929808405[192] = 0;
   out_7393239063929808405[193] = 0;
   out_7393239063929808405[194] = 0;
   out_7393239063929808405[195] = 0;
   out_7393239063929808405[196] = 0;
   out_7393239063929808405[197] = 0;
   out_7393239063929808405[198] = 0;
   out_7393239063929808405[199] = 0;
   out_7393239063929808405[200] = 0;
   out_7393239063929808405[201] = 0;
   out_7393239063929808405[202] = 0;
   out_7393239063929808405[203] = 0;
   out_7393239063929808405[204] = 0;
   out_7393239063929808405[205] = 0;
   out_7393239063929808405[206] = 0;
   out_7393239063929808405[207] = 0;
   out_7393239063929808405[208] = 0;
   out_7393239063929808405[209] = 1;
   out_7393239063929808405[210] = 0;
   out_7393239063929808405[211] = 0;
   out_7393239063929808405[212] = 0;
   out_7393239063929808405[213] = 0;
   out_7393239063929808405[214] = 0;
   out_7393239063929808405[215] = 0;
   out_7393239063929808405[216] = 0;
   out_7393239063929808405[217] = 0;
   out_7393239063929808405[218] = 0;
   out_7393239063929808405[219] = 0;
   out_7393239063929808405[220] = 0;
   out_7393239063929808405[221] = 0;
   out_7393239063929808405[222] = 0;
   out_7393239063929808405[223] = 0;
   out_7393239063929808405[224] = 0;
   out_7393239063929808405[225] = 0;
   out_7393239063929808405[226] = 0;
   out_7393239063929808405[227] = 0;
   out_7393239063929808405[228] = 1;
   out_7393239063929808405[229] = 0;
   out_7393239063929808405[230] = 0;
   out_7393239063929808405[231] = 0;
   out_7393239063929808405[232] = 0;
   out_7393239063929808405[233] = 0;
   out_7393239063929808405[234] = 0;
   out_7393239063929808405[235] = 0;
   out_7393239063929808405[236] = 0;
   out_7393239063929808405[237] = 0;
   out_7393239063929808405[238] = 0;
   out_7393239063929808405[239] = 0;
   out_7393239063929808405[240] = 0;
   out_7393239063929808405[241] = 0;
   out_7393239063929808405[242] = 0;
   out_7393239063929808405[243] = 0;
   out_7393239063929808405[244] = 0;
   out_7393239063929808405[245] = 0;
   out_7393239063929808405[246] = 0;
   out_7393239063929808405[247] = 1;
   out_7393239063929808405[248] = 0;
   out_7393239063929808405[249] = 0;
   out_7393239063929808405[250] = 0;
   out_7393239063929808405[251] = 0;
   out_7393239063929808405[252] = 0;
   out_7393239063929808405[253] = 0;
   out_7393239063929808405[254] = 0;
   out_7393239063929808405[255] = 0;
   out_7393239063929808405[256] = 0;
   out_7393239063929808405[257] = 0;
   out_7393239063929808405[258] = 0;
   out_7393239063929808405[259] = 0;
   out_7393239063929808405[260] = 0;
   out_7393239063929808405[261] = 0;
   out_7393239063929808405[262] = 0;
   out_7393239063929808405[263] = 0;
   out_7393239063929808405[264] = 0;
   out_7393239063929808405[265] = 0;
   out_7393239063929808405[266] = 1;
   out_7393239063929808405[267] = 0;
   out_7393239063929808405[268] = 0;
   out_7393239063929808405[269] = 0;
   out_7393239063929808405[270] = 0;
   out_7393239063929808405[271] = 0;
   out_7393239063929808405[272] = 0;
   out_7393239063929808405[273] = 0;
   out_7393239063929808405[274] = 0;
   out_7393239063929808405[275] = 0;
   out_7393239063929808405[276] = 0;
   out_7393239063929808405[277] = 0;
   out_7393239063929808405[278] = 0;
   out_7393239063929808405[279] = 0;
   out_7393239063929808405[280] = 0;
   out_7393239063929808405[281] = 0;
   out_7393239063929808405[282] = 0;
   out_7393239063929808405[283] = 0;
   out_7393239063929808405[284] = 0;
   out_7393239063929808405[285] = 1;
   out_7393239063929808405[286] = 0;
   out_7393239063929808405[287] = 0;
   out_7393239063929808405[288] = 0;
   out_7393239063929808405[289] = 0;
   out_7393239063929808405[290] = 0;
   out_7393239063929808405[291] = 0;
   out_7393239063929808405[292] = 0;
   out_7393239063929808405[293] = 0;
   out_7393239063929808405[294] = 0;
   out_7393239063929808405[295] = 0;
   out_7393239063929808405[296] = 0;
   out_7393239063929808405[297] = 0;
   out_7393239063929808405[298] = 0;
   out_7393239063929808405[299] = 0;
   out_7393239063929808405[300] = 0;
   out_7393239063929808405[301] = 0;
   out_7393239063929808405[302] = 0;
   out_7393239063929808405[303] = 0;
   out_7393239063929808405[304] = 1;
   out_7393239063929808405[305] = 0;
   out_7393239063929808405[306] = 0;
   out_7393239063929808405[307] = 0;
   out_7393239063929808405[308] = 0;
   out_7393239063929808405[309] = 0;
   out_7393239063929808405[310] = 0;
   out_7393239063929808405[311] = 0;
   out_7393239063929808405[312] = 0;
   out_7393239063929808405[313] = 0;
   out_7393239063929808405[314] = 0;
   out_7393239063929808405[315] = 0;
   out_7393239063929808405[316] = 0;
   out_7393239063929808405[317] = 0;
   out_7393239063929808405[318] = 0;
   out_7393239063929808405[319] = 0;
   out_7393239063929808405[320] = 0;
   out_7393239063929808405[321] = 0;
   out_7393239063929808405[322] = 0;
   out_7393239063929808405[323] = 1;
}
void h_4(double *state, double *unused, double *out_5952459838685677664) {
   out_5952459838685677664[0] = state[6] + state[9];
   out_5952459838685677664[1] = state[7] + state[10];
   out_5952459838685677664[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_8035170281729974239) {
   out_8035170281729974239[0] = 0;
   out_8035170281729974239[1] = 0;
   out_8035170281729974239[2] = 0;
   out_8035170281729974239[3] = 0;
   out_8035170281729974239[4] = 0;
   out_8035170281729974239[5] = 0;
   out_8035170281729974239[6] = 1;
   out_8035170281729974239[7] = 0;
   out_8035170281729974239[8] = 0;
   out_8035170281729974239[9] = 1;
   out_8035170281729974239[10] = 0;
   out_8035170281729974239[11] = 0;
   out_8035170281729974239[12] = 0;
   out_8035170281729974239[13] = 0;
   out_8035170281729974239[14] = 0;
   out_8035170281729974239[15] = 0;
   out_8035170281729974239[16] = 0;
   out_8035170281729974239[17] = 0;
   out_8035170281729974239[18] = 0;
   out_8035170281729974239[19] = 0;
   out_8035170281729974239[20] = 0;
   out_8035170281729974239[21] = 0;
   out_8035170281729974239[22] = 0;
   out_8035170281729974239[23] = 0;
   out_8035170281729974239[24] = 0;
   out_8035170281729974239[25] = 1;
   out_8035170281729974239[26] = 0;
   out_8035170281729974239[27] = 0;
   out_8035170281729974239[28] = 1;
   out_8035170281729974239[29] = 0;
   out_8035170281729974239[30] = 0;
   out_8035170281729974239[31] = 0;
   out_8035170281729974239[32] = 0;
   out_8035170281729974239[33] = 0;
   out_8035170281729974239[34] = 0;
   out_8035170281729974239[35] = 0;
   out_8035170281729974239[36] = 0;
   out_8035170281729974239[37] = 0;
   out_8035170281729974239[38] = 0;
   out_8035170281729974239[39] = 0;
   out_8035170281729974239[40] = 0;
   out_8035170281729974239[41] = 0;
   out_8035170281729974239[42] = 0;
   out_8035170281729974239[43] = 0;
   out_8035170281729974239[44] = 1;
   out_8035170281729974239[45] = 0;
   out_8035170281729974239[46] = 0;
   out_8035170281729974239[47] = 1;
   out_8035170281729974239[48] = 0;
   out_8035170281729974239[49] = 0;
   out_8035170281729974239[50] = 0;
   out_8035170281729974239[51] = 0;
   out_8035170281729974239[52] = 0;
   out_8035170281729974239[53] = 0;
}
void h_10(double *state, double *unused, double *out_3472976061268600135) {
   out_3472976061268600135[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_3472976061268600135[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_3472976061268600135[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_3986091875956058549) {
   out_3986091875956058549[0] = 0;
   out_3986091875956058549[1] = 9.8100000000000005*cos(state[1]);
   out_3986091875956058549[2] = 0;
   out_3986091875956058549[3] = 0;
   out_3986091875956058549[4] = -state[8];
   out_3986091875956058549[5] = state[7];
   out_3986091875956058549[6] = 0;
   out_3986091875956058549[7] = state[5];
   out_3986091875956058549[8] = -state[4];
   out_3986091875956058549[9] = 0;
   out_3986091875956058549[10] = 0;
   out_3986091875956058549[11] = 0;
   out_3986091875956058549[12] = 1;
   out_3986091875956058549[13] = 0;
   out_3986091875956058549[14] = 0;
   out_3986091875956058549[15] = 1;
   out_3986091875956058549[16] = 0;
   out_3986091875956058549[17] = 0;
   out_3986091875956058549[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_3986091875956058549[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_3986091875956058549[20] = 0;
   out_3986091875956058549[21] = state[8];
   out_3986091875956058549[22] = 0;
   out_3986091875956058549[23] = -state[6];
   out_3986091875956058549[24] = -state[5];
   out_3986091875956058549[25] = 0;
   out_3986091875956058549[26] = state[3];
   out_3986091875956058549[27] = 0;
   out_3986091875956058549[28] = 0;
   out_3986091875956058549[29] = 0;
   out_3986091875956058549[30] = 0;
   out_3986091875956058549[31] = 1;
   out_3986091875956058549[32] = 0;
   out_3986091875956058549[33] = 0;
   out_3986091875956058549[34] = 1;
   out_3986091875956058549[35] = 0;
   out_3986091875956058549[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_3986091875956058549[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_3986091875956058549[38] = 0;
   out_3986091875956058549[39] = -state[7];
   out_3986091875956058549[40] = state[6];
   out_3986091875956058549[41] = 0;
   out_3986091875956058549[42] = state[4];
   out_3986091875956058549[43] = -state[3];
   out_3986091875956058549[44] = 0;
   out_3986091875956058549[45] = 0;
   out_3986091875956058549[46] = 0;
   out_3986091875956058549[47] = 0;
   out_3986091875956058549[48] = 0;
   out_3986091875956058549[49] = 0;
   out_3986091875956058549[50] = 1;
   out_3986091875956058549[51] = 0;
   out_3986091875956058549[52] = 0;
   out_3986091875956058549[53] = 1;
}
void h_13(double *state, double *unused, double *out_4496303610004593389) {
   out_4496303610004593389[0] = state[3];
   out_4496303610004593389[1] = state[4];
   out_4496303610004593389[2] = state[5];
}
void H_13(double *state, double *unused, double *out_8599772201411818343) {
   out_8599772201411818343[0] = 0;
   out_8599772201411818343[1] = 0;
   out_8599772201411818343[2] = 0;
   out_8599772201411818343[3] = 1;
   out_8599772201411818343[4] = 0;
   out_8599772201411818343[5] = 0;
   out_8599772201411818343[6] = 0;
   out_8599772201411818343[7] = 0;
   out_8599772201411818343[8] = 0;
   out_8599772201411818343[9] = 0;
   out_8599772201411818343[10] = 0;
   out_8599772201411818343[11] = 0;
   out_8599772201411818343[12] = 0;
   out_8599772201411818343[13] = 0;
   out_8599772201411818343[14] = 0;
   out_8599772201411818343[15] = 0;
   out_8599772201411818343[16] = 0;
   out_8599772201411818343[17] = 0;
   out_8599772201411818343[18] = 0;
   out_8599772201411818343[19] = 0;
   out_8599772201411818343[20] = 0;
   out_8599772201411818343[21] = 0;
   out_8599772201411818343[22] = 1;
   out_8599772201411818343[23] = 0;
   out_8599772201411818343[24] = 0;
   out_8599772201411818343[25] = 0;
   out_8599772201411818343[26] = 0;
   out_8599772201411818343[27] = 0;
   out_8599772201411818343[28] = 0;
   out_8599772201411818343[29] = 0;
   out_8599772201411818343[30] = 0;
   out_8599772201411818343[31] = 0;
   out_8599772201411818343[32] = 0;
   out_8599772201411818343[33] = 0;
   out_8599772201411818343[34] = 0;
   out_8599772201411818343[35] = 0;
   out_8599772201411818343[36] = 0;
   out_8599772201411818343[37] = 0;
   out_8599772201411818343[38] = 0;
   out_8599772201411818343[39] = 0;
   out_8599772201411818343[40] = 0;
   out_8599772201411818343[41] = 1;
   out_8599772201411818343[42] = 0;
   out_8599772201411818343[43] = 0;
   out_8599772201411818343[44] = 0;
   out_8599772201411818343[45] = 0;
   out_8599772201411818343[46] = 0;
   out_8599772201411818343[47] = 0;
   out_8599772201411818343[48] = 0;
   out_8599772201411818343[49] = 0;
   out_8599772201411818343[50] = 0;
   out_8599772201411818343[51] = 0;
   out_8599772201411818343[52] = 0;
   out_8599772201411818343[53] = 0;
}
void h_14(double *state, double *unused, double *out_7353773663794788489) {
   out_7353773663794788489[0] = state[6];
   out_7353773663794788489[1] = state[7];
   out_7353773663794788489[2] = state[8];
}
void H_14(double *state, double *unused, double *out_4952381849434601943) {
   out_4952381849434601943[0] = 0;
   out_4952381849434601943[1] = 0;
   out_4952381849434601943[2] = 0;
   out_4952381849434601943[3] = 0;
   out_4952381849434601943[4] = 0;
   out_4952381849434601943[5] = 0;
   out_4952381849434601943[6] = 1;
   out_4952381849434601943[7] = 0;
   out_4952381849434601943[8] = 0;
   out_4952381849434601943[9] = 0;
   out_4952381849434601943[10] = 0;
   out_4952381849434601943[11] = 0;
   out_4952381849434601943[12] = 0;
   out_4952381849434601943[13] = 0;
   out_4952381849434601943[14] = 0;
   out_4952381849434601943[15] = 0;
   out_4952381849434601943[16] = 0;
   out_4952381849434601943[17] = 0;
   out_4952381849434601943[18] = 0;
   out_4952381849434601943[19] = 0;
   out_4952381849434601943[20] = 0;
   out_4952381849434601943[21] = 0;
   out_4952381849434601943[22] = 0;
   out_4952381849434601943[23] = 0;
   out_4952381849434601943[24] = 0;
   out_4952381849434601943[25] = 1;
   out_4952381849434601943[26] = 0;
   out_4952381849434601943[27] = 0;
   out_4952381849434601943[28] = 0;
   out_4952381849434601943[29] = 0;
   out_4952381849434601943[30] = 0;
   out_4952381849434601943[31] = 0;
   out_4952381849434601943[32] = 0;
   out_4952381849434601943[33] = 0;
   out_4952381849434601943[34] = 0;
   out_4952381849434601943[35] = 0;
   out_4952381849434601943[36] = 0;
   out_4952381849434601943[37] = 0;
   out_4952381849434601943[38] = 0;
   out_4952381849434601943[39] = 0;
   out_4952381849434601943[40] = 0;
   out_4952381849434601943[41] = 0;
   out_4952381849434601943[42] = 0;
   out_4952381849434601943[43] = 0;
   out_4952381849434601943[44] = 1;
   out_4952381849434601943[45] = 0;
   out_4952381849434601943[46] = 0;
   out_4952381849434601943[47] = 0;
   out_4952381849434601943[48] = 0;
   out_4952381849434601943[49] = 0;
   out_4952381849434601943[50] = 0;
   out_4952381849434601943[51] = 0;
   out_4952381849434601943[52] = 0;
   out_4952381849434601943[53] = 0;
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

void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_4, H_4, NULL, in_z, in_R, in_ea, MAHA_THRESH_4);
}
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_10, H_10, NULL, in_z, in_R, in_ea, MAHA_THRESH_10);
}
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_13, H_13, NULL, in_z, in_R, in_ea, MAHA_THRESH_13);
}
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_14, H_14, NULL, in_z, in_R, in_ea, MAHA_THRESH_14);
}
void pose_err_fun(double *nom_x, double *delta_x, double *out_6947624313872495524) {
  err_fun(nom_x, delta_x, out_6947624313872495524);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_6870382180897404022) {
  inv_err_fun(nom_x, true_x, out_6870382180897404022);
}
void pose_H_mod_fun(double *state, double *out_7211163890878107353) {
  H_mod_fun(state, out_7211163890878107353);
}
void pose_f_fun(double *state, double dt, double *out_6340326609391524869) {
  f_fun(state,  dt, out_6340326609391524869);
}
void pose_F_fun(double *state, double dt, double *out_7393239063929808405) {
  F_fun(state,  dt, out_7393239063929808405);
}
void pose_h_4(double *state, double *unused, double *out_5952459838685677664) {
  h_4(state, unused, out_5952459838685677664);
}
void pose_H_4(double *state, double *unused, double *out_8035170281729974239) {
  H_4(state, unused, out_8035170281729974239);
}
void pose_h_10(double *state, double *unused, double *out_3472976061268600135) {
  h_10(state, unused, out_3472976061268600135);
}
void pose_H_10(double *state, double *unused, double *out_3986091875956058549) {
  H_10(state, unused, out_3986091875956058549);
}
void pose_h_13(double *state, double *unused, double *out_4496303610004593389) {
  h_13(state, unused, out_4496303610004593389);
}
void pose_H_13(double *state, double *unused, double *out_8599772201411818343) {
  H_13(state, unused, out_8599772201411818343);
}
void pose_h_14(double *state, double *unused, double *out_7353773663794788489) {
  h_14(state, unused, out_7353773663794788489);
}
void pose_H_14(double *state, double *unused, double *out_4952381849434601943) {
  H_14(state, unused, out_4952381849434601943);
}
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
}

const EKF pose = {
  .name = "pose",
  .kinds = { 4, 10, 13, 14 },
  .feature_kinds = {  },
  .f_fun = pose_f_fun,
  .F_fun = pose_F_fun,
  .err_fun = pose_err_fun,
  .inv_err_fun = pose_inv_err_fun,
  .H_mod_fun = pose_H_mod_fun,
  .predict = pose_predict,
  .hs = {
    { 4, pose_h_4 },
    { 10, pose_h_10 },
    { 13, pose_h_13 },
    { 14, pose_h_14 },
  },
  .Hs = {
    { 4, pose_H_4 },
    { 10, pose_H_10 },
    { 13, pose_H_13 },
    { 14, pose_H_14 },
  },
  .updates = {
    { 4, pose_update_4 },
    { 10, pose_update_10 },
    { 13, pose_update_13 },
    { 14, pose_update_14 },
  },
  .Hes = {
  },
  .sets = {
  },
  .extra_routines = {
  },
};

ekf_lib_init(pose)
