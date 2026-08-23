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
void err_fun(double *nom_x, double *delta_x, double *out_9020563603504726210) {
   out_9020563603504726210[0] = delta_x[0] + nom_x[0];
   out_9020563603504726210[1] = delta_x[1] + nom_x[1];
   out_9020563603504726210[2] = delta_x[2] + nom_x[2];
   out_9020563603504726210[3] = delta_x[3] + nom_x[3];
   out_9020563603504726210[4] = delta_x[4] + nom_x[4];
   out_9020563603504726210[5] = delta_x[5] + nom_x[5];
   out_9020563603504726210[6] = delta_x[6] + nom_x[6];
   out_9020563603504726210[7] = delta_x[7] + nom_x[7];
   out_9020563603504726210[8] = delta_x[8] + nom_x[8];
   out_9020563603504726210[9] = delta_x[9] + nom_x[9];
   out_9020563603504726210[10] = delta_x[10] + nom_x[10];
   out_9020563603504726210[11] = delta_x[11] + nom_x[11];
   out_9020563603504726210[12] = delta_x[12] + nom_x[12];
   out_9020563603504726210[13] = delta_x[13] + nom_x[13];
   out_9020563603504726210[14] = delta_x[14] + nom_x[14];
   out_9020563603504726210[15] = delta_x[15] + nom_x[15];
   out_9020563603504726210[16] = delta_x[16] + nom_x[16];
   out_9020563603504726210[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_6858679601398523695) {
   out_6858679601398523695[0] = -nom_x[0] + true_x[0];
   out_6858679601398523695[1] = -nom_x[1] + true_x[1];
   out_6858679601398523695[2] = -nom_x[2] + true_x[2];
   out_6858679601398523695[3] = -nom_x[3] + true_x[3];
   out_6858679601398523695[4] = -nom_x[4] + true_x[4];
   out_6858679601398523695[5] = -nom_x[5] + true_x[5];
   out_6858679601398523695[6] = -nom_x[6] + true_x[6];
   out_6858679601398523695[7] = -nom_x[7] + true_x[7];
   out_6858679601398523695[8] = -nom_x[8] + true_x[8];
   out_6858679601398523695[9] = -nom_x[9] + true_x[9];
   out_6858679601398523695[10] = -nom_x[10] + true_x[10];
   out_6858679601398523695[11] = -nom_x[11] + true_x[11];
   out_6858679601398523695[12] = -nom_x[12] + true_x[12];
   out_6858679601398523695[13] = -nom_x[13] + true_x[13];
   out_6858679601398523695[14] = -nom_x[14] + true_x[14];
   out_6858679601398523695[15] = -nom_x[15] + true_x[15];
   out_6858679601398523695[16] = -nom_x[16] + true_x[16];
   out_6858679601398523695[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_7505068867812799858) {
   out_7505068867812799858[0] = 1.0;
   out_7505068867812799858[1] = 0.0;
   out_7505068867812799858[2] = 0.0;
   out_7505068867812799858[3] = 0.0;
   out_7505068867812799858[4] = 0.0;
   out_7505068867812799858[5] = 0.0;
   out_7505068867812799858[6] = 0.0;
   out_7505068867812799858[7] = 0.0;
   out_7505068867812799858[8] = 0.0;
   out_7505068867812799858[9] = 0.0;
   out_7505068867812799858[10] = 0.0;
   out_7505068867812799858[11] = 0.0;
   out_7505068867812799858[12] = 0.0;
   out_7505068867812799858[13] = 0.0;
   out_7505068867812799858[14] = 0.0;
   out_7505068867812799858[15] = 0.0;
   out_7505068867812799858[16] = 0.0;
   out_7505068867812799858[17] = 0.0;
   out_7505068867812799858[18] = 0.0;
   out_7505068867812799858[19] = 1.0;
   out_7505068867812799858[20] = 0.0;
   out_7505068867812799858[21] = 0.0;
   out_7505068867812799858[22] = 0.0;
   out_7505068867812799858[23] = 0.0;
   out_7505068867812799858[24] = 0.0;
   out_7505068867812799858[25] = 0.0;
   out_7505068867812799858[26] = 0.0;
   out_7505068867812799858[27] = 0.0;
   out_7505068867812799858[28] = 0.0;
   out_7505068867812799858[29] = 0.0;
   out_7505068867812799858[30] = 0.0;
   out_7505068867812799858[31] = 0.0;
   out_7505068867812799858[32] = 0.0;
   out_7505068867812799858[33] = 0.0;
   out_7505068867812799858[34] = 0.0;
   out_7505068867812799858[35] = 0.0;
   out_7505068867812799858[36] = 0.0;
   out_7505068867812799858[37] = 0.0;
   out_7505068867812799858[38] = 1.0;
   out_7505068867812799858[39] = 0.0;
   out_7505068867812799858[40] = 0.0;
   out_7505068867812799858[41] = 0.0;
   out_7505068867812799858[42] = 0.0;
   out_7505068867812799858[43] = 0.0;
   out_7505068867812799858[44] = 0.0;
   out_7505068867812799858[45] = 0.0;
   out_7505068867812799858[46] = 0.0;
   out_7505068867812799858[47] = 0.0;
   out_7505068867812799858[48] = 0.0;
   out_7505068867812799858[49] = 0.0;
   out_7505068867812799858[50] = 0.0;
   out_7505068867812799858[51] = 0.0;
   out_7505068867812799858[52] = 0.0;
   out_7505068867812799858[53] = 0.0;
   out_7505068867812799858[54] = 0.0;
   out_7505068867812799858[55] = 0.0;
   out_7505068867812799858[56] = 0.0;
   out_7505068867812799858[57] = 1.0;
   out_7505068867812799858[58] = 0.0;
   out_7505068867812799858[59] = 0.0;
   out_7505068867812799858[60] = 0.0;
   out_7505068867812799858[61] = 0.0;
   out_7505068867812799858[62] = 0.0;
   out_7505068867812799858[63] = 0.0;
   out_7505068867812799858[64] = 0.0;
   out_7505068867812799858[65] = 0.0;
   out_7505068867812799858[66] = 0.0;
   out_7505068867812799858[67] = 0.0;
   out_7505068867812799858[68] = 0.0;
   out_7505068867812799858[69] = 0.0;
   out_7505068867812799858[70] = 0.0;
   out_7505068867812799858[71] = 0.0;
   out_7505068867812799858[72] = 0.0;
   out_7505068867812799858[73] = 0.0;
   out_7505068867812799858[74] = 0.0;
   out_7505068867812799858[75] = 0.0;
   out_7505068867812799858[76] = 1.0;
   out_7505068867812799858[77] = 0.0;
   out_7505068867812799858[78] = 0.0;
   out_7505068867812799858[79] = 0.0;
   out_7505068867812799858[80] = 0.0;
   out_7505068867812799858[81] = 0.0;
   out_7505068867812799858[82] = 0.0;
   out_7505068867812799858[83] = 0.0;
   out_7505068867812799858[84] = 0.0;
   out_7505068867812799858[85] = 0.0;
   out_7505068867812799858[86] = 0.0;
   out_7505068867812799858[87] = 0.0;
   out_7505068867812799858[88] = 0.0;
   out_7505068867812799858[89] = 0.0;
   out_7505068867812799858[90] = 0.0;
   out_7505068867812799858[91] = 0.0;
   out_7505068867812799858[92] = 0.0;
   out_7505068867812799858[93] = 0.0;
   out_7505068867812799858[94] = 0.0;
   out_7505068867812799858[95] = 1.0;
   out_7505068867812799858[96] = 0.0;
   out_7505068867812799858[97] = 0.0;
   out_7505068867812799858[98] = 0.0;
   out_7505068867812799858[99] = 0.0;
   out_7505068867812799858[100] = 0.0;
   out_7505068867812799858[101] = 0.0;
   out_7505068867812799858[102] = 0.0;
   out_7505068867812799858[103] = 0.0;
   out_7505068867812799858[104] = 0.0;
   out_7505068867812799858[105] = 0.0;
   out_7505068867812799858[106] = 0.0;
   out_7505068867812799858[107] = 0.0;
   out_7505068867812799858[108] = 0.0;
   out_7505068867812799858[109] = 0.0;
   out_7505068867812799858[110] = 0.0;
   out_7505068867812799858[111] = 0.0;
   out_7505068867812799858[112] = 0.0;
   out_7505068867812799858[113] = 0.0;
   out_7505068867812799858[114] = 1.0;
   out_7505068867812799858[115] = 0.0;
   out_7505068867812799858[116] = 0.0;
   out_7505068867812799858[117] = 0.0;
   out_7505068867812799858[118] = 0.0;
   out_7505068867812799858[119] = 0.0;
   out_7505068867812799858[120] = 0.0;
   out_7505068867812799858[121] = 0.0;
   out_7505068867812799858[122] = 0.0;
   out_7505068867812799858[123] = 0.0;
   out_7505068867812799858[124] = 0.0;
   out_7505068867812799858[125] = 0.0;
   out_7505068867812799858[126] = 0.0;
   out_7505068867812799858[127] = 0.0;
   out_7505068867812799858[128] = 0.0;
   out_7505068867812799858[129] = 0.0;
   out_7505068867812799858[130] = 0.0;
   out_7505068867812799858[131] = 0.0;
   out_7505068867812799858[132] = 0.0;
   out_7505068867812799858[133] = 1.0;
   out_7505068867812799858[134] = 0.0;
   out_7505068867812799858[135] = 0.0;
   out_7505068867812799858[136] = 0.0;
   out_7505068867812799858[137] = 0.0;
   out_7505068867812799858[138] = 0.0;
   out_7505068867812799858[139] = 0.0;
   out_7505068867812799858[140] = 0.0;
   out_7505068867812799858[141] = 0.0;
   out_7505068867812799858[142] = 0.0;
   out_7505068867812799858[143] = 0.0;
   out_7505068867812799858[144] = 0.0;
   out_7505068867812799858[145] = 0.0;
   out_7505068867812799858[146] = 0.0;
   out_7505068867812799858[147] = 0.0;
   out_7505068867812799858[148] = 0.0;
   out_7505068867812799858[149] = 0.0;
   out_7505068867812799858[150] = 0.0;
   out_7505068867812799858[151] = 0.0;
   out_7505068867812799858[152] = 1.0;
   out_7505068867812799858[153] = 0.0;
   out_7505068867812799858[154] = 0.0;
   out_7505068867812799858[155] = 0.0;
   out_7505068867812799858[156] = 0.0;
   out_7505068867812799858[157] = 0.0;
   out_7505068867812799858[158] = 0.0;
   out_7505068867812799858[159] = 0.0;
   out_7505068867812799858[160] = 0.0;
   out_7505068867812799858[161] = 0.0;
   out_7505068867812799858[162] = 0.0;
   out_7505068867812799858[163] = 0.0;
   out_7505068867812799858[164] = 0.0;
   out_7505068867812799858[165] = 0.0;
   out_7505068867812799858[166] = 0.0;
   out_7505068867812799858[167] = 0.0;
   out_7505068867812799858[168] = 0.0;
   out_7505068867812799858[169] = 0.0;
   out_7505068867812799858[170] = 0.0;
   out_7505068867812799858[171] = 1.0;
   out_7505068867812799858[172] = 0.0;
   out_7505068867812799858[173] = 0.0;
   out_7505068867812799858[174] = 0.0;
   out_7505068867812799858[175] = 0.0;
   out_7505068867812799858[176] = 0.0;
   out_7505068867812799858[177] = 0.0;
   out_7505068867812799858[178] = 0.0;
   out_7505068867812799858[179] = 0.0;
   out_7505068867812799858[180] = 0.0;
   out_7505068867812799858[181] = 0.0;
   out_7505068867812799858[182] = 0.0;
   out_7505068867812799858[183] = 0.0;
   out_7505068867812799858[184] = 0.0;
   out_7505068867812799858[185] = 0.0;
   out_7505068867812799858[186] = 0.0;
   out_7505068867812799858[187] = 0.0;
   out_7505068867812799858[188] = 0.0;
   out_7505068867812799858[189] = 0.0;
   out_7505068867812799858[190] = 1.0;
   out_7505068867812799858[191] = 0.0;
   out_7505068867812799858[192] = 0.0;
   out_7505068867812799858[193] = 0.0;
   out_7505068867812799858[194] = 0.0;
   out_7505068867812799858[195] = 0.0;
   out_7505068867812799858[196] = 0.0;
   out_7505068867812799858[197] = 0.0;
   out_7505068867812799858[198] = 0.0;
   out_7505068867812799858[199] = 0.0;
   out_7505068867812799858[200] = 0.0;
   out_7505068867812799858[201] = 0.0;
   out_7505068867812799858[202] = 0.0;
   out_7505068867812799858[203] = 0.0;
   out_7505068867812799858[204] = 0.0;
   out_7505068867812799858[205] = 0.0;
   out_7505068867812799858[206] = 0.0;
   out_7505068867812799858[207] = 0.0;
   out_7505068867812799858[208] = 0.0;
   out_7505068867812799858[209] = 1.0;
   out_7505068867812799858[210] = 0.0;
   out_7505068867812799858[211] = 0.0;
   out_7505068867812799858[212] = 0.0;
   out_7505068867812799858[213] = 0.0;
   out_7505068867812799858[214] = 0.0;
   out_7505068867812799858[215] = 0.0;
   out_7505068867812799858[216] = 0.0;
   out_7505068867812799858[217] = 0.0;
   out_7505068867812799858[218] = 0.0;
   out_7505068867812799858[219] = 0.0;
   out_7505068867812799858[220] = 0.0;
   out_7505068867812799858[221] = 0.0;
   out_7505068867812799858[222] = 0.0;
   out_7505068867812799858[223] = 0.0;
   out_7505068867812799858[224] = 0.0;
   out_7505068867812799858[225] = 0.0;
   out_7505068867812799858[226] = 0.0;
   out_7505068867812799858[227] = 0.0;
   out_7505068867812799858[228] = 1.0;
   out_7505068867812799858[229] = 0.0;
   out_7505068867812799858[230] = 0.0;
   out_7505068867812799858[231] = 0.0;
   out_7505068867812799858[232] = 0.0;
   out_7505068867812799858[233] = 0.0;
   out_7505068867812799858[234] = 0.0;
   out_7505068867812799858[235] = 0.0;
   out_7505068867812799858[236] = 0.0;
   out_7505068867812799858[237] = 0.0;
   out_7505068867812799858[238] = 0.0;
   out_7505068867812799858[239] = 0.0;
   out_7505068867812799858[240] = 0.0;
   out_7505068867812799858[241] = 0.0;
   out_7505068867812799858[242] = 0.0;
   out_7505068867812799858[243] = 0.0;
   out_7505068867812799858[244] = 0.0;
   out_7505068867812799858[245] = 0.0;
   out_7505068867812799858[246] = 0.0;
   out_7505068867812799858[247] = 1.0;
   out_7505068867812799858[248] = 0.0;
   out_7505068867812799858[249] = 0.0;
   out_7505068867812799858[250] = 0.0;
   out_7505068867812799858[251] = 0.0;
   out_7505068867812799858[252] = 0.0;
   out_7505068867812799858[253] = 0.0;
   out_7505068867812799858[254] = 0.0;
   out_7505068867812799858[255] = 0.0;
   out_7505068867812799858[256] = 0.0;
   out_7505068867812799858[257] = 0.0;
   out_7505068867812799858[258] = 0.0;
   out_7505068867812799858[259] = 0.0;
   out_7505068867812799858[260] = 0.0;
   out_7505068867812799858[261] = 0.0;
   out_7505068867812799858[262] = 0.0;
   out_7505068867812799858[263] = 0.0;
   out_7505068867812799858[264] = 0.0;
   out_7505068867812799858[265] = 0.0;
   out_7505068867812799858[266] = 1.0;
   out_7505068867812799858[267] = 0.0;
   out_7505068867812799858[268] = 0.0;
   out_7505068867812799858[269] = 0.0;
   out_7505068867812799858[270] = 0.0;
   out_7505068867812799858[271] = 0.0;
   out_7505068867812799858[272] = 0.0;
   out_7505068867812799858[273] = 0.0;
   out_7505068867812799858[274] = 0.0;
   out_7505068867812799858[275] = 0.0;
   out_7505068867812799858[276] = 0.0;
   out_7505068867812799858[277] = 0.0;
   out_7505068867812799858[278] = 0.0;
   out_7505068867812799858[279] = 0.0;
   out_7505068867812799858[280] = 0.0;
   out_7505068867812799858[281] = 0.0;
   out_7505068867812799858[282] = 0.0;
   out_7505068867812799858[283] = 0.0;
   out_7505068867812799858[284] = 0.0;
   out_7505068867812799858[285] = 1.0;
   out_7505068867812799858[286] = 0.0;
   out_7505068867812799858[287] = 0.0;
   out_7505068867812799858[288] = 0.0;
   out_7505068867812799858[289] = 0.0;
   out_7505068867812799858[290] = 0.0;
   out_7505068867812799858[291] = 0.0;
   out_7505068867812799858[292] = 0.0;
   out_7505068867812799858[293] = 0.0;
   out_7505068867812799858[294] = 0.0;
   out_7505068867812799858[295] = 0.0;
   out_7505068867812799858[296] = 0.0;
   out_7505068867812799858[297] = 0.0;
   out_7505068867812799858[298] = 0.0;
   out_7505068867812799858[299] = 0.0;
   out_7505068867812799858[300] = 0.0;
   out_7505068867812799858[301] = 0.0;
   out_7505068867812799858[302] = 0.0;
   out_7505068867812799858[303] = 0.0;
   out_7505068867812799858[304] = 1.0;
   out_7505068867812799858[305] = 0.0;
   out_7505068867812799858[306] = 0.0;
   out_7505068867812799858[307] = 0.0;
   out_7505068867812799858[308] = 0.0;
   out_7505068867812799858[309] = 0.0;
   out_7505068867812799858[310] = 0.0;
   out_7505068867812799858[311] = 0.0;
   out_7505068867812799858[312] = 0.0;
   out_7505068867812799858[313] = 0.0;
   out_7505068867812799858[314] = 0.0;
   out_7505068867812799858[315] = 0.0;
   out_7505068867812799858[316] = 0.0;
   out_7505068867812799858[317] = 0.0;
   out_7505068867812799858[318] = 0.0;
   out_7505068867812799858[319] = 0.0;
   out_7505068867812799858[320] = 0.0;
   out_7505068867812799858[321] = 0.0;
   out_7505068867812799858[322] = 0.0;
   out_7505068867812799858[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_7693532277985119128) {
   out_7693532277985119128[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_7693532277985119128[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_7693532277985119128[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_7693532277985119128[3] = dt*state[12] + state[3];
   out_7693532277985119128[4] = dt*state[13] + state[4];
   out_7693532277985119128[5] = dt*state[14] + state[5];
   out_7693532277985119128[6] = state[6];
   out_7693532277985119128[7] = state[7];
   out_7693532277985119128[8] = state[8];
   out_7693532277985119128[9] = state[9];
   out_7693532277985119128[10] = state[10];
   out_7693532277985119128[11] = state[11];
   out_7693532277985119128[12] = state[12];
   out_7693532277985119128[13] = state[13];
   out_7693532277985119128[14] = state[14];
   out_7693532277985119128[15] = state[15];
   out_7693532277985119128[16] = state[16];
   out_7693532277985119128[17] = state[17];
}
void F_fun(double *state, double dt, double *out_2354363096336885288) {
   out_2354363096336885288[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2354363096336885288[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2354363096336885288[2] = 0;
   out_2354363096336885288[3] = 0;
   out_2354363096336885288[4] = 0;
   out_2354363096336885288[5] = 0;
   out_2354363096336885288[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2354363096336885288[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2354363096336885288[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2354363096336885288[9] = 0;
   out_2354363096336885288[10] = 0;
   out_2354363096336885288[11] = 0;
   out_2354363096336885288[12] = 0;
   out_2354363096336885288[13] = 0;
   out_2354363096336885288[14] = 0;
   out_2354363096336885288[15] = 0;
   out_2354363096336885288[16] = 0;
   out_2354363096336885288[17] = 0;
   out_2354363096336885288[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2354363096336885288[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2354363096336885288[20] = 0;
   out_2354363096336885288[21] = 0;
   out_2354363096336885288[22] = 0;
   out_2354363096336885288[23] = 0;
   out_2354363096336885288[24] = 0;
   out_2354363096336885288[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2354363096336885288[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2354363096336885288[27] = 0;
   out_2354363096336885288[28] = 0;
   out_2354363096336885288[29] = 0;
   out_2354363096336885288[30] = 0;
   out_2354363096336885288[31] = 0;
   out_2354363096336885288[32] = 0;
   out_2354363096336885288[33] = 0;
   out_2354363096336885288[34] = 0;
   out_2354363096336885288[35] = 0;
   out_2354363096336885288[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2354363096336885288[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2354363096336885288[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2354363096336885288[39] = 0;
   out_2354363096336885288[40] = 0;
   out_2354363096336885288[41] = 0;
   out_2354363096336885288[42] = 0;
   out_2354363096336885288[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2354363096336885288[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2354363096336885288[45] = 0;
   out_2354363096336885288[46] = 0;
   out_2354363096336885288[47] = 0;
   out_2354363096336885288[48] = 0;
   out_2354363096336885288[49] = 0;
   out_2354363096336885288[50] = 0;
   out_2354363096336885288[51] = 0;
   out_2354363096336885288[52] = 0;
   out_2354363096336885288[53] = 0;
   out_2354363096336885288[54] = 0;
   out_2354363096336885288[55] = 0;
   out_2354363096336885288[56] = 0;
   out_2354363096336885288[57] = 1;
   out_2354363096336885288[58] = 0;
   out_2354363096336885288[59] = 0;
   out_2354363096336885288[60] = 0;
   out_2354363096336885288[61] = 0;
   out_2354363096336885288[62] = 0;
   out_2354363096336885288[63] = 0;
   out_2354363096336885288[64] = 0;
   out_2354363096336885288[65] = 0;
   out_2354363096336885288[66] = dt;
   out_2354363096336885288[67] = 0;
   out_2354363096336885288[68] = 0;
   out_2354363096336885288[69] = 0;
   out_2354363096336885288[70] = 0;
   out_2354363096336885288[71] = 0;
   out_2354363096336885288[72] = 0;
   out_2354363096336885288[73] = 0;
   out_2354363096336885288[74] = 0;
   out_2354363096336885288[75] = 0;
   out_2354363096336885288[76] = 1;
   out_2354363096336885288[77] = 0;
   out_2354363096336885288[78] = 0;
   out_2354363096336885288[79] = 0;
   out_2354363096336885288[80] = 0;
   out_2354363096336885288[81] = 0;
   out_2354363096336885288[82] = 0;
   out_2354363096336885288[83] = 0;
   out_2354363096336885288[84] = 0;
   out_2354363096336885288[85] = dt;
   out_2354363096336885288[86] = 0;
   out_2354363096336885288[87] = 0;
   out_2354363096336885288[88] = 0;
   out_2354363096336885288[89] = 0;
   out_2354363096336885288[90] = 0;
   out_2354363096336885288[91] = 0;
   out_2354363096336885288[92] = 0;
   out_2354363096336885288[93] = 0;
   out_2354363096336885288[94] = 0;
   out_2354363096336885288[95] = 1;
   out_2354363096336885288[96] = 0;
   out_2354363096336885288[97] = 0;
   out_2354363096336885288[98] = 0;
   out_2354363096336885288[99] = 0;
   out_2354363096336885288[100] = 0;
   out_2354363096336885288[101] = 0;
   out_2354363096336885288[102] = 0;
   out_2354363096336885288[103] = 0;
   out_2354363096336885288[104] = dt;
   out_2354363096336885288[105] = 0;
   out_2354363096336885288[106] = 0;
   out_2354363096336885288[107] = 0;
   out_2354363096336885288[108] = 0;
   out_2354363096336885288[109] = 0;
   out_2354363096336885288[110] = 0;
   out_2354363096336885288[111] = 0;
   out_2354363096336885288[112] = 0;
   out_2354363096336885288[113] = 0;
   out_2354363096336885288[114] = 1;
   out_2354363096336885288[115] = 0;
   out_2354363096336885288[116] = 0;
   out_2354363096336885288[117] = 0;
   out_2354363096336885288[118] = 0;
   out_2354363096336885288[119] = 0;
   out_2354363096336885288[120] = 0;
   out_2354363096336885288[121] = 0;
   out_2354363096336885288[122] = 0;
   out_2354363096336885288[123] = 0;
   out_2354363096336885288[124] = 0;
   out_2354363096336885288[125] = 0;
   out_2354363096336885288[126] = 0;
   out_2354363096336885288[127] = 0;
   out_2354363096336885288[128] = 0;
   out_2354363096336885288[129] = 0;
   out_2354363096336885288[130] = 0;
   out_2354363096336885288[131] = 0;
   out_2354363096336885288[132] = 0;
   out_2354363096336885288[133] = 1;
   out_2354363096336885288[134] = 0;
   out_2354363096336885288[135] = 0;
   out_2354363096336885288[136] = 0;
   out_2354363096336885288[137] = 0;
   out_2354363096336885288[138] = 0;
   out_2354363096336885288[139] = 0;
   out_2354363096336885288[140] = 0;
   out_2354363096336885288[141] = 0;
   out_2354363096336885288[142] = 0;
   out_2354363096336885288[143] = 0;
   out_2354363096336885288[144] = 0;
   out_2354363096336885288[145] = 0;
   out_2354363096336885288[146] = 0;
   out_2354363096336885288[147] = 0;
   out_2354363096336885288[148] = 0;
   out_2354363096336885288[149] = 0;
   out_2354363096336885288[150] = 0;
   out_2354363096336885288[151] = 0;
   out_2354363096336885288[152] = 1;
   out_2354363096336885288[153] = 0;
   out_2354363096336885288[154] = 0;
   out_2354363096336885288[155] = 0;
   out_2354363096336885288[156] = 0;
   out_2354363096336885288[157] = 0;
   out_2354363096336885288[158] = 0;
   out_2354363096336885288[159] = 0;
   out_2354363096336885288[160] = 0;
   out_2354363096336885288[161] = 0;
   out_2354363096336885288[162] = 0;
   out_2354363096336885288[163] = 0;
   out_2354363096336885288[164] = 0;
   out_2354363096336885288[165] = 0;
   out_2354363096336885288[166] = 0;
   out_2354363096336885288[167] = 0;
   out_2354363096336885288[168] = 0;
   out_2354363096336885288[169] = 0;
   out_2354363096336885288[170] = 0;
   out_2354363096336885288[171] = 1;
   out_2354363096336885288[172] = 0;
   out_2354363096336885288[173] = 0;
   out_2354363096336885288[174] = 0;
   out_2354363096336885288[175] = 0;
   out_2354363096336885288[176] = 0;
   out_2354363096336885288[177] = 0;
   out_2354363096336885288[178] = 0;
   out_2354363096336885288[179] = 0;
   out_2354363096336885288[180] = 0;
   out_2354363096336885288[181] = 0;
   out_2354363096336885288[182] = 0;
   out_2354363096336885288[183] = 0;
   out_2354363096336885288[184] = 0;
   out_2354363096336885288[185] = 0;
   out_2354363096336885288[186] = 0;
   out_2354363096336885288[187] = 0;
   out_2354363096336885288[188] = 0;
   out_2354363096336885288[189] = 0;
   out_2354363096336885288[190] = 1;
   out_2354363096336885288[191] = 0;
   out_2354363096336885288[192] = 0;
   out_2354363096336885288[193] = 0;
   out_2354363096336885288[194] = 0;
   out_2354363096336885288[195] = 0;
   out_2354363096336885288[196] = 0;
   out_2354363096336885288[197] = 0;
   out_2354363096336885288[198] = 0;
   out_2354363096336885288[199] = 0;
   out_2354363096336885288[200] = 0;
   out_2354363096336885288[201] = 0;
   out_2354363096336885288[202] = 0;
   out_2354363096336885288[203] = 0;
   out_2354363096336885288[204] = 0;
   out_2354363096336885288[205] = 0;
   out_2354363096336885288[206] = 0;
   out_2354363096336885288[207] = 0;
   out_2354363096336885288[208] = 0;
   out_2354363096336885288[209] = 1;
   out_2354363096336885288[210] = 0;
   out_2354363096336885288[211] = 0;
   out_2354363096336885288[212] = 0;
   out_2354363096336885288[213] = 0;
   out_2354363096336885288[214] = 0;
   out_2354363096336885288[215] = 0;
   out_2354363096336885288[216] = 0;
   out_2354363096336885288[217] = 0;
   out_2354363096336885288[218] = 0;
   out_2354363096336885288[219] = 0;
   out_2354363096336885288[220] = 0;
   out_2354363096336885288[221] = 0;
   out_2354363096336885288[222] = 0;
   out_2354363096336885288[223] = 0;
   out_2354363096336885288[224] = 0;
   out_2354363096336885288[225] = 0;
   out_2354363096336885288[226] = 0;
   out_2354363096336885288[227] = 0;
   out_2354363096336885288[228] = 1;
   out_2354363096336885288[229] = 0;
   out_2354363096336885288[230] = 0;
   out_2354363096336885288[231] = 0;
   out_2354363096336885288[232] = 0;
   out_2354363096336885288[233] = 0;
   out_2354363096336885288[234] = 0;
   out_2354363096336885288[235] = 0;
   out_2354363096336885288[236] = 0;
   out_2354363096336885288[237] = 0;
   out_2354363096336885288[238] = 0;
   out_2354363096336885288[239] = 0;
   out_2354363096336885288[240] = 0;
   out_2354363096336885288[241] = 0;
   out_2354363096336885288[242] = 0;
   out_2354363096336885288[243] = 0;
   out_2354363096336885288[244] = 0;
   out_2354363096336885288[245] = 0;
   out_2354363096336885288[246] = 0;
   out_2354363096336885288[247] = 1;
   out_2354363096336885288[248] = 0;
   out_2354363096336885288[249] = 0;
   out_2354363096336885288[250] = 0;
   out_2354363096336885288[251] = 0;
   out_2354363096336885288[252] = 0;
   out_2354363096336885288[253] = 0;
   out_2354363096336885288[254] = 0;
   out_2354363096336885288[255] = 0;
   out_2354363096336885288[256] = 0;
   out_2354363096336885288[257] = 0;
   out_2354363096336885288[258] = 0;
   out_2354363096336885288[259] = 0;
   out_2354363096336885288[260] = 0;
   out_2354363096336885288[261] = 0;
   out_2354363096336885288[262] = 0;
   out_2354363096336885288[263] = 0;
   out_2354363096336885288[264] = 0;
   out_2354363096336885288[265] = 0;
   out_2354363096336885288[266] = 1;
   out_2354363096336885288[267] = 0;
   out_2354363096336885288[268] = 0;
   out_2354363096336885288[269] = 0;
   out_2354363096336885288[270] = 0;
   out_2354363096336885288[271] = 0;
   out_2354363096336885288[272] = 0;
   out_2354363096336885288[273] = 0;
   out_2354363096336885288[274] = 0;
   out_2354363096336885288[275] = 0;
   out_2354363096336885288[276] = 0;
   out_2354363096336885288[277] = 0;
   out_2354363096336885288[278] = 0;
   out_2354363096336885288[279] = 0;
   out_2354363096336885288[280] = 0;
   out_2354363096336885288[281] = 0;
   out_2354363096336885288[282] = 0;
   out_2354363096336885288[283] = 0;
   out_2354363096336885288[284] = 0;
   out_2354363096336885288[285] = 1;
   out_2354363096336885288[286] = 0;
   out_2354363096336885288[287] = 0;
   out_2354363096336885288[288] = 0;
   out_2354363096336885288[289] = 0;
   out_2354363096336885288[290] = 0;
   out_2354363096336885288[291] = 0;
   out_2354363096336885288[292] = 0;
   out_2354363096336885288[293] = 0;
   out_2354363096336885288[294] = 0;
   out_2354363096336885288[295] = 0;
   out_2354363096336885288[296] = 0;
   out_2354363096336885288[297] = 0;
   out_2354363096336885288[298] = 0;
   out_2354363096336885288[299] = 0;
   out_2354363096336885288[300] = 0;
   out_2354363096336885288[301] = 0;
   out_2354363096336885288[302] = 0;
   out_2354363096336885288[303] = 0;
   out_2354363096336885288[304] = 1;
   out_2354363096336885288[305] = 0;
   out_2354363096336885288[306] = 0;
   out_2354363096336885288[307] = 0;
   out_2354363096336885288[308] = 0;
   out_2354363096336885288[309] = 0;
   out_2354363096336885288[310] = 0;
   out_2354363096336885288[311] = 0;
   out_2354363096336885288[312] = 0;
   out_2354363096336885288[313] = 0;
   out_2354363096336885288[314] = 0;
   out_2354363096336885288[315] = 0;
   out_2354363096336885288[316] = 0;
   out_2354363096336885288[317] = 0;
   out_2354363096336885288[318] = 0;
   out_2354363096336885288[319] = 0;
   out_2354363096336885288[320] = 0;
   out_2354363096336885288[321] = 0;
   out_2354363096336885288[322] = 0;
   out_2354363096336885288[323] = 1;
}
void h_4(double *state, double *unused, double *out_2798176097030080284) {
   out_2798176097030080284[0] = state[6] + state[9];
   out_2798176097030080284[1] = state[7] + state[10];
   out_2798176097030080284[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_8259229869867512465) {
   out_8259229869867512465[0] = 0;
   out_8259229869867512465[1] = 0;
   out_8259229869867512465[2] = 0;
   out_8259229869867512465[3] = 0;
   out_8259229869867512465[4] = 0;
   out_8259229869867512465[5] = 0;
   out_8259229869867512465[6] = 1;
   out_8259229869867512465[7] = 0;
   out_8259229869867512465[8] = 0;
   out_8259229869867512465[9] = 1;
   out_8259229869867512465[10] = 0;
   out_8259229869867512465[11] = 0;
   out_8259229869867512465[12] = 0;
   out_8259229869867512465[13] = 0;
   out_8259229869867512465[14] = 0;
   out_8259229869867512465[15] = 0;
   out_8259229869867512465[16] = 0;
   out_8259229869867512465[17] = 0;
   out_8259229869867512465[18] = 0;
   out_8259229869867512465[19] = 0;
   out_8259229869867512465[20] = 0;
   out_8259229869867512465[21] = 0;
   out_8259229869867512465[22] = 0;
   out_8259229869867512465[23] = 0;
   out_8259229869867512465[24] = 0;
   out_8259229869867512465[25] = 1;
   out_8259229869867512465[26] = 0;
   out_8259229869867512465[27] = 0;
   out_8259229869867512465[28] = 1;
   out_8259229869867512465[29] = 0;
   out_8259229869867512465[30] = 0;
   out_8259229869867512465[31] = 0;
   out_8259229869867512465[32] = 0;
   out_8259229869867512465[33] = 0;
   out_8259229869867512465[34] = 0;
   out_8259229869867512465[35] = 0;
   out_8259229869867512465[36] = 0;
   out_8259229869867512465[37] = 0;
   out_8259229869867512465[38] = 0;
   out_8259229869867512465[39] = 0;
   out_8259229869867512465[40] = 0;
   out_8259229869867512465[41] = 0;
   out_8259229869867512465[42] = 0;
   out_8259229869867512465[43] = 0;
   out_8259229869867512465[44] = 1;
   out_8259229869867512465[45] = 0;
   out_8259229869867512465[46] = 0;
   out_8259229869867512465[47] = 1;
   out_8259229869867512465[48] = 0;
   out_8259229869867512465[49] = 0;
   out_8259229869867512465[50] = 0;
   out_8259229869867512465[51] = 0;
   out_8259229869867512465[52] = 0;
   out_8259229869867512465[53] = 0;
}
void h_10(double *state, double *unused, double *out_6129012920849367651) {
   out_6129012920849367651[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_6129012920849367651[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_6129012920849367651[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_6492774096974950579) {
   out_6492774096974950579[0] = 0;
   out_6492774096974950579[1] = 9.8100000000000005*cos(state[1]);
   out_6492774096974950579[2] = 0;
   out_6492774096974950579[3] = 0;
   out_6492774096974950579[4] = -state[8];
   out_6492774096974950579[5] = state[7];
   out_6492774096974950579[6] = 0;
   out_6492774096974950579[7] = state[5];
   out_6492774096974950579[8] = -state[4];
   out_6492774096974950579[9] = 0;
   out_6492774096974950579[10] = 0;
   out_6492774096974950579[11] = 0;
   out_6492774096974950579[12] = 1;
   out_6492774096974950579[13] = 0;
   out_6492774096974950579[14] = 0;
   out_6492774096974950579[15] = 1;
   out_6492774096974950579[16] = 0;
   out_6492774096974950579[17] = 0;
   out_6492774096974950579[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_6492774096974950579[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_6492774096974950579[20] = 0;
   out_6492774096974950579[21] = state[8];
   out_6492774096974950579[22] = 0;
   out_6492774096974950579[23] = -state[6];
   out_6492774096974950579[24] = -state[5];
   out_6492774096974950579[25] = 0;
   out_6492774096974950579[26] = state[3];
   out_6492774096974950579[27] = 0;
   out_6492774096974950579[28] = 0;
   out_6492774096974950579[29] = 0;
   out_6492774096974950579[30] = 0;
   out_6492774096974950579[31] = 1;
   out_6492774096974950579[32] = 0;
   out_6492774096974950579[33] = 0;
   out_6492774096974950579[34] = 1;
   out_6492774096974950579[35] = 0;
   out_6492774096974950579[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_6492774096974950579[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_6492774096974950579[38] = 0;
   out_6492774096974950579[39] = -state[7];
   out_6492774096974950579[40] = state[6];
   out_6492774096974950579[41] = 0;
   out_6492774096974950579[42] = state[4];
   out_6492774096974950579[43] = -state[3];
   out_6492774096974950579[44] = 0;
   out_6492774096974950579[45] = 0;
   out_6492774096974950579[46] = 0;
   out_6492774096974950579[47] = 0;
   out_6492774096974950579[48] = 0;
   out_6492774096974950579[49] = 0;
   out_6492774096974950579[50] = 1;
   out_6492774096974950579[51] = 0;
   out_6492774096974950579[52] = 0;
   out_6492774096974950579[53] = 1;
}
void h_13(double *state, double *unused, double *out_630259235338554445) {
   out_630259235338554445[0] = state[3];
   out_630259235338554445[1] = state[4];
   out_630259235338554445[2] = state[5];
}
void H_13(double *state, double *unused, double *out_2576882995525338222) {
   out_2576882995525338222[0] = 0;
   out_2576882995525338222[1] = 0;
   out_2576882995525338222[2] = 0;
   out_2576882995525338222[3] = 1;
   out_2576882995525338222[4] = 0;
   out_2576882995525338222[5] = 0;
   out_2576882995525338222[6] = 0;
   out_2576882995525338222[7] = 0;
   out_2576882995525338222[8] = 0;
   out_2576882995525338222[9] = 0;
   out_2576882995525338222[10] = 0;
   out_2576882995525338222[11] = 0;
   out_2576882995525338222[12] = 0;
   out_2576882995525338222[13] = 0;
   out_2576882995525338222[14] = 0;
   out_2576882995525338222[15] = 0;
   out_2576882995525338222[16] = 0;
   out_2576882995525338222[17] = 0;
   out_2576882995525338222[18] = 0;
   out_2576882995525338222[19] = 0;
   out_2576882995525338222[20] = 0;
   out_2576882995525338222[21] = 0;
   out_2576882995525338222[22] = 1;
   out_2576882995525338222[23] = 0;
   out_2576882995525338222[24] = 0;
   out_2576882995525338222[25] = 0;
   out_2576882995525338222[26] = 0;
   out_2576882995525338222[27] = 0;
   out_2576882995525338222[28] = 0;
   out_2576882995525338222[29] = 0;
   out_2576882995525338222[30] = 0;
   out_2576882995525338222[31] = 0;
   out_2576882995525338222[32] = 0;
   out_2576882995525338222[33] = 0;
   out_2576882995525338222[34] = 0;
   out_2576882995525338222[35] = 0;
   out_2576882995525338222[36] = 0;
   out_2576882995525338222[37] = 0;
   out_2576882995525338222[38] = 0;
   out_2576882995525338222[39] = 0;
   out_2576882995525338222[40] = 0;
   out_2576882995525338222[41] = 1;
   out_2576882995525338222[42] = 0;
   out_2576882995525338222[43] = 0;
   out_2576882995525338222[44] = 0;
   out_2576882995525338222[45] = 0;
   out_2576882995525338222[46] = 0;
   out_2576882995525338222[47] = 0;
   out_2576882995525338222[48] = 0;
   out_2576882995525338222[49] = 0;
   out_2576882995525338222[50] = 0;
   out_2576882995525338222[51] = 0;
   out_2576882995525338222[52] = 0;
   out_2576882995525338222[53] = 0;
}
void h_14(double *state, double *unused, double *out_5108820496996726073) {
   out_5108820496996726073[0] = state[6];
   out_5108820496996726073[1] = state[7];
   out_5108820496996726073[2] = state[8];
}
void H_14(double *state, double *unused, double *out_5176441437572140169) {
   out_5176441437572140169[0] = 0;
   out_5176441437572140169[1] = 0;
   out_5176441437572140169[2] = 0;
   out_5176441437572140169[3] = 0;
   out_5176441437572140169[4] = 0;
   out_5176441437572140169[5] = 0;
   out_5176441437572140169[6] = 1;
   out_5176441437572140169[7] = 0;
   out_5176441437572140169[8] = 0;
   out_5176441437572140169[9] = 0;
   out_5176441437572140169[10] = 0;
   out_5176441437572140169[11] = 0;
   out_5176441437572140169[12] = 0;
   out_5176441437572140169[13] = 0;
   out_5176441437572140169[14] = 0;
   out_5176441437572140169[15] = 0;
   out_5176441437572140169[16] = 0;
   out_5176441437572140169[17] = 0;
   out_5176441437572140169[18] = 0;
   out_5176441437572140169[19] = 0;
   out_5176441437572140169[20] = 0;
   out_5176441437572140169[21] = 0;
   out_5176441437572140169[22] = 0;
   out_5176441437572140169[23] = 0;
   out_5176441437572140169[24] = 0;
   out_5176441437572140169[25] = 1;
   out_5176441437572140169[26] = 0;
   out_5176441437572140169[27] = 0;
   out_5176441437572140169[28] = 0;
   out_5176441437572140169[29] = 0;
   out_5176441437572140169[30] = 0;
   out_5176441437572140169[31] = 0;
   out_5176441437572140169[32] = 0;
   out_5176441437572140169[33] = 0;
   out_5176441437572140169[34] = 0;
   out_5176441437572140169[35] = 0;
   out_5176441437572140169[36] = 0;
   out_5176441437572140169[37] = 0;
   out_5176441437572140169[38] = 0;
   out_5176441437572140169[39] = 0;
   out_5176441437572140169[40] = 0;
   out_5176441437572140169[41] = 0;
   out_5176441437572140169[42] = 0;
   out_5176441437572140169[43] = 0;
   out_5176441437572140169[44] = 1;
   out_5176441437572140169[45] = 0;
   out_5176441437572140169[46] = 0;
   out_5176441437572140169[47] = 0;
   out_5176441437572140169[48] = 0;
   out_5176441437572140169[49] = 0;
   out_5176441437572140169[50] = 0;
   out_5176441437572140169[51] = 0;
   out_5176441437572140169[52] = 0;
   out_5176441437572140169[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_9020563603504726210) {
  err_fun(nom_x, delta_x, out_9020563603504726210);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_6858679601398523695) {
  inv_err_fun(nom_x, true_x, out_6858679601398523695);
}
void pose_H_mod_fun(double *state, double *out_7505068867812799858) {
  H_mod_fun(state, out_7505068867812799858);
}
void pose_f_fun(double *state, double dt, double *out_7693532277985119128) {
  f_fun(state,  dt, out_7693532277985119128);
}
void pose_F_fun(double *state, double dt, double *out_2354363096336885288) {
  F_fun(state,  dt, out_2354363096336885288);
}
void pose_h_4(double *state, double *unused, double *out_2798176097030080284) {
  h_4(state, unused, out_2798176097030080284);
}
void pose_H_4(double *state, double *unused, double *out_8259229869867512465) {
  H_4(state, unused, out_8259229869867512465);
}
void pose_h_10(double *state, double *unused, double *out_6129012920849367651) {
  h_10(state, unused, out_6129012920849367651);
}
void pose_H_10(double *state, double *unused, double *out_6492774096974950579) {
  H_10(state, unused, out_6492774096974950579);
}
void pose_h_13(double *state, double *unused, double *out_630259235338554445) {
  h_13(state, unused, out_630259235338554445);
}
void pose_H_13(double *state, double *unused, double *out_2576882995525338222) {
  H_13(state, unused, out_2576882995525338222);
}
void pose_h_14(double *state, double *unused, double *out_5108820496996726073) {
  h_14(state, unused, out_5108820496996726073);
}
void pose_H_14(double *state, double *unused, double *out_5176441437572140169) {
  H_14(state, unused, out_5176441437572140169);
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
