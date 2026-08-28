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
void err_fun(double *nom_x, double *delta_x, double *out_1700850028159621162) {
   out_1700850028159621162[0] = delta_x[0] + nom_x[0];
   out_1700850028159621162[1] = delta_x[1] + nom_x[1];
   out_1700850028159621162[2] = delta_x[2] + nom_x[2];
   out_1700850028159621162[3] = delta_x[3] + nom_x[3];
   out_1700850028159621162[4] = delta_x[4] + nom_x[4];
   out_1700850028159621162[5] = delta_x[5] + nom_x[5];
   out_1700850028159621162[6] = delta_x[6] + nom_x[6];
   out_1700850028159621162[7] = delta_x[7] + nom_x[7];
   out_1700850028159621162[8] = delta_x[8] + nom_x[8];
   out_1700850028159621162[9] = delta_x[9] + nom_x[9];
   out_1700850028159621162[10] = delta_x[10] + nom_x[10];
   out_1700850028159621162[11] = delta_x[11] + nom_x[11];
   out_1700850028159621162[12] = delta_x[12] + nom_x[12];
   out_1700850028159621162[13] = delta_x[13] + nom_x[13];
   out_1700850028159621162[14] = delta_x[14] + nom_x[14];
   out_1700850028159621162[15] = delta_x[15] + nom_x[15];
   out_1700850028159621162[16] = delta_x[16] + nom_x[16];
   out_1700850028159621162[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_3416595063278262141) {
   out_3416595063278262141[0] = -nom_x[0] + true_x[0];
   out_3416595063278262141[1] = -nom_x[1] + true_x[1];
   out_3416595063278262141[2] = -nom_x[2] + true_x[2];
   out_3416595063278262141[3] = -nom_x[3] + true_x[3];
   out_3416595063278262141[4] = -nom_x[4] + true_x[4];
   out_3416595063278262141[5] = -nom_x[5] + true_x[5];
   out_3416595063278262141[6] = -nom_x[6] + true_x[6];
   out_3416595063278262141[7] = -nom_x[7] + true_x[7];
   out_3416595063278262141[8] = -nom_x[8] + true_x[8];
   out_3416595063278262141[9] = -nom_x[9] + true_x[9];
   out_3416595063278262141[10] = -nom_x[10] + true_x[10];
   out_3416595063278262141[11] = -nom_x[11] + true_x[11];
   out_3416595063278262141[12] = -nom_x[12] + true_x[12];
   out_3416595063278262141[13] = -nom_x[13] + true_x[13];
   out_3416595063278262141[14] = -nom_x[14] + true_x[14];
   out_3416595063278262141[15] = -nom_x[15] + true_x[15];
   out_3416595063278262141[16] = -nom_x[16] + true_x[16];
   out_3416595063278262141[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_2045417260865528734) {
   out_2045417260865528734[0] = 1.0;
   out_2045417260865528734[1] = 0.0;
   out_2045417260865528734[2] = 0.0;
   out_2045417260865528734[3] = 0.0;
   out_2045417260865528734[4] = 0.0;
   out_2045417260865528734[5] = 0.0;
   out_2045417260865528734[6] = 0.0;
   out_2045417260865528734[7] = 0.0;
   out_2045417260865528734[8] = 0.0;
   out_2045417260865528734[9] = 0.0;
   out_2045417260865528734[10] = 0.0;
   out_2045417260865528734[11] = 0.0;
   out_2045417260865528734[12] = 0.0;
   out_2045417260865528734[13] = 0.0;
   out_2045417260865528734[14] = 0.0;
   out_2045417260865528734[15] = 0.0;
   out_2045417260865528734[16] = 0.0;
   out_2045417260865528734[17] = 0.0;
   out_2045417260865528734[18] = 0.0;
   out_2045417260865528734[19] = 1.0;
   out_2045417260865528734[20] = 0.0;
   out_2045417260865528734[21] = 0.0;
   out_2045417260865528734[22] = 0.0;
   out_2045417260865528734[23] = 0.0;
   out_2045417260865528734[24] = 0.0;
   out_2045417260865528734[25] = 0.0;
   out_2045417260865528734[26] = 0.0;
   out_2045417260865528734[27] = 0.0;
   out_2045417260865528734[28] = 0.0;
   out_2045417260865528734[29] = 0.0;
   out_2045417260865528734[30] = 0.0;
   out_2045417260865528734[31] = 0.0;
   out_2045417260865528734[32] = 0.0;
   out_2045417260865528734[33] = 0.0;
   out_2045417260865528734[34] = 0.0;
   out_2045417260865528734[35] = 0.0;
   out_2045417260865528734[36] = 0.0;
   out_2045417260865528734[37] = 0.0;
   out_2045417260865528734[38] = 1.0;
   out_2045417260865528734[39] = 0.0;
   out_2045417260865528734[40] = 0.0;
   out_2045417260865528734[41] = 0.0;
   out_2045417260865528734[42] = 0.0;
   out_2045417260865528734[43] = 0.0;
   out_2045417260865528734[44] = 0.0;
   out_2045417260865528734[45] = 0.0;
   out_2045417260865528734[46] = 0.0;
   out_2045417260865528734[47] = 0.0;
   out_2045417260865528734[48] = 0.0;
   out_2045417260865528734[49] = 0.0;
   out_2045417260865528734[50] = 0.0;
   out_2045417260865528734[51] = 0.0;
   out_2045417260865528734[52] = 0.0;
   out_2045417260865528734[53] = 0.0;
   out_2045417260865528734[54] = 0.0;
   out_2045417260865528734[55] = 0.0;
   out_2045417260865528734[56] = 0.0;
   out_2045417260865528734[57] = 1.0;
   out_2045417260865528734[58] = 0.0;
   out_2045417260865528734[59] = 0.0;
   out_2045417260865528734[60] = 0.0;
   out_2045417260865528734[61] = 0.0;
   out_2045417260865528734[62] = 0.0;
   out_2045417260865528734[63] = 0.0;
   out_2045417260865528734[64] = 0.0;
   out_2045417260865528734[65] = 0.0;
   out_2045417260865528734[66] = 0.0;
   out_2045417260865528734[67] = 0.0;
   out_2045417260865528734[68] = 0.0;
   out_2045417260865528734[69] = 0.0;
   out_2045417260865528734[70] = 0.0;
   out_2045417260865528734[71] = 0.0;
   out_2045417260865528734[72] = 0.0;
   out_2045417260865528734[73] = 0.0;
   out_2045417260865528734[74] = 0.0;
   out_2045417260865528734[75] = 0.0;
   out_2045417260865528734[76] = 1.0;
   out_2045417260865528734[77] = 0.0;
   out_2045417260865528734[78] = 0.0;
   out_2045417260865528734[79] = 0.0;
   out_2045417260865528734[80] = 0.0;
   out_2045417260865528734[81] = 0.0;
   out_2045417260865528734[82] = 0.0;
   out_2045417260865528734[83] = 0.0;
   out_2045417260865528734[84] = 0.0;
   out_2045417260865528734[85] = 0.0;
   out_2045417260865528734[86] = 0.0;
   out_2045417260865528734[87] = 0.0;
   out_2045417260865528734[88] = 0.0;
   out_2045417260865528734[89] = 0.0;
   out_2045417260865528734[90] = 0.0;
   out_2045417260865528734[91] = 0.0;
   out_2045417260865528734[92] = 0.0;
   out_2045417260865528734[93] = 0.0;
   out_2045417260865528734[94] = 0.0;
   out_2045417260865528734[95] = 1.0;
   out_2045417260865528734[96] = 0.0;
   out_2045417260865528734[97] = 0.0;
   out_2045417260865528734[98] = 0.0;
   out_2045417260865528734[99] = 0.0;
   out_2045417260865528734[100] = 0.0;
   out_2045417260865528734[101] = 0.0;
   out_2045417260865528734[102] = 0.0;
   out_2045417260865528734[103] = 0.0;
   out_2045417260865528734[104] = 0.0;
   out_2045417260865528734[105] = 0.0;
   out_2045417260865528734[106] = 0.0;
   out_2045417260865528734[107] = 0.0;
   out_2045417260865528734[108] = 0.0;
   out_2045417260865528734[109] = 0.0;
   out_2045417260865528734[110] = 0.0;
   out_2045417260865528734[111] = 0.0;
   out_2045417260865528734[112] = 0.0;
   out_2045417260865528734[113] = 0.0;
   out_2045417260865528734[114] = 1.0;
   out_2045417260865528734[115] = 0.0;
   out_2045417260865528734[116] = 0.0;
   out_2045417260865528734[117] = 0.0;
   out_2045417260865528734[118] = 0.0;
   out_2045417260865528734[119] = 0.0;
   out_2045417260865528734[120] = 0.0;
   out_2045417260865528734[121] = 0.0;
   out_2045417260865528734[122] = 0.0;
   out_2045417260865528734[123] = 0.0;
   out_2045417260865528734[124] = 0.0;
   out_2045417260865528734[125] = 0.0;
   out_2045417260865528734[126] = 0.0;
   out_2045417260865528734[127] = 0.0;
   out_2045417260865528734[128] = 0.0;
   out_2045417260865528734[129] = 0.0;
   out_2045417260865528734[130] = 0.0;
   out_2045417260865528734[131] = 0.0;
   out_2045417260865528734[132] = 0.0;
   out_2045417260865528734[133] = 1.0;
   out_2045417260865528734[134] = 0.0;
   out_2045417260865528734[135] = 0.0;
   out_2045417260865528734[136] = 0.0;
   out_2045417260865528734[137] = 0.0;
   out_2045417260865528734[138] = 0.0;
   out_2045417260865528734[139] = 0.0;
   out_2045417260865528734[140] = 0.0;
   out_2045417260865528734[141] = 0.0;
   out_2045417260865528734[142] = 0.0;
   out_2045417260865528734[143] = 0.0;
   out_2045417260865528734[144] = 0.0;
   out_2045417260865528734[145] = 0.0;
   out_2045417260865528734[146] = 0.0;
   out_2045417260865528734[147] = 0.0;
   out_2045417260865528734[148] = 0.0;
   out_2045417260865528734[149] = 0.0;
   out_2045417260865528734[150] = 0.0;
   out_2045417260865528734[151] = 0.0;
   out_2045417260865528734[152] = 1.0;
   out_2045417260865528734[153] = 0.0;
   out_2045417260865528734[154] = 0.0;
   out_2045417260865528734[155] = 0.0;
   out_2045417260865528734[156] = 0.0;
   out_2045417260865528734[157] = 0.0;
   out_2045417260865528734[158] = 0.0;
   out_2045417260865528734[159] = 0.0;
   out_2045417260865528734[160] = 0.0;
   out_2045417260865528734[161] = 0.0;
   out_2045417260865528734[162] = 0.0;
   out_2045417260865528734[163] = 0.0;
   out_2045417260865528734[164] = 0.0;
   out_2045417260865528734[165] = 0.0;
   out_2045417260865528734[166] = 0.0;
   out_2045417260865528734[167] = 0.0;
   out_2045417260865528734[168] = 0.0;
   out_2045417260865528734[169] = 0.0;
   out_2045417260865528734[170] = 0.0;
   out_2045417260865528734[171] = 1.0;
   out_2045417260865528734[172] = 0.0;
   out_2045417260865528734[173] = 0.0;
   out_2045417260865528734[174] = 0.0;
   out_2045417260865528734[175] = 0.0;
   out_2045417260865528734[176] = 0.0;
   out_2045417260865528734[177] = 0.0;
   out_2045417260865528734[178] = 0.0;
   out_2045417260865528734[179] = 0.0;
   out_2045417260865528734[180] = 0.0;
   out_2045417260865528734[181] = 0.0;
   out_2045417260865528734[182] = 0.0;
   out_2045417260865528734[183] = 0.0;
   out_2045417260865528734[184] = 0.0;
   out_2045417260865528734[185] = 0.0;
   out_2045417260865528734[186] = 0.0;
   out_2045417260865528734[187] = 0.0;
   out_2045417260865528734[188] = 0.0;
   out_2045417260865528734[189] = 0.0;
   out_2045417260865528734[190] = 1.0;
   out_2045417260865528734[191] = 0.0;
   out_2045417260865528734[192] = 0.0;
   out_2045417260865528734[193] = 0.0;
   out_2045417260865528734[194] = 0.0;
   out_2045417260865528734[195] = 0.0;
   out_2045417260865528734[196] = 0.0;
   out_2045417260865528734[197] = 0.0;
   out_2045417260865528734[198] = 0.0;
   out_2045417260865528734[199] = 0.0;
   out_2045417260865528734[200] = 0.0;
   out_2045417260865528734[201] = 0.0;
   out_2045417260865528734[202] = 0.0;
   out_2045417260865528734[203] = 0.0;
   out_2045417260865528734[204] = 0.0;
   out_2045417260865528734[205] = 0.0;
   out_2045417260865528734[206] = 0.0;
   out_2045417260865528734[207] = 0.0;
   out_2045417260865528734[208] = 0.0;
   out_2045417260865528734[209] = 1.0;
   out_2045417260865528734[210] = 0.0;
   out_2045417260865528734[211] = 0.0;
   out_2045417260865528734[212] = 0.0;
   out_2045417260865528734[213] = 0.0;
   out_2045417260865528734[214] = 0.0;
   out_2045417260865528734[215] = 0.0;
   out_2045417260865528734[216] = 0.0;
   out_2045417260865528734[217] = 0.0;
   out_2045417260865528734[218] = 0.0;
   out_2045417260865528734[219] = 0.0;
   out_2045417260865528734[220] = 0.0;
   out_2045417260865528734[221] = 0.0;
   out_2045417260865528734[222] = 0.0;
   out_2045417260865528734[223] = 0.0;
   out_2045417260865528734[224] = 0.0;
   out_2045417260865528734[225] = 0.0;
   out_2045417260865528734[226] = 0.0;
   out_2045417260865528734[227] = 0.0;
   out_2045417260865528734[228] = 1.0;
   out_2045417260865528734[229] = 0.0;
   out_2045417260865528734[230] = 0.0;
   out_2045417260865528734[231] = 0.0;
   out_2045417260865528734[232] = 0.0;
   out_2045417260865528734[233] = 0.0;
   out_2045417260865528734[234] = 0.0;
   out_2045417260865528734[235] = 0.0;
   out_2045417260865528734[236] = 0.0;
   out_2045417260865528734[237] = 0.0;
   out_2045417260865528734[238] = 0.0;
   out_2045417260865528734[239] = 0.0;
   out_2045417260865528734[240] = 0.0;
   out_2045417260865528734[241] = 0.0;
   out_2045417260865528734[242] = 0.0;
   out_2045417260865528734[243] = 0.0;
   out_2045417260865528734[244] = 0.0;
   out_2045417260865528734[245] = 0.0;
   out_2045417260865528734[246] = 0.0;
   out_2045417260865528734[247] = 1.0;
   out_2045417260865528734[248] = 0.0;
   out_2045417260865528734[249] = 0.0;
   out_2045417260865528734[250] = 0.0;
   out_2045417260865528734[251] = 0.0;
   out_2045417260865528734[252] = 0.0;
   out_2045417260865528734[253] = 0.0;
   out_2045417260865528734[254] = 0.0;
   out_2045417260865528734[255] = 0.0;
   out_2045417260865528734[256] = 0.0;
   out_2045417260865528734[257] = 0.0;
   out_2045417260865528734[258] = 0.0;
   out_2045417260865528734[259] = 0.0;
   out_2045417260865528734[260] = 0.0;
   out_2045417260865528734[261] = 0.0;
   out_2045417260865528734[262] = 0.0;
   out_2045417260865528734[263] = 0.0;
   out_2045417260865528734[264] = 0.0;
   out_2045417260865528734[265] = 0.0;
   out_2045417260865528734[266] = 1.0;
   out_2045417260865528734[267] = 0.0;
   out_2045417260865528734[268] = 0.0;
   out_2045417260865528734[269] = 0.0;
   out_2045417260865528734[270] = 0.0;
   out_2045417260865528734[271] = 0.0;
   out_2045417260865528734[272] = 0.0;
   out_2045417260865528734[273] = 0.0;
   out_2045417260865528734[274] = 0.0;
   out_2045417260865528734[275] = 0.0;
   out_2045417260865528734[276] = 0.0;
   out_2045417260865528734[277] = 0.0;
   out_2045417260865528734[278] = 0.0;
   out_2045417260865528734[279] = 0.0;
   out_2045417260865528734[280] = 0.0;
   out_2045417260865528734[281] = 0.0;
   out_2045417260865528734[282] = 0.0;
   out_2045417260865528734[283] = 0.0;
   out_2045417260865528734[284] = 0.0;
   out_2045417260865528734[285] = 1.0;
   out_2045417260865528734[286] = 0.0;
   out_2045417260865528734[287] = 0.0;
   out_2045417260865528734[288] = 0.0;
   out_2045417260865528734[289] = 0.0;
   out_2045417260865528734[290] = 0.0;
   out_2045417260865528734[291] = 0.0;
   out_2045417260865528734[292] = 0.0;
   out_2045417260865528734[293] = 0.0;
   out_2045417260865528734[294] = 0.0;
   out_2045417260865528734[295] = 0.0;
   out_2045417260865528734[296] = 0.0;
   out_2045417260865528734[297] = 0.0;
   out_2045417260865528734[298] = 0.0;
   out_2045417260865528734[299] = 0.0;
   out_2045417260865528734[300] = 0.0;
   out_2045417260865528734[301] = 0.0;
   out_2045417260865528734[302] = 0.0;
   out_2045417260865528734[303] = 0.0;
   out_2045417260865528734[304] = 1.0;
   out_2045417260865528734[305] = 0.0;
   out_2045417260865528734[306] = 0.0;
   out_2045417260865528734[307] = 0.0;
   out_2045417260865528734[308] = 0.0;
   out_2045417260865528734[309] = 0.0;
   out_2045417260865528734[310] = 0.0;
   out_2045417260865528734[311] = 0.0;
   out_2045417260865528734[312] = 0.0;
   out_2045417260865528734[313] = 0.0;
   out_2045417260865528734[314] = 0.0;
   out_2045417260865528734[315] = 0.0;
   out_2045417260865528734[316] = 0.0;
   out_2045417260865528734[317] = 0.0;
   out_2045417260865528734[318] = 0.0;
   out_2045417260865528734[319] = 0.0;
   out_2045417260865528734[320] = 0.0;
   out_2045417260865528734[321] = 0.0;
   out_2045417260865528734[322] = 0.0;
   out_2045417260865528734[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_1001887333786351958) {
   out_1001887333786351958[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_1001887333786351958[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_1001887333786351958[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_1001887333786351958[3] = dt*state[12] + state[3];
   out_1001887333786351958[4] = dt*state[13] + state[4];
   out_1001887333786351958[5] = dt*state[14] + state[5];
   out_1001887333786351958[6] = state[6];
   out_1001887333786351958[7] = state[7];
   out_1001887333786351958[8] = state[8];
   out_1001887333786351958[9] = state[9];
   out_1001887333786351958[10] = state[10];
   out_1001887333786351958[11] = state[11];
   out_1001887333786351958[12] = state[12];
   out_1001887333786351958[13] = state[13];
   out_1001887333786351958[14] = state[14];
   out_1001887333786351958[15] = state[15];
   out_1001887333786351958[16] = state[16];
   out_1001887333786351958[17] = state[17];
}
void F_fun(double *state, double dt, double *out_7083458297094230765) {
   out_7083458297094230765[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7083458297094230765[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7083458297094230765[2] = 0;
   out_7083458297094230765[3] = 0;
   out_7083458297094230765[4] = 0;
   out_7083458297094230765[5] = 0;
   out_7083458297094230765[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7083458297094230765[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7083458297094230765[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_7083458297094230765[9] = 0;
   out_7083458297094230765[10] = 0;
   out_7083458297094230765[11] = 0;
   out_7083458297094230765[12] = 0;
   out_7083458297094230765[13] = 0;
   out_7083458297094230765[14] = 0;
   out_7083458297094230765[15] = 0;
   out_7083458297094230765[16] = 0;
   out_7083458297094230765[17] = 0;
   out_7083458297094230765[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7083458297094230765[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7083458297094230765[20] = 0;
   out_7083458297094230765[21] = 0;
   out_7083458297094230765[22] = 0;
   out_7083458297094230765[23] = 0;
   out_7083458297094230765[24] = 0;
   out_7083458297094230765[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7083458297094230765[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_7083458297094230765[27] = 0;
   out_7083458297094230765[28] = 0;
   out_7083458297094230765[29] = 0;
   out_7083458297094230765[30] = 0;
   out_7083458297094230765[31] = 0;
   out_7083458297094230765[32] = 0;
   out_7083458297094230765[33] = 0;
   out_7083458297094230765[34] = 0;
   out_7083458297094230765[35] = 0;
   out_7083458297094230765[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7083458297094230765[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7083458297094230765[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7083458297094230765[39] = 0;
   out_7083458297094230765[40] = 0;
   out_7083458297094230765[41] = 0;
   out_7083458297094230765[42] = 0;
   out_7083458297094230765[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7083458297094230765[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_7083458297094230765[45] = 0;
   out_7083458297094230765[46] = 0;
   out_7083458297094230765[47] = 0;
   out_7083458297094230765[48] = 0;
   out_7083458297094230765[49] = 0;
   out_7083458297094230765[50] = 0;
   out_7083458297094230765[51] = 0;
   out_7083458297094230765[52] = 0;
   out_7083458297094230765[53] = 0;
   out_7083458297094230765[54] = 0;
   out_7083458297094230765[55] = 0;
   out_7083458297094230765[56] = 0;
   out_7083458297094230765[57] = 1;
   out_7083458297094230765[58] = 0;
   out_7083458297094230765[59] = 0;
   out_7083458297094230765[60] = 0;
   out_7083458297094230765[61] = 0;
   out_7083458297094230765[62] = 0;
   out_7083458297094230765[63] = 0;
   out_7083458297094230765[64] = 0;
   out_7083458297094230765[65] = 0;
   out_7083458297094230765[66] = dt;
   out_7083458297094230765[67] = 0;
   out_7083458297094230765[68] = 0;
   out_7083458297094230765[69] = 0;
   out_7083458297094230765[70] = 0;
   out_7083458297094230765[71] = 0;
   out_7083458297094230765[72] = 0;
   out_7083458297094230765[73] = 0;
   out_7083458297094230765[74] = 0;
   out_7083458297094230765[75] = 0;
   out_7083458297094230765[76] = 1;
   out_7083458297094230765[77] = 0;
   out_7083458297094230765[78] = 0;
   out_7083458297094230765[79] = 0;
   out_7083458297094230765[80] = 0;
   out_7083458297094230765[81] = 0;
   out_7083458297094230765[82] = 0;
   out_7083458297094230765[83] = 0;
   out_7083458297094230765[84] = 0;
   out_7083458297094230765[85] = dt;
   out_7083458297094230765[86] = 0;
   out_7083458297094230765[87] = 0;
   out_7083458297094230765[88] = 0;
   out_7083458297094230765[89] = 0;
   out_7083458297094230765[90] = 0;
   out_7083458297094230765[91] = 0;
   out_7083458297094230765[92] = 0;
   out_7083458297094230765[93] = 0;
   out_7083458297094230765[94] = 0;
   out_7083458297094230765[95] = 1;
   out_7083458297094230765[96] = 0;
   out_7083458297094230765[97] = 0;
   out_7083458297094230765[98] = 0;
   out_7083458297094230765[99] = 0;
   out_7083458297094230765[100] = 0;
   out_7083458297094230765[101] = 0;
   out_7083458297094230765[102] = 0;
   out_7083458297094230765[103] = 0;
   out_7083458297094230765[104] = dt;
   out_7083458297094230765[105] = 0;
   out_7083458297094230765[106] = 0;
   out_7083458297094230765[107] = 0;
   out_7083458297094230765[108] = 0;
   out_7083458297094230765[109] = 0;
   out_7083458297094230765[110] = 0;
   out_7083458297094230765[111] = 0;
   out_7083458297094230765[112] = 0;
   out_7083458297094230765[113] = 0;
   out_7083458297094230765[114] = 1;
   out_7083458297094230765[115] = 0;
   out_7083458297094230765[116] = 0;
   out_7083458297094230765[117] = 0;
   out_7083458297094230765[118] = 0;
   out_7083458297094230765[119] = 0;
   out_7083458297094230765[120] = 0;
   out_7083458297094230765[121] = 0;
   out_7083458297094230765[122] = 0;
   out_7083458297094230765[123] = 0;
   out_7083458297094230765[124] = 0;
   out_7083458297094230765[125] = 0;
   out_7083458297094230765[126] = 0;
   out_7083458297094230765[127] = 0;
   out_7083458297094230765[128] = 0;
   out_7083458297094230765[129] = 0;
   out_7083458297094230765[130] = 0;
   out_7083458297094230765[131] = 0;
   out_7083458297094230765[132] = 0;
   out_7083458297094230765[133] = 1;
   out_7083458297094230765[134] = 0;
   out_7083458297094230765[135] = 0;
   out_7083458297094230765[136] = 0;
   out_7083458297094230765[137] = 0;
   out_7083458297094230765[138] = 0;
   out_7083458297094230765[139] = 0;
   out_7083458297094230765[140] = 0;
   out_7083458297094230765[141] = 0;
   out_7083458297094230765[142] = 0;
   out_7083458297094230765[143] = 0;
   out_7083458297094230765[144] = 0;
   out_7083458297094230765[145] = 0;
   out_7083458297094230765[146] = 0;
   out_7083458297094230765[147] = 0;
   out_7083458297094230765[148] = 0;
   out_7083458297094230765[149] = 0;
   out_7083458297094230765[150] = 0;
   out_7083458297094230765[151] = 0;
   out_7083458297094230765[152] = 1;
   out_7083458297094230765[153] = 0;
   out_7083458297094230765[154] = 0;
   out_7083458297094230765[155] = 0;
   out_7083458297094230765[156] = 0;
   out_7083458297094230765[157] = 0;
   out_7083458297094230765[158] = 0;
   out_7083458297094230765[159] = 0;
   out_7083458297094230765[160] = 0;
   out_7083458297094230765[161] = 0;
   out_7083458297094230765[162] = 0;
   out_7083458297094230765[163] = 0;
   out_7083458297094230765[164] = 0;
   out_7083458297094230765[165] = 0;
   out_7083458297094230765[166] = 0;
   out_7083458297094230765[167] = 0;
   out_7083458297094230765[168] = 0;
   out_7083458297094230765[169] = 0;
   out_7083458297094230765[170] = 0;
   out_7083458297094230765[171] = 1;
   out_7083458297094230765[172] = 0;
   out_7083458297094230765[173] = 0;
   out_7083458297094230765[174] = 0;
   out_7083458297094230765[175] = 0;
   out_7083458297094230765[176] = 0;
   out_7083458297094230765[177] = 0;
   out_7083458297094230765[178] = 0;
   out_7083458297094230765[179] = 0;
   out_7083458297094230765[180] = 0;
   out_7083458297094230765[181] = 0;
   out_7083458297094230765[182] = 0;
   out_7083458297094230765[183] = 0;
   out_7083458297094230765[184] = 0;
   out_7083458297094230765[185] = 0;
   out_7083458297094230765[186] = 0;
   out_7083458297094230765[187] = 0;
   out_7083458297094230765[188] = 0;
   out_7083458297094230765[189] = 0;
   out_7083458297094230765[190] = 1;
   out_7083458297094230765[191] = 0;
   out_7083458297094230765[192] = 0;
   out_7083458297094230765[193] = 0;
   out_7083458297094230765[194] = 0;
   out_7083458297094230765[195] = 0;
   out_7083458297094230765[196] = 0;
   out_7083458297094230765[197] = 0;
   out_7083458297094230765[198] = 0;
   out_7083458297094230765[199] = 0;
   out_7083458297094230765[200] = 0;
   out_7083458297094230765[201] = 0;
   out_7083458297094230765[202] = 0;
   out_7083458297094230765[203] = 0;
   out_7083458297094230765[204] = 0;
   out_7083458297094230765[205] = 0;
   out_7083458297094230765[206] = 0;
   out_7083458297094230765[207] = 0;
   out_7083458297094230765[208] = 0;
   out_7083458297094230765[209] = 1;
   out_7083458297094230765[210] = 0;
   out_7083458297094230765[211] = 0;
   out_7083458297094230765[212] = 0;
   out_7083458297094230765[213] = 0;
   out_7083458297094230765[214] = 0;
   out_7083458297094230765[215] = 0;
   out_7083458297094230765[216] = 0;
   out_7083458297094230765[217] = 0;
   out_7083458297094230765[218] = 0;
   out_7083458297094230765[219] = 0;
   out_7083458297094230765[220] = 0;
   out_7083458297094230765[221] = 0;
   out_7083458297094230765[222] = 0;
   out_7083458297094230765[223] = 0;
   out_7083458297094230765[224] = 0;
   out_7083458297094230765[225] = 0;
   out_7083458297094230765[226] = 0;
   out_7083458297094230765[227] = 0;
   out_7083458297094230765[228] = 1;
   out_7083458297094230765[229] = 0;
   out_7083458297094230765[230] = 0;
   out_7083458297094230765[231] = 0;
   out_7083458297094230765[232] = 0;
   out_7083458297094230765[233] = 0;
   out_7083458297094230765[234] = 0;
   out_7083458297094230765[235] = 0;
   out_7083458297094230765[236] = 0;
   out_7083458297094230765[237] = 0;
   out_7083458297094230765[238] = 0;
   out_7083458297094230765[239] = 0;
   out_7083458297094230765[240] = 0;
   out_7083458297094230765[241] = 0;
   out_7083458297094230765[242] = 0;
   out_7083458297094230765[243] = 0;
   out_7083458297094230765[244] = 0;
   out_7083458297094230765[245] = 0;
   out_7083458297094230765[246] = 0;
   out_7083458297094230765[247] = 1;
   out_7083458297094230765[248] = 0;
   out_7083458297094230765[249] = 0;
   out_7083458297094230765[250] = 0;
   out_7083458297094230765[251] = 0;
   out_7083458297094230765[252] = 0;
   out_7083458297094230765[253] = 0;
   out_7083458297094230765[254] = 0;
   out_7083458297094230765[255] = 0;
   out_7083458297094230765[256] = 0;
   out_7083458297094230765[257] = 0;
   out_7083458297094230765[258] = 0;
   out_7083458297094230765[259] = 0;
   out_7083458297094230765[260] = 0;
   out_7083458297094230765[261] = 0;
   out_7083458297094230765[262] = 0;
   out_7083458297094230765[263] = 0;
   out_7083458297094230765[264] = 0;
   out_7083458297094230765[265] = 0;
   out_7083458297094230765[266] = 1;
   out_7083458297094230765[267] = 0;
   out_7083458297094230765[268] = 0;
   out_7083458297094230765[269] = 0;
   out_7083458297094230765[270] = 0;
   out_7083458297094230765[271] = 0;
   out_7083458297094230765[272] = 0;
   out_7083458297094230765[273] = 0;
   out_7083458297094230765[274] = 0;
   out_7083458297094230765[275] = 0;
   out_7083458297094230765[276] = 0;
   out_7083458297094230765[277] = 0;
   out_7083458297094230765[278] = 0;
   out_7083458297094230765[279] = 0;
   out_7083458297094230765[280] = 0;
   out_7083458297094230765[281] = 0;
   out_7083458297094230765[282] = 0;
   out_7083458297094230765[283] = 0;
   out_7083458297094230765[284] = 0;
   out_7083458297094230765[285] = 1;
   out_7083458297094230765[286] = 0;
   out_7083458297094230765[287] = 0;
   out_7083458297094230765[288] = 0;
   out_7083458297094230765[289] = 0;
   out_7083458297094230765[290] = 0;
   out_7083458297094230765[291] = 0;
   out_7083458297094230765[292] = 0;
   out_7083458297094230765[293] = 0;
   out_7083458297094230765[294] = 0;
   out_7083458297094230765[295] = 0;
   out_7083458297094230765[296] = 0;
   out_7083458297094230765[297] = 0;
   out_7083458297094230765[298] = 0;
   out_7083458297094230765[299] = 0;
   out_7083458297094230765[300] = 0;
   out_7083458297094230765[301] = 0;
   out_7083458297094230765[302] = 0;
   out_7083458297094230765[303] = 0;
   out_7083458297094230765[304] = 1;
   out_7083458297094230765[305] = 0;
   out_7083458297094230765[306] = 0;
   out_7083458297094230765[307] = 0;
   out_7083458297094230765[308] = 0;
   out_7083458297094230765[309] = 0;
   out_7083458297094230765[310] = 0;
   out_7083458297094230765[311] = 0;
   out_7083458297094230765[312] = 0;
   out_7083458297094230765[313] = 0;
   out_7083458297094230765[314] = 0;
   out_7083458297094230765[315] = 0;
   out_7083458297094230765[316] = 0;
   out_7083458297094230765[317] = 0;
   out_7083458297094230765[318] = 0;
   out_7083458297094230765[319] = 0;
   out_7083458297094230765[320] = 0;
   out_7083458297094230765[321] = 0;
   out_7083458297094230765[322] = 0;
   out_7083458297094230765[323] = 1;
}
void h_4(double *state, double *unused, double *out_8007441403531526269) {
   out_8007441403531526269[0] = state[6] + state[9];
   out_8007441403531526269[1] = state[7] + state[10];
   out_8007441403531526269[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_989904710527973009) {
   out_989904710527973009[0] = 0;
   out_989904710527973009[1] = 0;
   out_989904710527973009[2] = 0;
   out_989904710527973009[3] = 0;
   out_989904710527973009[4] = 0;
   out_989904710527973009[5] = 0;
   out_989904710527973009[6] = 1;
   out_989904710527973009[7] = 0;
   out_989904710527973009[8] = 0;
   out_989904710527973009[9] = 1;
   out_989904710527973009[10] = 0;
   out_989904710527973009[11] = 0;
   out_989904710527973009[12] = 0;
   out_989904710527973009[13] = 0;
   out_989904710527973009[14] = 0;
   out_989904710527973009[15] = 0;
   out_989904710527973009[16] = 0;
   out_989904710527973009[17] = 0;
   out_989904710527973009[18] = 0;
   out_989904710527973009[19] = 0;
   out_989904710527973009[20] = 0;
   out_989904710527973009[21] = 0;
   out_989904710527973009[22] = 0;
   out_989904710527973009[23] = 0;
   out_989904710527973009[24] = 0;
   out_989904710527973009[25] = 1;
   out_989904710527973009[26] = 0;
   out_989904710527973009[27] = 0;
   out_989904710527973009[28] = 1;
   out_989904710527973009[29] = 0;
   out_989904710527973009[30] = 0;
   out_989904710527973009[31] = 0;
   out_989904710527973009[32] = 0;
   out_989904710527973009[33] = 0;
   out_989904710527973009[34] = 0;
   out_989904710527973009[35] = 0;
   out_989904710527973009[36] = 0;
   out_989904710527973009[37] = 0;
   out_989904710527973009[38] = 0;
   out_989904710527973009[39] = 0;
   out_989904710527973009[40] = 0;
   out_989904710527973009[41] = 0;
   out_989904710527973009[42] = 0;
   out_989904710527973009[43] = 0;
   out_989904710527973009[44] = 1;
   out_989904710527973009[45] = 0;
   out_989904710527973009[46] = 0;
   out_989904710527973009[47] = 1;
   out_989904710527973009[48] = 0;
   out_989904710527973009[49] = 0;
   out_989904710527973009[50] = 0;
   out_989904710527973009[51] = 0;
   out_989904710527973009[52] = 0;
   out_989904710527973009[53] = 0;
}
void h_10(double *state, double *unused, double *out_781128545146885635) {
   out_781128545146885635[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_781128545146885635[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_781128545146885635[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_2086425279933156357) {
   out_2086425279933156357[0] = 0;
   out_2086425279933156357[1] = 9.8100000000000005*cos(state[1]);
   out_2086425279933156357[2] = 0;
   out_2086425279933156357[3] = 0;
   out_2086425279933156357[4] = -state[8];
   out_2086425279933156357[5] = state[7];
   out_2086425279933156357[6] = 0;
   out_2086425279933156357[7] = state[5];
   out_2086425279933156357[8] = -state[4];
   out_2086425279933156357[9] = 0;
   out_2086425279933156357[10] = 0;
   out_2086425279933156357[11] = 0;
   out_2086425279933156357[12] = 1;
   out_2086425279933156357[13] = 0;
   out_2086425279933156357[14] = 0;
   out_2086425279933156357[15] = 1;
   out_2086425279933156357[16] = 0;
   out_2086425279933156357[17] = 0;
   out_2086425279933156357[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_2086425279933156357[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_2086425279933156357[20] = 0;
   out_2086425279933156357[21] = state[8];
   out_2086425279933156357[22] = 0;
   out_2086425279933156357[23] = -state[6];
   out_2086425279933156357[24] = -state[5];
   out_2086425279933156357[25] = 0;
   out_2086425279933156357[26] = state[3];
   out_2086425279933156357[27] = 0;
   out_2086425279933156357[28] = 0;
   out_2086425279933156357[29] = 0;
   out_2086425279933156357[30] = 0;
   out_2086425279933156357[31] = 1;
   out_2086425279933156357[32] = 0;
   out_2086425279933156357[33] = 0;
   out_2086425279933156357[34] = 1;
   out_2086425279933156357[35] = 0;
   out_2086425279933156357[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_2086425279933156357[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_2086425279933156357[38] = 0;
   out_2086425279933156357[39] = -state[7];
   out_2086425279933156357[40] = state[6];
   out_2086425279933156357[41] = 0;
   out_2086425279933156357[42] = state[4];
   out_2086425279933156357[43] = -state[3];
   out_2086425279933156357[44] = 0;
   out_2086425279933156357[45] = 0;
   out_2086425279933156357[46] = 0;
   out_2086425279933156357[47] = 0;
   out_2086425279933156357[48] = 0;
   out_2086425279933156357[49] = 0;
   out_2086425279933156357[50] = 1;
   out_2086425279933156357[51] = 0;
   out_2086425279933156357[52] = 0;
   out_2086425279933156357[53] = 1;
}
void h_13(double *state, double *unused, double *out_2650077392226112998) {
   out_2650077392226112998[0] = state[3];
   out_2650077392226112998[1] = state[4];
   out_2650077392226112998[2] = state[5];
}
void H_13(double *state, double *unused, double *out_4202178535860305810) {
   out_4202178535860305810[0] = 0;
   out_4202178535860305810[1] = 0;
   out_4202178535860305810[2] = 0;
   out_4202178535860305810[3] = 1;
   out_4202178535860305810[4] = 0;
   out_4202178535860305810[5] = 0;
   out_4202178535860305810[6] = 0;
   out_4202178535860305810[7] = 0;
   out_4202178535860305810[8] = 0;
   out_4202178535860305810[9] = 0;
   out_4202178535860305810[10] = 0;
   out_4202178535860305810[11] = 0;
   out_4202178535860305810[12] = 0;
   out_4202178535860305810[13] = 0;
   out_4202178535860305810[14] = 0;
   out_4202178535860305810[15] = 0;
   out_4202178535860305810[16] = 0;
   out_4202178535860305810[17] = 0;
   out_4202178535860305810[18] = 0;
   out_4202178535860305810[19] = 0;
   out_4202178535860305810[20] = 0;
   out_4202178535860305810[21] = 0;
   out_4202178535860305810[22] = 1;
   out_4202178535860305810[23] = 0;
   out_4202178535860305810[24] = 0;
   out_4202178535860305810[25] = 0;
   out_4202178535860305810[26] = 0;
   out_4202178535860305810[27] = 0;
   out_4202178535860305810[28] = 0;
   out_4202178535860305810[29] = 0;
   out_4202178535860305810[30] = 0;
   out_4202178535860305810[31] = 0;
   out_4202178535860305810[32] = 0;
   out_4202178535860305810[33] = 0;
   out_4202178535860305810[34] = 0;
   out_4202178535860305810[35] = 0;
   out_4202178535860305810[36] = 0;
   out_4202178535860305810[37] = 0;
   out_4202178535860305810[38] = 0;
   out_4202178535860305810[39] = 0;
   out_4202178535860305810[40] = 0;
   out_4202178535860305810[41] = 1;
   out_4202178535860305810[42] = 0;
   out_4202178535860305810[43] = 0;
   out_4202178535860305810[44] = 0;
   out_4202178535860305810[45] = 0;
   out_4202178535860305810[46] = 0;
   out_4202178535860305810[47] = 0;
   out_4202178535860305810[48] = 0;
   out_4202178535860305810[49] = 0;
   out_4202178535860305810[50] = 0;
   out_4202178535860305810[51] = 0;
   out_4202178535860305810[52] = 0;
   out_4202178535860305810[53] = 0;
}
void h_14(double *state, double *unused, double *out_7818811588763480757) {
   out_7818811588763480757[0] = state[6];
   out_7818811588763480757[1] = state[7];
   out_7818811588763480757[2] = state[8];
}
void H_14(double *state, double *unused, double *out_4953145566867457538) {
   out_4953145566867457538[0] = 0;
   out_4953145566867457538[1] = 0;
   out_4953145566867457538[2] = 0;
   out_4953145566867457538[3] = 0;
   out_4953145566867457538[4] = 0;
   out_4953145566867457538[5] = 0;
   out_4953145566867457538[6] = 1;
   out_4953145566867457538[7] = 0;
   out_4953145566867457538[8] = 0;
   out_4953145566867457538[9] = 0;
   out_4953145566867457538[10] = 0;
   out_4953145566867457538[11] = 0;
   out_4953145566867457538[12] = 0;
   out_4953145566867457538[13] = 0;
   out_4953145566867457538[14] = 0;
   out_4953145566867457538[15] = 0;
   out_4953145566867457538[16] = 0;
   out_4953145566867457538[17] = 0;
   out_4953145566867457538[18] = 0;
   out_4953145566867457538[19] = 0;
   out_4953145566867457538[20] = 0;
   out_4953145566867457538[21] = 0;
   out_4953145566867457538[22] = 0;
   out_4953145566867457538[23] = 0;
   out_4953145566867457538[24] = 0;
   out_4953145566867457538[25] = 1;
   out_4953145566867457538[26] = 0;
   out_4953145566867457538[27] = 0;
   out_4953145566867457538[28] = 0;
   out_4953145566867457538[29] = 0;
   out_4953145566867457538[30] = 0;
   out_4953145566867457538[31] = 0;
   out_4953145566867457538[32] = 0;
   out_4953145566867457538[33] = 0;
   out_4953145566867457538[34] = 0;
   out_4953145566867457538[35] = 0;
   out_4953145566867457538[36] = 0;
   out_4953145566867457538[37] = 0;
   out_4953145566867457538[38] = 0;
   out_4953145566867457538[39] = 0;
   out_4953145566867457538[40] = 0;
   out_4953145566867457538[41] = 0;
   out_4953145566867457538[42] = 0;
   out_4953145566867457538[43] = 0;
   out_4953145566867457538[44] = 1;
   out_4953145566867457538[45] = 0;
   out_4953145566867457538[46] = 0;
   out_4953145566867457538[47] = 0;
   out_4953145566867457538[48] = 0;
   out_4953145566867457538[49] = 0;
   out_4953145566867457538[50] = 0;
   out_4953145566867457538[51] = 0;
   out_4953145566867457538[52] = 0;
   out_4953145566867457538[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_1700850028159621162) {
  err_fun(nom_x, delta_x, out_1700850028159621162);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_3416595063278262141) {
  inv_err_fun(nom_x, true_x, out_3416595063278262141);
}
void pose_H_mod_fun(double *state, double *out_2045417260865528734) {
  H_mod_fun(state, out_2045417260865528734);
}
void pose_f_fun(double *state, double dt, double *out_1001887333786351958) {
  f_fun(state,  dt, out_1001887333786351958);
}
void pose_F_fun(double *state, double dt, double *out_7083458297094230765) {
  F_fun(state,  dt, out_7083458297094230765);
}
void pose_h_4(double *state, double *unused, double *out_8007441403531526269) {
  h_4(state, unused, out_8007441403531526269);
}
void pose_H_4(double *state, double *unused, double *out_989904710527973009) {
  H_4(state, unused, out_989904710527973009);
}
void pose_h_10(double *state, double *unused, double *out_781128545146885635) {
  h_10(state, unused, out_781128545146885635);
}
void pose_H_10(double *state, double *unused, double *out_2086425279933156357) {
  H_10(state, unused, out_2086425279933156357);
}
void pose_h_13(double *state, double *unused, double *out_2650077392226112998) {
  h_13(state, unused, out_2650077392226112998);
}
void pose_H_13(double *state, double *unused, double *out_4202178535860305810) {
  H_13(state, unused, out_4202178535860305810);
}
void pose_h_14(double *state, double *unused, double *out_7818811588763480757) {
  h_14(state, unused, out_7818811588763480757);
}
void pose_H_14(double *state, double *unused, double *out_4953145566867457538) {
  H_14(state, unused, out_4953145566867457538);
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
