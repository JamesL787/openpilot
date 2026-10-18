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
void err_fun(double *nom_x, double *delta_x, double *out_6550964315864651157) {
   out_6550964315864651157[0] = delta_x[0] + nom_x[0];
   out_6550964315864651157[1] = delta_x[1] + nom_x[1];
   out_6550964315864651157[2] = delta_x[2] + nom_x[2];
   out_6550964315864651157[3] = delta_x[3] + nom_x[3];
   out_6550964315864651157[4] = delta_x[4] + nom_x[4];
   out_6550964315864651157[5] = delta_x[5] + nom_x[5];
   out_6550964315864651157[6] = delta_x[6] + nom_x[6];
   out_6550964315864651157[7] = delta_x[7] + nom_x[7];
   out_6550964315864651157[8] = delta_x[8] + nom_x[8];
   out_6550964315864651157[9] = delta_x[9] + nom_x[9];
   out_6550964315864651157[10] = delta_x[10] + nom_x[10];
   out_6550964315864651157[11] = delta_x[11] + nom_x[11];
   out_6550964315864651157[12] = delta_x[12] + nom_x[12];
   out_6550964315864651157[13] = delta_x[13] + nom_x[13];
   out_6550964315864651157[14] = delta_x[14] + nom_x[14];
   out_6550964315864651157[15] = delta_x[15] + nom_x[15];
   out_6550964315864651157[16] = delta_x[16] + nom_x[16];
   out_6550964315864651157[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_4895562721991879665) {
   out_4895562721991879665[0] = -nom_x[0] + true_x[0];
   out_4895562721991879665[1] = -nom_x[1] + true_x[1];
   out_4895562721991879665[2] = -nom_x[2] + true_x[2];
   out_4895562721991879665[3] = -nom_x[3] + true_x[3];
   out_4895562721991879665[4] = -nom_x[4] + true_x[4];
   out_4895562721991879665[5] = -nom_x[5] + true_x[5];
   out_4895562721991879665[6] = -nom_x[6] + true_x[6];
   out_4895562721991879665[7] = -nom_x[7] + true_x[7];
   out_4895562721991879665[8] = -nom_x[8] + true_x[8];
   out_4895562721991879665[9] = -nom_x[9] + true_x[9];
   out_4895562721991879665[10] = -nom_x[10] + true_x[10];
   out_4895562721991879665[11] = -nom_x[11] + true_x[11];
   out_4895562721991879665[12] = -nom_x[12] + true_x[12];
   out_4895562721991879665[13] = -nom_x[13] + true_x[13];
   out_4895562721991879665[14] = -nom_x[14] + true_x[14];
   out_4895562721991879665[15] = -nom_x[15] + true_x[15];
   out_4895562721991879665[16] = -nom_x[16] + true_x[16];
   out_4895562721991879665[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_2502229566014209319) {
   out_2502229566014209319[0] = 1.0;
   out_2502229566014209319[1] = 0.0;
   out_2502229566014209319[2] = 0.0;
   out_2502229566014209319[3] = 0.0;
   out_2502229566014209319[4] = 0.0;
   out_2502229566014209319[5] = 0.0;
   out_2502229566014209319[6] = 0.0;
   out_2502229566014209319[7] = 0.0;
   out_2502229566014209319[8] = 0.0;
   out_2502229566014209319[9] = 0.0;
   out_2502229566014209319[10] = 0.0;
   out_2502229566014209319[11] = 0.0;
   out_2502229566014209319[12] = 0.0;
   out_2502229566014209319[13] = 0.0;
   out_2502229566014209319[14] = 0.0;
   out_2502229566014209319[15] = 0.0;
   out_2502229566014209319[16] = 0.0;
   out_2502229566014209319[17] = 0.0;
   out_2502229566014209319[18] = 0.0;
   out_2502229566014209319[19] = 1.0;
   out_2502229566014209319[20] = 0.0;
   out_2502229566014209319[21] = 0.0;
   out_2502229566014209319[22] = 0.0;
   out_2502229566014209319[23] = 0.0;
   out_2502229566014209319[24] = 0.0;
   out_2502229566014209319[25] = 0.0;
   out_2502229566014209319[26] = 0.0;
   out_2502229566014209319[27] = 0.0;
   out_2502229566014209319[28] = 0.0;
   out_2502229566014209319[29] = 0.0;
   out_2502229566014209319[30] = 0.0;
   out_2502229566014209319[31] = 0.0;
   out_2502229566014209319[32] = 0.0;
   out_2502229566014209319[33] = 0.0;
   out_2502229566014209319[34] = 0.0;
   out_2502229566014209319[35] = 0.0;
   out_2502229566014209319[36] = 0.0;
   out_2502229566014209319[37] = 0.0;
   out_2502229566014209319[38] = 1.0;
   out_2502229566014209319[39] = 0.0;
   out_2502229566014209319[40] = 0.0;
   out_2502229566014209319[41] = 0.0;
   out_2502229566014209319[42] = 0.0;
   out_2502229566014209319[43] = 0.0;
   out_2502229566014209319[44] = 0.0;
   out_2502229566014209319[45] = 0.0;
   out_2502229566014209319[46] = 0.0;
   out_2502229566014209319[47] = 0.0;
   out_2502229566014209319[48] = 0.0;
   out_2502229566014209319[49] = 0.0;
   out_2502229566014209319[50] = 0.0;
   out_2502229566014209319[51] = 0.0;
   out_2502229566014209319[52] = 0.0;
   out_2502229566014209319[53] = 0.0;
   out_2502229566014209319[54] = 0.0;
   out_2502229566014209319[55] = 0.0;
   out_2502229566014209319[56] = 0.0;
   out_2502229566014209319[57] = 1.0;
   out_2502229566014209319[58] = 0.0;
   out_2502229566014209319[59] = 0.0;
   out_2502229566014209319[60] = 0.0;
   out_2502229566014209319[61] = 0.0;
   out_2502229566014209319[62] = 0.0;
   out_2502229566014209319[63] = 0.0;
   out_2502229566014209319[64] = 0.0;
   out_2502229566014209319[65] = 0.0;
   out_2502229566014209319[66] = 0.0;
   out_2502229566014209319[67] = 0.0;
   out_2502229566014209319[68] = 0.0;
   out_2502229566014209319[69] = 0.0;
   out_2502229566014209319[70] = 0.0;
   out_2502229566014209319[71] = 0.0;
   out_2502229566014209319[72] = 0.0;
   out_2502229566014209319[73] = 0.0;
   out_2502229566014209319[74] = 0.0;
   out_2502229566014209319[75] = 0.0;
   out_2502229566014209319[76] = 1.0;
   out_2502229566014209319[77] = 0.0;
   out_2502229566014209319[78] = 0.0;
   out_2502229566014209319[79] = 0.0;
   out_2502229566014209319[80] = 0.0;
   out_2502229566014209319[81] = 0.0;
   out_2502229566014209319[82] = 0.0;
   out_2502229566014209319[83] = 0.0;
   out_2502229566014209319[84] = 0.0;
   out_2502229566014209319[85] = 0.0;
   out_2502229566014209319[86] = 0.0;
   out_2502229566014209319[87] = 0.0;
   out_2502229566014209319[88] = 0.0;
   out_2502229566014209319[89] = 0.0;
   out_2502229566014209319[90] = 0.0;
   out_2502229566014209319[91] = 0.0;
   out_2502229566014209319[92] = 0.0;
   out_2502229566014209319[93] = 0.0;
   out_2502229566014209319[94] = 0.0;
   out_2502229566014209319[95] = 1.0;
   out_2502229566014209319[96] = 0.0;
   out_2502229566014209319[97] = 0.0;
   out_2502229566014209319[98] = 0.0;
   out_2502229566014209319[99] = 0.0;
   out_2502229566014209319[100] = 0.0;
   out_2502229566014209319[101] = 0.0;
   out_2502229566014209319[102] = 0.0;
   out_2502229566014209319[103] = 0.0;
   out_2502229566014209319[104] = 0.0;
   out_2502229566014209319[105] = 0.0;
   out_2502229566014209319[106] = 0.0;
   out_2502229566014209319[107] = 0.0;
   out_2502229566014209319[108] = 0.0;
   out_2502229566014209319[109] = 0.0;
   out_2502229566014209319[110] = 0.0;
   out_2502229566014209319[111] = 0.0;
   out_2502229566014209319[112] = 0.0;
   out_2502229566014209319[113] = 0.0;
   out_2502229566014209319[114] = 1.0;
   out_2502229566014209319[115] = 0.0;
   out_2502229566014209319[116] = 0.0;
   out_2502229566014209319[117] = 0.0;
   out_2502229566014209319[118] = 0.0;
   out_2502229566014209319[119] = 0.0;
   out_2502229566014209319[120] = 0.0;
   out_2502229566014209319[121] = 0.0;
   out_2502229566014209319[122] = 0.0;
   out_2502229566014209319[123] = 0.0;
   out_2502229566014209319[124] = 0.0;
   out_2502229566014209319[125] = 0.0;
   out_2502229566014209319[126] = 0.0;
   out_2502229566014209319[127] = 0.0;
   out_2502229566014209319[128] = 0.0;
   out_2502229566014209319[129] = 0.0;
   out_2502229566014209319[130] = 0.0;
   out_2502229566014209319[131] = 0.0;
   out_2502229566014209319[132] = 0.0;
   out_2502229566014209319[133] = 1.0;
   out_2502229566014209319[134] = 0.0;
   out_2502229566014209319[135] = 0.0;
   out_2502229566014209319[136] = 0.0;
   out_2502229566014209319[137] = 0.0;
   out_2502229566014209319[138] = 0.0;
   out_2502229566014209319[139] = 0.0;
   out_2502229566014209319[140] = 0.0;
   out_2502229566014209319[141] = 0.0;
   out_2502229566014209319[142] = 0.0;
   out_2502229566014209319[143] = 0.0;
   out_2502229566014209319[144] = 0.0;
   out_2502229566014209319[145] = 0.0;
   out_2502229566014209319[146] = 0.0;
   out_2502229566014209319[147] = 0.0;
   out_2502229566014209319[148] = 0.0;
   out_2502229566014209319[149] = 0.0;
   out_2502229566014209319[150] = 0.0;
   out_2502229566014209319[151] = 0.0;
   out_2502229566014209319[152] = 1.0;
   out_2502229566014209319[153] = 0.0;
   out_2502229566014209319[154] = 0.0;
   out_2502229566014209319[155] = 0.0;
   out_2502229566014209319[156] = 0.0;
   out_2502229566014209319[157] = 0.0;
   out_2502229566014209319[158] = 0.0;
   out_2502229566014209319[159] = 0.0;
   out_2502229566014209319[160] = 0.0;
   out_2502229566014209319[161] = 0.0;
   out_2502229566014209319[162] = 0.0;
   out_2502229566014209319[163] = 0.0;
   out_2502229566014209319[164] = 0.0;
   out_2502229566014209319[165] = 0.0;
   out_2502229566014209319[166] = 0.0;
   out_2502229566014209319[167] = 0.0;
   out_2502229566014209319[168] = 0.0;
   out_2502229566014209319[169] = 0.0;
   out_2502229566014209319[170] = 0.0;
   out_2502229566014209319[171] = 1.0;
   out_2502229566014209319[172] = 0.0;
   out_2502229566014209319[173] = 0.0;
   out_2502229566014209319[174] = 0.0;
   out_2502229566014209319[175] = 0.0;
   out_2502229566014209319[176] = 0.0;
   out_2502229566014209319[177] = 0.0;
   out_2502229566014209319[178] = 0.0;
   out_2502229566014209319[179] = 0.0;
   out_2502229566014209319[180] = 0.0;
   out_2502229566014209319[181] = 0.0;
   out_2502229566014209319[182] = 0.0;
   out_2502229566014209319[183] = 0.0;
   out_2502229566014209319[184] = 0.0;
   out_2502229566014209319[185] = 0.0;
   out_2502229566014209319[186] = 0.0;
   out_2502229566014209319[187] = 0.0;
   out_2502229566014209319[188] = 0.0;
   out_2502229566014209319[189] = 0.0;
   out_2502229566014209319[190] = 1.0;
   out_2502229566014209319[191] = 0.0;
   out_2502229566014209319[192] = 0.0;
   out_2502229566014209319[193] = 0.0;
   out_2502229566014209319[194] = 0.0;
   out_2502229566014209319[195] = 0.0;
   out_2502229566014209319[196] = 0.0;
   out_2502229566014209319[197] = 0.0;
   out_2502229566014209319[198] = 0.0;
   out_2502229566014209319[199] = 0.0;
   out_2502229566014209319[200] = 0.0;
   out_2502229566014209319[201] = 0.0;
   out_2502229566014209319[202] = 0.0;
   out_2502229566014209319[203] = 0.0;
   out_2502229566014209319[204] = 0.0;
   out_2502229566014209319[205] = 0.0;
   out_2502229566014209319[206] = 0.0;
   out_2502229566014209319[207] = 0.0;
   out_2502229566014209319[208] = 0.0;
   out_2502229566014209319[209] = 1.0;
   out_2502229566014209319[210] = 0.0;
   out_2502229566014209319[211] = 0.0;
   out_2502229566014209319[212] = 0.0;
   out_2502229566014209319[213] = 0.0;
   out_2502229566014209319[214] = 0.0;
   out_2502229566014209319[215] = 0.0;
   out_2502229566014209319[216] = 0.0;
   out_2502229566014209319[217] = 0.0;
   out_2502229566014209319[218] = 0.0;
   out_2502229566014209319[219] = 0.0;
   out_2502229566014209319[220] = 0.0;
   out_2502229566014209319[221] = 0.0;
   out_2502229566014209319[222] = 0.0;
   out_2502229566014209319[223] = 0.0;
   out_2502229566014209319[224] = 0.0;
   out_2502229566014209319[225] = 0.0;
   out_2502229566014209319[226] = 0.0;
   out_2502229566014209319[227] = 0.0;
   out_2502229566014209319[228] = 1.0;
   out_2502229566014209319[229] = 0.0;
   out_2502229566014209319[230] = 0.0;
   out_2502229566014209319[231] = 0.0;
   out_2502229566014209319[232] = 0.0;
   out_2502229566014209319[233] = 0.0;
   out_2502229566014209319[234] = 0.0;
   out_2502229566014209319[235] = 0.0;
   out_2502229566014209319[236] = 0.0;
   out_2502229566014209319[237] = 0.0;
   out_2502229566014209319[238] = 0.0;
   out_2502229566014209319[239] = 0.0;
   out_2502229566014209319[240] = 0.0;
   out_2502229566014209319[241] = 0.0;
   out_2502229566014209319[242] = 0.0;
   out_2502229566014209319[243] = 0.0;
   out_2502229566014209319[244] = 0.0;
   out_2502229566014209319[245] = 0.0;
   out_2502229566014209319[246] = 0.0;
   out_2502229566014209319[247] = 1.0;
   out_2502229566014209319[248] = 0.0;
   out_2502229566014209319[249] = 0.0;
   out_2502229566014209319[250] = 0.0;
   out_2502229566014209319[251] = 0.0;
   out_2502229566014209319[252] = 0.0;
   out_2502229566014209319[253] = 0.0;
   out_2502229566014209319[254] = 0.0;
   out_2502229566014209319[255] = 0.0;
   out_2502229566014209319[256] = 0.0;
   out_2502229566014209319[257] = 0.0;
   out_2502229566014209319[258] = 0.0;
   out_2502229566014209319[259] = 0.0;
   out_2502229566014209319[260] = 0.0;
   out_2502229566014209319[261] = 0.0;
   out_2502229566014209319[262] = 0.0;
   out_2502229566014209319[263] = 0.0;
   out_2502229566014209319[264] = 0.0;
   out_2502229566014209319[265] = 0.0;
   out_2502229566014209319[266] = 1.0;
   out_2502229566014209319[267] = 0.0;
   out_2502229566014209319[268] = 0.0;
   out_2502229566014209319[269] = 0.0;
   out_2502229566014209319[270] = 0.0;
   out_2502229566014209319[271] = 0.0;
   out_2502229566014209319[272] = 0.0;
   out_2502229566014209319[273] = 0.0;
   out_2502229566014209319[274] = 0.0;
   out_2502229566014209319[275] = 0.0;
   out_2502229566014209319[276] = 0.0;
   out_2502229566014209319[277] = 0.0;
   out_2502229566014209319[278] = 0.0;
   out_2502229566014209319[279] = 0.0;
   out_2502229566014209319[280] = 0.0;
   out_2502229566014209319[281] = 0.0;
   out_2502229566014209319[282] = 0.0;
   out_2502229566014209319[283] = 0.0;
   out_2502229566014209319[284] = 0.0;
   out_2502229566014209319[285] = 1.0;
   out_2502229566014209319[286] = 0.0;
   out_2502229566014209319[287] = 0.0;
   out_2502229566014209319[288] = 0.0;
   out_2502229566014209319[289] = 0.0;
   out_2502229566014209319[290] = 0.0;
   out_2502229566014209319[291] = 0.0;
   out_2502229566014209319[292] = 0.0;
   out_2502229566014209319[293] = 0.0;
   out_2502229566014209319[294] = 0.0;
   out_2502229566014209319[295] = 0.0;
   out_2502229566014209319[296] = 0.0;
   out_2502229566014209319[297] = 0.0;
   out_2502229566014209319[298] = 0.0;
   out_2502229566014209319[299] = 0.0;
   out_2502229566014209319[300] = 0.0;
   out_2502229566014209319[301] = 0.0;
   out_2502229566014209319[302] = 0.0;
   out_2502229566014209319[303] = 0.0;
   out_2502229566014209319[304] = 1.0;
   out_2502229566014209319[305] = 0.0;
   out_2502229566014209319[306] = 0.0;
   out_2502229566014209319[307] = 0.0;
   out_2502229566014209319[308] = 0.0;
   out_2502229566014209319[309] = 0.0;
   out_2502229566014209319[310] = 0.0;
   out_2502229566014209319[311] = 0.0;
   out_2502229566014209319[312] = 0.0;
   out_2502229566014209319[313] = 0.0;
   out_2502229566014209319[314] = 0.0;
   out_2502229566014209319[315] = 0.0;
   out_2502229566014209319[316] = 0.0;
   out_2502229566014209319[317] = 0.0;
   out_2502229566014209319[318] = 0.0;
   out_2502229566014209319[319] = 0.0;
   out_2502229566014209319[320] = 0.0;
   out_2502229566014209319[321] = 0.0;
   out_2502229566014209319[322] = 0.0;
   out_2502229566014209319[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_7650543638844674851) {
   out_7650543638844674851[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_7650543638844674851[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_7650543638844674851[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_7650543638844674851[3] = dt*state[12] + state[3];
   out_7650543638844674851[4] = dt*state[13] + state[4];
   out_7650543638844674851[5] = dt*state[14] + state[5];
   out_7650543638844674851[6] = state[6];
   out_7650543638844674851[7] = state[7];
   out_7650543638844674851[8] = state[8];
   out_7650543638844674851[9] = state[9];
   out_7650543638844674851[10] = state[10];
   out_7650543638844674851[11] = state[11];
   out_7650543638844674851[12] = state[12];
   out_7650543638844674851[13] = state[13];
   out_7650543638844674851[14] = state[14];
   out_7650543638844674851[15] = state[15];
   out_7650543638844674851[16] = state[16];
   out_7650543638844674851[17] = state[17];
}
void F_fun(double *state, double dt, double *out_3194571375064067580) {
   out_3194571375064067580[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3194571375064067580[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3194571375064067580[2] = 0;
   out_3194571375064067580[3] = 0;
   out_3194571375064067580[4] = 0;
   out_3194571375064067580[5] = 0;
   out_3194571375064067580[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3194571375064067580[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3194571375064067580[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3194571375064067580[9] = 0;
   out_3194571375064067580[10] = 0;
   out_3194571375064067580[11] = 0;
   out_3194571375064067580[12] = 0;
   out_3194571375064067580[13] = 0;
   out_3194571375064067580[14] = 0;
   out_3194571375064067580[15] = 0;
   out_3194571375064067580[16] = 0;
   out_3194571375064067580[17] = 0;
   out_3194571375064067580[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3194571375064067580[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3194571375064067580[20] = 0;
   out_3194571375064067580[21] = 0;
   out_3194571375064067580[22] = 0;
   out_3194571375064067580[23] = 0;
   out_3194571375064067580[24] = 0;
   out_3194571375064067580[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3194571375064067580[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3194571375064067580[27] = 0;
   out_3194571375064067580[28] = 0;
   out_3194571375064067580[29] = 0;
   out_3194571375064067580[30] = 0;
   out_3194571375064067580[31] = 0;
   out_3194571375064067580[32] = 0;
   out_3194571375064067580[33] = 0;
   out_3194571375064067580[34] = 0;
   out_3194571375064067580[35] = 0;
   out_3194571375064067580[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3194571375064067580[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3194571375064067580[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3194571375064067580[39] = 0;
   out_3194571375064067580[40] = 0;
   out_3194571375064067580[41] = 0;
   out_3194571375064067580[42] = 0;
   out_3194571375064067580[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3194571375064067580[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3194571375064067580[45] = 0;
   out_3194571375064067580[46] = 0;
   out_3194571375064067580[47] = 0;
   out_3194571375064067580[48] = 0;
   out_3194571375064067580[49] = 0;
   out_3194571375064067580[50] = 0;
   out_3194571375064067580[51] = 0;
   out_3194571375064067580[52] = 0;
   out_3194571375064067580[53] = 0;
   out_3194571375064067580[54] = 0;
   out_3194571375064067580[55] = 0;
   out_3194571375064067580[56] = 0;
   out_3194571375064067580[57] = 1;
   out_3194571375064067580[58] = 0;
   out_3194571375064067580[59] = 0;
   out_3194571375064067580[60] = 0;
   out_3194571375064067580[61] = 0;
   out_3194571375064067580[62] = 0;
   out_3194571375064067580[63] = 0;
   out_3194571375064067580[64] = 0;
   out_3194571375064067580[65] = 0;
   out_3194571375064067580[66] = dt;
   out_3194571375064067580[67] = 0;
   out_3194571375064067580[68] = 0;
   out_3194571375064067580[69] = 0;
   out_3194571375064067580[70] = 0;
   out_3194571375064067580[71] = 0;
   out_3194571375064067580[72] = 0;
   out_3194571375064067580[73] = 0;
   out_3194571375064067580[74] = 0;
   out_3194571375064067580[75] = 0;
   out_3194571375064067580[76] = 1;
   out_3194571375064067580[77] = 0;
   out_3194571375064067580[78] = 0;
   out_3194571375064067580[79] = 0;
   out_3194571375064067580[80] = 0;
   out_3194571375064067580[81] = 0;
   out_3194571375064067580[82] = 0;
   out_3194571375064067580[83] = 0;
   out_3194571375064067580[84] = 0;
   out_3194571375064067580[85] = dt;
   out_3194571375064067580[86] = 0;
   out_3194571375064067580[87] = 0;
   out_3194571375064067580[88] = 0;
   out_3194571375064067580[89] = 0;
   out_3194571375064067580[90] = 0;
   out_3194571375064067580[91] = 0;
   out_3194571375064067580[92] = 0;
   out_3194571375064067580[93] = 0;
   out_3194571375064067580[94] = 0;
   out_3194571375064067580[95] = 1;
   out_3194571375064067580[96] = 0;
   out_3194571375064067580[97] = 0;
   out_3194571375064067580[98] = 0;
   out_3194571375064067580[99] = 0;
   out_3194571375064067580[100] = 0;
   out_3194571375064067580[101] = 0;
   out_3194571375064067580[102] = 0;
   out_3194571375064067580[103] = 0;
   out_3194571375064067580[104] = dt;
   out_3194571375064067580[105] = 0;
   out_3194571375064067580[106] = 0;
   out_3194571375064067580[107] = 0;
   out_3194571375064067580[108] = 0;
   out_3194571375064067580[109] = 0;
   out_3194571375064067580[110] = 0;
   out_3194571375064067580[111] = 0;
   out_3194571375064067580[112] = 0;
   out_3194571375064067580[113] = 0;
   out_3194571375064067580[114] = 1;
   out_3194571375064067580[115] = 0;
   out_3194571375064067580[116] = 0;
   out_3194571375064067580[117] = 0;
   out_3194571375064067580[118] = 0;
   out_3194571375064067580[119] = 0;
   out_3194571375064067580[120] = 0;
   out_3194571375064067580[121] = 0;
   out_3194571375064067580[122] = 0;
   out_3194571375064067580[123] = 0;
   out_3194571375064067580[124] = 0;
   out_3194571375064067580[125] = 0;
   out_3194571375064067580[126] = 0;
   out_3194571375064067580[127] = 0;
   out_3194571375064067580[128] = 0;
   out_3194571375064067580[129] = 0;
   out_3194571375064067580[130] = 0;
   out_3194571375064067580[131] = 0;
   out_3194571375064067580[132] = 0;
   out_3194571375064067580[133] = 1;
   out_3194571375064067580[134] = 0;
   out_3194571375064067580[135] = 0;
   out_3194571375064067580[136] = 0;
   out_3194571375064067580[137] = 0;
   out_3194571375064067580[138] = 0;
   out_3194571375064067580[139] = 0;
   out_3194571375064067580[140] = 0;
   out_3194571375064067580[141] = 0;
   out_3194571375064067580[142] = 0;
   out_3194571375064067580[143] = 0;
   out_3194571375064067580[144] = 0;
   out_3194571375064067580[145] = 0;
   out_3194571375064067580[146] = 0;
   out_3194571375064067580[147] = 0;
   out_3194571375064067580[148] = 0;
   out_3194571375064067580[149] = 0;
   out_3194571375064067580[150] = 0;
   out_3194571375064067580[151] = 0;
   out_3194571375064067580[152] = 1;
   out_3194571375064067580[153] = 0;
   out_3194571375064067580[154] = 0;
   out_3194571375064067580[155] = 0;
   out_3194571375064067580[156] = 0;
   out_3194571375064067580[157] = 0;
   out_3194571375064067580[158] = 0;
   out_3194571375064067580[159] = 0;
   out_3194571375064067580[160] = 0;
   out_3194571375064067580[161] = 0;
   out_3194571375064067580[162] = 0;
   out_3194571375064067580[163] = 0;
   out_3194571375064067580[164] = 0;
   out_3194571375064067580[165] = 0;
   out_3194571375064067580[166] = 0;
   out_3194571375064067580[167] = 0;
   out_3194571375064067580[168] = 0;
   out_3194571375064067580[169] = 0;
   out_3194571375064067580[170] = 0;
   out_3194571375064067580[171] = 1;
   out_3194571375064067580[172] = 0;
   out_3194571375064067580[173] = 0;
   out_3194571375064067580[174] = 0;
   out_3194571375064067580[175] = 0;
   out_3194571375064067580[176] = 0;
   out_3194571375064067580[177] = 0;
   out_3194571375064067580[178] = 0;
   out_3194571375064067580[179] = 0;
   out_3194571375064067580[180] = 0;
   out_3194571375064067580[181] = 0;
   out_3194571375064067580[182] = 0;
   out_3194571375064067580[183] = 0;
   out_3194571375064067580[184] = 0;
   out_3194571375064067580[185] = 0;
   out_3194571375064067580[186] = 0;
   out_3194571375064067580[187] = 0;
   out_3194571375064067580[188] = 0;
   out_3194571375064067580[189] = 0;
   out_3194571375064067580[190] = 1;
   out_3194571375064067580[191] = 0;
   out_3194571375064067580[192] = 0;
   out_3194571375064067580[193] = 0;
   out_3194571375064067580[194] = 0;
   out_3194571375064067580[195] = 0;
   out_3194571375064067580[196] = 0;
   out_3194571375064067580[197] = 0;
   out_3194571375064067580[198] = 0;
   out_3194571375064067580[199] = 0;
   out_3194571375064067580[200] = 0;
   out_3194571375064067580[201] = 0;
   out_3194571375064067580[202] = 0;
   out_3194571375064067580[203] = 0;
   out_3194571375064067580[204] = 0;
   out_3194571375064067580[205] = 0;
   out_3194571375064067580[206] = 0;
   out_3194571375064067580[207] = 0;
   out_3194571375064067580[208] = 0;
   out_3194571375064067580[209] = 1;
   out_3194571375064067580[210] = 0;
   out_3194571375064067580[211] = 0;
   out_3194571375064067580[212] = 0;
   out_3194571375064067580[213] = 0;
   out_3194571375064067580[214] = 0;
   out_3194571375064067580[215] = 0;
   out_3194571375064067580[216] = 0;
   out_3194571375064067580[217] = 0;
   out_3194571375064067580[218] = 0;
   out_3194571375064067580[219] = 0;
   out_3194571375064067580[220] = 0;
   out_3194571375064067580[221] = 0;
   out_3194571375064067580[222] = 0;
   out_3194571375064067580[223] = 0;
   out_3194571375064067580[224] = 0;
   out_3194571375064067580[225] = 0;
   out_3194571375064067580[226] = 0;
   out_3194571375064067580[227] = 0;
   out_3194571375064067580[228] = 1;
   out_3194571375064067580[229] = 0;
   out_3194571375064067580[230] = 0;
   out_3194571375064067580[231] = 0;
   out_3194571375064067580[232] = 0;
   out_3194571375064067580[233] = 0;
   out_3194571375064067580[234] = 0;
   out_3194571375064067580[235] = 0;
   out_3194571375064067580[236] = 0;
   out_3194571375064067580[237] = 0;
   out_3194571375064067580[238] = 0;
   out_3194571375064067580[239] = 0;
   out_3194571375064067580[240] = 0;
   out_3194571375064067580[241] = 0;
   out_3194571375064067580[242] = 0;
   out_3194571375064067580[243] = 0;
   out_3194571375064067580[244] = 0;
   out_3194571375064067580[245] = 0;
   out_3194571375064067580[246] = 0;
   out_3194571375064067580[247] = 1;
   out_3194571375064067580[248] = 0;
   out_3194571375064067580[249] = 0;
   out_3194571375064067580[250] = 0;
   out_3194571375064067580[251] = 0;
   out_3194571375064067580[252] = 0;
   out_3194571375064067580[253] = 0;
   out_3194571375064067580[254] = 0;
   out_3194571375064067580[255] = 0;
   out_3194571375064067580[256] = 0;
   out_3194571375064067580[257] = 0;
   out_3194571375064067580[258] = 0;
   out_3194571375064067580[259] = 0;
   out_3194571375064067580[260] = 0;
   out_3194571375064067580[261] = 0;
   out_3194571375064067580[262] = 0;
   out_3194571375064067580[263] = 0;
   out_3194571375064067580[264] = 0;
   out_3194571375064067580[265] = 0;
   out_3194571375064067580[266] = 1;
   out_3194571375064067580[267] = 0;
   out_3194571375064067580[268] = 0;
   out_3194571375064067580[269] = 0;
   out_3194571375064067580[270] = 0;
   out_3194571375064067580[271] = 0;
   out_3194571375064067580[272] = 0;
   out_3194571375064067580[273] = 0;
   out_3194571375064067580[274] = 0;
   out_3194571375064067580[275] = 0;
   out_3194571375064067580[276] = 0;
   out_3194571375064067580[277] = 0;
   out_3194571375064067580[278] = 0;
   out_3194571375064067580[279] = 0;
   out_3194571375064067580[280] = 0;
   out_3194571375064067580[281] = 0;
   out_3194571375064067580[282] = 0;
   out_3194571375064067580[283] = 0;
   out_3194571375064067580[284] = 0;
   out_3194571375064067580[285] = 1;
   out_3194571375064067580[286] = 0;
   out_3194571375064067580[287] = 0;
   out_3194571375064067580[288] = 0;
   out_3194571375064067580[289] = 0;
   out_3194571375064067580[290] = 0;
   out_3194571375064067580[291] = 0;
   out_3194571375064067580[292] = 0;
   out_3194571375064067580[293] = 0;
   out_3194571375064067580[294] = 0;
   out_3194571375064067580[295] = 0;
   out_3194571375064067580[296] = 0;
   out_3194571375064067580[297] = 0;
   out_3194571375064067580[298] = 0;
   out_3194571375064067580[299] = 0;
   out_3194571375064067580[300] = 0;
   out_3194571375064067580[301] = 0;
   out_3194571375064067580[302] = 0;
   out_3194571375064067580[303] = 0;
   out_3194571375064067580[304] = 1;
   out_3194571375064067580[305] = 0;
   out_3194571375064067580[306] = 0;
   out_3194571375064067580[307] = 0;
   out_3194571375064067580[308] = 0;
   out_3194571375064067580[309] = 0;
   out_3194571375064067580[310] = 0;
   out_3194571375064067580[311] = 0;
   out_3194571375064067580[312] = 0;
   out_3194571375064067580[313] = 0;
   out_3194571375064067580[314] = 0;
   out_3194571375064067580[315] = 0;
   out_3194571375064067580[316] = 0;
   out_3194571375064067580[317] = 0;
   out_3194571375064067580[318] = 0;
   out_3194571375064067580[319] = 0;
   out_3194571375064067580[320] = 0;
   out_3194571375064067580[321] = 0;
   out_3194571375064067580[322] = 0;
   out_3194571375064067580[323] = 1;
}
void h_4(double *state, double *unused, double *out_5032667598116974010) {
   out_5032667598116974010[0] = state[6] + state[9];
   out_5032667598116974010[1] = state[7] + state[10];
   out_5032667598116974010[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_1269577643829698253) {
   out_1269577643829698253[0] = 0;
   out_1269577643829698253[1] = 0;
   out_1269577643829698253[2] = 0;
   out_1269577643829698253[3] = 0;
   out_1269577643829698253[4] = 0;
   out_1269577643829698253[5] = 0;
   out_1269577643829698253[6] = 1;
   out_1269577643829698253[7] = 0;
   out_1269577643829698253[8] = 0;
   out_1269577643829698253[9] = 1;
   out_1269577643829698253[10] = 0;
   out_1269577643829698253[11] = 0;
   out_1269577643829698253[12] = 0;
   out_1269577643829698253[13] = 0;
   out_1269577643829698253[14] = 0;
   out_1269577643829698253[15] = 0;
   out_1269577643829698253[16] = 0;
   out_1269577643829698253[17] = 0;
   out_1269577643829698253[18] = 0;
   out_1269577643829698253[19] = 0;
   out_1269577643829698253[20] = 0;
   out_1269577643829698253[21] = 0;
   out_1269577643829698253[22] = 0;
   out_1269577643829698253[23] = 0;
   out_1269577643829698253[24] = 0;
   out_1269577643829698253[25] = 1;
   out_1269577643829698253[26] = 0;
   out_1269577643829698253[27] = 0;
   out_1269577643829698253[28] = 1;
   out_1269577643829698253[29] = 0;
   out_1269577643829698253[30] = 0;
   out_1269577643829698253[31] = 0;
   out_1269577643829698253[32] = 0;
   out_1269577643829698253[33] = 0;
   out_1269577643829698253[34] = 0;
   out_1269577643829698253[35] = 0;
   out_1269577643829698253[36] = 0;
   out_1269577643829698253[37] = 0;
   out_1269577643829698253[38] = 0;
   out_1269577643829698253[39] = 0;
   out_1269577643829698253[40] = 0;
   out_1269577643829698253[41] = 0;
   out_1269577643829698253[42] = 0;
   out_1269577643829698253[43] = 0;
   out_1269577643829698253[44] = 1;
   out_1269577643829698253[45] = 0;
   out_1269577643829698253[46] = 0;
   out_1269577643829698253[47] = 1;
   out_1269577643829698253[48] = 0;
   out_1269577643829698253[49] = 0;
   out_1269577643829698253[50] = 0;
   out_1269577643829698253[51] = 0;
   out_1269577643829698253[52] = 0;
   out_1269577643829698253[53] = 0;
}
void h_10(double *state, double *unused, double *out_1000851722634065522) {
   out_1000851722634065522[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_1000851722634065522[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_1000851722634065522[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_1846180802078735142) {
   out_1846180802078735142[0] = 0;
   out_1846180802078735142[1] = 9.8100000000000005*cos(state[1]);
   out_1846180802078735142[2] = 0;
   out_1846180802078735142[3] = 0;
   out_1846180802078735142[4] = -state[8];
   out_1846180802078735142[5] = state[7];
   out_1846180802078735142[6] = 0;
   out_1846180802078735142[7] = state[5];
   out_1846180802078735142[8] = -state[4];
   out_1846180802078735142[9] = 0;
   out_1846180802078735142[10] = 0;
   out_1846180802078735142[11] = 0;
   out_1846180802078735142[12] = 1;
   out_1846180802078735142[13] = 0;
   out_1846180802078735142[14] = 0;
   out_1846180802078735142[15] = 1;
   out_1846180802078735142[16] = 0;
   out_1846180802078735142[17] = 0;
   out_1846180802078735142[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_1846180802078735142[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_1846180802078735142[20] = 0;
   out_1846180802078735142[21] = state[8];
   out_1846180802078735142[22] = 0;
   out_1846180802078735142[23] = -state[6];
   out_1846180802078735142[24] = -state[5];
   out_1846180802078735142[25] = 0;
   out_1846180802078735142[26] = state[3];
   out_1846180802078735142[27] = 0;
   out_1846180802078735142[28] = 0;
   out_1846180802078735142[29] = 0;
   out_1846180802078735142[30] = 0;
   out_1846180802078735142[31] = 1;
   out_1846180802078735142[32] = 0;
   out_1846180802078735142[33] = 0;
   out_1846180802078735142[34] = 1;
   out_1846180802078735142[35] = 0;
   out_1846180802078735142[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_1846180802078735142[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_1846180802078735142[38] = 0;
   out_1846180802078735142[39] = -state[7];
   out_1846180802078735142[40] = state[6];
   out_1846180802078735142[41] = 0;
   out_1846180802078735142[42] = state[4];
   out_1846180802078735142[43] = -state[3];
   out_1846180802078735142[44] = 0;
   out_1846180802078735142[45] = 0;
   out_1846180802078735142[46] = 0;
   out_1846180802078735142[47] = 0;
   out_1846180802078735142[48] = 0;
   out_1846180802078735142[49] = 0;
   out_1846180802078735142[50] = 1;
   out_1846180802078735142[51] = 0;
   out_1846180802078735142[52] = 0;
   out_1846180802078735142[53] = 1;
}
void h_13(double *state, double *unused, double *out_2099618547077747222) {
   out_2099618547077747222[0] = state[3];
   out_2099618547077747222[1] = state[4];
   out_2099618547077747222[2] = state[5];
}
void H_13(double *state, double *unused, double *out_4481851469162031054) {
   out_4481851469162031054[0] = 0;
   out_4481851469162031054[1] = 0;
   out_4481851469162031054[2] = 0;
   out_4481851469162031054[3] = 1;
   out_4481851469162031054[4] = 0;
   out_4481851469162031054[5] = 0;
   out_4481851469162031054[6] = 0;
   out_4481851469162031054[7] = 0;
   out_4481851469162031054[8] = 0;
   out_4481851469162031054[9] = 0;
   out_4481851469162031054[10] = 0;
   out_4481851469162031054[11] = 0;
   out_4481851469162031054[12] = 0;
   out_4481851469162031054[13] = 0;
   out_4481851469162031054[14] = 0;
   out_4481851469162031054[15] = 0;
   out_4481851469162031054[16] = 0;
   out_4481851469162031054[17] = 0;
   out_4481851469162031054[18] = 0;
   out_4481851469162031054[19] = 0;
   out_4481851469162031054[20] = 0;
   out_4481851469162031054[21] = 0;
   out_4481851469162031054[22] = 1;
   out_4481851469162031054[23] = 0;
   out_4481851469162031054[24] = 0;
   out_4481851469162031054[25] = 0;
   out_4481851469162031054[26] = 0;
   out_4481851469162031054[27] = 0;
   out_4481851469162031054[28] = 0;
   out_4481851469162031054[29] = 0;
   out_4481851469162031054[30] = 0;
   out_4481851469162031054[31] = 0;
   out_4481851469162031054[32] = 0;
   out_4481851469162031054[33] = 0;
   out_4481851469162031054[34] = 0;
   out_4481851469162031054[35] = 0;
   out_4481851469162031054[36] = 0;
   out_4481851469162031054[37] = 0;
   out_4481851469162031054[38] = 0;
   out_4481851469162031054[39] = 0;
   out_4481851469162031054[40] = 0;
   out_4481851469162031054[41] = 1;
   out_4481851469162031054[42] = 0;
   out_4481851469162031054[43] = 0;
   out_4481851469162031054[44] = 0;
   out_4481851469162031054[45] = 0;
   out_4481851469162031054[46] = 0;
   out_4481851469162031054[47] = 0;
   out_4481851469162031054[48] = 0;
   out_4481851469162031054[49] = 0;
   out_4481851469162031054[50] = 0;
   out_4481851469162031054[51] = 0;
   out_4481851469162031054[52] = 0;
   out_4481851469162031054[53] = 0;
}
void h_14(double *state, double *unused, double *out_3950821452670665122) {
   out_3950821452670665122[0] = state[6];
   out_3950821452670665122[1] = state[7];
   out_3950821452670665122[2] = state[8];
}
void H_14(double *state, double *unused, double *out_5232818500169182782) {
   out_5232818500169182782[0] = 0;
   out_5232818500169182782[1] = 0;
   out_5232818500169182782[2] = 0;
   out_5232818500169182782[3] = 0;
   out_5232818500169182782[4] = 0;
   out_5232818500169182782[5] = 0;
   out_5232818500169182782[6] = 1;
   out_5232818500169182782[7] = 0;
   out_5232818500169182782[8] = 0;
   out_5232818500169182782[9] = 0;
   out_5232818500169182782[10] = 0;
   out_5232818500169182782[11] = 0;
   out_5232818500169182782[12] = 0;
   out_5232818500169182782[13] = 0;
   out_5232818500169182782[14] = 0;
   out_5232818500169182782[15] = 0;
   out_5232818500169182782[16] = 0;
   out_5232818500169182782[17] = 0;
   out_5232818500169182782[18] = 0;
   out_5232818500169182782[19] = 0;
   out_5232818500169182782[20] = 0;
   out_5232818500169182782[21] = 0;
   out_5232818500169182782[22] = 0;
   out_5232818500169182782[23] = 0;
   out_5232818500169182782[24] = 0;
   out_5232818500169182782[25] = 1;
   out_5232818500169182782[26] = 0;
   out_5232818500169182782[27] = 0;
   out_5232818500169182782[28] = 0;
   out_5232818500169182782[29] = 0;
   out_5232818500169182782[30] = 0;
   out_5232818500169182782[31] = 0;
   out_5232818500169182782[32] = 0;
   out_5232818500169182782[33] = 0;
   out_5232818500169182782[34] = 0;
   out_5232818500169182782[35] = 0;
   out_5232818500169182782[36] = 0;
   out_5232818500169182782[37] = 0;
   out_5232818500169182782[38] = 0;
   out_5232818500169182782[39] = 0;
   out_5232818500169182782[40] = 0;
   out_5232818500169182782[41] = 0;
   out_5232818500169182782[42] = 0;
   out_5232818500169182782[43] = 0;
   out_5232818500169182782[44] = 1;
   out_5232818500169182782[45] = 0;
   out_5232818500169182782[46] = 0;
   out_5232818500169182782[47] = 0;
   out_5232818500169182782[48] = 0;
   out_5232818500169182782[49] = 0;
   out_5232818500169182782[50] = 0;
   out_5232818500169182782[51] = 0;
   out_5232818500169182782[52] = 0;
   out_5232818500169182782[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_6550964315864651157) {
  err_fun(nom_x, delta_x, out_6550964315864651157);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_4895562721991879665) {
  inv_err_fun(nom_x, true_x, out_4895562721991879665);
}
void pose_H_mod_fun(double *state, double *out_2502229566014209319) {
  H_mod_fun(state, out_2502229566014209319);
}
void pose_f_fun(double *state, double dt, double *out_7650543638844674851) {
  f_fun(state,  dt, out_7650543638844674851);
}
void pose_F_fun(double *state, double dt, double *out_3194571375064067580) {
  F_fun(state,  dt, out_3194571375064067580);
}
void pose_h_4(double *state, double *unused, double *out_5032667598116974010) {
  h_4(state, unused, out_5032667598116974010);
}
void pose_H_4(double *state, double *unused, double *out_1269577643829698253) {
  H_4(state, unused, out_1269577643829698253);
}
void pose_h_10(double *state, double *unused, double *out_1000851722634065522) {
  h_10(state, unused, out_1000851722634065522);
}
void pose_H_10(double *state, double *unused, double *out_1846180802078735142) {
  H_10(state, unused, out_1846180802078735142);
}
void pose_h_13(double *state, double *unused, double *out_2099618547077747222) {
  h_13(state, unused, out_2099618547077747222);
}
void pose_H_13(double *state, double *unused, double *out_4481851469162031054) {
  H_13(state, unused, out_4481851469162031054);
}
void pose_h_14(double *state, double *unused, double *out_3950821452670665122) {
  h_14(state, unused, out_3950821452670665122);
}
void pose_H_14(double *state, double *unused, double *out_5232818500169182782) {
  H_14(state, unused, out_5232818500169182782);
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
