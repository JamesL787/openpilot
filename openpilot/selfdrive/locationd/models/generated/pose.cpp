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
void err_fun(double *nom_x, double *delta_x, double *out_1063797637258796766) {
   out_1063797637258796766[0] = delta_x[0] + nom_x[0];
   out_1063797637258796766[1] = delta_x[1] + nom_x[1];
   out_1063797637258796766[2] = delta_x[2] + nom_x[2];
   out_1063797637258796766[3] = delta_x[3] + nom_x[3];
   out_1063797637258796766[4] = delta_x[4] + nom_x[4];
   out_1063797637258796766[5] = delta_x[5] + nom_x[5];
   out_1063797637258796766[6] = delta_x[6] + nom_x[6];
   out_1063797637258796766[7] = delta_x[7] + nom_x[7];
   out_1063797637258796766[8] = delta_x[8] + nom_x[8];
   out_1063797637258796766[9] = delta_x[9] + nom_x[9];
   out_1063797637258796766[10] = delta_x[10] + nom_x[10];
   out_1063797637258796766[11] = delta_x[11] + nom_x[11];
   out_1063797637258796766[12] = delta_x[12] + nom_x[12];
   out_1063797637258796766[13] = delta_x[13] + nom_x[13];
   out_1063797637258796766[14] = delta_x[14] + nom_x[14];
   out_1063797637258796766[15] = delta_x[15] + nom_x[15];
   out_1063797637258796766[16] = delta_x[16] + nom_x[16];
   out_1063797637258796766[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_5886317630058333046) {
   out_5886317630058333046[0] = -nom_x[0] + true_x[0];
   out_5886317630058333046[1] = -nom_x[1] + true_x[1];
   out_5886317630058333046[2] = -nom_x[2] + true_x[2];
   out_5886317630058333046[3] = -nom_x[3] + true_x[3];
   out_5886317630058333046[4] = -nom_x[4] + true_x[4];
   out_5886317630058333046[5] = -nom_x[5] + true_x[5];
   out_5886317630058333046[6] = -nom_x[6] + true_x[6];
   out_5886317630058333046[7] = -nom_x[7] + true_x[7];
   out_5886317630058333046[8] = -nom_x[8] + true_x[8];
   out_5886317630058333046[9] = -nom_x[9] + true_x[9];
   out_5886317630058333046[10] = -nom_x[10] + true_x[10];
   out_5886317630058333046[11] = -nom_x[11] + true_x[11];
   out_5886317630058333046[12] = -nom_x[12] + true_x[12];
   out_5886317630058333046[13] = -nom_x[13] + true_x[13];
   out_5886317630058333046[14] = -nom_x[14] + true_x[14];
   out_5886317630058333046[15] = -nom_x[15] + true_x[15];
   out_5886317630058333046[16] = -nom_x[16] + true_x[16];
   out_5886317630058333046[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_9034902037276537918) {
   out_9034902037276537918[0] = 1.0;
   out_9034902037276537918[1] = 0.0;
   out_9034902037276537918[2] = 0.0;
   out_9034902037276537918[3] = 0.0;
   out_9034902037276537918[4] = 0.0;
   out_9034902037276537918[5] = 0.0;
   out_9034902037276537918[6] = 0.0;
   out_9034902037276537918[7] = 0.0;
   out_9034902037276537918[8] = 0.0;
   out_9034902037276537918[9] = 0.0;
   out_9034902037276537918[10] = 0.0;
   out_9034902037276537918[11] = 0.0;
   out_9034902037276537918[12] = 0.0;
   out_9034902037276537918[13] = 0.0;
   out_9034902037276537918[14] = 0.0;
   out_9034902037276537918[15] = 0.0;
   out_9034902037276537918[16] = 0.0;
   out_9034902037276537918[17] = 0.0;
   out_9034902037276537918[18] = 0.0;
   out_9034902037276537918[19] = 1.0;
   out_9034902037276537918[20] = 0.0;
   out_9034902037276537918[21] = 0.0;
   out_9034902037276537918[22] = 0.0;
   out_9034902037276537918[23] = 0.0;
   out_9034902037276537918[24] = 0.0;
   out_9034902037276537918[25] = 0.0;
   out_9034902037276537918[26] = 0.0;
   out_9034902037276537918[27] = 0.0;
   out_9034902037276537918[28] = 0.0;
   out_9034902037276537918[29] = 0.0;
   out_9034902037276537918[30] = 0.0;
   out_9034902037276537918[31] = 0.0;
   out_9034902037276537918[32] = 0.0;
   out_9034902037276537918[33] = 0.0;
   out_9034902037276537918[34] = 0.0;
   out_9034902037276537918[35] = 0.0;
   out_9034902037276537918[36] = 0.0;
   out_9034902037276537918[37] = 0.0;
   out_9034902037276537918[38] = 1.0;
   out_9034902037276537918[39] = 0.0;
   out_9034902037276537918[40] = 0.0;
   out_9034902037276537918[41] = 0.0;
   out_9034902037276537918[42] = 0.0;
   out_9034902037276537918[43] = 0.0;
   out_9034902037276537918[44] = 0.0;
   out_9034902037276537918[45] = 0.0;
   out_9034902037276537918[46] = 0.0;
   out_9034902037276537918[47] = 0.0;
   out_9034902037276537918[48] = 0.0;
   out_9034902037276537918[49] = 0.0;
   out_9034902037276537918[50] = 0.0;
   out_9034902037276537918[51] = 0.0;
   out_9034902037276537918[52] = 0.0;
   out_9034902037276537918[53] = 0.0;
   out_9034902037276537918[54] = 0.0;
   out_9034902037276537918[55] = 0.0;
   out_9034902037276537918[56] = 0.0;
   out_9034902037276537918[57] = 1.0;
   out_9034902037276537918[58] = 0.0;
   out_9034902037276537918[59] = 0.0;
   out_9034902037276537918[60] = 0.0;
   out_9034902037276537918[61] = 0.0;
   out_9034902037276537918[62] = 0.0;
   out_9034902037276537918[63] = 0.0;
   out_9034902037276537918[64] = 0.0;
   out_9034902037276537918[65] = 0.0;
   out_9034902037276537918[66] = 0.0;
   out_9034902037276537918[67] = 0.0;
   out_9034902037276537918[68] = 0.0;
   out_9034902037276537918[69] = 0.0;
   out_9034902037276537918[70] = 0.0;
   out_9034902037276537918[71] = 0.0;
   out_9034902037276537918[72] = 0.0;
   out_9034902037276537918[73] = 0.0;
   out_9034902037276537918[74] = 0.0;
   out_9034902037276537918[75] = 0.0;
   out_9034902037276537918[76] = 1.0;
   out_9034902037276537918[77] = 0.0;
   out_9034902037276537918[78] = 0.0;
   out_9034902037276537918[79] = 0.0;
   out_9034902037276537918[80] = 0.0;
   out_9034902037276537918[81] = 0.0;
   out_9034902037276537918[82] = 0.0;
   out_9034902037276537918[83] = 0.0;
   out_9034902037276537918[84] = 0.0;
   out_9034902037276537918[85] = 0.0;
   out_9034902037276537918[86] = 0.0;
   out_9034902037276537918[87] = 0.0;
   out_9034902037276537918[88] = 0.0;
   out_9034902037276537918[89] = 0.0;
   out_9034902037276537918[90] = 0.0;
   out_9034902037276537918[91] = 0.0;
   out_9034902037276537918[92] = 0.0;
   out_9034902037276537918[93] = 0.0;
   out_9034902037276537918[94] = 0.0;
   out_9034902037276537918[95] = 1.0;
   out_9034902037276537918[96] = 0.0;
   out_9034902037276537918[97] = 0.0;
   out_9034902037276537918[98] = 0.0;
   out_9034902037276537918[99] = 0.0;
   out_9034902037276537918[100] = 0.0;
   out_9034902037276537918[101] = 0.0;
   out_9034902037276537918[102] = 0.0;
   out_9034902037276537918[103] = 0.0;
   out_9034902037276537918[104] = 0.0;
   out_9034902037276537918[105] = 0.0;
   out_9034902037276537918[106] = 0.0;
   out_9034902037276537918[107] = 0.0;
   out_9034902037276537918[108] = 0.0;
   out_9034902037276537918[109] = 0.0;
   out_9034902037276537918[110] = 0.0;
   out_9034902037276537918[111] = 0.0;
   out_9034902037276537918[112] = 0.0;
   out_9034902037276537918[113] = 0.0;
   out_9034902037276537918[114] = 1.0;
   out_9034902037276537918[115] = 0.0;
   out_9034902037276537918[116] = 0.0;
   out_9034902037276537918[117] = 0.0;
   out_9034902037276537918[118] = 0.0;
   out_9034902037276537918[119] = 0.0;
   out_9034902037276537918[120] = 0.0;
   out_9034902037276537918[121] = 0.0;
   out_9034902037276537918[122] = 0.0;
   out_9034902037276537918[123] = 0.0;
   out_9034902037276537918[124] = 0.0;
   out_9034902037276537918[125] = 0.0;
   out_9034902037276537918[126] = 0.0;
   out_9034902037276537918[127] = 0.0;
   out_9034902037276537918[128] = 0.0;
   out_9034902037276537918[129] = 0.0;
   out_9034902037276537918[130] = 0.0;
   out_9034902037276537918[131] = 0.0;
   out_9034902037276537918[132] = 0.0;
   out_9034902037276537918[133] = 1.0;
   out_9034902037276537918[134] = 0.0;
   out_9034902037276537918[135] = 0.0;
   out_9034902037276537918[136] = 0.0;
   out_9034902037276537918[137] = 0.0;
   out_9034902037276537918[138] = 0.0;
   out_9034902037276537918[139] = 0.0;
   out_9034902037276537918[140] = 0.0;
   out_9034902037276537918[141] = 0.0;
   out_9034902037276537918[142] = 0.0;
   out_9034902037276537918[143] = 0.0;
   out_9034902037276537918[144] = 0.0;
   out_9034902037276537918[145] = 0.0;
   out_9034902037276537918[146] = 0.0;
   out_9034902037276537918[147] = 0.0;
   out_9034902037276537918[148] = 0.0;
   out_9034902037276537918[149] = 0.0;
   out_9034902037276537918[150] = 0.0;
   out_9034902037276537918[151] = 0.0;
   out_9034902037276537918[152] = 1.0;
   out_9034902037276537918[153] = 0.0;
   out_9034902037276537918[154] = 0.0;
   out_9034902037276537918[155] = 0.0;
   out_9034902037276537918[156] = 0.0;
   out_9034902037276537918[157] = 0.0;
   out_9034902037276537918[158] = 0.0;
   out_9034902037276537918[159] = 0.0;
   out_9034902037276537918[160] = 0.0;
   out_9034902037276537918[161] = 0.0;
   out_9034902037276537918[162] = 0.0;
   out_9034902037276537918[163] = 0.0;
   out_9034902037276537918[164] = 0.0;
   out_9034902037276537918[165] = 0.0;
   out_9034902037276537918[166] = 0.0;
   out_9034902037276537918[167] = 0.0;
   out_9034902037276537918[168] = 0.0;
   out_9034902037276537918[169] = 0.0;
   out_9034902037276537918[170] = 0.0;
   out_9034902037276537918[171] = 1.0;
   out_9034902037276537918[172] = 0.0;
   out_9034902037276537918[173] = 0.0;
   out_9034902037276537918[174] = 0.0;
   out_9034902037276537918[175] = 0.0;
   out_9034902037276537918[176] = 0.0;
   out_9034902037276537918[177] = 0.0;
   out_9034902037276537918[178] = 0.0;
   out_9034902037276537918[179] = 0.0;
   out_9034902037276537918[180] = 0.0;
   out_9034902037276537918[181] = 0.0;
   out_9034902037276537918[182] = 0.0;
   out_9034902037276537918[183] = 0.0;
   out_9034902037276537918[184] = 0.0;
   out_9034902037276537918[185] = 0.0;
   out_9034902037276537918[186] = 0.0;
   out_9034902037276537918[187] = 0.0;
   out_9034902037276537918[188] = 0.0;
   out_9034902037276537918[189] = 0.0;
   out_9034902037276537918[190] = 1.0;
   out_9034902037276537918[191] = 0.0;
   out_9034902037276537918[192] = 0.0;
   out_9034902037276537918[193] = 0.0;
   out_9034902037276537918[194] = 0.0;
   out_9034902037276537918[195] = 0.0;
   out_9034902037276537918[196] = 0.0;
   out_9034902037276537918[197] = 0.0;
   out_9034902037276537918[198] = 0.0;
   out_9034902037276537918[199] = 0.0;
   out_9034902037276537918[200] = 0.0;
   out_9034902037276537918[201] = 0.0;
   out_9034902037276537918[202] = 0.0;
   out_9034902037276537918[203] = 0.0;
   out_9034902037276537918[204] = 0.0;
   out_9034902037276537918[205] = 0.0;
   out_9034902037276537918[206] = 0.0;
   out_9034902037276537918[207] = 0.0;
   out_9034902037276537918[208] = 0.0;
   out_9034902037276537918[209] = 1.0;
   out_9034902037276537918[210] = 0.0;
   out_9034902037276537918[211] = 0.0;
   out_9034902037276537918[212] = 0.0;
   out_9034902037276537918[213] = 0.0;
   out_9034902037276537918[214] = 0.0;
   out_9034902037276537918[215] = 0.0;
   out_9034902037276537918[216] = 0.0;
   out_9034902037276537918[217] = 0.0;
   out_9034902037276537918[218] = 0.0;
   out_9034902037276537918[219] = 0.0;
   out_9034902037276537918[220] = 0.0;
   out_9034902037276537918[221] = 0.0;
   out_9034902037276537918[222] = 0.0;
   out_9034902037276537918[223] = 0.0;
   out_9034902037276537918[224] = 0.0;
   out_9034902037276537918[225] = 0.0;
   out_9034902037276537918[226] = 0.0;
   out_9034902037276537918[227] = 0.0;
   out_9034902037276537918[228] = 1.0;
   out_9034902037276537918[229] = 0.0;
   out_9034902037276537918[230] = 0.0;
   out_9034902037276537918[231] = 0.0;
   out_9034902037276537918[232] = 0.0;
   out_9034902037276537918[233] = 0.0;
   out_9034902037276537918[234] = 0.0;
   out_9034902037276537918[235] = 0.0;
   out_9034902037276537918[236] = 0.0;
   out_9034902037276537918[237] = 0.0;
   out_9034902037276537918[238] = 0.0;
   out_9034902037276537918[239] = 0.0;
   out_9034902037276537918[240] = 0.0;
   out_9034902037276537918[241] = 0.0;
   out_9034902037276537918[242] = 0.0;
   out_9034902037276537918[243] = 0.0;
   out_9034902037276537918[244] = 0.0;
   out_9034902037276537918[245] = 0.0;
   out_9034902037276537918[246] = 0.0;
   out_9034902037276537918[247] = 1.0;
   out_9034902037276537918[248] = 0.0;
   out_9034902037276537918[249] = 0.0;
   out_9034902037276537918[250] = 0.0;
   out_9034902037276537918[251] = 0.0;
   out_9034902037276537918[252] = 0.0;
   out_9034902037276537918[253] = 0.0;
   out_9034902037276537918[254] = 0.0;
   out_9034902037276537918[255] = 0.0;
   out_9034902037276537918[256] = 0.0;
   out_9034902037276537918[257] = 0.0;
   out_9034902037276537918[258] = 0.0;
   out_9034902037276537918[259] = 0.0;
   out_9034902037276537918[260] = 0.0;
   out_9034902037276537918[261] = 0.0;
   out_9034902037276537918[262] = 0.0;
   out_9034902037276537918[263] = 0.0;
   out_9034902037276537918[264] = 0.0;
   out_9034902037276537918[265] = 0.0;
   out_9034902037276537918[266] = 1.0;
   out_9034902037276537918[267] = 0.0;
   out_9034902037276537918[268] = 0.0;
   out_9034902037276537918[269] = 0.0;
   out_9034902037276537918[270] = 0.0;
   out_9034902037276537918[271] = 0.0;
   out_9034902037276537918[272] = 0.0;
   out_9034902037276537918[273] = 0.0;
   out_9034902037276537918[274] = 0.0;
   out_9034902037276537918[275] = 0.0;
   out_9034902037276537918[276] = 0.0;
   out_9034902037276537918[277] = 0.0;
   out_9034902037276537918[278] = 0.0;
   out_9034902037276537918[279] = 0.0;
   out_9034902037276537918[280] = 0.0;
   out_9034902037276537918[281] = 0.0;
   out_9034902037276537918[282] = 0.0;
   out_9034902037276537918[283] = 0.0;
   out_9034902037276537918[284] = 0.0;
   out_9034902037276537918[285] = 1.0;
   out_9034902037276537918[286] = 0.0;
   out_9034902037276537918[287] = 0.0;
   out_9034902037276537918[288] = 0.0;
   out_9034902037276537918[289] = 0.0;
   out_9034902037276537918[290] = 0.0;
   out_9034902037276537918[291] = 0.0;
   out_9034902037276537918[292] = 0.0;
   out_9034902037276537918[293] = 0.0;
   out_9034902037276537918[294] = 0.0;
   out_9034902037276537918[295] = 0.0;
   out_9034902037276537918[296] = 0.0;
   out_9034902037276537918[297] = 0.0;
   out_9034902037276537918[298] = 0.0;
   out_9034902037276537918[299] = 0.0;
   out_9034902037276537918[300] = 0.0;
   out_9034902037276537918[301] = 0.0;
   out_9034902037276537918[302] = 0.0;
   out_9034902037276537918[303] = 0.0;
   out_9034902037276537918[304] = 1.0;
   out_9034902037276537918[305] = 0.0;
   out_9034902037276537918[306] = 0.0;
   out_9034902037276537918[307] = 0.0;
   out_9034902037276537918[308] = 0.0;
   out_9034902037276537918[309] = 0.0;
   out_9034902037276537918[310] = 0.0;
   out_9034902037276537918[311] = 0.0;
   out_9034902037276537918[312] = 0.0;
   out_9034902037276537918[313] = 0.0;
   out_9034902037276537918[314] = 0.0;
   out_9034902037276537918[315] = 0.0;
   out_9034902037276537918[316] = 0.0;
   out_9034902037276537918[317] = 0.0;
   out_9034902037276537918[318] = 0.0;
   out_9034902037276537918[319] = 0.0;
   out_9034902037276537918[320] = 0.0;
   out_9034902037276537918[321] = 0.0;
   out_9034902037276537918[322] = 0.0;
   out_9034902037276537918[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_7872094071272015340) {
   out_7872094071272015340[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_7872094071272015340[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_7872094071272015340[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_7872094071272015340[3] = dt*state[12] + state[3];
   out_7872094071272015340[4] = dt*state[13] + state[4];
   out_7872094071272015340[5] = dt*state[14] + state[5];
   out_7872094071272015340[6] = state[6];
   out_7872094071272015340[7] = state[7];
   out_7872094071272015340[8] = state[8];
   out_7872094071272015340[9] = state[9];
   out_7872094071272015340[10] = state[10];
   out_7872094071272015340[11] = state[11];
   out_7872094071272015340[12] = state[12];
   out_7872094071272015340[13] = state[13];
   out_7872094071272015340[14] = state[14];
   out_7872094071272015340[15] = state[15];
   out_7872094071272015340[16] = state[16];
   out_7872094071272015340[17] = state[17];
}
void F_fun(double *state, double dt, double *out_306824247471662228) {
   out_306824247471662228[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_306824247471662228[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_306824247471662228[2] = 0;
   out_306824247471662228[3] = 0;
   out_306824247471662228[4] = 0;
   out_306824247471662228[5] = 0;
   out_306824247471662228[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_306824247471662228[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_306824247471662228[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_306824247471662228[9] = 0;
   out_306824247471662228[10] = 0;
   out_306824247471662228[11] = 0;
   out_306824247471662228[12] = 0;
   out_306824247471662228[13] = 0;
   out_306824247471662228[14] = 0;
   out_306824247471662228[15] = 0;
   out_306824247471662228[16] = 0;
   out_306824247471662228[17] = 0;
   out_306824247471662228[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_306824247471662228[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_306824247471662228[20] = 0;
   out_306824247471662228[21] = 0;
   out_306824247471662228[22] = 0;
   out_306824247471662228[23] = 0;
   out_306824247471662228[24] = 0;
   out_306824247471662228[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_306824247471662228[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_306824247471662228[27] = 0;
   out_306824247471662228[28] = 0;
   out_306824247471662228[29] = 0;
   out_306824247471662228[30] = 0;
   out_306824247471662228[31] = 0;
   out_306824247471662228[32] = 0;
   out_306824247471662228[33] = 0;
   out_306824247471662228[34] = 0;
   out_306824247471662228[35] = 0;
   out_306824247471662228[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_306824247471662228[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_306824247471662228[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_306824247471662228[39] = 0;
   out_306824247471662228[40] = 0;
   out_306824247471662228[41] = 0;
   out_306824247471662228[42] = 0;
   out_306824247471662228[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_306824247471662228[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_306824247471662228[45] = 0;
   out_306824247471662228[46] = 0;
   out_306824247471662228[47] = 0;
   out_306824247471662228[48] = 0;
   out_306824247471662228[49] = 0;
   out_306824247471662228[50] = 0;
   out_306824247471662228[51] = 0;
   out_306824247471662228[52] = 0;
   out_306824247471662228[53] = 0;
   out_306824247471662228[54] = 0;
   out_306824247471662228[55] = 0;
   out_306824247471662228[56] = 0;
   out_306824247471662228[57] = 1;
   out_306824247471662228[58] = 0;
   out_306824247471662228[59] = 0;
   out_306824247471662228[60] = 0;
   out_306824247471662228[61] = 0;
   out_306824247471662228[62] = 0;
   out_306824247471662228[63] = 0;
   out_306824247471662228[64] = 0;
   out_306824247471662228[65] = 0;
   out_306824247471662228[66] = dt;
   out_306824247471662228[67] = 0;
   out_306824247471662228[68] = 0;
   out_306824247471662228[69] = 0;
   out_306824247471662228[70] = 0;
   out_306824247471662228[71] = 0;
   out_306824247471662228[72] = 0;
   out_306824247471662228[73] = 0;
   out_306824247471662228[74] = 0;
   out_306824247471662228[75] = 0;
   out_306824247471662228[76] = 1;
   out_306824247471662228[77] = 0;
   out_306824247471662228[78] = 0;
   out_306824247471662228[79] = 0;
   out_306824247471662228[80] = 0;
   out_306824247471662228[81] = 0;
   out_306824247471662228[82] = 0;
   out_306824247471662228[83] = 0;
   out_306824247471662228[84] = 0;
   out_306824247471662228[85] = dt;
   out_306824247471662228[86] = 0;
   out_306824247471662228[87] = 0;
   out_306824247471662228[88] = 0;
   out_306824247471662228[89] = 0;
   out_306824247471662228[90] = 0;
   out_306824247471662228[91] = 0;
   out_306824247471662228[92] = 0;
   out_306824247471662228[93] = 0;
   out_306824247471662228[94] = 0;
   out_306824247471662228[95] = 1;
   out_306824247471662228[96] = 0;
   out_306824247471662228[97] = 0;
   out_306824247471662228[98] = 0;
   out_306824247471662228[99] = 0;
   out_306824247471662228[100] = 0;
   out_306824247471662228[101] = 0;
   out_306824247471662228[102] = 0;
   out_306824247471662228[103] = 0;
   out_306824247471662228[104] = dt;
   out_306824247471662228[105] = 0;
   out_306824247471662228[106] = 0;
   out_306824247471662228[107] = 0;
   out_306824247471662228[108] = 0;
   out_306824247471662228[109] = 0;
   out_306824247471662228[110] = 0;
   out_306824247471662228[111] = 0;
   out_306824247471662228[112] = 0;
   out_306824247471662228[113] = 0;
   out_306824247471662228[114] = 1;
   out_306824247471662228[115] = 0;
   out_306824247471662228[116] = 0;
   out_306824247471662228[117] = 0;
   out_306824247471662228[118] = 0;
   out_306824247471662228[119] = 0;
   out_306824247471662228[120] = 0;
   out_306824247471662228[121] = 0;
   out_306824247471662228[122] = 0;
   out_306824247471662228[123] = 0;
   out_306824247471662228[124] = 0;
   out_306824247471662228[125] = 0;
   out_306824247471662228[126] = 0;
   out_306824247471662228[127] = 0;
   out_306824247471662228[128] = 0;
   out_306824247471662228[129] = 0;
   out_306824247471662228[130] = 0;
   out_306824247471662228[131] = 0;
   out_306824247471662228[132] = 0;
   out_306824247471662228[133] = 1;
   out_306824247471662228[134] = 0;
   out_306824247471662228[135] = 0;
   out_306824247471662228[136] = 0;
   out_306824247471662228[137] = 0;
   out_306824247471662228[138] = 0;
   out_306824247471662228[139] = 0;
   out_306824247471662228[140] = 0;
   out_306824247471662228[141] = 0;
   out_306824247471662228[142] = 0;
   out_306824247471662228[143] = 0;
   out_306824247471662228[144] = 0;
   out_306824247471662228[145] = 0;
   out_306824247471662228[146] = 0;
   out_306824247471662228[147] = 0;
   out_306824247471662228[148] = 0;
   out_306824247471662228[149] = 0;
   out_306824247471662228[150] = 0;
   out_306824247471662228[151] = 0;
   out_306824247471662228[152] = 1;
   out_306824247471662228[153] = 0;
   out_306824247471662228[154] = 0;
   out_306824247471662228[155] = 0;
   out_306824247471662228[156] = 0;
   out_306824247471662228[157] = 0;
   out_306824247471662228[158] = 0;
   out_306824247471662228[159] = 0;
   out_306824247471662228[160] = 0;
   out_306824247471662228[161] = 0;
   out_306824247471662228[162] = 0;
   out_306824247471662228[163] = 0;
   out_306824247471662228[164] = 0;
   out_306824247471662228[165] = 0;
   out_306824247471662228[166] = 0;
   out_306824247471662228[167] = 0;
   out_306824247471662228[168] = 0;
   out_306824247471662228[169] = 0;
   out_306824247471662228[170] = 0;
   out_306824247471662228[171] = 1;
   out_306824247471662228[172] = 0;
   out_306824247471662228[173] = 0;
   out_306824247471662228[174] = 0;
   out_306824247471662228[175] = 0;
   out_306824247471662228[176] = 0;
   out_306824247471662228[177] = 0;
   out_306824247471662228[178] = 0;
   out_306824247471662228[179] = 0;
   out_306824247471662228[180] = 0;
   out_306824247471662228[181] = 0;
   out_306824247471662228[182] = 0;
   out_306824247471662228[183] = 0;
   out_306824247471662228[184] = 0;
   out_306824247471662228[185] = 0;
   out_306824247471662228[186] = 0;
   out_306824247471662228[187] = 0;
   out_306824247471662228[188] = 0;
   out_306824247471662228[189] = 0;
   out_306824247471662228[190] = 1;
   out_306824247471662228[191] = 0;
   out_306824247471662228[192] = 0;
   out_306824247471662228[193] = 0;
   out_306824247471662228[194] = 0;
   out_306824247471662228[195] = 0;
   out_306824247471662228[196] = 0;
   out_306824247471662228[197] = 0;
   out_306824247471662228[198] = 0;
   out_306824247471662228[199] = 0;
   out_306824247471662228[200] = 0;
   out_306824247471662228[201] = 0;
   out_306824247471662228[202] = 0;
   out_306824247471662228[203] = 0;
   out_306824247471662228[204] = 0;
   out_306824247471662228[205] = 0;
   out_306824247471662228[206] = 0;
   out_306824247471662228[207] = 0;
   out_306824247471662228[208] = 0;
   out_306824247471662228[209] = 1;
   out_306824247471662228[210] = 0;
   out_306824247471662228[211] = 0;
   out_306824247471662228[212] = 0;
   out_306824247471662228[213] = 0;
   out_306824247471662228[214] = 0;
   out_306824247471662228[215] = 0;
   out_306824247471662228[216] = 0;
   out_306824247471662228[217] = 0;
   out_306824247471662228[218] = 0;
   out_306824247471662228[219] = 0;
   out_306824247471662228[220] = 0;
   out_306824247471662228[221] = 0;
   out_306824247471662228[222] = 0;
   out_306824247471662228[223] = 0;
   out_306824247471662228[224] = 0;
   out_306824247471662228[225] = 0;
   out_306824247471662228[226] = 0;
   out_306824247471662228[227] = 0;
   out_306824247471662228[228] = 1;
   out_306824247471662228[229] = 0;
   out_306824247471662228[230] = 0;
   out_306824247471662228[231] = 0;
   out_306824247471662228[232] = 0;
   out_306824247471662228[233] = 0;
   out_306824247471662228[234] = 0;
   out_306824247471662228[235] = 0;
   out_306824247471662228[236] = 0;
   out_306824247471662228[237] = 0;
   out_306824247471662228[238] = 0;
   out_306824247471662228[239] = 0;
   out_306824247471662228[240] = 0;
   out_306824247471662228[241] = 0;
   out_306824247471662228[242] = 0;
   out_306824247471662228[243] = 0;
   out_306824247471662228[244] = 0;
   out_306824247471662228[245] = 0;
   out_306824247471662228[246] = 0;
   out_306824247471662228[247] = 1;
   out_306824247471662228[248] = 0;
   out_306824247471662228[249] = 0;
   out_306824247471662228[250] = 0;
   out_306824247471662228[251] = 0;
   out_306824247471662228[252] = 0;
   out_306824247471662228[253] = 0;
   out_306824247471662228[254] = 0;
   out_306824247471662228[255] = 0;
   out_306824247471662228[256] = 0;
   out_306824247471662228[257] = 0;
   out_306824247471662228[258] = 0;
   out_306824247471662228[259] = 0;
   out_306824247471662228[260] = 0;
   out_306824247471662228[261] = 0;
   out_306824247471662228[262] = 0;
   out_306824247471662228[263] = 0;
   out_306824247471662228[264] = 0;
   out_306824247471662228[265] = 0;
   out_306824247471662228[266] = 1;
   out_306824247471662228[267] = 0;
   out_306824247471662228[268] = 0;
   out_306824247471662228[269] = 0;
   out_306824247471662228[270] = 0;
   out_306824247471662228[271] = 0;
   out_306824247471662228[272] = 0;
   out_306824247471662228[273] = 0;
   out_306824247471662228[274] = 0;
   out_306824247471662228[275] = 0;
   out_306824247471662228[276] = 0;
   out_306824247471662228[277] = 0;
   out_306824247471662228[278] = 0;
   out_306824247471662228[279] = 0;
   out_306824247471662228[280] = 0;
   out_306824247471662228[281] = 0;
   out_306824247471662228[282] = 0;
   out_306824247471662228[283] = 0;
   out_306824247471662228[284] = 0;
   out_306824247471662228[285] = 1;
   out_306824247471662228[286] = 0;
   out_306824247471662228[287] = 0;
   out_306824247471662228[288] = 0;
   out_306824247471662228[289] = 0;
   out_306824247471662228[290] = 0;
   out_306824247471662228[291] = 0;
   out_306824247471662228[292] = 0;
   out_306824247471662228[293] = 0;
   out_306824247471662228[294] = 0;
   out_306824247471662228[295] = 0;
   out_306824247471662228[296] = 0;
   out_306824247471662228[297] = 0;
   out_306824247471662228[298] = 0;
   out_306824247471662228[299] = 0;
   out_306824247471662228[300] = 0;
   out_306824247471662228[301] = 0;
   out_306824247471662228[302] = 0;
   out_306824247471662228[303] = 0;
   out_306824247471662228[304] = 1;
   out_306824247471662228[305] = 0;
   out_306824247471662228[306] = 0;
   out_306824247471662228[307] = 0;
   out_306824247471662228[308] = 0;
   out_306824247471662228[309] = 0;
   out_306824247471662228[310] = 0;
   out_306824247471662228[311] = 0;
   out_306824247471662228[312] = 0;
   out_306824247471662228[313] = 0;
   out_306824247471662228[314] = 0;
   out_306824247471662228[315] = 0;
   out_306824247471662228[316] = 0;
   out_306824247471662228[317] = 0;
   out_306824247471662228[318] = 0;
   out_306824247471662228[319] = 0;
   out_306824247471662228[320] = 0;
   out_306824247471662228[321] = 0;
   out_306824247471662228[322] = 0;
   out_306824247471662228[323] = 1;
}
void h_4(double *state, double *unused, double *out_8123411127694778865) {
   out_8123411127694778865[0] = state[6] + state[9];
   out_8123411127694778865[1] = state[7] + state[10];
   out_8123411127694778865[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_546114021891860012) {
   out_546114021891860012[0] = 0;
   out_546114021891860012[1] = 0;
   out_546114021891860012[2] = 0;
   out_546114021891860012[3] = 0;
   out_546114021891860012[4] = 0;
   out_546114021891860012[5] = 0;
   out_546114021891860012[6] = 1;
   out_546114021891860012[7] = 0;
   out_546114021891860012[8] = 0;
   out_546114021891860012[9] = 1;
   out_546114021891860012[10] = 0;
   out_546114021891860012[11] = 0;
   out_546114021891860012[12] = 0;
   out_546114021891860012[13] = 0;
   out_546114021891860012[14] = 0;
   out_546114021891860012[15] = 0;
   out_546114021891860012[16] = 0;
   out_546114021891860012[17] = 0;
   out_546114021891860012[18] = 0;
   out_546114021891860012[19] = 0;
   out_546114021891860012[20] = 0;
   out_546114021891860012[21] = 0;
   out_546114021891860012[22] = 0;
   out_546114021891860012[23] = 0;
   out_546114021891860012[24] = 0;
   out_546114021891860012[25] = 1;
   out_546114021891860012[26] = 0;
   out_546114021891860012[27] = 0;
   out_546114021891860012[28] = 1;
   out_546114021891860012[29] = 0;
   out_546114021891860012[30] = 0;
   out_546114021891860012[31] = 0;
   out_546114021891860012[32] = 0;
   out_546114021891860012[33] = 0;
   out_546114021891860012[34] = 0;
   out_546114021891860012[35] = 0;
   out_546114021891860012[36] = 0;
   out_546114021891860012[37] = 0;
   out_546114021891860012[38] = 0;
   out_546114021891860012[39] = 0;
   out_546114021891860012[40] = 0;
   out_546114021891860012[41] = 0;
   out_546114021891860012[42] = 0;
   out_546114021891860012[43] = 0;
   out_546114021891860012[44] = 1;
   out_546114021891860012[45] = 0;
   out_546114021891860012[46] = 0;
   out_546114021891860012[47] = 1;
   out_546114021891860012[48] = 0;
   out_546114021891860012[49] = 0;
   out_546114021891860012[50] = 0;
   out_546114021891860012[51] = 0;
   out_546114021891860012[52] = 0;
   out_546114021891860012[53] = 0;
}
void h_10(double *state, double *unused, double *out_1547906265708858286) {
   out_1547906265708858286[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_1547906265708858286[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_1547906265708858286[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_5776283871331797156) {
   out_5776283871331797156[0] = 0;
   out_5776283871331797156[1] = 9.8100000000000005*cos(state[1]);
   out_5776283871331797156[2] = 0;
   out_5776283871331797156[3] = 0;
   out_5776283871331797156[4] = -state[8];
   out_5776283871331797156[5] = state[7];
   out_5776283871331797156[6] = 0;
   out_5776283871331797156[7] = state[5];
   out_5776283871331797156[8] = -state[4];
   out_5776283871331797156[9] = 0;
   out_5776283871331797156[10] = 0;
   out_5776283871331797156[11] = 0;
   out_5776283871331797156[12] = 1;
   out_5776283871331797156[13] = 0;
   out_5776283871331797156[14] = 0;
   out_5776283871331797156[15] = 1;
   out_5776283871331797156[16] = 0;
   out_5776283871331797156[17] = 0;
   out_5776283871331797156[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_5776283871331797156[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_5776283871331797156[20] = 0;
   out_5776283871331797156[21] = state[8];
   out_5776283871331797156[22] = 0;
   out_5776283871331797156[23] = -state[6];
   out_5776283871331797156[24] = -state[5];
   out_5776283871331797156[25] = 0;
   out_5776283871331797156[26] = state[3];
   out_5776283871331797156[27] = 0;
   out_5776283871331797156[28] = 0;
   out_5776283871331797156[29] = 0;
   out_5776283871331797156[30] = 0;
   out_5776283871331797156[31] = 1;
   out_5776283871331797156[32] = 0;
   out_5776283871331797156[33] = 0;
   out_5776283871331797156[34] = 1;
   out_5776283871331797156[35] = 0;
   out_5776283871331797156[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_5776283871331797156[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_5776283871331797156[38] = 0;
   out_5776283871331797156[39] = -state[7];
   out_5776283871331797156[40] = state[6];
   out_5776283871331797156[41] = 0;
   out_5776283871331797156[42] = state[4];
   out_5776283871331797156[43] = -state[3];
   out_5776283871331797156[44] = 0;
   out_5776283871331797156[45] = 0;
   out_5776283871331797156[46] = 0;
   out_5776283871331797156[47] = 0;
   out_5776283871331797156[48] = 0;
   out_5776283871331797156[49] = 0;
   out_5776283871331797156[50] = 1;
   out_5776283871331797156[51] = 0;
   out_5776283871331797156[52] = 0;
   out_5776283871331797156[53] = 1;
}
void h_13(double *state, double *unused, double *out_1149091238389542330) {
   out_1149091238389542330[0] = state[3];
   out_1149091238389542330[1] = state[4];
   out_1149091238389542330[2] = state[5];
}
void H_13(double *state, double *unused, double *out_8156745230208560941) {
   out_8156745230208560941[0] = 0;
   out_8156745230208560941[1] = 0;
   out_8156745230208560941[2] = 0;
   out_8156745230208560941[3] = 1;
   out_8156745230208560941[4] = 0;
   out_8156745230208560941[5] = 0;
   out_8156745230208560941[6] = 0;
   out_8156745230208560941[7] = 0;
   out_8156745230208560941[8] = 0;
   out_8156745230208560941[9] = 0;
   out_8156745230208560941[10] = 0;
   out_8156745230208560941[11] = 0;
   out_8156745230208560941[12] = 0;
   out_8156745230208560941[13] = 0;
   out_8156745230208560941[14] = 0;
   out_8156745230208560941[15] = 0;
   out_8156745230208560941[16] = 0;
   out_8156745230208560941[17] = 0;
   out_8156745230208560941[18] = 0;
   out_8156745230208560941[19] = 0;
   out_8156745230208560941[20] = 0;
   out_8156745230208560941[21] = 0;
   out_8156745230208560941[22] = 1;
   out_8156745230208560941[23] = 0;
   out_8156745230208560941[24] = 0;
   out_8156745230208560941[25] = 0;
   out_8156745230208560941[26] = 0;
   out_8156745230208560941[27] = 0;
   out_8156745230208560941[28] = 0;
   out_8156745230208560941[29] = 0;
   out_8156745230208560941[30] = 0;
   out_8156745230208560941[31] = 0;
   out_8156745230208560941[32] = 0;
   out_8156745230208560941[33] = 0;
   out_8156745230208560941[34] = 0;
   out_8156745230208560941[35] = 0;
   out_8156745230208560941[36] = 0;
   out_8156745230208560941[37] = 0;
   out_8156745230208560941[38] = 0;
   out_8156745230208560941[39] = 0;
   out_8156745230208560941[40] = 0;
   out_8156745230208560941[41] = 1;
   out_8156745230208560941[42] = 0;
   out_8156745230208560941[43] = 0;
   out_8156745230208560941[44] = 0;
   out_8156745230208560941[45] = 0;
   out_8156745230208560941[46] = 0;
   out_8156745230208560941[47] = 0;
   out_8156745230208560941[48] = 0;
   out_8156745230208560941[49] = 0;
   out_8156745230208560941[50] = 0;
   out_8156745230208560941[51] = 0;
   out_8156745230208560941[52] = 0;
   out_8156745230208560941[53] = 0;
}
void h_14(double *state, double *unused, double *out_2710515986937060210) {
   out_2710515986937060210[0] = state[6];
   out_2710515986937060210[1] = state[7];
   out_2710515986937060210[2] = state[8];
}
void H_14(double *state, double *unused, double *out_4509354878231344541) {
   out_4509354878231344541[0] = 0;
   out_4509354878231344541[1] = 0;
   out_4509354878231344541[2] = 0;
   out_4509354878231344541[3] = 0;
   out_4509354878231344541[4] = 0;
   out_4509354878231344541[5] = 0;
   out_4509354878231344541[6] = 1;
   out_4509354878231344541[7] = 0;
   out_4509354878231344541[8] = 0;
   out_4509354878231344541[9] = 0;
   out_4509354878231344541[10] = 0;
   out_4509354878231344541[11] = 0;
   out_4509354878231344541[12] = 0;
   out_4509354878231344541[13] = 0;
   out_4509354878231344541[14] = 0;
   out_4509354878231344541[15] = 0;
   out_4509354878231344541[16] = 0;
   out_4509354878231344541[17] = 0;
   out_4509354878231344541[18] = 0;
   out_4509354878231344541[19] = 0;
   out_4509354878231344541[20] = 0;
   out_4509354878231344541[21] = 0;
   out_4509354878231344541[22] = 0;
   out_4509354878231344541[23] = 0;
   out_4509354878231344541[24] = 0;
   out_4509354878231344541[25] = 1;
   out_4509354878231344541[26] = 0;
   out_4509354878231344541[27] = 0;
   out_4509354878231344541[28] = 0;
   out_4509354878231344541[29] = 0;
   out_4509354878231344541[30] = 0;
   out_4509354878231344541[31] = 0;
   out_4509354878231344541[32] = 0;
   out_4509354878231344541[33] = 0;
   out_4509354878231344541[34] = 0;
   out_4509354878231344541[35] = 0;
   out_4509354878231344541[36] = 0;
   out_4509354878231344541[37] = 0;
   out_4509354878231344541[38] = 0;
   out_4509354878231344541[39] = 0;
   out_4509354878231344541[40] = 0;
   out_4509354878231344541[41] = 0;
   out_4509354878231344541[42] = 0;
   out_4509354878231344541[43] = 0;
   out_4509354878231344541[44] = 1;
   out_4509354878231344541[45] = 0;
   out_4509354878231344541[46] = 0;
   out_4509354878231344541[47] = 0;
   out_4509354878231344541[48] = 0;
   out_4509354878231344541[49] = 0;
   out_4509354878231344541[50] = 0;
   out_4509354878231344541[51] = 0;
   out_4509354878231344541[52] = 0;
   out_4509354878231344541[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_1063797637258796766) {
  err_fun(nom_x, delta_x, out_1063797637258796766);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_5886317630058333046) {
  inv_err_fun(nom_x, true_x, out_5886317630058333046);
}
void pose_H_mod_fun(double *state, double *out_9034902037276537918) {
  H_mod_fun(state, out_9034902037276537918);
}
void pose_f_fun(double *state, double dt, double *out_7872094071272015340) {
  f_fun(state,  dt, out_7872094071272015340);
}
void pose_F_fun(double *state, double dt, double *out_306824247471662228) {
  F_fun(state,  dt, out_306824247471662228);
}
void pose_h_4(double *state, double *unused, double *out_8123411127694778865) {
  h_4(state, unused, out_8123411127694778865);
}
void pose_H_4(double *state, double *unused, double *out_546114021891860012) {
  H_4(state, unused, out_546114021891860012);
}
void pose_h_10(double *state, double *unused, double *out_1547906265708858286) {
  h_10(state, unused, out_1547906265708858286);
}
void pose_H_10(double *state, double *unused, double *out_5776283871331797156) {
  H_10(state, unused, out_5776283871331797156);
}
void pose_h_13(double *state, double *unused, double *out_1149091238389542330) {
  h_13(state, unused, out_1149091238389542330);
}
void pose_H_13(double *state, double *unused, double *out_8156745230208560941) {
  H_13(state, unused, out_8156745230208560941);
}
void pose_h_14(double *state, double *unused, double *out_2710515986937060210) {
  h_14(state, unused, out_2710515986937060210);
}
void pose_H_14(double *state, double *unused, double *out_4509354878231344541) {
  H_14(state, unused, out_4509354878231344541);
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
