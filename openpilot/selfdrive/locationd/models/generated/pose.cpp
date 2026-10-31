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
void err_fun(double *nom_x, double *delta_x, double *out_7263283861877820451) {
   out_7263283861877820451[0] = delta_x[0] + nom_x[0];
   out_7263283861877820451[1] = delta_x[1] + nom_x[1];
   out_7263283861877820451[2] = delta_x[2] + nom_x[2];
   out_7263283861877820451[3] = delta_x[3] + nom_x[3];
   out_7263283861877820451[4] = delta_x[4] + nom_x[4];
   out_7263283861877820451[5] = delta_x[5] + nom_x[5];
   out_7263283861877820451[6] = delta_x[6] + nom_x[6];
   out_7263283861877820451[7] = delta_x[7] + nom_x[7];
   out_7263283861877820451[8] = delta_x[8] + nom_x[8];
   out_7263283861877820451[9] = delta_x[9] + nom_x[9];
   out_7263283861877820451[10] = delta_x[10] + nom_x[10];
   out_7263283861877820451[11] = delta_x[11] + nom_x[11];
   out_7263283861877820451[12] = delta_x[12] + nom_x[12];
   out_7263283861877820451[13] = delta_x[13] + nom_x[13];
   out_7263283861877820451[14] = delta_x[14] + nom_x[14];
   out_7263283861877820451[15] = delta_x[15] + nom_x[15];
   out_7263283861877820451[16] = delta_x[16] + nom_x[16];
   out_7263283861877820451[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_5554489381921509580) {
   out_5554489381921509580[0] = -nom_x[0] + true_x[0];
   out_5554489381921509580[1] = -nom_x[1] + true_x[1];
   out_5554489381921509580[2] = -nom_x[2] + true_x[2];
   out_5554489381921509580[3] = -nom_x[3] + true_x[3];
   out_5554489381921509580[4] = -nom_x[4] + true_x[4];
   out_5554489381921509580[5] = -nom_x[5] + true_x[5];
   out_5554489381921509580[6] = -nom_x[6] + true_x[6];
   out_5554489381921509580[7] = -nom_x[7] + true_x[7];
   out_5554489381921509580[8] = -nom_x[8] + true_x[8];
   out_5554489381921509580[9] = -nom_x[9] + true_x[9];
   out_5554489381921509580[10] = -nom_x[10] + true_x[10];
   out_5554489381921509580[11] = -nom_x[11] + true_x[11];
   out_5554489381921509580[12] = -nom_x[12] + true_x[12];
   out_5554489381921509580[13] = -nom_x[13] + true_x[13];
   out_5554489381921509580[14] = -nom_x[14] + true_x[14];
   out_5554489381921509580[15] = -nom_x[15] + true_x[15];
   out_5554489381921509580[16] = -nom_x[16] + true_x[16];
   out_5554489381921509580[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_8221733452837955123) {
   out_8221733452837955123[0] = 1.0;
   out_8221733452837955123[1] = 0.0;
   out_8221733452837955123[2] = 0.0;
   out_8221733452837955123[3] = 0.0;
   out_8221733452837955123[4] = 0.0;
   out_8221733452837955123[5] = 0.0;
   out_8221733452837955123[6] = 0.0;
   out_8221733452837955123[7] = 0.0;
   out_8221733452837955123[8] = 0.0;
   out_8221733452837955123[9] = 0.0;
   out_8221733452837955123[10] = 0.0;
   out_8221733452837955123[11] = 0.0;
   out_8221733452837955123[12] = 0.0;
   out_8221733452837955123[13] = 0.0;
   out_8221733452837955123[14] = 0.0;
   out_8221733452837955123[15] = 0.0;
   out_8221733452837955123[16] = 0.0;
   out_8221733452837955123[17] = 0.0;
   out_8221733452837955123[18] = 0.0;
   out_8221733452837955123[19] = 1.0;
   out_8221733452837955123[20] = 0.0;
   out_8221733452837955123[21] = 0.0;
   out_8221733452837955123[22] = 0.0;
   out_8221733452837955123[23] = 0.0;
   out_8221733452837955123[24] = 0.0;
   out_8221733452837955123[25] = 0.0;
   out_8221733452837955123[26] = 0.0;
   out_8221733452837955123[27] = 0.0;
   out_8221733452837955123[28] = 0.0;
   out_8221733452837955123[29] = 0.0;
   out_8221733452837955123[30] = 0.0;
   out_8221733452837955123[31] = 0.0;
   out_8221733452837955123[32] = 0.0;
   out_8221733452837955123[33] = 0.0;
   out_8221733452837955123[34] = 0.0;
   out_8221733452837955123[35] = 0.0;
   out_8221733452837955123[36] = 0.0;
   out_8221733452837955123[37] = 0.0;
   out_8221733452837955123[38] = 1.0;
   out_8221733452837955123[39] = 0.0;
   out_8221733452837955123[40] = 0.0;
   out_8221733452837955123[41] = 0.0;
   out_8221733452837955123[42] = 0.0;
   out_8221733452837955123[43] = 0.0;
   out_8221733452837955123[44] = 0.0;
   out_8221733452837955123[45] = 0.0;
   out_8221733452837955123[46] = 0.0;
   out_8221733452837955123[47] = 0.0;
   out_8221733452837955123[48] = 0.0;
   out_8221733452837955123[49] = 0.0;
   out_8221733452837955123[50] = 0.0;
   out_8221733452837955123[51] = 0.0;
   out_8221733452837955123[52] = 0.0;
   out_8221733452837955123[53] = 0.0;
   out_8221733452837955123[54] = 0.0;
   out_8221733452837955123[55] = 0.0;
   out_8221733452837955123[56] = 0.0;
   out_8221733452837955123[57] = 1.0;
   out_8221733452837955123[58] = 0.0;
   out_8221733452837955123[59] = 0.0;
   out_8221733452837955123[60] = 0.0;
   out_8221733452837955123[61] = 0.0;
   out_8221733452837955123[62] = 0.0;
   out_8221733452837955123[63] = 0.0;
   out_8221733452837955123[64] = 0.0;
   out_8221733452837955123[65] = 0.0;
   out_8221733452837955123[66] = 0.0;
   out_8221733452837955123[67] = 0.0;
   out_8221733452837955123[68] = 0.0;
   out_8221733452837955123[69] = 0.0;
   out_8221733452837955123[70] = 0.0;
   out_8221733452837955123[71] = 0.0;
   out_8221733452837955123[72] = 0.0;
   out_8221733452837955123[73] = 0.0;
   out_8221733452837955123[74] = 0.0;
   out_8221733452837955123[75] = 0.0;
   out_8221733452837955123[76] = 1.0;
   out_8221733452837955123[77] = 0.0;
   out_8221733452837955123[78] = 0.0;
   out_8221733452837955123[79] = 0.0;
   out_8221733452837955123[80] = 0.0;
   out_8221733452837955123[81] = 0.0;
   out_8221733452837955123[82] = 0.0;
   out_8221733452837955123[83] = 0.0;
   out_8221733452837955123[84] = 0.0;
   out_8221733452837955123[85] = 0.0;
   out_8221733452837955123[86] = 0.0;
   out_8221733452837955123[87] = 0.0;
   out_8221733452837955123[88] = 0.0;
   out_8221733452837955123[89] = 0.0;
   out_8221733452837955123[90] = 0.0;
   out_8221733452837955123[91] = 0.0;
   out_8221733452837955123[92] = 0.0;
   out_8221733452837955123[93] = 0.0;
   out_8221733452837955123[94] = 0.0;
   out_8221733452837955123[95] = 1.0;
   out_8221733452837955123[96] = 0.0;
   out_8221733452837955123[97] = 0.0;
   out_8221733452837955123[98] = 0.0;
   out_8221733452837955123[99] = 0.0;
   out_8221733452837955123[100] = 0.0;
   out_8221733452837955123[101] = 0.0;
   out_8221733452837955123[102] = 0.0;
   out_8221733452837955123[103] = 0.0;
   out_8221733452837955123[104] = 0.0;
   out_8221733452837955123[105] = 0.0;
   out_8221733452837955123[106] = 0.0;
   out_8221733452837955123[107] = 0.0;
   out_8221733452837955123[108] = 0.0;
   out_8221733452837955123[109] = 0.0;
   out_8221733452837955123[110] = 0.0;
   out_8221733452837955123[111] = 0.0;
   out_8221733452837955123[112] = 0.0;
   out_8221733452837955123[113] = 0.0;
   out_8221733452837955123[114] = 1.0;
   out_8221733452837955123[115] = 0.0;
   out_8221733452837955123[116] = 0.0;
   out_8221733452837955123[117] = 0.0;
   out_8221733452837955123[118] = 0.0;
   out_8221733452837955123[119] = 0.0;
   out_8221733452837955123[120] = 0.0;
   out_8221733452837955123[121] = 0.0;
   out_8221733452837955123[122] = 0.0;
   out_8221733452837955123[123] = 0.0;
   out_8221733452837955123[124] = 0.0;
   out_8221733452837955123[125] = 0.0;
   out_8221733452837955123[126] = 0.0;
   out_8221733452837955123[127] = 0.0;
   out_8221733452837955123[128] = 0.0;
   out_8221733452837955123[129] = 0.0;
   out_8221733452837955123[130] = 0.0;
   out_8221733452837955123[131] = 0.0;
   out_8221733452837955123[132] = 0.0;
   out_8221733452837955123[133] = 1.0;
   out_8221733452837955123[134] = 0.0;
   out_8221733452837955123[135] = 0.0;
   out_8221733452837955123[136] = 0.0;
   out_8221733452837955123[137] = 0.0;
   out_8221733452837955123[138] = 0.0;
   out_8221733452837955123[139] = 0.0;
   out_8221733452837955123[140] = 0.0;
   out_8221733452837955123[141] = 0.0;
   out_8221733452837955123[142] = 0.0;
   out_8221733452837955123[143] = 0.0;
   out_8221733452837955123[144] = 0.0;
   out_8221733452837955123[145] = 0.0;
   out_8221733452837955123[146] = 0.0;
   out_8221733452837955123[147] = 0.0;
   out_8221733452837955123[148] = 0.0;
   out_8221733452837955123[149] = 0.0;
   out_8221733452837955123[150] = 0.0;
   out_8221733452837955123[151] = 0.0;
   out_8221733452837955123[152] = 1.0;
   out_8221733452837955123[153] = 0.0;
   out_8221733452837955123[154] = 0.0;
   out_8221733452837955123[155] = 0.0;
   out_8221733452837955123[156] = 0.0;
   out_8221733452837955123[157] = 0.0;
   out_8221733452837955123[158] = 0.0;
   out_8221733452837955123[159] = 0.0;
   out_8221733452837955123[160] = 0.0;
   out_8221733452837955123[161] = 0.0;
   out_8221733452837955123[162] = 0.0;
   out_8221733452837955123[163] = 0.0;
   out_8221733452837955123[164] = 0.0;
   out_8221733452837955123[165] = 0.0;
   out_8221733452837955123[166] = 0.0;
   out_8221733452837955123[167] = 0.0;
   out_8221733452837955123[168] = 0.0;
   out_8221733452837955123[169] = 0.0;
   out_8221733452837955123[170] = 0.0;
   out_8221733452837955123[171] = 1.0;
   out_8221733452837955123[172] = 0.0;
   out_8221733452837955123[173] = 0.0;
   out_8221733452837955123[174] = 0.0;
   out_8221733452837955123[175] = 0.0;
   out_8221733452837955123[176] = 0.0;
   out_8221733452837955123[177] = 0.0;
   out_8221733452837955123[178] = 0.0;
   out_8221733452837955123[179] = 0.0;
   out_8221733452837955123[180] = 0.0;
   out_8221733452837955123[181] = 0.0;
   out_8221733452837955123[182] = 0.0;
   out_8221733452837955123[183] = 0.0;
   out_8221733452837955123[184] = 0.0;
   out_8221733452837955123[185] = 0.0;
   out_8221733452837955123[186] = 0.0;
   out_8221733452837955123[187] = 0.0;
   out_8221733452837955123[188] = 0.0;
   out_8221733452837955123[189] = 0.0;
   out_8221733452837955123[190] = 1.0;
   out_8221733452837955123[191] = 0.0;
   out_8221733452837955123[192] = 0.0;
   out_8221733452837955123[193] = 0.0;
   out_8221733452837955123[194] = 0.0;
   out_8221733452837955123[195] = 0.0;
   out_8221733452837955123[196] = 0.0;
   out_8221733452837955123[197] = 0.0;
   out_8221733452837955123[198] = 0.0;
   out_8221733452837955123[199] = 0.0;
   out_8221733452837955123[200] = 0.0;
   out_8221733452837955123[201] = 0.0;
   out_8221733452837955123[202] = 0.0;
   out_8221733452837955123[203] = 0.0;
   out_8221733452837955123[204] = 0.0;
   out_8221733452837955123[205] = 0.0;
   out_8221733452837955123[206] = 0.0;
   out_8221733452837955123[207] = 0.0;
   out_8221733452837955123[208] = 0.0;
   out_8221733452837955123[209] = 1.0;
   out_8221733452837955123[210] = 0.0;
   out_8221733452837955123[211] = 0.0;
   out_8221733452837955123[212] = 0.0;
   out_8221733452837955123[213] = 0.0;
   out_8221733452837955123[214] = 0.0;
   out_8221733452837955123[215] = 0.0;
   out_8221733452837955123[216] = 0.0;
   out_8221733452837955123[217] = 0.0;
   out_8221733452837955123[218] = 0.0;
   out_8221733452837955123[219] = 0.0;
   out_8221733452837955123[220] = 0.0;
   out_8221733452837955123[221] = 0.0;
   out_8221733452837955123[222] = 0.0;
   out_8221733452837955123[223] = 0.0;
   out_8221733452837955123[224] = 0.0;
   out_8221733452837955123[225] = 0.0;
   out_8221733452837955123[226] = 0.0;
   out_8221733452837955123[227] = 0.0;
   out_8221733452837955123[228] = 1.0;
   out_8221733452837955123[229] = 0.0;
   out_8221733452837955123[230] = 0.0;
   out_8221733452837955123[231] = 0.0;
   out_8221733452837955123[232] = 0.0;
   out_8221733452837955123[233] = 0.0;
   out_8221733452837955123[234] = 0.0;
   out_8221733452837955123[235] = 0.0;
   out_8221733452837955123[236] = 0.0;
   out_8221733452837955123[237] = 0.0;
   out_8221733452837955123[238] = 0.0;
   out_8221733452837955123[239] = 0.0;
   out_8221733452837955123[240] = 0.0;
   out_8221733452837955123[241] = 0.0;
   out_8221733452837955123[242] = 0.0;
   out_8221733452837955123[243] = 0.0;
   out_8221733452837955123[244] = 0.0;
   out_8221733452837955123[245] = 0.0;
   out_8221733452837955123[246] = 0.0;
   out_8221733452837955123[247] = 1.0;
   out_8221733452837955123[248] = 0.0;
   out_8221733452837955123[249] = 0.0;
   out_8221733452837955123[250] = 0.0;
   out_8221733452837955123[251] = 0.0;
   out_8221733452837955123[252] = 0.0;
   out_8221733452837955123[253] = 0.0;
   out_8221733452837955123[254] = 0.0;
   out_8221733452837955123[255] = 0.0;
   out_8221733452837955123[256] = 0.0;
   out_8221733452837955123[257] = 0.0;
   out_8221733452837955123[258] = 0.0;
   out_8221733452837955123[259] = 0.0;
   out_8221733452837955123[260] = 0.0;
   out_8221733452837955123[261] = 0.0;
   out_8221733452837955123[262] = 0.0;
   out_8221733452837955123[263] = 0.0;
   out_8221733452837955123[264] = 0.0;
   out_8221733452837955123[265] = 0.0;
   out_8221733452837955123[266] = 1.0;
   out_8221733452837955123[267] = 0.0;
   out_8221733452837955123[268] = 0.0;
   out_8221733452837955123[269] = 0.0;
   out_8221733452837955123[270] = 0.0;
   out_8221733452837955123[271] = 0.0;
   out_8221733452837955123[272] = 0.0;
   out_8221733452837955123[273] = 0.0;
   out_8221733452837955123[274] = 0.0;
   out_8221733452837955123[275] = 0.0;
   out_8221733452837955123[276] = 0.0;
   out_8221733452837955123[277] = 0.0;
   out_8221733452837955123[278] = 0.0;
   out_8221733452837955123[279] = 0.0;
   out_8221733452837955123[280] = 0.0;
   out_8221733452837955123[281] = 0.0;
   out_8221733452837955123[282] = 0.0;
   out_8221733452837955123[283] = 0.0;
   out_8221733452837955123[284] = 0.0;
   out_8221733452837955123[285] = 1.0;
   out_8221733452837955123[286] = 0.0;
   out_8221733452837955123[287] = 0.0;
   out_8221733452837955123[288] = 0.0;
   out_8221733452837955123[289] = 0.0;
   out_8221733452837955123[290] = 0.0;
   out_8221733452837955123[291] = 0.0;
   out_8221733452837955123[292] = 0.0;
   out_8221733452837955123[293] = 0.0;
   out_8221733452837955123[294] = 0.0;
   out_8221733452837955123[295] = 0.0;
   out_8221733452837955123[296] = 0.0;
   out_8221733452837955123[297] = 0.0;
   out_8221733452837955123[298] = 0.0;
   out_8221733452837955123[299] = 0.0;
   out_8221733452837955123[300] = 0.0;
   out_8221733452837955123[301] = 0.0;
   out_8221733452837955123[302] = 0.0;
   out_8221733452837955123[303] = 0.0;
   out_8221733452837955123[304] = 1.0;
   out_8221733452837955123[305] = 0.0;
   out_8221733452837955123[306] = 0.0;
   out_8221733452837955123[307] = 0.0;
   out_8221733452837955123[308] = 0.0;
   out_8221733452837955123[309] = 0.0;
   out_8221733452837955123[310] = 0.0;
   out_8221733452837955123[311] = 0.0;
   out_8221733452837955123[312] = 0.0;
   out_8221733452837955123[313] = 0.0;
   out_8221733452837955123[314] = 0.0;
   out_8221733452837955123[315] = 0.0;
   out_8221733452837955123[316] = 0.0;
   out_8221733452837955123[317] = 0.0;
   out_8221733452837955123[318] = 0.0;
   out_8221733452837955123[319] = 0.0;
   out_8221733452837955123[320] = 0.0;
   out_8221733452837955123[321] = 0.0;
   out_8221733452837955123[322] = 0.0;
   out_8221733452837955123[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_6005799925322513099) {
   out_6005799925322513099[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_6005799925322513099[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_6005799925322513099[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_6005799925322513099[3] = dt*state[12] + state[3];
   out_6005799925322513099[4] = dt*state[13] + state[4];
   out_6005799925322513099[5] = dt*state[14] + state[5];
   out_6005799925322513099[6] = state[6];
   out_6005799925322513099[7] = state[7];
   out_6005799925322513099[8] = state[8];
   out_6005799925322513099[9] = state[9];
   out_6005799925322513099[10] = state[10];
   out_6005799925322513099[11] = state[11];
   out_6005799925322513099[12] = state[12];
   out_6005799925322513099[13] = state[13];
   out_6005799925322513099[14] = state[14];
   out_6005799925322513099[15] = state[15];
   out_6005799925322513099[16] = state[16];
   out_6005799925322513099[17] = state[17];
}
void F_fun(double *state, double dt, double *out_8053498741610314229) {
   out_8053498741610314229[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8053498741610314229[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8053498741610314229[2] = 0;
   out_8053498741610314229[3] = 0;
   out_8053498741610314229[4] = 0;
   out_8053498741610314229[5] = 0;
   out_8053498741610314229[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8053498741610314229[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8053498741610314229[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8053498741610314229[9] = 0;
   out_8053498741610314229[10] = 0;
   out_8053498741610314229[11] = 0;
   out_8053498741610314229[12] = 0;
   out_8053498741610314229[13] = 0;
   out_8053498741610314229[14] = 0;
   out_8053498741610314229[15] = 0;
   out_8053498741610314229[16] = 0;
   out_8053498741610314229[17] = 0;
   out_8053498741610314229[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8053498741610314229[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8053498741610314229[20] = 0;
   out_8053498741610314229[21] = 0;
   out_8053498741610314229[22] = 0;
   out_8053498741610314229[23] = 0;
   out_8053498741610314229[24] = 0;
   out_8053498741610314229[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8053498741610314229[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8053498741610314229[27] = 0;
   out_8053498741610314229[28] = 0;
   out_8053498741610314229[29] = 0;
   out_8053498741610314229[30] = 0;
   out_8053498741610314229[31] = 0;
   out_8053498741610314229[32] = 0;
   out_8053498741610314229[33] = 0;
   out_8053498741610314229[34] = 0;
   out_8053498741610314229[35] = 0;
   out_8053498741610314229[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8053498741610314229[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8053498741610314229[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8053498741610314229[39] = 0;
   out_8053498741610314229[40] = 0;
   out_8053498741610314229[41] = 0;
   out_8053498741610314229[42] = 0;
   out_8053498741610314229[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8053498741610314229[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8053498741610314229[45] = 0;
   out_8053498741610314229[46] = 0;
   out_8053498741610314229[47] = 0;
   out_8053498741610314229[48] = 0;
   out_8053498741610314229[49] = 0;
   out_8053498741610314229[50] = 0;
   out_8053498741610314229[51] = 0;
   out_8053498741610314229[52] = 0;
   out_8053498741610314229[53] = 0;
   out_8053498741610314229[54] = 0;
   out_8053498741610314229[55] = 0;
   out_8053498741610314229[56] = 0;
   out_8053498741610314229[57] = 1;
   out_8053498741610314229[58] = 0;
   out_8053498741610314229[59] = 0;
   out_8053498741610314229[60] = 0;
   out_8053498741610314229[61] = 0;
   out_8053498741610314229[62] = 0;
   out_8053498741610314229[63] = 0;
   out_8053498741610314229[64] = 0;
   out_8053498741610314229[65] = 0;
   out_8053498741610314229[66] = dt;
   out_8053498741610314229[67] = 0;
   out_8053498741610314229[68] = 0;
   out_8053498741610314229[69] = 0;
   out_8053498741610314229[70] = 0;
   out_8053498741610314229[71] = 0;
   out_8053498741610314229[72] = 0;
   out_8053498741610314229[73] = 0;
   out_8053498741610314229[74] = 0;
   out_8053498741610314229[75] = 0;
   out_8053498741610314229[76] = 1;
   out_8053498741610314229[77] = 0;
   out_8053498741610314229[78] = 0;
   out_8053498741610314229[79] = 0;
   out_8053498741610314229[80] = 0;
   out_8053498741610314229[81] = 0;
   out_8053498741610314229[82] = 0;
   out_8053498741610314229[83] = 0;
   out_8053498741610314229[84] = 0;
   out_8053498741610314229[85] = dt;
   out_8053498741610314229[86] = 0;
   out_8053498741610314229[87] = 0;
   out_8053498741610314229[88] = 0;
   out_8053498741610314229[89] = 0;
   out_8053498741610314229[90] = 0;
   out_8053498741610314229[91] = 0;
   out_8053498741610314229[92] = 0;
   out_8053498741610314229[93] = 0;
   out_8053498741610314229[94] = 0;
   out_8053498741610314229[95] = 1;
   out_8053498741610314229[96] = 0;
   out_8053498741610314229[97] = 0;
   out_8053498741610314229[98] = 0;
   out_8053498741610314229[99] = 0;
   out_8053498741610314229[100] = 0;
   out_8053498741610314229[101] = 0;
   out_8053498741610314229[102] = 0;
   out_8053498741610314229[103] = 0;
   out_8053498741610314229[104] = dt;
   out_8053498741610314229[105] = 0;
   out_8053498741610314229[106] = 0;
   out_8053498741610314229[107] = 0;
   out_8053498741610314229[108] = 0;
   out_8053498741610314229[109] = 0;
   out_8053498741610314229[110] = 0;
   out_8053498741610314229[111] = 0;
   out_8053498741610314229[112] = 0;
   out_8053498741610314229[113] = 0;
   out_8053498741610314229[114] = 1;
   out_8053498741610314229[115] = 0;
   out_8053498741610314229[116] = 0;
   out_8053498741610314229[117] = 0;
   out_8053498741610314229[118] = 0;
   out_8053498741610314229[119] = 0;
   out_8053498741610314229[120] = 0;
   out_8053498741610314229[121] = 0;
   out_8053498741610314229[122] = 0;
   out_8053498741610314229[123] = 0;
   out_8053498741610314229[124] = 0;
   out_8053498741610314229[125] = 0;
   out_8053498741610314229[126] = 0;
   out_8053498741610314229[127] = 0;
   out_8053498741610314229[128] = 0;
   out_8053498741610314229[129] = 0;
   out_8053498741610314229[130] = 0;
   out_8053498741610314229[131] = 0;
   out_8053498741610314229[132] = 0;
   out_8053498741610314229[133] = 1;
   out_8053498741610314229[134] = 0;
   out_8053498741610314229[135] = 0;
   out_8053498741610314229[136] = 0;
   out_8053498741610314229[137] = 0;
   out_8053498741610314229[138] = 0;
   out_8053498741610314229[139] = 0;
   out_8053498741610314229[140] = 0;
   out_8053498741610314229[141] = 0;
   out_8053498741610314229[142] = 0;
   out_8053498741610314229[143] = 0;
   out_8053498741610314229[144] = 0;
   out_8053498741610314229[145] = 0;
   out_8053498741610314229[146] = 0;
   out_8053498741610314229[147] = 0;
   out_8053498741610314229[148] = 0;
   out_8053498741610314229[149] = 0;
   out_8053498741610314229[150] = 0;
   out_8053498741610314229[151] = 0;
   out_8053498741610314229[152] = 1;
   out_8053498741610314229[153] = 0;
   out_8053498741610314229[154] = 0;
   out_8053498741610314229[155] = 0;
   out_8053498741610314229[156] = 0;
   out_8053498741610314229[157] = 0;
   out_8053498741610314229[158] = 0;
   out_8053498741610314229[159] = 0;
   out_8053498741610314229[160] = 0;
   out_8053498741610314229[161] = 0;
   out_8053498741610314229[162] = 0;
   out_8053498741610314229[163] = 0;
   out_8053498741610314229[164] = 0;
   out_8053498741610314229[165] = 0;
   out_8053498741610314229[166] = 0;
   out_8053498741610314229[167] = 0;
   out_8053498741610314229[168] = 0;
   out_8053498741610314229[169] = 0;
   out_8053498741610314229[170] = 0;
   out_8053498741610314229[171] = 1;
   out_8053498741610314229[172] = 0;
   out_8053498741610314229[173] = 0;
   out_8053498741610314229[174] = 0;
   out_8053498741610314229[175] = 0;
   out_8053498741610314229[176] = 0;
   out_8053498741610314229[177] = 0;
   out_8053498741610314229[178] = 0;
   out_8053498741610314229[179] = 0;
   out_8053498741610314229[180] = 0;
   out_8053498741610314229[181] = 0;
   out_8053498741610314229[182] = 0;
   out_8053498741610314229[183] = 0;
   out_8053498741610314229[184] = 0;
   out_8053498741610314229[185] = 0;
   out_8053498741610314229[186] = 0;
   out_8053498741610314229[187] = 0;
   out_8053498741610314229[188] = 0;
   out_8053498741610314229[189] = 0;
   out_8053498741610314229[190] = 1;
   out_8053498741610314229[191] = 0;
   out_8053498741610314229[192] = 0;
   out_8053498741610314229[193] = 0;
   out_8053498741610314229[194] = 0;
   out_8053498741610314229[195] = 0;
   out_8053498741610314229[196] = 0;
   out_8053498741610314229[197] = 0;
   out_8053498741610314229[198] = 0;
   out_8053498741610314229[199] = 0;
   out_8053498741610314229[200] = 0;
   out_8053498741610314229[201] = 0;
   out_8053498741610314229[202] = 0;
   out_8053498741610314229[203] = 0;
   out_8053498741610314229[204] = 0;
   out_8053498741610314229[205] = 0;
   out_8053498741610314229[206] = 0;
   out_8053498741610314229[207] = 0;
   out_8053498741610314229[208] = 0;
   out_8053498741610314229[209] = 1;
   out_8053498741610314229[210] = 0;
   out_8053498741610314229[211] = 0;
   out_8053498741610314229[212] = 0;
   out_8053498741610314229[213] = 0;
   out_8053498741610314229[214] = 0;
   out_8053498741610314229[215] = 0;
   out_8053498741610314229[216] = 0;
   out_8053498741610314229[217] = 0;
   out_8053498741610314229[218] = 0;
   out_8053498741610314229[219] = 0;
   out_8053498741610314229[220] = 0;
   out_8053498741610314229[221] = 0;
   out_8053498741610314229[222] = 0;
   out_8053498741610314229[223] = 0;
   out_8053498741610314229[224] = 0;
   out_8053498741610314229[225] = 0;
   out_8053498741610314229[226] = 0;
   out_8053498741610314229[227] = 0;
   out_8053498741610314229[228] = 1;
   out_8053498741610314229[229] = 0;
   out_8053498741610314229[230] = 0;
   out_8053498741610314229[231] = 0;
   out_8053498741610314229[232] = 0;
   out_8053498741610314229[233] = 0;
   out_8053498741610314229[234] = 0;
   out_8053498741610314229[235] = 0;
   out_8053498741610314229[236] = 0;
   out_8053498741610314229[237] = 0;
   out_8053498741610314229[238] = 0;
   out_8053498741610314229[239] = 0;
   out_8053498741610314229[240] = 0;
   out_8053498741610314229[241] = 0;
   out_8053498741610314229[242] = 0;
   out_8053498741610314229[243] = 0;
   out_8053498741610314229[244] = 0;
   out_8053498741610314229[245] = 0;
   out_8053498741610314229[246] = 0;
   out_8053498741610314229[247] = 1;
   out_8053498741610314229[248] = 0;
   out_8053498741610314229[249] = 0;
   out_8053498741610314229[250] = 0;
   out_8053498741610314229[251] = 0;
   out_8053498741610314229[252] = 0;
   out_8053498741610314229[253] = 0;
   out_8053498741610314229[254] = 0;
   out_8053498741610314229[255] = 0;
   out_8053498741610314229[256] = 0;
   out_8053498741610314229[257] = 0;
   out_8053498741610314229[258] = 0;
   out_8053498741610314229[259] = 0;
   out_8053498741610314229[260] = 0;
   out_8053498741610314229[261] = 0;
   out_8053498741610314229[262] = 0;
   out_8053498741610314229[263] = 0;
   out_8053498741610314229[264] = 0;
   out_8053498741610314229[265] = 0;
   out_8053498741610314229[266] = 1;
   out_8053498741610314229[267] = 0;
   out_8053498741610314229[268] = 0;
   out_8053498741610314229[269] = 0;
   out_8053498741610314229[270] = 0;
   out_8053498741610314229[271] = 0;
   out_8053498741610314229[272] = 0;
   out_8053498741610314229[273] = 0;
   out_8053498741610314229[274] = 0;
   out_8053498741610314229[275] = 0;
   out_8053498741610314229[276] = 0;
   out_8053498741610314229[277] = 0;
   out_8053498741610314229[278] = 0;
   out_8053498741610314229[279] = 0;
   out_8053498741610314229[280] = 0;
   out_8053498741610314229[281] = 0;
   out_8053498741610314229[282] = 0;
   out_8053498741610314229[283] = 0;
   out_8053498741610314229[284] = 0;
   out_8053498741610314229[285] = 1;
   out_8053498741610314229[286] = 0;
   out_8053498741610314229[287] = 0;
   out_8053498741610314229[288] = 0;
   out_8053498741610314229[289] = 0;
   out_8053498741610314229[290] = 0;
   out_8053498741610314229[291] = 0;
   out_8053498741610314229[292] = 0;
   out_8053498741610314229[293] = 0;
   out_8053498741610314229[294] = 0;
   out_8053498741610314229[295] = 0;
   out_8053498741610314229[296] = 0;
   out_8053498741610314229[297] = 0;
   out_8053498741610314229[298] = 0;
   out_8053498741610314229[299] = 0;
   out_8053498741610314229[300] = 0;
   out_8053498741610314229[301] = 0;
   out_8053498741610314229[302] = 0;
   out_8053498741610314229[303] = 0;
   out_8053498741610314229[304] = 1;
   out_8053498741610314229[305] = 0;
   out_8053498741610314229[306] = 0;
   out_8053498741610314229[307] = 0;
   out_8053498741610314229[308] = 0;
   out_8053498741610314229[309] = 0;
   out_8053498741610314229[310] = 0;
   out_8053498741610314229[311] = 0;
   out_8053498741610314229[312] = 0;
   out_8053498741610314229[313] = 0;
   out_8053498741610314229[314] = 0;
   out_8053498741610314229[315] = 0;
   out_8053498741610314229[316] = 0;
   out_8053498741610314229[317] = 0;
   out_8053498741610314229[318] = 0;
   out_8053498741610314229[319] = 0;
   out_8053498741610314229[320] = 0;
   out_8053498741610314229[321] = 0;
   out_8053498741610314229[322] = 0;
   out_8053498741610314229[323] = 1;
}
void h_4(double *state, double *unused, double *out_8491036372839021910) {
   out_8491036372839021910[0] = state[6] + state[9];
   out_8491036372839021910[1] = state[7] + state[10];
   out_8491036372839021910[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_4947511374047005870) {
   out_4947511374047005870[0] = 0;
   out_4947511374047005870[1] = 0;
   out_4947511374047005870[2] = 0;
   out_4947511374047005870[3] = 0;
   out_4947511374047005870[4] = 0;
   out_4947511374047005870[5] = 0;
   out_4947511374047005870[6] = 1;
   out_4947511374047005870[7] = 0;
   out_4947511374047005870[8] = 0;
   out_4947511374047005870[9] = 1;
   out_4947511374047005870[10] = 0;
   out_4947511374047005870[11] = 0;
   out_4947511374047005870[12] = 0;
   out_4947511374047005870[13] = 0;
   out_4947511374047005870[14] = 0;
   out_4947511374047005870[15] = 0;
   out_4947511374047005870[16] = 0;
   out_4947511374047005870[17] = 0;
   out_4947511374047005870[18] = 0;
   out_4947511374047005870[19] = 0;
   out_4947511374047005870[20] = 0;
   out_4947511374047005870[21] = 0;
   out_4947511374047005870[22] = 0;
   out_4947511374047005870[23] = 0;
   out_4947511374047005870[24] = 0;
   out_4947511374047005870[25] = 1;
   out_4947511374047005870[26] = 0;
   out_4947511374047005870[27] = 0;
   out_4947511374047005870[28] = 1;
   out_4947511374047005870[29] = 0;
   out_4947511374047005870[30] = 0;
   out_4947511374047005870[31] = 0;
   out_4947511374047005870[32] = 0;
   out_4947511374047005870[33] = 0;
   out_4947511374047005870[34] = 0;
   out_4947511374047005870[35] = 0;
   out_4947511374047005870[36] = 0;
   out_4947511374047005870[37] = 0;
   out_4947511374047005870[38] = 0;
   out_4947511374047005870[39] = 0;
   out_4947511374047005870[40] = 0;
   out_4947511374047005870[41] = 0;
   out_4947511374047005870[42] = 0;
   out_4947511374047005870[43] = 0;
   out_4947511374047005870[44] = 1;
   out_4947511374047005870[45] = 0;
   out_4947511374047005870[46] = 0;
   out_4947511374047005870[47] = 1;
   out_4947511374047005870[48] = 0;
   out_4947511374047005870[49] = 0;
   out_4947511374047005870[50] = 0;
   out_4947511374047005870[51] = 0;
   out_4947511374047005870[52] = 0;
   out_4947511374047005870[53] = 0;
}
void h_10(double *state, double *unused, double *out_5511963967555442025) {
   out_5511963967555442025[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_5511963967555442025[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_5511963967555442025[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_4954425742172604258) {
   out_4954425742172604258[0] = 0;
   out_4954425742172604258[1] = 9.8100000000000005*cos(state[1]);
   out_4954425742172604258[2] = 0;
   out_4954425742172604258[3] = 0;
   out_4954425742172604258[4] = -state[8];
   out_4954425742172604258[5] = state[7];
   out_4954425742172604258[6] = 0;
   out_4954425742172604258[7] = state[5];
   out_4954425742172604258[8] = -state[4];
   out_4954425742172604258[9] = 0;
   out_4954425742172604258[10] = 0;
   out_4954425742172604258[11] = 0;
   out_4954425742172604258[12] = 1;
   out_4954425742172604258[13] = 0;
   out_4954425742172604258[14] = 0;
   out_4954425742172604258[15] = 1;
   out_4954425742172604258[16] = 0;
   out_4954425742172604258[17] = 0;
   out_4954425742172604258[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_4954425742172604258[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_4954425742172604258[20] = 0;
   out_4954425742172604258[21] = state[8];
   out_4954425742172604258[22] = 0;
   out_4954425742172604258[23] = -state[6];
   out_4954425742172604258[24] = -state[5];
   out_4954425742172604258[25] = 0;
   out_4954425742172604258[26] = state[3];
   out_4954425742172604258[27] = 0;
   out_4954425742172604258[28] = 0;
   out_4954425742172604258[29] = 0;
   out_4954425742172604258[30] = 0;
   out_4954425742172604258[31] = 1;
   out_4954425742172604258[32] = 0;
   out_4954425742172604258[33] = 0;
   out_4954425742172604258[34] = 1;
   out_4954425742172604258[35] = 0;
   out_4954425742172604258[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_4954425742172604258[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_4954425742172604258[38] = 0;
   out_4954425742172604258[39] = -state[7];
   out_4954425742172604258[40] = state[6];
   out_4954425742172604258[41] = 0;
   out_4954425742172604258[42] = state[4];
   out_4954425742172604258[43] = -state[3];
   out_4954425742172604258[44] = 0;
   out_4954425742172604258[45] = 0;
   out_4954425742172604258[46] = 0;
   out_4954425742172604258[47] = 0;
   out_4954425742172604258[48] = 0;
   out_4954425742172604258[49] = 0;
   out_4954425742172604258[50] = 1;
   out_4954425742172604258[51] = 0;
   out_4954425742172604258[52] = 0;
   out_4954425742172604258[53] = 1;
}
void h_13(double *state, double *unused, double *out_2978335881196755829) {
   out_2978335881196755829[0] = state[3];
   out_2978335881196755829[1] = state[4];
   out_2978335881196755829[2] = state[5];
}
void H_13(double *state, double *unused, double *out_8159785199379338671) {
   out_8159785199379338671[0] = 0;
   out_8159785199379338671[1] = 0;
   out_8159785199379338671[2] = 0;
   out_8159785199379338671[3] = 1;
   out_8159785199379338671[4] = 0;
   out_8159785199379338671[5] = 0;
   out_8159785199379338671[6] = 0;
   out_8159785199379338671[7] = 0;
   out_8159785199379338671[8] = 0;
   out_8159785199379338671[9] = 0;
   out_8159785199379338671[10] = 0;
   out_8159785199379338671[11] = 0;
   out_8159785199379338671[12] = 0;
   out_8159785199379338671[13] = 0;
   out_8159785199379338671[14] = 0;
   out_8159785199379338671[15] = 0;
   out_8159785199379338671[16] = 0;
   out_8159785199379338671[17] = 0;
   out_8159785199379338671[18] = 0;
   out_8159785199379338671[19] = 0;
   out_8159785199379338671[20] = 0;
   out_8159785199379338671[21] = 0;
   out_8159785199379338671[22] = 1;
   out_8159785199379338671[23] = 0;
   out_8159785199379338671[24] = 0;
   out_8159785199379338671[25] = 0;
   out_8159785199379338671[26] = 0;
   out_8159785199379338671[27] = 0;
   out_8159785199379338671[28] = 0;
   out_8159785199379338671[29] = 0;
   out_8159785199379338671[30] = 0;
   out_8159785199379338671[31] = 0;
   out_8159785199379338671[32] = 0;
   out_8159785199379338671[33] = 0;
   out_8159785199379338671[34] = 0;
   out_8159785199379338671[35] = 0;
   out_8159785199379338671[36] = 0;
   out_8159785199379338671[37] = 0;
   out_8159785199379338671[38] = 0;
   out_8159785199379338671[39] = 0;
   out_8159785199379338671[40] = 0;
   out_8159785199379338671[41] = 1;
   out_8159785199379338671[42] = 0;
   out_8159785199379338671[43] = 0;
   out_8159785199379338671[44] = 0;
   out_8159785199379338671[45] = 0;
   out_8159785199379338671[46] = 0;
   out_8159785199379338671[47] = 0;
   out_8159785199379338671[48] = 0;
   out_8159785199379338671[49] = 0;
   out_8159785199379338671[50] = 0;
   out_8159785199379338671[51] = 0;
   out_8159785199379338671[52] = 0;
   out_8159785199379338671[53] = 0;
}
void h_14(double *state, double *unused, double *out_3775673678134670228) {
   out_3775673678134670228[0] = state[6];
   out_3775673678134670228[1] = state[7];
   out_3775673678134670228[2] = state[8];
}
void H_14(double *state, double *unused, double *out_8910752230386490399) {
   out_8910752230386490399[0] = 0;
   out_8910752230386490399[1] = 0;
   out_8910752230386490399[2] = 0;
   out_8910752230386490399[3] = 0;
   out_8910752230386490399[4] = 0;
   out_8910752230386490399[5] = 0;
   out_8910752230386490399[6] = 1;
   out_8910752230386490399[7] = 0;
   out_8910752230386490399[8] = 0;
   out_8910752230386490399[9] = 0;
   out_8910752230386490399[10] = 0;
   out_8910752230386490399[11] = 0;
   out_8910752230386490399[12] = 0;
   out_8910752230386490399[13] = 0;
   out_8910752230386490399[14] = 0;
   out_8910752230386490399[15] = 0;
   out_8910752230386490399[16] = 0;
   out_8910752230386490399[17] = 0;
   out_8910752230386490399[18] = 0;
   out_8910752230386490399[19] = 0;
   out_8910752230386490399[20] = 0;
   out_8910752230386490399[21] = 0;
   out_8910752230386490399[22] = 0;
   out_8910752230386490399[23] = 0;
   out_8910752230386490399[24] = 0;
   out_8910752230386490399[25] = 1;
   out_8910752230386490399[26] = 0;
   out_8910752230386490399[27] = 0;
   out_8910752230386490399[28] = 0;
   out_8910752230386490399[29] = 0;
   out_8910752230386490399[30] = 0;
   out_8910752230386490399[31] = 0;
   out_8910752230386490399[32] = 0;
   out_8910752230386490399[33] = 0;
   out_8910752230386490399[34] = 0;
   out_8910752230386490399[35] = 0;
   out_8910752230386490399[36] = 0;
   out_8910752230386490399[37] = 0;
   out_8910752230386490399[38] = 0;
   out_8910752230386490399[39] = 0;
   out_8910752230386490399[40] = 0;
   out_8910752230386490399[41] = 0;
   out_8910752230386490399[42] = 0;
   out_8910752230386490399[43] = 0;
   out_8910752230386490399[44] = 1;
   out_8910752230386490399[45] = 0;
   out_8910752230386490399[46] = 0;
   out_8910752230386490399[47] = 0;
   out_8910752230386490399[48] = 0;
   out_8910752230386490399[49] = 0;
   out_8910752230386490399[50] = 0;
   out_8910752230386490399[51] = 0;
   out_8910752230386490399[52] = 0;
   out_8910752230386490399[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_7263283861877820451) {
  err_fun(nom_x, delta_x, out_7263283861877820451);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_5554489381921509580) {
  inv_err_fun(nom_x, true_x, out_5554489381921509580);
}
void pose_H_mod_fun(double *state, double *out_8221733452837955123) {
  H_mod_fun(state, out_8221733452837955123);
}
void pose_f_fun(double *state, double dt, double *out_6005799925322513099) {
  f_fun(state,  dt, out_6005799925322513099);
}
void pose_F_fun(double *state, double dt, double *out_8053498741610314229) {
  F_fun(state,  dt, out_8053498741610314229);
}
void pose_h_4(double *state, double *unused, double *out_8491036372839021910) {
  h_4(state, unused, out_8491036372839021910);
}
void pose_H_4(double *state, double *unused, double *out_4947511374047005870) {
  H_4(state, unused, out_4947511374047005870);
}
void pose_h_10(double *state, double *unused, double *out_5511963967555442025) {
  h_10(state, unused, out_5511963967555442025);
}
void pose_H_10(double *state, double *unused, double *out_4954425742172604258) {
  H_10(state, unused, out_4954425742172604258);
}
void pose_h_13(double *state, double *unused, double *out_2978335881196755829) {
  h_13(state, unused, out_2978335881196755829);
}
void pose_H_13(double *state, double *unused, double *out_8159785199379338671) {
  H_13(state, unused, out_8159785199379338671);
}
void pose_h_14(double *state, double *unused, double *out_3775673678134670228) {
  h_14(state, unused, out_3775673678134670228);
}
void pose_H_14(double *state, double *unused, double *out_8910752230386490399) {
  H_14(state, unused, out_8910752230386490399);
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
