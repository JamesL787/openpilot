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
void err_fun(double *nom_x, double *delta_x, double *out_6175920115328408936) {
   out_6175920115328408936[0] = delta_x[0] + nom_x[0];
   out_6175920115328408936[1] = delta_x[1] + nom_x[1];
   out_6175920115328408936[2] = delta_x[2] + nom_x[2];
   out_6175920115328408936[3] = delta_x[3] + nom_x[3];
   out_6175920115328408936[4] = delta_x[4] + nom_x[4];
   out_6175920115328408936[5] = delta_x[5] + nom_x[5];
   out_6175920115328408936[6] = delta_x[6] + nom_x[6];
   out_6175920115328408936[7] = delta_x[7] + nom_x[7];
   out_6175920115328408936[8] = delta_x[8] + nom_x[8];
   out_6175920115328408936[9] = delta_x[9] + nom_x[9];
   out_6175920115328408936[10] = delta_x[10] + nom_x[10];
   out_6175920115328408936[11] = delta_x[11] + nom_x[11];
   out_6175920115328408936[12] = delta_x[12] + nom_x[12];
   out_6175920115328408936[13] = delta_x[13] + nom_x[13];
   out_6175920115328408936[14] = delta_x[14] + nom_x[14];
   out_6175920115328408936[15] = delta_x[15] + nom_x[15];
   out_6175920115328408936[16] = delta_x[16] + nom_x[16];
   out_6175920115328408936[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_3805053601743496181) {
   out_3805053601743496181[0] = -nom_x[0] + true_x[0];
   out_3805053601743496181[1] = -nom_x[1] + true_x[1];
   out_3805053601743496181[2] = -nom_x[2] + true_x[2];
   out_3805053601743496181[3] = -nom_x[3] + true_x[3];
   out_3805053601743496181[4] = -nom_x[4] + true_x[4];
   out_3805053601743496181[5] = -nom_x[5] + true_x[5];
   out_3805053601743496181[6] = -nom_x[6] + true_x[6];
   out_3805053601743496181[7] = -nom_x[7] + true_x[7];
   out_3805053601743496181[8] = -nom_x[8] + true_x[8];
   out_3805053601743496181[9] = -nom_x[9] + true_x[9];
   out_3805053601743496181[10] = -nom_x[10] + true_x[10];
   out_3805053601743496181[11] = -nom_x[11] + true_x[11];
   out_3805053601743496181[12] = -nom_x[12] + true_x[12];
   out_3805053601743496181[13] = -nom_x[13] + true_x[13];
   out_3805053601743496181[14] = -nom_x[14] + true_x[14];
   out_3805053601743496181[15] = -nom_x[15] + true_x[15];
   out_3805053601743496181[16] = -nom_x[16] + true_x[16];
   out_3805053601743496181[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_5396462407665545837) {
   out_5396462407665545837[0] = 1.0;
   out_5396462407665545837[1] = 0.0;
   out_5396462407665545837[2] = 0.0;
   out_5396462407665545837[3] = 0.0;
   out_5396462407665545837[4] = 0.0;
   out_5396462407665545837[5] = 0.0;
   out_5396462407665545837[6] = 0.0;
   out_5396462407665545837[7] = 0.0;
   out_5396462407665545837[8] = 0.0;
   out_5396462407665545837[9] = 0.0;
   out_5396462407665545837[10] = 0.0;
   out_5396462407665545837[11] = 0.0;
   out_5396462407665545837[12] = 0.0;
   out_5396462407665545837[13] = 0.0;
   out_5396462407665545837[14] = 0.0;
   out_5396462407665545837[15] = 0.0;
   out_5396462407665545837[16] = 0.0;
   out_5396462407665545837[17] = 0.0;
   out_5396462407665545837[18] = 0.0;
   out_5396462407665545837[19] = 1.0;
   out_5396462407665545837[20] = 0.0;
   out_5396462407665545837[21] = 0.0;
   out_5396462407665545837[22] = 0.0;
   out_5396462407665545837[23] = 0.0;
   out_5396462407665545837[24] = 0.0;
   out_5396462407665545837[25] = 0.0;
   out_5396462407665545837[26] = 0.0;
   out_5396462407665545837[27] = 0.0;
   out_5396462407665545837[28] = 0.0;
   out_5396462407665545837[29] = 0.0;
   out_5396462407665545837[30] = 0.0;
   out_5396462407665545837[31] = 0.0;
   out_5396462407665545837[32] = 0.0;
   out_5396462407665545837[33] = 0.0;
   out_5396462407665545837[34] = 0.0;
   out_5396462407665545837[35] = 0.0;
   out_5396462407665545837[36] = 0.0;
   out_5396462407665545837[37] = 0.0;
   out_5396462407665545837[38] = 1.0;
   out_5396462407665545837[39] = 0.0;
   out_5396462407665545837[40] = 0.0;
   out_5396462407665545837[41] = 0.0;
   out_5396462407665545837[42] = 0.0;
   out_5396462407665545837[43] = 0.0;
   out_5396462407665545837[44] = 0.0;
   out_5396462407665545837[45] = 0.0;
   out_5396462407665545837[46] = 0.0;
   out_5396462407665545837[47] = 0.0;
   out_5396462407665545837[48] = 0.0;
   out_5396462407665545837[49] = 0.0;
   out_5396462407665545837[50] = 0.0;
   out_5396462407665545837[51] = 0.0;
   out_5396462407665545837[52] = 0.0;
   out_5396462407665545837[53] = 0.0;
   out_5396462407665545837[54] = 0.0;
   out_5396462407665545837[55] = 0.0;
   out_5396462407665545837[56] = 0.0;
   out_5396462407665545837[57] = 1.0;
   out_5396462407665545837[58] = 0.0;
   out_5396462407665545837[59] = 0.0;
   out_5396462407665545837[60] = 0.0;
   out_5396462407665545837[61] = 0.0;
   out_5396462407665545837[62] = 0.0;
   out_5396462407665545837[63] = 0.0;
   out_5396462407665545837[64] = 0.0;
   out_5396462407665545837[65] = 0.0;
   out_5396462407665545837[66] = 0.0;
   out_5396462407665545837[67] = 0.0;
   out_5396462407665545837[68] = 0.0;
   out_5396462407665545837[69] = 0.0;
   out_5396462407665545837[70] = 0.0;
   out_5396462407665545837[71] = 0.0;
   out_5396462407665545837[72] = 0.0;
   out_5396462407665545837[73] = 0.0;
   out_5396462407665545837[74] = 0.0;
   out_5396462407665545837[75] = 0.0;
   out_5396462407665545837[76] = 1.0;
   out_5396462407665545837[77] = 0.0;
   out_5396462407665545837[78] = 0.0;
   out_5396462407665545837[79] = 0.0;
   out_5396462407665545837[80] = 0.0;
   out_5396462407665545837[81] = 0.0;
   out_5396462407665545837[82] = 0.0;
   out_5396462407665545837[83] = 0.0;
   out_5396462407665545837[84] = 0.0;
   out_5396462407665545837[85] = 0.0;
   out_5396462407665545837[86] = 0.0;
   out_5396462407665545837[87] = 0.0;
   out_5396462407665545837[88] = 0.0;
   out_5396462407665545837[89] = 0.0;
   out_5396462407665545837[90] = 0.0;
   out_5396462407665545837[91] = 0.0;
   out_5396462407665545837[92] = 0.0;
   out_5396462407665545837[93] = 0.0;
   out_5396462407665545837[94] = 0.0;
   out_5396462407665545837[95] = 1.0;
   out_5396462407665545837[96] = 0.0;
   out_5396462407665545837[97] = 0.0;
   out_5396462407665545837[98] = 0.0;
   out_5396462407665545837[99] = 0.0;
   out_5396462407665545837[100] = 0.0;
   out_5396462407665545837[101] = 0.0;
   out_5396462407665545837[102] = 0.0;
   out_5396462407665545837[103] = 0.0;
   out_5396462407665545837[104] = 0.0;
   out_5396462407665545837[105] = 0.0;
   out_5396462407665545837[106] = 0.0;
   out_5396462407665545837[107] = 0.0;
   out_5396462407665545837[108] = 0.0;
   out_5396462407665545837[109] = 0.0;
   out_5396462407665545837[110] = 0.0;
   out_5396462407665545837[111] = 0.0;
   out_5396462407665545837[112] = 0.0;
   out_5396462407665545837[113] = 0.0;
   out_5396462407665545837[114] = 1.0;
   out_5396462407665545837[115] = 0.0;
   out_5396462407665545837[116] = 0.0;
   out_5396462407665545837[117] = 0.0;
   out_5396462407665545837[118] = 0.0;
   out_5396462407665545837[119] = 0.0;
   out_5396462407665545837[120] = 0.0;
   out_5396462407665545837[121] = 0.0;
   out_5396462407665545837[122] = 0.0;
   out_5396462407665545837[123] = 0.0;
   out_5396462407665545837[124] = 0.0;
   out_5396462407665545837[125] = 0.0;
   out_5396462407665545837[126] = 0.0;
   out_5396462407665545837[127] = 0.0;
   out_5396462407665545837[128] = 0.0;
   out_5396462407665545837[129] = 0.0;
   out_5396462407665545837[130] = 0.0;
   out_5396462407665545837[131] = 0.0;
   out_5396462407665545837[132] = 0.0;
   out_5396462407665545837[133] = 1.0;
   out_5396462407665545837[134] = 0.0;
   out_5396462407665545837[135] = 0.0;
   out_5396462407665545837[136] = 0.0;
   out_5396462407665545837[137] = 0.0;
   out_5396462407665545837[138] = 0.0;
   out_5396462407665545837[139] = 0.0;
   out_5396462407665545837[140] = 0.0;
   out_5396462407665545837[141] = 0.0;
   out_5396462407665545837[142] = 0.0;
   out_5396462407665545837[143] = 0.0;
   out_5396462407665545837[144] = 0.0;
   out_5396462407665545837[145] = 0.0;
   out_5396462407665545837[146] = 0.0;
   out_5396462407665545837[147] = 0.0;
   out_5396462407665545837[148] = 0.0;
   out_5396462407665545837[149] = 0.0;
   out_5396462407665545837[150] = 0.0;
   out_5396462407665545837[151] = 0.0;
   out_5396462407665545837[152] = 1.0;
   out_5396462407665545837[153] = 0.0;
   out_5396462407665545837[154] = 0.0;
   out_5396462407665545837[155] = 0.0;
   out_5396462407665545837[156] = 0.0;
   out_5396462407665545837[157] = 0.0;
   out_5396462407665545837[158] = 0.0;
   out_5396462407665545837[159] = 0.0;
   out_5396462407665545837[160] = 0.0;
   out_5396462407665545837[161] = 0.0;
   out_5396462407665545837[162] = 0.0;
   out_5396462407665545837[163] = 0.0;
   out_5396462407665545837[164] = 0.0;
   out_5396462407665545837[165] = 0.0;
   out_5396462407665545837[166] = 0.0;
   out_5396462407665545837[167] = 0.0;
   out_5396462407665545837[168] = 0.0;
   out_5396462407665545837[169] = 0.0;
   out_5396462407665545837[170] = 0.0;
   out_5396462407665545837[171] = 1.0;
   out_5396462407665545837[172] = 0.0;
   out_5396462407665545837[173] = 0.0;
   out_5396462407665545837[174] = 0.0;
   out_5396462407665545837[175] = 0.0;
   out_5396462407665545837[176] = 0.0;
   out_5396462407665545837[177] = 0.0;
   out_5396462407665545837[178] = 0.0;
   out_5396462407665545837[179] = 0.0;
   out_5396462407665545837[180] = 0.0;
   out_5396462407665545837[181] = 0.0;
   out_5396462407665545837[182] = 0.0;
   out_5396462407665545837[183] = 0.0;
   out_5396462407665545837[184] = 0.0;
   out_5396462407665545837[185] = 0.0;
   out_5396462407665545837[186] = 0.0;
   out_5396462407665545837[187] = 0.0;
   out_5396462407665545837[188] = 0.0;
   out_5396462407665545837[189] = 0.0;
   out_5396462407665545837[190] = 1.0;
   out_5396462407665545837[191] = 0.0;
   out_5396462407665545837[192] = 0.0;
   out_5396462407665545837[193] = 0.0;
   out_5396462407665545837[194] = 0.0;
   out_5396462407665545837[195] = 0.0;
   out_5396462407665545837[196] = 0.0;
   out_5396462407665545837[197] = 0.0;
   out_5396462407665545837[198] = 0.0;
   out_5396462407665545837[199] = 0.0;
   out_5396462407665545837[200] = 0.0;
   out_5396462407665545837[201] = 0.0;
   out_5396462407665545837[202] = 0.0;
   out_5396462407665545837[203] = 0.0;
   out_5396462407665545837[204] = 0.0;
   out_5396462407665545837[205] = 0.0;
   out_5396462407665545837[206] = 0.0;
   out_5396462407665545837[207] = 0.0;
   out_5396462407665545837[208] = 0.0;
   out_5396462407665545837[209] = 1.0;
   out_5396462407665545837[210] = 0.0;
   out_5396462407665545837[211] = 0.0;
   out_5396462407665545837[212] = 0.0;
   out_5396462407665545837[213] = 0.0;
   out_5396462407665545837[214] = 0.0;
   out_5396462407665545837[215] = 0.0;
   out_5396462407665545837[216] = 0.0;
   out_5396462407665545837[217] = 0.0;
   out_5396462407665545837[218] = 0.0;
   out_5396462407665545837[219] = 0.0;
   out_5396462407665545837[220] = 0.0;
   out_5396462407665545837[221] = 0.0;
   out_5396462407665545837[222] = 0.0;
   out_5396462407665545837[223] = 0.0;
   out_5396462407665545837[224] = 0.0;
   out_5396462407665545837[225] = 0.0;
   out_5396462407665545837[226] = 0.0;
   out_5396462407665545837[227] = 0.0;
   out_5396462407665545837[228] = 1.0;
   out_5396462407665545837[229] = 0.0;
   out_5396462407665545837[230] = 0.0;
   out_5396462407665545837[231] = 0.0;
   out_5396462407665545837[232] = 0.0;
   out_5396462407665545837[233] = 0.0;
   out_5396462407665545837[234] = 0.0;
   out_5396462407665545837[235] = 0.0;
   out_5396462407665545837[236] = 0.0;
   out_5396462407665545837[237] = 0.0;
   out_5396462407665545837[238] = 0.0;
   out_5396462407665545837[239] = 0.0;
   out_5396462407665545837[240] = 0.0;
   out_5396462407665545837[241] = 0.0;
   out_5396462407665545837[242] = 0.0;
   out_5396462407665545837[243] = 0.0;
   out_5396462407665545837[244] = 0.0;
   out_5396462407665545837[245] = 0.0;
   out_5396462407665545837[246] = 0.0;
   out_5396462407665545837[247] = 1.0;
   out_5396462407665545837[248] = 0.0;
   out_5396462407665545837[249] = 0.0;
   out_5396462407665545837[250] = 0.0;
   out_5396462407665545837[251] = 0.0;
   out_5396462407665545837[252] = 0.0;
   out_5396462407665545837[253] = 0.0;
   out_5396462407665545837[254] = 0.0;
   out_5396462407665545837[255] = 0.0;
   out_5396462407665545837[256] = 0.0;
   out_5396462407665545837[257] = 0.0;
   out_5396462407665545837[258] = 0.0;
   out_5396462407665545837[259] = 0.0;
   out_5396462407665545837[260] = 0.0;
   out_5396462407665545837[261] = 0.0;
   out_5396462407665545837[262] = 0.0;
   out_5396462407665545837[263] = 0.0;
   out_5396462407665545837[264] = 0.0;
   out_5396462407665545837[265] = 0.0;
   out_5396462407665545837[266] = 1.0;
   out_5396462407665545837[267] = 0.0;
   out_5396462407665545837[268] = 0.0;
   out_5396462407665545837[269] = 0.0;
   out_5396462407665545837[270] = 0.0;
   out_5396462407665545837[271] = 0.0;
   out_5396462407665545837[272] = 0.0;
   out_5396462407665545837[273] = 0.0;
   out_5396462407665545837[274] = 0.0;
   out_5396462407665545837[275] = 0.0;
   out_5396462407665545837[276] = 0.0;
   out_5396462407665545837[277] = 0.0;
   out_5396462407665545837[278] = 0.0;
   out_5396462407665545837[279] = 0.0;
   out_5396462407665545837[280] = 0.0;
   out_5396462407665545837[281] = 0.0;
   out_5396462407665545837[282] = 0.0;
   out_5396462407665545837[283] = 0.0;
   out_5396462407665545837[284] = 0.0;
   out_5396462407665545837[285] = 1.0;
   out_5396462407665545837[286] = 0.0;
   out_5396462407665545837[287] = 0.0;
   out_5396462407665545837[288] = 0.0;
   out_5396462407665545837[289] = 0.0;
   out_5396462407665545837[290] = 0.0;
   out_5396462407665545837[291] = 0.0;
   out_5396462407665545837[292] = 0.0;
   out_5396462407665545837[293] = 0.0;
   out_5396462407665545837[294] = 0.0;
   out_5396462407665545837[295] = 0.0;
   out_5396462407665545837[296] = 0.0;
   out_5396462407665545837[297] = 0.0;
   out_5396462407665545837[298] = 0.0;
   out_5396462407665545837[299] = 0.0;
   out_5396462407665545837[300] = 0.0;
   out_5396462407665545837[301] = 0.0;
   out_5396462407665545837[302] = 0.0;
   out_5396462407665545837[303] = 0.0;
   out_5396462407665545837[304] = 1.0;
   out_5396462407665545837[305] = 0.0;
   out_5396462407665545837[306] = 0.0;
   out_5396462407665545837[307] = 0.0;
   out_5396462407665545837[308] = 0.0;
   out_5396462407665545837[309] = 0.0;
   out_5396462407665545837[310] = 0.0;
   out_5396462407665545837[311] = 0.0;
   out_5396462407665545837[312] = 0.0;
   out_5396462407665545837[313] = 0.0;
   out_5396462407665545837[314] = 0.0;
   out_5396462407665545837[315] = 0.0;
   out_5396462407665545837[316] = 0.0;
   out_5396462407665545837[317] = 0.0;
   out_5396462407665545837[318] = 0.0;
   out_5396462407665545837[319] = 0.0;
   out_5396462407665545837[320] = 0.0;
   out_5396462407665545837[321] = 0.0;
   out_5396462407665545837[322] = 0.0;
   out_5396462407665545837[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_2259962914111940675) {
   out_2259962914111940675[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_2259962914111940675[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_2259962914111940675[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_2259962914111940675[3] = dt*state[12] + state[3];
   out_2259962914111940675[4] = dt*state[13] + state[4];
   out_2259962914111940675[5] = dt*state[14] + state[5];
   out_2259962914111940675[6] = state[6];
   out_2259962914111940675[7] = state[7];
   out_2259962914111940675[8] = state[8];
   out_2259962914111940675[9] = state[9];
   out_2259962914111940675[10] = state[10];
   out_2259962914111940675[11] = state[11];
   out_2259962914111940675[12] = state[12];
   out_2259962914111940675[13] = state[13];
   out_2259962914111940675[14] = state[14];
   out_2259962914111940675[15] = state[15];
   out_2259962914111940675[16] = state[16];
   out_2259962914111940675[17] = state[17];
}
void F_fun(double *state, double dt, double *out_7388593800552876568) {
   out_7388593800552876568[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7388593800552876568[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7388593800552876568[2] = 0;
   out_7388593800552876568[3] = 0;
   out_7388593800552876568[4] = 0;
   out_7388593800552876568[5] = 0;
   out_7388593800552876568[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7388593800552876568[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7388593800552876568[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7388593800552876568[9] = 0;
   out_7388593800552876568[10] = 0;
   out_7388593800552876568[11] = 0;
   out_7388593800552876568[12] = 0;
   out_7388593800552876568[13] = 0;
   out_7388593800552876568[14] = 0;
   out_7388593800552876568[15] = 0;
   out_7388593800552876568[16] = 0;
   out_7388593800552876568[17] = 0;
   out_7388593800552876568[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7388593800552876568[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7388593800552876568[20] = 0;
   out_7388593800552876568[21] = 0;
   out_7388593800552876568[22] = 0;
   out_7388593800552876568[23] = 0;
   out_7388593800552876568[24] = 0;
   out_7388593800552876568[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7388593800552876568[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7388593800552876568[27] = 0;
   out_7388593800552876568[28] = 0;
   out_7388593800552876568[29] = 0;
   out_7388593800552876568[30] = 0;
   out_7388593800552876568[31] = 0;
   out_7388593800552876568[32] = 0;
   out_7388593800552876568[33] = 0;
   out_7388593800552876568[34] = 0;
   out_7388593800552876568[35] = 0;
   out_7388593800552876568[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7388593800552876568[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7388593800552876568[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7388593800552876568[39] = 0;
   out_7388593800552876568[40] = 0;
   out_7388593800552876568[41] = 0;
   out_7388593800552876568[42] = 0;
   out_7388593800552876568[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7388593800552876568[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7388593800552876568[45] = 0;
   out_7388593800552876568[46] = 0;
   out_7388593800552876568[47] = 0;
   out_7388593800552876568[48] = 0;
   out_7388593800552876568[49] = 0;
   out_7388593800552876568[50] = 0;
   out_7388593800552876568[51] = 0;
   out_7388593800552876568[52] = 0;
   out_7388593800552876568[53] = 0;
   out_7388593800552876568[54] = 0;
   out_7388593800552876568[55] = 0;
   out_7388593800552876568[56] = 0;
   out_7388593800552876568[57] = 1;
   out_7388593800552876568[58] = 0;
   out_7388593800552876568[59] = 0;
   out_7388593800552876568[60] = 0;
   out_7388593800552876568[61] = 0;
   out_7388593800552876568[62] = 0;
   out_7388593800552876568[63] = 0;
   out_7388593800552876568[64] = 0;
   out_7388593800552876568[65] = 0;
   out_7388593800552876568[66] = dt;
   out_7388593800552876568[67] = 0;
   out_7388593800552876568[68] = 0;
   out_7388593800552876568[69] = 0;
   out_7388593800552876568[70] = 0;
   out_7388593800552876568[71] = 0;
   out_7388593800552876568[72] = 0;
   out_7388593800552876568[73] = 0;
   out_7388593800552876568[74] = 0;
   out_7388593800552876568[75] = 0;
   out_7388593800552876568[76] = 1;
   out_7388593800552876568[77] = 0;
   out_7388593800552876568[78] = 0;
   out_7388593800552876568[79] = 0;
   out_7388593800552876568[80] = 0;
   out_7388593800552876568[81] = 0;
   out_7388593800552876568[82] = 0;
   out_7388593800552876568[83] = 0;
   out_7388593800552876568[84] = 0;
   out_7388593800552876568[85] = dt;
   out_7388593800552876568[86] = 0;
   out_7388593800552876568[87] = 0;
   out_7388593800552876568[88] = 0;
   out_7388593800552876568[89] = 0;
   out_7388593800552876568[90] = 0;
   out_7388593800552876568[91] = 0;
   out_7388593800552876568[92] = 0;
   out_7388593800552876568[93] = 0;
   out_7388593800552876568[94] = 0;
   out_7388593800552876568[95] = 1;
   out_7388593800552876568[96] = 0;
   out_7388593800552876568[97] = 0;
   out_7388593800552876568[98] = 0;
   out_7388593800552876568[99] = 0;
   out_7388593800552876568[100] = 0;
   out_7388593800552876568[101] = 0;
   out_7388593800552876568[102] = 0;
   out_7388593800552876568[103] = 0;
   out_7388593800552876568[104] = dt;
   out_7388593800552876568[105] = 0;
   out_7388593800552876568[106] = 0;
   out_7388593800552876568[107] = 0;
   out_7388593800552876568[108] = 0;
   out_7388593800552876568[109] = 0;
   out_7388593800552876568[110] = 0;
   out_7388593800552876568[111] = 0;
   out_7388593800552876568[112] = 0;
   out_7388593800552876568[113] = 0;
   out_7388593800552876568[114] = 1;
   out_7388593800552876568[115] = 0;
   out_7388593800552876568[116] = 0;
   out_7388593800552876568[117] = 0;
   out_7388593800552876568[118] = 0;
   out_7388593800552876568[119] = 0;
   out_7388593800552876568[120] = 0;
   out_7388593800552876568[121] = 0;
   out_7388593800552876568[122] = 0;
   out_7388593800552876568[123] = 0;
   out_7388593800552876568[124] = 0;
   out_7388593800552876568[125] = 0;
   out_7388593800552876568[126] = 0;
   out_7388593800552876568[127] = 0;
   out_7388593800552876568[128] = 0;
   out_7388593800552876568[129] = 0;
   out_7388593800552876568[130] = 0;
   out_7388593800552876568[131] = 0;
   out_7388593800552876568[132] = 0;
   out_7388593800552876568[133] = 1;
   out_7388593800552876568[134] = 0;
   out_7388593800552876568[135] = 0;
   out_7388593800552876568[136] = 0;
   out_7388593800552876568[137] = 0;
   out_7388593800552876568[138] = 0;
   out_7388593800552876568[139] = 0;
   out_7388593800552876568[140] = 0;
   out_7388593800552876568[141] = 0;
   out_7388593800552876568[142] = 0;
   out_7388593800552876568[143] = 0;
   out_7388593800552876568[144] = 0;
   out_7388593800552876568[145] = 0;
   out_7388593800552876568[146] = 0;
   out_7388593800552876568[147] = 0;
   out_7388593800552876568[148] = 0;
   out_7388593800552876568[149] = 0;
   out_7388593800552876568[150] = 0;
   out_7388593800552876568[151] = 0;
   out_7388593800552876568[152] = 1;
   out_7388593800552876568[153] = 0;
   out_7388593800552876568[154] = 0;
   out_7388593800552876568[155] = 0;
   out_7388593800552876568[156] = 0;
   out_7388593800552876568[157] = 0;
   out_7388593800552876568[158] = 0;
   out_7388593800552876568[159] = 0;
   out_7388593800552876568[160] = 0;
   out_7388593800552876568[161] = 0;
   out_7388593800552876568[162] = 0;
   out_7388593800552876568[163] = 0;
   out_7388593800552876568[164] = 0;
   out_7388593800552876568[165] = 0;
   out_7388593800552876568[166] = 0;
   out_7388593800552876568[167] = 0;
   out_7388593800552876568[168] = 0;
   out_7388593800552876568[169] = 0;
   out_7388593800552876568[170] = 0;
   out_7388593800552876568[171] = 1;
   out_7388593800552876568[172] = 0;
   out_7388593800552876568[173] = 0;
   out_7388593800552876568[174] = 0;
   out_7388593800552876568[175] = 0;
   out_7388593800552876568[176] = 0;
   out_7388593800552876568[177] = 0;
   out_7388593800552876568[178] = 0;
   out_7388593800552876568[179] = 0;
   out_7388593800552876568[180] = 0;
   out_7388593800552876568[181] = 0;
   out_7388593800552876568[182] = 0;
   out_7388593800552876568[183] = 0;
   out_7388593800552876568[184] = 0;
   out_7388593800552876568[185] = 0;
   out_7388593800552876568[186] = 0;
   out_7388593800552876568[187] = 0;
   out_7388593800552876568[188] = 0;
   out_7388593800552876568[189] = 0;
   out_7388593800552876568[190] = 1;
   out_7388593800552876568[191] = 0;
   out_7388593800552876568[192] = 0;
   out_7388593800552876568[193] = 0;
   out_7388593800552876568[194] = 0;
   out_7388593800552876568[195] = 0;
   out_7388593800552876568[196] = 0;
   out_7388593800552876568[197] = 0;
   out_7388593800552876568[198] = 0;
   out_7388593800552876568[199] = 0;
   out_7388593800552876568[200] = 0;
   out_7388593800552876568[201] = 0;
   out_7388593800552876568[202] = 0;
   out_7388593800552876568[203] = 0;
   out_7388593800552876568[204] = 0;
   out_7388593800552876568[205] = 0;
   out_7388593800552876568[206] = 0;
   out_7388593800552876568[207] = 0;
   out_7388593800552876568[208] = 0;
   out_7388593800552876568[209] = 1;
   out_7388593800552876568[210] = 0;
   out_7388593800552876568[211] = 0;
   out_7388593800552876568[212] = 0;
   out_7388593800552876568[213] = 0;
   out_7388593800552876568[214] = 0;
   out_7388593800552876568[215] = 0;
   out_7388593800552876568[216] = 0;
   out_7388593800552876568[217] = 0;
   out_7388593800552876568[218] = 0;
   out_7388593800552876568[219] = 0;
   out_7388593800552876568[220] = 0;
   out_7388593800552876568[221] = 0;
   out_7388593800552876568[222] = 0;
   out_7388593800552876568[223] = 0;
   out_7388593800552876568[224] = 0;
   out_7388593800552876568[225] = 0;
   out_7388593800552876568[226] = 0;
   out_7388593800552876568[227] = 0;
   out_7388593800552876568[228] = 1;
   out_7388593800552876568[229] = 0;
   out_7388593800552876568[230] = 0;
   out_7388593800552876568[231] = 0;
   out_7388593800552876568[232] = 0;
   out_7388593800552876568[233] = 0;
   out_7388593800552876568[234] = 0;
   out_7388593800552876568[235] = 0;
   out_7388593800552876568[236] = 0;
   out_7388593800552876568[237] = 0;
   out_7388593800552876568[238] = 0;
   out_7388593800552876568[239] = 0;
   out_7388593800552876568[240] = 0;
   out_7388593800552876568[241] = 0;
   out_7388593800552876568[242] = 0;
   out_7388593800552876568[243] = 0;
   out_7388593800552876568[244] = 0;
   out_7388593800552876568[245] = 0;
   out_7388593800552876568[246] = 0;
   out_7388593800552876568[247] = 1;
   out_7388593800552876568[248] = 0;
   out_7388593800552876568[249] = 0;
   out_7388593800552876568[250] = 0;
   out_7388593800552876568[251] = 0;
   out_7388593800552876568[252] = 0;
   out_7388593800552876568[253] = 0;
   out_7388593800552876568[254] = 0;
   out_7388593800552876568[255] = 0;
   out_7388593800552876568[256] = 0;
   out_7388593800552876568[257] = 0;
   out_7388593800552876568[258] = 0;
   out_7388593800552876568[259] = 0;
   out_7388593800552876568[260] = 0;
   out_7388593800552876568[261] = 0;
   out_7388593800552876568[262] = 0;
   out_7388593800552876568[263] = 0;
   out_7388593800552876568[264] = 0;
   out_7388593800552876568[265] = 0;
   out_7388593800552876568[266] = 1;
   out_7388593800552876568[267] = 0;
   out_7388593800552876568[268] = 0;
   out_7388593800552876568[269] = 0;
   out_7388593800552876568[270] = 0;
   out_7388593800552876568[271] = 0;
   out_7388593800552876568[272] = 0;
   out_7388593800552876568[273] = 0;
   out_7388593800552876568[274] = 0;
   out_7388593800552876568[275] = 0;
   out_7388593800552876568[276] = 0;
   out_7388593800552876568[277] = 0;
   out_7388593800552876568[278] = 0;
   out_7388593800552876568[279] = 0;
   out_7388593800552876568[280] = 0;
   out_7388593800552876568[281] = 0;
   out_7388593800552876568[282] = 0;
   out_7388593800552876568[283] = 0;
   out_7388593800552876568[284] = 0;
   out_7388593800552876568[285] = 1;
   out_7388593800552876568[286] = 0;
   out_7388593800552876568[287] = 0;
   out_7388593800552876568[288] = 0;
   out_7388593800552876568[289] = 0;
   out_7388593800552876568[290] = 0;
   out_7388593800552876568[291] = 0;
   out_7388593800552876568[292] = 0;
   out_7388593800552876568[293] = 0;
   out_7388593800552876568[294] = 0;
   out_7388593800552876568[295] = 0;
   out_7388593800552876568[296] = 0;
   out_7388593800552876568[297] = 0;
   out_7388593800552876568[298] = 0;
   out_7388593800552876568[299] = 0;
   out_7388593800552876568[300] = 0;
   out_7388593800552876568[301] = 0;
   out_7388593800552876568[302] = 0;
   out_7388593800552876568[303] = 0;
   out_7388593800552876568[304] = 1;
   out_7388593800552876568[305] = 0;
   out_7388593800552876568[306] = 0;
   out_7388593800552876568[307] = 0;
   out_7388593800552876568[308] = 0;
   out_7388593800552876568[309] = 0;
   out_7388593800552876568[310] = 0;
   out_7388593800552876568[311] = 0;
   out_7388593800552876568[312] = 0;
   out_7388593800552876568[313] = 0;
   out_7388593800552876568[314] = 0;
   out_7388593800552876568[315] = 0;
   out_7388593800552876568[316] = 0;
   out_7388593800552876568[317] = 0;
   out_7388593800552876568[318] = 0;
   out_7388593800552876568[319] = 0;
   out_7388593800552876568[320] = 0;
   out_7388593800552876568[321] = 0;
   out_7388593800552876568[322] = 0;
   out_7388593800552876568[323] = 1;
}
void h_4(double *state, double *unused, double *out_6296325962549515069) {
   out_6296325962549515069[0] = state[6] + state[9];
   out_6296325962549515069[1] = state[7] + state[10];
   out_6296325962549515069[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_6150623409720258444) {
   out_6150623409720258444[0] = 0;
   out_6150623409720258444[1] = 0;
   out_6150623409720258444[2] = 0;
   out_6150623409720258444[3] = 0;
   out_6150623409720258444[4] = 0;
   out_6150623409720258444[5] = 0;
   out_6150623409720258444[6] = 1;
   out_6150623409720258444[7] = 0;
   out_6150623409720258444[8] = 0;
   out_6150623409720258444[9] = 1;
   out_6150623409720258444[10] = 0;
   out_6150623409720258444[11] = 0;
   out_6150623409720258444[12] = 0;
   out_6150623409720258444[13] = 0;
   out_6150623409720258444[14] = 0;
   out_6150623409720258444[15] = 0;
   out_6150623409720258444[16] = 0;
   out_6150623409720258444[17] = 0;
   out_6150623409720258444[18] = 0;
   out_6150623409720258444[19] = 0;
   out_6150623409720258444[20] = 0;
   out_6150623409720258444[21] = 0;
   out_6150623409720258444[22] = 0;
   out_6150623409720258444[23] = 0;
   out_6150623409720258444[24] = 0;
   out_6150623409720258444[25] = 1;
   out_6150623409720258444[26] = 0;
   out_6150623409720258444[27] = 0;
   out_6150623409720258444[28] = 1;
   out_6150623409720258444[29] = 0;
   out_6150623409720258444[30] = 0;
   out_6150623409720258444[31] = 0;
   out_6150623409720258444[32] = 0;
   out_6150623409720258444[33] = 0;
   out_6150623409720258444[34] = 0;
   out_6150623409720258444[35] = 0;
   out_6150623409720258444[36] = 0;
   out_6150623409720258444[37] = 0;
   out_6150623409720258444[38] = 0;
   out_6150623409720258444[39] = 0;
   out_6150623409720258444[40] = 0;
   out_6150623409720258444[41] = 0;
   out_6150623409720258444[42] = 0;
   out_6150623409720258444[43] = 0;
   out_6150623409720258444[44] = 1;
   out_6150623409720258444[45] = 0;
   out_6150623409720258444[46] = 0;
   out_6150623409720258444[47] = 1;
   out_6150623409720258444[48] = 0;
   out_6150623409720258444[49] = 0;
   out_6150623409720258444[50] = 0;
   out_6150623409720258444[51] = 0;
   out_6150623409720258444[52] = 0;
   out_6150623409720258444[53] = 0;
}
void h_10(double *state, double *unused, double *out_5257471290382701468) {
   out_5257471290382701468[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_5257471290382701468[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_5257471290382701468[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_2226857894068523198) {
   out_2226857894068523198[0] = 0;
   out_2226857894068523198[1] = 9.8100000000000005*cos(state[1]);
   out_2226857894068523198[2] = 0;
   out_2226857894068523198[3] = 0;
   out_2226857894068523198[4] = -state[8];
   out_2226857894068523198[5] = state[7];
   out_2226857894068523198[6] = 0;
   out_2226857894068523198[7] = state[5];
   out_2226857894068523198[8] = -state[4];
   out_2226857894068523198[9] = 0;
   out_2226857894068523198[10] = 0;
   out_2226857894068523198[11] = 0;
   out_2226857894068523198[12] = 1;
   out_2226857894068523198[13] = 0;
   out_2226857894068523198[14] = 0;
   out_2226857894068523198[15] = 1;
   out_2226857894068523198[16] = 0;
   out_2226857894068523198[17] = 0;
   out_2226857894068523198[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_2226857894068523198[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_2226857894068523198[20] = 0;
   out_2226857894068523198[21] = state[8];
   out_2226857894068523198[22] = 0;
   out_2226857894068523198[23] = -state[6];
   out_2226857894068523198[24] = -state[5];
   out_2226857894068523198[25] = 0;
   out_2226857894068523198[26] = state[3];
   out_2226857894068523198[27] = 0;
   out_2226857894068523198[28] = 0;
   out_2226857894068523198[29] = 0;
   out_2226857894068523198[30] = 0;
   out_2226857894068523198[31] = 1;
   out_2226857894068523198[32] = 0;
   out_2226857894068523198[33] = 0;
   out_2226857894068523198[34] = 1;
   out_2226857894068523198[35] = 0;
   out_2226857894068523198[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_2226857894068523198[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_2226857894068523198[38] = 0;
   out_2226857894068523198[39] = -state[7];
   out_2226857894068523198[40] = state[6];
   out_2226857894068523198[41] = 0;
   out_2226857894068523198[42] = state[4];
   out_2226857894068523198[43] = -state[3];
   out_2226857894068523198[44] = 0;
   out_2226857894068523198[45] = 0;
   out_2226857894068523198[46] = 0;
   out_2226857894068523198[47] = 0;
   out_2226857894068523198[48] = 0;
   out_2226857894068523198[49] = 0;
   out_2226857894068523198[50] = 1;
   out_2226857894068523198[51] = 0;
   out_2226857894068523198[52] = 0;
   out_2226857894068523198[53] = 1;
}
void h_13(double *state, double *unused, double *out_7555040188854800627) {
   out_7555040188854800627[0] = state[3];
   out_7555040188854800627[1] = state[4];
   out_7555040188854800627[2] = state[5];
}
void H_13(double *state, double *unused, double *out_2316867946417734420) {
   out_2316867946417734420[0] = 0;
   out_2316867946417734420[1] = 0;
   out_2316867946417734420[2] = 0;
   out_2316867946417734420[3] = 1;
   out_2316867946417734420[4] = 0;
   out_2316867946417734420[5] = 0;
   out_2316867946417734420[6] = 0;
   out_2316867946417734420[7] = 0;
   out_2316867946417734420[8] = 0;
   out_2316867946417734420[9] = 0;
   out_2316867946417734420[10] = 0;
   out_2316867946417734420[11] = 0;
   out_2316867946417734420[12] = 0;
   out_2316867946417734420[13] = 0;
   out_2316867946417734420[14] = 0;
   out_2316867946417734420[15] = 0;
   out_2316867946417734420[16] = 0;
   out_2316867946417734420[17] = 0;
   out_2316867946417734420[18] = 0;
   out_2316867946417734420[19] = 0;
   out_2316867946417734420[20] = 0;
   out_2316867946417734420[21] = 0;
   out_2316867946417734420[22] = 1;
   out_2316867946417734420[23] = 0;
   out_2316867946417734420[24] = 0;
   out_2316867946417734420[25] = 0;
   out_2316867946417734420[26] = 0;
   out_2316867946417734420[27] = 0;
   out_2316867946417734420[28] = 0;
   out_2316867946417734420[29] = 0;
   out_2316867946417734420[30] = 0;
   out_2316867946417734420[31] = 0;
   out_2316867946417734420[32] = 0;
   out_2316867946417734420[33] = 0;
   out_2316867946417734420[34] = 0;
   out_2316867946417734420[35] = 0;
   out_2316867946417734420[36] = 0;
   out_2316867946417734420[37] = 0;
   out_2316867946417734420[38] = 0;
   out_2316867946417734420[39] = 0;
   out_2316867946417734420[40] = 0;
   out_2316867946417734420[41] = 1;
   out_2316867946417734420[42] = 0;
   out_2316867946417734420[43] = 0;
   out_2316867946417734420[44] = 0;
   out_2316867946417734420[45] = 0;
   out_2316867946417734420[46] = 0;
   out_2316867946417734420[47] = 0;
   out_2316867946417734420[48] = 0;
   out_2316867946417734420[49] = 0;
   out_2316867946417734420[50] = 0;
   out_2316867946417734420[51] = 0;
   out_2316867946417734420[52] = 0;
   out_2316867946417734420[53] = 0;
}
void h_14(double *state, double *unused, double *out_7494435962469580158) {
   out_7494435962469580158[0] = state[6];
   out_7494435962469580158[1] = state[7];
   out_7494435962469580158[2] = state[8];
}
void H_14(double *state, double *unused, double *out_3067834977424886148) {
   out_3067834977424886148[0] = 0;
   out_3067834977424886148[1] = 0;
   out_3067834977424886148[2] = 0;
   out_3067834977424886148[3] = 0;
   out_3067834977424886148[4] = 0;
   out_3067834977424886148[5] = 0;
   out_3067834977424886148[6] = 1;
   out_3067834977424886148[7] = 0;
   out_3067834977424886148[8] = 0;
   out_3067834977424886148[9] = 0;
   out_3067834977424886148[10] = 0;
   out_3067834977424886148[11] = 0;
   out_3067834977424886148[12] = 0;
   out_3067834977424886148[13] = 0;
   out_3067834977424886148[14] = 0;
   out_3067834977424886148[15] = 0;
   out_3067834977424886148[16] = 0;
   out_3067834977424886148[17] = 0;
   out_3067834977424886148[18] = 0;
   out_3067834977424886148[19] = 0;
   out_3067834977424886148[20] = 0;
   out_3067834977424886148[21] = 0;
   out_3067834977424886148[22] = 0;
   out_3067834977424886148[23] = 0;
   out_3067834977424886148[24] = 0;
   out_3067834977424886148[25] = 1;
   out_3067834977424886148[26] = 0;
   out_3067834977424886148[27] = 0;
   out_3067834977424886148[28] = 0;
   out_3067834977424886148[29] = 0;
   out_3067834977424886148[30] = 0;
   out_3067834977424886148[31] = 0;
   out_3067834977424886148[32] = 0;
   out_3067834977424886148[33] = 0;
   out_3067834977424886148[34] = 0;
   out_3067834977424886148[35] = 0;
   out_3067834977424886148[36] = 0;
   out_3067834977424886148[37] = 0;
   out_3067834977424886148[38] = 0;
   out_3067834977424886148[39] = 0;
   out_3067834977424886148[40] = 0;
   out_3067834977424886148[41] = 0;
   out_3067834977424886148[42] = 0;
   out_3067834977424886148[43] = 0;
   out_3067834977424886148[44] = 1;
   out_3067834977424886148[45] = 0;
   out_3067834977424886148[46] = 0;
   out_3067834977424886148[47] = 0;
   out_3067834977424886148[48] = 0;
   out_3067834977424886148[49] = 0;
   out_3067834977424886148[50] = 0;
   out_3067834977424886148[51] = 0;
   out_3067834977424886148[52] = 0;
   out_3067834977424886148[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_6175920115328408936) {
  err_fun(nom_x, delta_x, out_6175920115328408936);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_3805053601743496181) {
  inv_err_fun(nom_x, true_x, out_3805053601743496181);
}
void pose_H_mod_fun(double *state, double *out_5396462407665545837) {
  H_mod_fun(state, out_5396462407665545837);
}
void pose_f_fun(double *state, double dt, double *out_2259962914111940675) {
  f_fun(state,  dt, out_2259962914111940675);
}
void pose_F_fun(double *state, double dt, double *out_7388593800552876568) {
  F_fun(state,  dt, out_7388593800552876568);
}
void pose_h_4(double *state, double *unused, double *out_6296325962549515069) {
  h_4(state, unused, out_6296325962549515069);
}
void pose_H_4(double *state, double *unused, double *out_6150623409720258444) {
  H_4(state, unused, out_6150623409720258444);
}
void pose_h_10(double *state, double *unused, double *out_5257471290382701468) {
  h_10(state, unused, out_5257471290382701468);
}
void pose_H_10(double *state, double *unused, double *out_2226857894068523198) {
  H_10(state, unused, out_2226857894068523198);
}
void pose_h_13(double *state, double *unused, double *out_7555040188854800627) {
  h_13(state, unused, out_7555040188854800627);
}
void pose_H_13(double *state, double *unused, double *out_2316867946417734420) {
  H_13(state, unused, out_2316867946417734420);
}
void pose_h_14(double *state, double *unused, double *out_7494435962469580158) {
  h_14(state, unused, out_7494435962469580158);
}
void pose_H_14(double *state, double *unused, double *out_3067834977424886148) {
  H_14(state, unused, out_3067834977424886148);
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
