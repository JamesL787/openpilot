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
void err_fun(double *nom_x, double *delta_x, double *out_7324534072166343284) {
   out_7324534072166343284[0] = delta_x[0] + nom_x[0];
   out_7324534072166343284[1] = delta_x[1] + nom_x[1];
   out_7324534072166343284[2] = delta_x[2] + nom_x[2];
   out_7324534072166343284[3] = delta_x[3] + nom_x[3];
   out_7324534072166343284[4] = delta_x[4] + nom_x[4];
   out_7324534072166343284[5] = delta_x[5] + nom_x[5];
   out_7324534072166343284[6] = delta_x[6] + nom_x[6];
   out_7324534072166343284[7] = delta_x[7] + nom_x[7];
   out_7324534072166343284[8] = delta_x[8] + nom_x[8];
   out_7324534072166343284[9] = delta_x[9] + nom_x[9];
   out_7324534072166343284[10] = delta_x[10] + nom_x[10];
   out_7324534072166343284[11] = delta_x[11] + nom_x[11];
   out_7324534072166343284[12] = delta_x[12] + nom_x[12];
   out_7324534072166343284[13] = delta_x[13] + nom_x[13];
   out_7324534072166343284[14] = delta_x[14] + nom_x[14];
   out_7324534072166343284[15] = delta_x[15] + nom_x[15];
   out_7324534072166343284[16] = delta_x[16] + nom_x[16];
   out_7324534072166343284[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_4093192572736199915) {
   out_4093192572736199915[0] = -nom_x[0] + true_x[0];
   out_4093192572736199915[1] = -nom_x[1] + true_x[1];
   out_4093192572736199915[2] = -nom_x[2] + true_x[2];
   out_4093192572736199915[3] = -nom_x[3] + true_x[3];
   out_4093192572736199915[4] = -nom_x[4] + true_x[4];
   out_4093192572736199915[5] = -nom_x[5] + true_x[5];
   out_4093192572736199915[6] = -nom_x[6] + true_x[6];
   out_4093192572736199915[7] = -nom_x[7] + true_x[7];
   out_4093192572736199915[8] = -nom_x[8] + true_x[8];
   out_4093192572736199915[9] = -nom_x[9] + true_x[9];
   out_4093192572736199915[10] = -nom_x[10] + true_x[10];
   out_4093192572736199915[11] = -nom_x[11] + true_x[11];
   out_4093192572736199915[12] = -nom_x[12] + true_x[12];
   out_4093192572736199915[13] = -nom_x[13] + true_x[13];
   out_4093192572736199915[14] = -nom_x[14] + true_x[14];
   out_4093192572736199915[15] = -nom_x[15] + true_x[15];
   out_4093192572736199915[16] = -nom_x[16] + true_x[16];
   out_4093192572736199915[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_829763465388208705) {
   out_829763465388208705[0] = 1.0;
   out_829763465388208705[1] = 0.0;
   out_829763465388208705[2] = 0.0;
   out_829763465388208705[3] = 0.0;
   out_829763465388208705[4] = 0.0;
   out_829763465388208705[5] = 0.0;
   out_829763465388208705[6] = 0.0;
   out_829763465388208705[7] = 0.0;
   out_829763465388208705[8] = 0.0;
   out_829763465388208705[9] = 0.0;
   out_829763465388208705[10] = 0.0;
   out_829763465388208705[11] = 0.0;
   out_829763465388208705[12] = 0.0;
   out_829763465388208705[13] = 0.0;
   out_829763465388208705[14] = 0.0;
   out_829763465388208705[15] = 0.0;
   out_829763465388208705[16] = 0.0;
   out_829763465388208705[17] = 0.0;
   out_829763465388208705[18] = 0.0;
   out_829763465388208705[19] = 1.0;
   out_829763465388208705[20] = 0.0;
   out_829763465388208705[21] = 0.0;
   out_829763465388208705[22] = 0.0;
   out_829763465388208705[23] = 0.0;
   out_829763465388208705[24] = 0.0;
   out_829763465388208705[25] = 0.0;
   out_829763465388208705[26] = 0.0;
   out_829763465388208705[27] = 0.0;
   out_829763465388208705[28] = 0.0;
   out_829763465388208705[29] = 0.0;
   out_829763465388208705[30] = 0.0;
   out_829763465388208705[31] = 0.0;
   out_829763465388208705[32] = 0.0;
   out_829763465388208705[33] = 0.0;
   out_829763465388208705[34] = 0.0;
   out_829763465388208705[35] = 0.0;
   out_829763465388208705[36] = 0.0;
   out_829763465388208705[37] = 0.0;
   out_829763465388208705[38] = 1.0;
   out_829763465388208705[39] = 0.0;
   out_829763465388208705[40] = 0.0;
   out_829763465388208705[41] = 0.0;
   out_829763465388208705[42] = 0.0;
   out_829763465388208705[43] = 0.0;
   out_829763465388208705[44] = 0.0;
   out_829763465388208705[45] = 0.0;
   out_829763465388208705[46] = 0.0;
   out_829763465388208705[47] = 0.0;
   out_829763465388208705[48] = 0.0;
   out_829763465388208705[49] = 0.0;
   out_829763465388208705[50] = 0.0;
   out_829763465388208705[51] = 0.0;
   out_829763465388208705[52] = 0.0;
   out_829763465388208705[53] = 0.0;
   out_829763465388208705[54] = 0.0;
   out_829763465388208705[55] = 0.0;
   out_829763465388208705[56] = 0.0;
   out_829763465388208705[57] = 1.0;
   out_829763465388208705[58] = 0.0;
   out_829763465388208705[59] = 0.0;
   out_829763465388208705[60] = 0.0;
   out_829763465388208705[61] = 0.0;
   out_829763465388208705[62] = 0.0;
   out_829763465388208705[63] = 0.0;
   out_829763465388208705[64] = 0.0;
   out_829763465388208705[65] = 0.0;
   out_829763465388208705[66] = 0.0;
   out_829763465388208705[67] = 0.0;
   out_829763465388208705[68] = 0.0;
   out_829763465388208705[69] = 0.0;
   out_829763465388208705[70] = 0.0;
   out_829763465388208705[71] = 0.0;
   out_829763465388208705[72] = 0.0;
   out_829763465388208705[73] = 0.0;
   out_829763465388208705[74] = 0.0;
   out_829763465388208705[75] = 0.0;
   out_829763465388208705[76] = 1.0;
   out_829763465388208705[77] = 0.0;
   out_829763465388208705[78] = 0.0;
   out_829763465388208705[79] = 0.0;
   out_829763465388208705[80] = 0.0;
   out_829763465388208705[81] = 0.0;
   out_829763465388208705[82] = 0.0;
   out_829763465388208705[83] = 0.0;
   out_829763465388208705[84] = 0.0;
   out_829763465388208705[85] = 0.0;
   out_829763465388208705[86] = 0.0;
   out_829763465388208705[87] = 0.0;
   out_829763465388208705[88] = 0.0;
   out_829763465388208705[89] = 0.0;
   out_829763465388208705[90] = 0.0;
   out_829763465388208705[91] = 0.0;
   out_829763465388208705[92] = 0.0;
   out_829763465388208705[93] = 0.0;
   out_829763465388208705[94] = 0.0;
   out_829763465388208705[95] = 1.0;
   out_829763465388208705[96] = 0.0;
   out_829763465388208705[97] = 0.0;
   out_829763465388208705[98] = 0.0;
   out_829763465388208705[99] = 0.0;
   out_829763465388208705[100] = 0.0;
   out_829763465388208705[101] = 0.0;
   out_829763465388208705[102] = 0.0;
   out_829763465388208705[103] = 0.0;
   out_829763465388208705[104] = 0.0;
   out_829763465388208705[105] = 0.0;
   out_829763465388208705[106] = 0.0;
   out_829763465388208705[107] = 0.0;
   out_829763465388208705[108] = 0.0;
   out_829763465388208705[109] = 0.0;
   out_829763465388208705[110] = 0.0;
   out_829763465388208705[111] = 0.0;
   out_829763465388208705[112] = 0.0;
   out_829763465388208705[113] = 0.0;
   out_829763465388208705[114] = 1.0;
   out_829763465388208705[115] = 0.0;
   out_829763465388208705[116] = 0.0;
   out_829763465388208705[117] = 0.0;
   out_829763465388208705[118] = 0.0;
   out_829763465388208705[119] = 0.0;
   out_829763465388208705[120] = 0.0;
   out_829763465388208705[121] = 0.0;
   out_829763465388208705[122] = 0.0;
   out_829763465388208705[123] = 0.0;
   out_829763465388208705[124] = 0.0;
   out_829763465388208705[125] = 0.0;
   out_829763465388208705[126] = 0.0;
   out_829763465388208705[127] = 0.0;
   out_829763465388208705[128] = 0.0;
   out_829763465388208705[129] = 0.0;
   out_829763465388208705[130] = 0.0;
   out_829763465388208705[131] = 0.0;
   out_829763465388208705[132] = 0.0;
   out_829763465388208705[133] = 1.0;
   out_829763465388208705[134] = 0.0;
   out_829763465388208705[135] = 0.0;
   out_829763465388208705[136] = 0.0;
   out_829763465388208705[137] = 0.0;
   out_829763465388208705[138] = 0.0;
   out_829763465388208705[139] = 0.0;
   out_829763465388208705[140] = 0.0;
   out_829763465388208705[141] = 0.0;
   out_829763465388208705[142] = 0.0;
   out_829763465388208705[143] = 0.0;
   out_829763465388208705[144] = 0.0;
   out_829763465388208705[145] = 0.0;
   out_829763465388208705[146] = 0.0;
   out_829763465388208705[147] = 0.0;
   out_829763465388208705[148] = 0.0;
   out_829763465388208705[149] = 0.0;
   out_829763465388208705[150] = 0.0;
   out_829763465388208705[151] = 0.0;
   out_829763465388208705[152] = 1.0;
   out_829763465388208705[153] = 0.0;
   out_829763465388208705[154] = 0.0;
   out_829763465388208705[155] = 0.0;
   out_829763465388208705[156] = 0.0;
   out_829763465388208705[157] = 0.0;
   out_829763465388208705[158] = 0.0;
   out_829763465388208705[159] = 0.0;
   out_829763465388208705[160] = 0.0;
   out_829763465388208705[161] = 0.0;
   out_829763465388208705[162] = 0.0;
   out_829763465388208705[163] = 0.0;
   out_829763465388208705[164] = 0.0;
   out_829763465388208705[165] = 0.0;
   out_829763465388208705[166] = 0.0;
   out_829763465388208705[167] = 0.0;
   out_829763465388208705[168] = 0.0;
   out_829763465388208705[169] = 0.0;
   out_829763465388208705[170] = 0.0;
   out_829763465388208705[171] = 1.0;
   out_829763465388208705[172] = 0.0;
   out_829763465388208705[173] = 0.0;
   out_829763465388208705[174] = 0.0;
   out_829763465388208705[175] = 0.0;
   out_829763465388208705[176] = 0.0;
   out_829763465388208705[177] = 0.0;
   out_829763465388208705[178] = 0.0;
   out_829763465388208705[179] = 0.0;
   out_829763465388208705[180] = 0.0;
   out_829763465388208705[181] = 0.0;
   out_829763465388208705[182] = 0.0;
   out_829763465388208705[183] = 0.0;
   out_829763465388208705[184] = 0.0;
   out_829763465388208705[185] = 0.0;
   out_829763465388208705[186] = 0.0;
   out_829763465388208705[187] = 0.0;
   out_829763465388208705[188] = 0.0;
   out_829763465388208705[189] = 0.0;
   out_829763465388208705[190] = 1.0;
   out_829763465388208705[191] = 0.0;
   out_829763465388208705[192] = 0.0;
   out_829763465388208705[193] = 0.0;
   out_829763465388208705[194] = 0.0;
   out_829763465388208705[195] = 0.0;
   out_829763465388208705[196] = 0.0;
   out_829763465388208705[197] = 0.0;
   out_829763465388208705[198] = 0.0;
   out_829763465388208705[199] = 0.0;
   out_829763465388208705[200] = 0.0;
   out_829763465388208705[201] = 0.0;
   out_829763465388208705[202] = 0.0;
   out_829763465388208705[203] = 0.0;
   out_829763465388208705[204] = 0.0;
   out_829763465388208705[205] = 0.0;
   out_829763465388208705[206] = 0.0;
   out_829763465388208705[207] = 0.0;
   out_829763465388208705[208] = 0.0;
   out_829763465388208705[209] = 1.0;
   out_829763465388208705[210] = 0.0;
   out_829763465388208705[211] = 0.0;
   out_829763465388208705[212] = 0.0;
   out_829763465388208705[213] = 0.0;
   out_829763465388208705[214] = 0.0;
   out_829763465388208705[215] = 0.0;
   out_829763465388208705[216] = 0.0;
   out_829763465388208705[217] = 0.0;
   out_829763465388208705[218] = 0.0;
   out_829763465388208705[219] = 0.0;
   out_829763465388208705[220] = 0.0;
   out_829763465388208705[221] = 0.0;
   out_829763465388208705[222] = 0.0;
   out_829763465388208705[223] = 0.0;
   out_829763465388208705[224] = 0.0;
   out_829763465388208705[225] = 0.0;
   out_829763465388208705[226] = 0.0;
   out_829763465388208705[227] = 0.0;
   out_829763465388208705[228] = 1.0;
   out_829763465388208705[229] = 0.0;
   out_829763465388208705[230] = 0.0;
   out_829763465388208705[231] = 0.0;
   out_829763465388208705[232] = 0.0;
   out_829763465388208705[233] = 0.0;
   out_829763465388208705[234] = 0.0;
   out_829763465388208705[235] = 0.0;
   out_829763465388208705[236] = 0.0;
   out_829763465388208705[237] = 0.0;
   out_829763465388208705[238] = 0.0;
   out_829763465388208705[239] = 0.0;
   out_829763465388208705[240] = 0.0;
   out_829763465388208705[241] = 0.0;
   out_829763465388208705[242] = 0.0;
   out_829763465388208705[243] = 0.0;
   out_829763465388208705[244] = 0.0;
   out_829763465388208705[245] = 0.0;
   out_829763465388208705[246] = 0.0;
   out_829763465388208705[247] = 1.0;
   out_829763465388208705[248] = 0.0;
   out_829763465388208705[249] = 0.0;
   out_829763465388208705[250] = 0.0;
   out_829763465388208705[251] = 0.0;
   out_829763465388208705[252] = 0.0;
   out_829763465388208705[253] = 0.0;
   out_829763465388208705[254] = 0.0;
   out_829763465388208705[255] = 0.0;
   out_829763465388208705[256] = 0.0;
   out_829763465388208705[257] = 0.0;
   out_829763465388208705[258] = 0.0;
   out_829763465388208705[259] = 0.0;
   out_829763465388208705[260] = 0.0;
   out_829763465388208705[261] = 0.0;
   out_829763465388208705[262] = 0.0;
   out_829763465388208705[263] = 0.0;
   out_829763465388208705[264] = 0.0;
   out_829763465388208705[265] = 0.0;
   out_829763465388208705[266] = 1.0;
   out_829763465388208705[267] = 0.0;
   out_829763465388208705[268] = 0.0;
   out_829763465388208705[269] = 0.0;
   out_829763465388208705[270] = 0.0;
   out_829763465388208705[271] = 0.0;
   out_829763465388208705[272] = 0.0;
   out_829763465388208705[273] = 0.0;
   out_829763465388208705[274] = 0.0;
   out_829763465388208705[275] = 0.0;
   out_829763465388208705[276] = 0.0;
   out_829763465388208705[277] = 0.0;
   out_829763465388208705[278] = 0.0;
   out_829763465388208705[279] = 0.0;
   out_829763465388208705[280] = 0.0;
   out_829763465388208705[281] = 0.0;
   out_829763465388208705[282] = 0.0;
   out_829763465388208705[283] = 0.0;
   out_829763465388208705[284] = 0.0;
   out_829763465388208705[285] = 1.0;
   out_829763465388208705[286] = 0.0;
   out_829763465388208705[287] = 0.0;
   out_829763465388208705[288] = 0.0;
   out_829763465388208705[289] = 0.0;
   out_829763465388208705[290] = 0.0;
   out_829763465388208705[291] = 0.0;
   out_829763465388208705[292] = 0.0;
   out_829763465388208705[293] = 0.0;
   out_829763465388208705[294] = 0.0;
   out_829763465388208705[295] = 0.0;
   out_829763465388208705[296] = 0.0;
   out_829763465388208705[297] = 0.0;
   out_829763465388208705[298] = 0.0;
   out_829763465388208705[299] = 0.0;
   out_829763465388208705[300] = 0.0;
   out_829763465388208705[301] = 0.0;
   out_829763465388208705[302] = 0.0;
   out_829763465388208705[303] = 0.0;
   out_829763465388208705[304] = 1.0;
   out_829763465388208705[305] = 0.0;
   out_829763465388208705[306] = 0.0;
   out_829763465388208705[307] = 0.0;
   out_829763465388208705[308] = 0.0;
   out_829763465388208705[309] = 0.0;
   out_829763465388208705[310] = 0.0;
   out_829763465388208705[311] = 0.0;
   out_829763465388208705[312] = 0.0;
   out_829763465388208705[313] = 0.0;
   out_829763465388208705[314] = 0.0;
   out_829763465388208705[315] = 0.0;
   out_829763465388208705[316] = 0.0;
   out_829763465388208705[317] = 0.0;
   out_829763465388208705[318] = 0.0;
   out_829763465388208705[319] = 0.0;
   out_829763465388208705[320] = 0.0;
   out_829763465388208705[321] = 0.0;
   out_829763465388208705[322] = 0.0;
   out_829763465388208705[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_6925502751931868556) {
   out_6925502751931868556[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_6925502751931868556[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_6925502751931868556[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_6925502751931868556[3] = dt*state[12] + state[3];
   out_6925502751931868556[4] = dt*state[13] + state[4];
   out_6925502751931868556[5] = dt*state[14] + state[5];
   out_6925502751931868556[6] = state[6];
   out_6925502751931868556[7] = state[7];
   out_6925502751931868556[8] = state[8];
   out_6925502751931868556[9] = state[9];
   out_6925502751931868556[10] = state[10];
   out_6925502751931868556[11] = state[11];
   out_6925502751931868556[12] = state[12];
   out_6925502751931868556[13] = state[13];
   out_6925502751931868556[14] = state[14];
   out_6925502751931868556[15] = state[15];
   out_6925502751931868556[16] = state[16];
   out_6925502751931868556[17] = state[17];
}
void F_fun(double *state, double dt, double *out_5096874786388754966) {
   out_5096874786388754966[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5096874786388754966[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5096874786388754966[2] = 0;
   out_5096874786388754966[3] = 0;
   out_5096874786388754966[4] = 0;
   out_5096874786388754966[5] = 0;
   out_5096874786388754966[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5096874786388754966[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5096874786388754966[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5096874786388754966[9] = 0;
   out_5096874786388754966[10] = 0;
   out_5096874786388754966[11] = 0;
   out_5096874786388754966[12] = 0;
   out_5096874786388754966[13] = 0;
   out_5096874786388754966[14] = 0;
   out_5096874786388754966[15] = 0;
   out_5096874786388754966[16] = 0;
   out_5096874786388754966[17] = 0;
   out_5096874786388754966[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5096874786388754966[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5096874786388754966[20] = 0;
   out_5096874786388754966[21] = 0;
   out_5096874786388754966[22] = 0;
   out_5096874786388754966[23] = 0;
   out_5096874786388754966[24] = 0;
   out_5096874786388754966[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5096874786388754966[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5096874786388754966[27] = 0;
   out_5096874786388754966[28] = 0;
   out_5096874786388754966[29] = 0;
   out_5096874786388754966[30] = 0;
   out_5096874786388754966[31] = 0;
   out_5096874786388754966[32] = 0;
   out_5096874786388754966[33] = 0;
   out_5096874786388754966[34] = 0;
   out_5096874786388754966[35] = 0;
   out_5096874786388754966[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5096874786388754966[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5096874786388754966[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5096874786388754966[39] = 0;
   out_5096874786388754966[40] = 0;
   out_5096874786388754966[41] = 0;
   out_5096874786388754966[42] = 0;
   out_5096874786388754966[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5096874786388754966[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5096874786388754966[45] = 0;
   out_5096874786388754966[46] = 0;
   out_5096874786388754966[47] = 0;
   out_5096874786388754966[48] = 0;
   out_5096874786388754966[49] = 0;
   out_5096874786388754966[50] = 0;
   out_5096874786388754966[51] = 0;
   out_5096874786388754966[52] = 0;
   out_5096874786388754966[53] = 0;
   out_5096874786388754966[54] = 0;
   out_5096874786388754966[55] = 0;
   out_5096874786388754966[56] = 0;
   out_5096874786388754966[57] = 1;
   out_5096874786388754966[58] = 0;
   out_5096874786388754966[59] = 0;
   out_5096874786388754966[60] = 0;
   out_5096874786388754966[61] = 0;
   out_5096874786388754966[62] = 0;
   out_5096874786388754966[63] = 0;
   out_5096874786388754966[64] = 0;
   out_5096874786388754966[65] = 0;
   out_5096874786388754966[66] = dt;
   out_5096874786388754966[67] = 0;
   out_5096874786388754966[68] = 0;
   out_5096874786388754966[69] = 0;
   out_5096874786388754966[70] = 0;
   out_5096874786388754966[71] = 0;
   out_5096874786388754966[72] = 0;
   out_5096874786388754966[73] = 0;
   out_5096874786388754966[74] = 0;
   out_5096874786388754966[75] = 0;
   out_5096874786388754966[76] = 1;
   out_5096874786388754966[77] = 0;
   out_5096874786388754966[78] = 0;
   out_5096874786388754966[79] = 0;
   out_5096874786388754966[80] = 0;
   out_5096874786388754966[81] = 0;
   out_5096874786388754966[82] = 0;
   out_5096874786388754966[83] = 0;
   out_5096874786388754966[84] = 0;
   out_5096874786388754966[85] = dt;
   out_5096874786388754966[86] = 0;
   out_5096874786388754966[87] = 0;
   out_5096874786388754966[88] = 0;
   out_5096874786388754966[89] = 0;
   out_5096874786388754966[90] = 0;
   out_5096874786388754966[91] = 0;
   out_5096874786388754966[92] = 0;
   out_5096874786388754966[93] = 0;
   out_5096874786388754966[94] = 0;
   out_5096874786388754966[95] = 1;
   out_5096874786388754966[96] = 0;
   out_5096874786388754966[97] = 0;
   out_5096874786388754966[98] = 0;
   out_5096874786388754966[99] = 0;
   out_5096874786388754966[100] = 0;
   out_5096874786388754966[101] = 0;
   out_5096874786388754966[102] = 0;
   out_5096874786388754966[103] = 0;
   out_5096874786388754966[104] = dt;
   out_5096874786388754966[105] = 0;
   out_5096874786388754966[106] = 0;
   out_5096874786388754966[107] = 0;
   out_5096874786388754966[108] = 0;
   out_5096874786388754966[109] = 0;
   out_5096874786388754966[110] = 0;
   out_5096874786388754966[111] = 0;
   out_5096874786388754966[112] = 0;
   out_5096874786388754966[113] = 0;
   out_5096874786388754966[114] = 1;
   out_5096874786388754966[115] = 0;
   out_5096874786388754966[116] = 0;
   out_5096874786388754966[117] = 0;
   out_5096874786388754966[118] = 0;
   out_5096874786388754966[119] = 0;
   out_5096874786388754966[120] = 0;
   out_5096874786388754966[121] = 0;
   out_5096874786388754966[122] = 0;
   out_5096874786388754966[123] = 0;
   out_5096874786388754966[124] = 0;
   out_5096874786388754966[125] = 0;
   out_5096874786388754966[126] = 0;
   out_5096874786388754966[127] = 0;
   out_5096874786388754966[128] = 0;
   out_5096874786388754966[129] = 0;
   out_5096874786388754966[130] = 0;
   out_5096874786388754966[131] = 0;
   out_5096874786388754966[132] = 0;
   out_5096874786388754966[133] = 1;
   out_5096874786388754966[134] = 0;
   out_5096874786388754966[135] = 0;
   out_5096874786388754966[136] = 0;
   out_5096874786388754966[137] = 0;
   out_5096874786388754966[138] = 0;
   out_5096874786388754966[139] = 0;
   out_5096874786388754966[140] = 0;
   out_5096874786388754966[141] = 0;
   out_5096874786388754966[142] = 0;
   out_5096874786388754966[143] = 0;
   out_5096874786388754966[144] = 0;
   out_5096874786388754966[145] = 0;
   out_5096874786388754966[146] = 0;
   out_5096874786388754966[147] = 0;
   out_5096874786388754966[148] = 0;
   out_5096874786388754966[149] = 0;
   out_5096874786388754966[150] = 0;
   out_5096874786388754966[151] = 0;
   out_5096874786388754966[152] = 1;
   out_5096874786388754966[153] = 0;
   out_5096874786388754966[154] = 0;
   out_5096874786388754966[155] = 0;
   out_5096874786388754966[156] = 0;
   out_5096874786388754966[157] = 0;
   out_5096874786388754966[158] = 0;
   out_5096874786388754966[159] = 0;
   out_5096874786388754966[160] = 0;
   out_5096874786388754966[161] = 0;
   out_5096874786388754966[162] = 0;
   out_5096874786388754966[163] = 0;
   out_5096874786388754966[164] = 0;
   out_5096874786388754966[165] = 0;
   out_5096874786388754966[166] = 0;
   out_5096874786388754966[167] = 0;
   out_5096874786388754966[168] = 0;
   out_5096874786388754966[169] = 0;
   out_5096874786388754966[170] = 0;
   out_5096874786388754966[171] = 1;
   out_5096874786388754966[172] = 0;
   out_5096874786388754966[173] = 0;
   out_5096874786388754966[174] = 0;
   out_5096874786388754966[175] = 0;
   out_5096874786388754966[176] = 0;
   out_5096874786388754966[177] = 0;
   out_5096874786388754966[178] = 0;
   out_5096874786388754966[179] = 0;
   out_5096874786388754966[180] = 0;
   out_5096874786388754966[181] = 0;
   out_5096874786388754966[182] = 0;
   out_5096874786388754966[183] = 0;
   out_5096874786388754966[184] = 0;
   out_5096874786388754966[185] = 0;
   out_5096874786388754966[186] = 0;
   out_5096874786388754966[187] = 0;
   out_5096874786388754966[188] = 0;
   out_5096874786388754966[189] = 0;
   out_5096874786388754966[190] = 1;
   out_5096874786388754966[191] = 0;
   out_5096874786388754966[192] = 0;
   out_5096874786388754966[193] = 0;
   out_5096874786388754966[194] = 0;
   out_5096874786388754966[195] = 0;
   out_5096874786388754966[196] = 0;
   out_5096874786388754966[197] = 0;
   out_5096874786388754966[198] = 0;
   out_5096874786388754966[199] = 0;
   out_5096874786388754966[200] = 0;
   out_5096874786388754966[201] = 0;
   out_5096874786388754966[202] = 0;
   out_5096874786388754966[203] = 0;
   out_5096874786388754966[204] = 0;
   out_5096874786388754966[205] = 0;
   out_5096874786388754966[206] = 0;
   out_5096874786388754966[207] = 0;
   out_5096874786388754966[208] = 0;
   out_5096874786388754966[209] = 1;
   out_5096874786388754966[210] = 0;
   out_5096874786388754966[211] = 0;
   out_5096874786388754966[212] = 0;
   out_5096874786388754966[213] = 0;
   out_5096874786388754966[214] = 0;
   out_5096874786388754966[215] = 0;
   out_5096874786388754966[216] = 0;
   out_5096874786388754966[217] = 0;
   out_5096874786388754966[218] = 0;
   out_5096874786388754966[219] = 0;
   out_5096874786388754966[220] = 0;
   out_5096874786388754966[221] = 0;
   out_5096874786388754966[222] = 0;
   out_5096874786388754966[223] = 0;
   out_5096874786388754966[224] = 0;
   out_5096874786388754966[225] = 0;
   out_5096874786388754966[226] = 0;
   out_5096874786388754966[227] = 0;
   out_5096874786388754966[228] = 1;
   out_5096874786388754966[229] = 0;
   out_5096874786388754966[230] = 0;
   out_5096874786388754966[231] = 0;
   out_5096874786388754966[232] = 0;
   out_5096874786388754966[233] = 0;
   out_5096874786388754966[234] = 0;
   out_5096874786388754966[235] = 0;
   out_5096874786388754966[236] = 0;
   out_5096874786388754966[237] = 0;
   out_5096874786388754966[238] = 0;
   out_5096874786388754966[239] = 0;
   out_5096874786388754966[240] = 0;
   out_5096874786388754966[241] = 0;
   out_5096874786388754966[242] = 0;
   out_5096874786388754966[243] = 0;
   out_5096874786388754966[244] = 0;
   out_5096874786388754966[245] = 0;
   out_5096874786388754966[246] = 0;
   out_5096874786388754966[247] = 1;
   out_5096874786388754966[248] = 0;
   out_5096874786388754966[249] = 0;
   out_5096874786388754966[250] = 0;
   out_5096874786388754966[251] = 0;
   out_5096874786388754966[252] = 0;
   out_5096874786388754966[253] = 0;
   out_5096874786388754966[254] = 0;
   out_5096874786388754966[255] = 0;
   out_5096874786388754966[256] = 0;
   out_5096874786388754966[257] = 0;
   out_5096874786388754966[258] = 0;
   out_5096874786388754966[259] = 0;
   out_5096874786388754966[260] = 0;
   out_5096874786388754966[261] = 0;
   out_5096874786388754966[262] = 0;
   out_5096874786388754966[263] = 0;
   out_5096874786388754966[264] = 0;
   out_5096874786388754966[265] = 0;
   out_5096874786388754966[266] = 1;
   out_5096874786388754966[267] = 0;
   out_5096874786388754966[268] = 0;
   out_5096874786388754966[269] = 0;
   out_5096874786388754966[270] = 0;
   out_5096874786388754966[271] = 0;
   out_5096874786388754966[272] = 0;
   out_5096874786388754966[273] = 0;
   out_5096874786388754966[274] = 0;
   out_5096874786388754966[275] = 0;
   out_5096874786388754966[276] = 0;
   out_5096874786388754966[277] = 0;
   out_5096874786388754966[278] = 0;
   out_5096874786388754966[279] = 0;
   out_5096874786388754966[280] = 0;
   out_5096874786388754966[281] = 0;
   out_5096874786388754966[282] = 0;
   out_5096874786388754966[283] = 0;
   out_5096874786388754966[284] = 0;
   out_5096874786388754966[285] = 1;
   out_5096874786388754966[286] = 0;
   out_5096874786388754966[287] = 0;
   out_5096874786388754966[288] = 0;
   out_5096874786388754966[289] = 0;
   out_5096874786388754966[290] = 0;
   out_5096874786388754966[291] = 0;
   out_5096874786388754966[292] = 0;
   out_5096874786388754966[293] = 0;
   out_5096874786388754966[294] = 0;
   out_5096874786388754966[295] = 0;
   out_5096874786388754966[296] = 0;
   out_5096874786388754966[297] = 0;
   out_5096874786388754966[298] = 0;
   out_5096874786388754966[299] = 0;
   out_5096874786388754966[300] = 0;
   out_5096874786388754966[301] = 0;
   out_5096874786388754966[302] = 0;
   out_5096874786388754966[303] = 0;
   out_5096874786388754966[304] = 1;
   out_5096874786388754966[305] = 0;
   out_5096874786388754966[306] = 0;
   out_5096874786388754966[307] = 0;
   out_5096874786388754966[308] = 0;
   out_5096874786388754966[309] = 0;
   out_5096874786388754966[310] = 0;
   out_5096874786388754966[311] = 0;
   out_5096874786388754966[312] = 0;
   out_5096874786388754966[313] = 0;
   out_5096874786388754966[314] = 0;
   out_5096874786388754966[315] = 0;
   out_5096874786388754966[316] = 0;
   out_5096874786388754966[317] = 0;
   out_5096874786388754966[318] = 0;
   out_5096874786388754966[319] = 0;
   out_5096874786388754966[320] = 0;
   out_5096874786388754966[321] = 0;
   out_5096874786388754966[322] = 0;
   out_5096874786388754966[323] = 1;
}
void h_4(double *state, double *unused, double *out_2729563795634279142) {
   out_2729563795634279142[0] = state[6] + state[9];
   out_2729563795634279142[1] = state[7] + state[10];
   out_2729563795634279142[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_75602463333496098) {
   out_75602463333496098[0] = 0;
   out_75602463333496098[1] = 0;
   out_75602463333496098[2] = 0;
   out_75602463333496098[3] = 0;
   out_75602463333496098[4] = 0;
   out_75602463333496098[5] = 0;
   out_75602463333496098[6] = 1;
   out_75602463333496098[7] = 0;
   out_75602463333496098[8] = 0;
   out_75602463333496098[9] = 1;
   out_75602463333496098[10] = 0;
   out_75602463333496098[11] = 0;
   out_75602463333496098[12] = 0;
   out_75602463333496098[13] = 0;
   out_75602463333496098[14] = 0;
   out_75602463333496098[15] = 0;
   out_75602463333496098[16] = 0;
   out_75602463333496098[17] = 0;
   out_75602463333496098[18] = 0;
   out_75602463333496098[19] = 0;
   out_75602463333496098[20] = 0;
   out_75602463333496098[21] = 0;
   out_75602463333496098[22] = 0;
   out_75602463333496098[23] = 0;
   out_75602463333496098[24] = 0;
   out_75602463333496098[25] = 1;
   out_75602463333496098[26] = 0;
   out_75602463333496098[27] = 0;
   out_75602463333496098[28] = 1;
   out_75602463333496098[29] = 0;
   out_75602463333496098[30] = 0;
   out_75602463333496098[31] = 0;
   out_75602463333496098[32] = 0;
   out_75602463333496098[33] = 0;
   out_75602463333496098[34] = 0;
   out_75602463333496098[35] = 0;
   out_75602463333496098[36] = 0;
   out_75602463333496098[37] = 0;
   out_75602463333496098[38] = 0;
   out_75602463333496098[39] = 0;
   out_75602463333496098[40] = 0;
   out_75602463333496098[41] = 0;
   out_75602463333496098[42] = 0;
   out_75602463333496098[43] = 0;
   out_75602463333496098[44] = 1;
   out_75602463333496098[45] = 0;
   out_75602463333496098[46] = 0;
   out_75602463333496098[47] = 1;
   out_75602463333496098[48] = 0;
   out_75602463333496098[49] = 0;
   out_75602463333496098[50] = 0;
   out_75602463333496098[51] = 0;
   out_75602463333496098[52] = 0;
   out_75602463333496098[53] = 0;
}
void h_10(double *state, double *unused, double *out_8200253958922815090) {
   out_8200253958922815090[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_8200253958922815090[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_8200253958922815090[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_2124391000687077810) {
   out_2124391000687077810[0] = 0;
   out_2124391000687077810[1] = 9.8100000000000005*cos(state[1]);
   out_2124391000687077810[2] = 0;
   out_2124391000687077810[3] = 0;
   out_2124391000687077810[4] = -state[8];
   out_2124391000687077810[5] = state[7];
   out_2124391000687077810[6] = 0;
   out_2124391000687077810[7] = state[5];
   out_2124391000687077810[8] = -state[4];
   out_2124391000687077810[9] = 0;
   out_2124391000687077810[10] = 0;
   out_2124391000687077810[11] = 0;
   out_2124391000687077810[12] = 1;
   out_2124391000687077810[13] = 0;
   out_2124391000687077810[14] = 0;
   out_2124391000687077810[15] = 1;
   out_2124391000687077810[16] = 0;
   out_2124391000687077810[17] = 0;
   out_2124391000687077810[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_2124391000687077810[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_2124391000687077810[20] = 0;
   out_2124391000687077810[21] = state[8];
   out_2124391000687077810[22] = 0;
   out_2124391000687077810[23] = -state[6];
   out_2124391000687077810[24] = -state[5];
   out_2124391000687077810[25] = 0;
   out_2124391000687077810[26] = state[3];
   out_2124391000687077810[27] = 0;
   out_2124391000687077810[28] = 0;
   out_2124391000687077810[29] = 0;
   out_2124391000687077810[30] = 0;
   out_2124391000687077810[31] = 1;
   out_2124391000687077810[32] = 0;
   out_2124391000687077810[33] = 0;
   out_2124391000687077810[34] = 1;
   out_2124391000687077810[35] = 0;
   out_2124391000687077810[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_2124391000687077810[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_2124391000687077810[38] = 0;
   out_2124391000687077810[39] = -state[7];
   out_2124391000687077810[40] = state[6];
   out_2124391000687077810[41] = 0;
   out_2124391000687077810[42] = state[4];
   out_2124391000687077810[43] = -state[3];
   out_2124391000687077810[44] = 0;
   out_2124391000687077810[45] = 0;
   out_2124391000687077810[46] = 0;
   out_2124391000687077810[47] = 0;
   out_2124391000687077810[48] = 0;
   out_2124391000687077810[49] = 0;
   out_2124391000687077810[50] = 1;
   out_2124391000687077810[51] = 0;
   out_2124391000687077810[52] = 0;
   out_2124391000687077810[53] = 1;
}
void h_13(double *state, double *unused, double *out_7771148490220590299) {
   out_7771148490220590299[0] = state[3];
   out_7771148490220590299[1] = state[4];
   out_7771148490220590299[2] = state[5];
}
void H_13(double *state, double *unused, double *out_3136671361998836703) {
   out_3136671361998836703[0] = 0;
   out_3136671361998836703[1] = 0;
   out_3136671361998836703[2] = 0;
   out_3136671361998836703[3] = 1;
   out_3136671361998836703[4] = 0;
   out_3136671361998836703[5] = 0;
   out_3136671361998836703[6] = 0;
   out_3136671361998836703[7] = 0;
   out_3136671361998836703[8] = 0;
   out_3136671361998836703[9] = 0;
   out_3136671361998836703[10] = 0;
   out_3136671361998836703[11] = 0;
   out_3136671361998836703[12] = 0;
   out_3136671361998836703[13] = 0;
   out_3136671361998836703[14] = 0;
   out_3136671361998836703[15] = 0;
   out_3136671361998836703[16] = 0;
   out_3136671361998836703[17] = 0;
   out_3136671361998836703[18] = 0;
   out_3136671361998836703[19] = 0;
   out_3136671361998836703[20] = 0;
   out_3136671361998836703[21] = 0;
   out_3136671361998836703[22] = 1;
   out_3136671361998836703[23] = 0;
   out_3136671361998836703[24] = 0;
   out_3136671361998836703[25] = 0;
   out_3136671361998836703[26] = 0;
   out_3136671361998836703[27] = 0;
   out_3136671361998836703[28] = 0;
   out_3136671361998836703[29] = 0;
   out_3136671361998836703[30] = 0;
   out_3136671361998836703[31] = 0;
   out_3136671361998836703[32] = 0;
   out_3136671361998836703[33] = 0;
   out_3136671361998836703[34] = 0;
   out_3136671361998836703[35] = 0;
   out_3136671361998836703[36] = 0;
   out_3136671361998836703[37] = 0;
   out_3136671361998836703[38] = 0;
   out_3136671361998836703[39] = 0;
   out_3136671361998836703[40] = 0;
   out_3136671361998836703[41] = 1;
   out_3136671361998836703[42] = 0;
   out_3136671361998836703[43] = 0;
   out_3136671361998836703[44] = 0;
   out_3136671361998836703[45] = 0;
   out_3136671361998836703[46] = 0;
   out_3136671361998836703[47] = 0;
   out_3136671361998836703[48] = 0;
   out_3136671361998836703[49] = 0;
   out_3136671361998836703[50] = 0;
   out_3136671361998836703[51] = 0;
   out_3136671361998836703[52] = 0;
   out_3136671361998836703[53] = 0;
}
void h_14(double *state, double *unused, double *out_7607766202558535283) {
   out_7607766202558535283[0] = state[6];
   out_7607766202558535283[1] = state[7];
   out_7607766202558535283[2] = state[8];
}
void H_14(double *state, double *unused, double *out_3158390895628868394) {
   out_3158390895628868394[0] = 0;
   out_3158390895628868394[1] = 0;
   out_3158390895628868394[2] = 0;
   out_3158390895628868394[3] = 0;
   out_3158390895628868394[4] = 0;
   out_3158390895628868394[5] = 0;
   out_3158390895628868394[6] = 1;
   out_3158390895628868394[7] = 0;
   out_3158390895628868394[8] = 0;
   out_3158390895628868394[9] = 0;
   out_3158390895628868394[10] = 0;
   out_3158390895628868394[11] = 0;
   out_3158390895628868394[12] = 0;
   out_3158390895628868394[13] = 0;
   out_3158390895628868394[14] = 0;
   out_3158390895628868394[15] = 0;
   out_3158390895628868394[16] = 0;
   out_3158390895628868394[17] = 0;
   out_3158390895628868394[18] = 0;
   out_3158390895628868394[19] = 0;
   out_3158390895628868394[20] = 0;
   out_3158390895628868394[21] = 0;
   out_3158390895628868394[22] = 0;
   out_3158390895628868394[23] = 0;
   out_3158390895628868394[24] = 0;
   out_3158390895628868394[25] = 1;
   out_3158390895628868394[26] = 0;
   out_3158390895628868394[27] = 0;
   out_3158390895628868394[28] = 0;
   out_3158390895628868394[29] = 0;
   out_3158390895628868394[30] = 0;
   out_3158390895628868394[31] = 0;
   out_3158390895628868394[32] = 0;
   out_3158390895628868394[33] = 0;
   out_3158390895628868394[34] = 0;
   out_3158390895628868394[35] = 0;
   out_3158390895628868394[36] = 0;
   out_3158390895628868394[37] = 0;
   out_3158390895628868394[38] = 0;
   out_3158390895628868394[39] = 0;
   out_3158390895628868394[40] = 0;
   out_3158390895628868394[41] = 0;
   out_3158390895628868394[42] = 0;
   out_3158390895628868394[43] = 0;
   out_3158390895628868394[44] = 1;
   out_3158390895628868394[45] = 0;
   out_3158390895628868394[46] = 0;
   out_3158390895628868394[47] = 0;
   out_3158390895628868394[48] = 0;
   out_3158390895628868394[49] = 0;
   out_3158390895628868394[50] = 0;
   out_3158390895628868394[51] = 0;
   out_3158390895628868394[52] = 0;
   out_3158390895628868394[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_7324534072166343284) {
  err_fun(nom_x, delta_x, out_7324534072166343284);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_4093192572736199915) {
  inv_err_fun(nom_x, true_x, out_4093192572736199915);
}
void pose_H_mod_fun(double *state, double *out_829763465388208705) {
  H_mod_fun(state, out_829763465388208705);
}
void pose_f_fun(double *state, double dt, double *out_6925502751931868556) {
  f_fun(state,  dt, out_6925502751931868556);
}
void pose_F_fun(double *state, double dt, double *out_5096874786388754966) {
  F_fun(state,  dt, out_5096874786388754966);
}
void pose_h_4(double *state, double *unused, double *out_2729563795634279142) {
  h_4(state, unused, out_2729563795634279142);
}
void pose_H_4(double *state, double *unused, double *out_75602463333496098) {
  H_4(state, unused, out_75602463333496098);
}
void pose_h_10(double *state, double *unused, double *out_8200253958922815090) {
  h_10(state, unused, out_8200253958922815090);
}
void pose_H_10(double *state, double *unused, double *out_2124391000687077810) {
  H_10(state, unused, out_2124391000687077810);
}
void pose_h_13(double *state, double *unused, double *out_7771148490220590299) {
  h_13(state, unused, out_7771148490220590299);
}
void pose_H_13(double *state, double *unused, double *out_3136671361998836703) {
  H_13(state, unused, out_3136671361998836703);
}
void pose_h_14(double *state, double *unused, double *out_7607766202558535283) {
  h_14(state, unused, out_7607766202558535283);
}
void pose_H_14(double *state, double *unused, double *out_3158390895628868394) {
  H_14(state, unused, out_3158390895628868394);
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
