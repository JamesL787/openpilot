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
void err_fun(double *nom_x, double *delta_x, double *out_6021173093259519341) {
   out_6021173093259519341[0] = delta_x[0] + nom_x[0];
   out_6021173093259519341[1] = delta_x[1] + nom_x[1];
   out_6021173093259519341[2] = delta_x[2] + nom_x[2];
   out_6021173093259519341[3] = delta_x[3] + nom_x[3];
   out_6021173093259519341[4] = delta_x[4] + nom_x[4];
   out_6021173093259519341[5] = delta_x[5] + nom_x[5];
   out_6021173093259519341[6] = delta_x[6] + nom_x[6];
   out_6021173093259519341[7] = delta_x[7] + nom_x[7];
   out_6021173093259519341[8] = delta_x[8] + nom_x[8];
   out_6021173093259519341[9] = delta_x[9] + nom_x[9];
   out_6021173093259519341[10] = delta_x[10] + nom_x[10];
   out_6021173093259519341[11] = delta_x[11] + nom_x[11];
   out_6021173093259519341[12] = delta_x[12] + nom_x[12];
   out_6021173093259519341[13] = delta_x[13] + nom_x[13];
   out_6021173093259519341[14] = delta_x[14] + nom_x[14];
   out_6021173093259519341[15] = delta_x[15] + nom_x[15];
   out_6021173093259519341[16] = delta_x[16] + nom_x[16];
   out_6021173093259519341[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_3203995659568275494) {
   out_3203995659568275494[0] = -nom_x[0] + true_x[0];
   out_3203995659568275494[1] = -nom_x[1] + true_x[1];
   out_3203995659568275494[2] = -nom_x[2] + true_x[2];
   out_3203995659568275494[3] = -nom_x[3] + true_x[3];
   out_3203995659568275494[4] = -nom_x[4] + true_x[4];
   out_3203995659568275494[5] = -nom_x[5] + true_x[5];
   out_3203995659568275494[6] = -nom_x[6] + true_x[6];
   out_3203995659568275494[7] = -nom_x[7] + true_x[7];
   out_3203995659568275494[8] = -nom_x[8] + true_x[8];
   out_3203995659568275494[9] = -nom_x[9] + true_x[9];
   out_3203995659568275494[10] = -nom_x[10] + true_x[10];
   out_3203995659568275494[11] = -nom_x[11] + true_x[11];
   out_3203995659568275494[12] = -nom_x[12] + true_x[12];
   out_3203995659568275494[13] = -nom_x[13] + true_x[13];
   out_3203995659568275494[14] = -nom_x[14] + true_x[14];
   out_3203995659568275494[15] = -nom_x[15] + true_x[15];
   out_3203995659568275494[16] = -nom_x[16] + true_x[16];
   out_3203995659568275494[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_128560542949297932) {
   out_128560542949297932[0] = 1.0;
   out_128560542949297932[1] = 0.0;
   out_128560542949297932[2] = 0.0;
   out_128560542949297932[3] = 0.0;
   out_128560542949297932[4] = 0.0;
   out_128560542949297932[5] = 0.0;
   out_128560542949297932[6] = 0.0;
   out_128560542949297932[7] = 0.0;
   out_128560542949297932[8] = 0.0;
   out_128560542949297932[9] = 0.0;
   out_128560542949297932[10] = 0.0;
   out_128560542949297932[11] = 0.0;
   out_128560542949297932[12] = 0.0;
   out_128560542949297932[13] = 0.0;
   out_128560542949297932[14] = 0.0;
   out_128560542949297932[15] = 0.0;
   out_128560542949297932[16] = 0.0;
   out_128560542949297932[17] = 0.0;
   out_128560542949297932[18] = 0.0;
   out_128560542949297932[19] = 1.0;
   out_128560542949297932[20] = 0.0;
   out_128560542949297932[21] = 0.0;
   out_128560542949297932[22] = 0.0;
   out_128560542949297932[23] = 0.0;
   out_128560542949297932[24] = 0.0;
   out_128560542949297932[25] = 0.0;
   out_128560542949297932[26] = 0.0;
   out_128560542949297932[27] = 0.0;
   out_128560542949297932[28] = 0.0;
   out_128560542949297932[29] = 0.0;
   out_128560542949297932[30] = 0.0;
   out_128560542949297932[31] = 0.0;
   out_128560542949297932[32] = 0.0;
   out_128560542949297932[33] = 0.0;
   out_128560542949297932[34] = 0.0;
   out_128560542949297932[35] = 0.0;
   out_128560542949297932[36] = 0.0;
   out_128560542949297932[37] = 0.0;
   out_128560542949297932[38] = 1.0;
   out_128560542949297932[39] = 0.0;
   out_128560542949297932[40] = 0.0;
   out_128560542949297932[41] = 0.0;
   out_128560542949297932[42] = 0.0;
   out_128560542949297932[43] = 0.0;
   out_128560542949297932[44] = 0.0;
   out_128560542949297932[45] = 0.0;
   out_128560542949297932[46] = 0.0;
   out_128560542949297932[47] = 0.0;
   out_128560542949297932[48] = 0.0;
   out_128560542949297932[49] = 0.0;
   out_128560542949297932[50] = 0.0;
   out_128560542949297932[51] = 0.0;
   out_128560542949297932[52] = 0.0;
   out_128560542949297932[53] = 0.0;
   out_128560542949297932[54] = 0.0;
   out_128560542949297932[55] = 0.0;
   out_128560542949297932[56] = 0.0;
   out_128560542949297932[57] = 1.0;
   out_128560542949297932[58] = 0.0;
   out_128560542949297932[59] = 0.0;
   out_128560542949297932[60] = 0.0;
   out_128560542949297932[61] = 0.0;
   out_128560542949297932[62] = 0.0;
   out_128560542949297932[63] = 0.0;
   out_128560542949297932[64] = 0.0;
   out_128560542949297932[65] = 0.0;
   out_128560542949297932[66] = 0.0;
   out_128560542949297932[67] = 0.0;
   out_128560542949297932[68] = 0.0;
   out_128560542949297932[69] = 0.0;
   out_128560542949297932[70] = 0.0;
   out_128560542949297932[71] = 0.0;
   out_128560542949297932[72] = 0.0;
   out_128560542949297932[73] = 0.0;
   out_128560542949297932[74] = 0.0;
   out_128560542949297932[75] = 0.0;
   out_128560542949297932[76] = 1.0;
   out_128560542949297932[77] = 0.0;
   out_128560542949297932[78] = 0.0;
   out_128560542949297932[79] = 0.0;
   out_128560542949297932[80] = 0.0;
   out_128560542949297932[81] = 0.0;
   out_128560542949297932[82] = 0.0;
   out_128560542949297932[83] = 0.0;
   out_128560542949297932[84] = 0.0;
   out_128560542949297932[85] = 0.0;
   out_128560542949297932[86] = 0.0;
   out_128560542949297932[87] = 0.0;
   out_128560542949297932[88] = 0.0;
   out_128560542949297932[89] = 0.0;
   out_128560542949297932[90] = 0.0;
   out_128560542949297932[91] = 0.0;
   out_128560542949297932[92] = 0.0;
   out_128560542949297932[93] = 0.0;
   out_128560542949297932[94] = 0.0;
   out_128560542949297932[95] = 1.0;
   out_128560542949297932[96] = 0.0;
   out_128560542949297932[97] = 0.0;
   out_128560542949297932[98] = 0.0;
   out_128560542949297932[99] = 0.0;
   out_128560542949297932[100] = 0.0;
   out_128560542949297932[101] = 0.0;
   out_128560542949297932[102] = 0.0;
   out_128560542949297932[103] = 0.0;
   out_128560542949297932[104] = 0.0;
   out_128560542949297932[105] = 0.0;
   out_128560542949297932[106] = 0.0;
   out_128560542949297932[107] = 0.0;
   out_128560542949297932[108] = 0.0;
   out_128560542949297932[109] = 0.0;
   out_128560542949297932[110] = 0.0;
   out_128560542949297932[111] = 0.0;
   out_128560542949297932[112] = 0.0;
   out_128560542949297932[113] = 0.0;
   out_128560542949297932[114] = 1.0;
   out_128560542949297932[115] = 0.0;
   out_128560542949297932[116] = 0.0;
   out_128560542949297932[117] = 0.0;
   out_128560542949297932[118] = 0.0;
   out_128560542949297932[119] = 0.0;
   out_128560542949297932[120] = 0.0;
   out_128560542949297932[121] = 0.0;
   out_128560542949297932[122] = 0.0;
   out_128560542949297932[123] = 0.0;
   out_128560542949297932[124] = 0.0;
   out_128560542949297932[125] = 0.0;
   out_128560542949297932[126] = 0.0;
   out_128560542949297932[127] = 0.0;
   out_128560542949297932[128] = 0.0;
   out_128560542949297932[129] = 0.0;
   out_128560542949297932[130] = 0.0;
   out_128560542949297932[131] = 0.0;
   out_128560542949297932[132] = 0.0;
   out_128560542949297932[133] = 1.0;
   out_128560542949297932[134] = 0.0;
   out_128560542949297932[135] = 0.0;
   out_128560542949297932[136] = 0.0;
   out_128560542949297932[137] = 0.0;
   out_128560542949297932[138] = 0.0;
   out_128560542949297932[139] = 0.0;
   out_128560542949297932[140] = 0.0;
   out_128560542949297932[141] = 0.0;
   out_128560542949297932[142] = 0.0;
   out_128560542949297932[143] = 0.0;
   out_128560542949297932[144] = 0.0;
   out_128560542949297932[145] = 0.0;
   out_128560542949297932[146] = 0.0;
   out_128560542949297932[147] = 0.0;
   out_128560542949297932[148] = 0.0;
   out_128560542949297932[149] = 0.0;
   out_128560542949297932[150] = 0.0;
   out_128560542949297932[151] = 0.0;
   out_128560542949297932[152] = 1.0;
   out_128560542949297932[153] = 0.0;
   out_128560542949297932[154] = 0.0;
   out_128560542949297932[155] = 0.0;
   out_128560542949297932[156] = 0.0;
   out_128560542949297932[157] = 0.0;
   out_128560542949297932[158] = 0.0;
   out_128560542949297932[159] = 0.0;
   out_128560542949297932[160] = 0.0;
   out_128560542949297932[161] = 0.0;
   out_128560542949297932[162] = 0.0;
   out_128560542949297932[163] = 0.0;
   out_128560542949297932[164] = 0.0;
   out_128560542949297932[165] = 0.0;
   out_128560542949297932[166] = 0.0;
   out_128560542949297932[167] = 0.0;
   out_128560542949297932[168] = 0.0;
   out_128560542949297932[169] = 0.0;
   out_128560542949297932[170] = 0.0;
   out_128560542949297932[171] = 1.0;
   out_128560542949297932[172] = 0.0;
   out_128560542949297932[173] = 0.0;
   out_128560542949297932[174] = 0.0;
   out_128560542949297932[175] = 0.0;
   out_128560542949297932[176] = 0.0;
   out_128560542949297932[177] = 0.0;
   out_128560542949297932[178] = 0.0;
   out_128560542949297932[179] = 0.0;
   out_128560542949297932[180] = 0.0;
   out_128560542949297932[181] = 0.0;
   out_128560542949297932[182] = 0.0;
   out_128560542949297932[183] = 0.0;
   out_128560542949297932[184] = 0.0;
   out_128560542949297932[185] = 0.0;
   out_128560542949297932[186] = 0.0;
   out_128560542949297932[187] = 0.0;
   out_128560542949297932[188] = 0.0;
   out_128560542949297932[189] = 0.0;
   out_128560542949297932[190] = 1.0;
   out_128560542949297932[191] = 0.0;
   out_128560542949297932[192] = 0.0;
   out_128560542949297932[193] = 0.0;
   out_128560542949297932[194] = 0.0;
   out_128560542949297932[195] = 0.0;
   out_128560542949297932[196] = 0.0;
   out_128560542949297932[197] = 0.0;
   out_128560542949297932[198] = 0.0;
   out_128560542949297932[199] = 0.0;
   out_128560542949297932[200] = 0.0;
   out_128560542949297932[201] = 0.0;
   out_128560542949297932[202] = 0.0;
   out_128560542949297932[203] = 0.0;
   out_128560542949297932[204] = 0.0;
   out_128560542949297932[205] = 0.0;
   out_128560542949297932[206] = 0.0;
   out_128560542949297932[207] = 0.0;
   out_128560542949297932[208] = 0.0;
   out_128560542949297932[209] = 1.0;
   out_128560542949297932[210] = 0.0;
   out_128560542949297932[211] = 0.0;
   out_128560542949297932[212] = 0.0;
   out_128560542949297932[213] = 0.0;
   out_128560542949297932[214] = 0.0;
   out_128560542949297932[215] = 0.0;
   out_128560542949297932[216] = 0.0;
   out_128560542949297932[217] = 0.0;
   out_128560542949297932[218] = 0.0;
   out_128560542949297932[219] = 0.0;
   out_128560542949297932[220] = 0.0;
   out_128560542949297932[221] = 0.0;
   out_128560542949297932[222] = 0.0;
   out_128560542949297932[223] = 0.0;
   out_128560542949297932[224] = 0.0;
   out_128560542949297932[225] = 0.0;
   out_128560542949297932[226] = 0.0;
   out_128560542949297932[227] = 0.0;
   out_128560542949297932[228] = 1.0;
   out_128560542949297932[229] = 0.0;
   out_128560542949297932[230] = 0.0;
   out_128560542949297932[231] = 0.0;
   out_128560542949297932[232] = 0.0;
   out_128560542949297932[233] = 0.0;
   out_128560542949297932[234] = 0.0;
   out_128560542949297932[235] = 0.0;
   out_128560542949297932[236] = 0.0;
   out_128560542949297932[237] = 0.0;
   out_128560542949297932[238] = 0.0;
   out_128560542949297932[239] = 0.0;
   out_128560542949297932[240] = 0.0;
   out_128560542949297932[241] = 0.0;
   out_128560542949297932[242] = 0.0;
   out_128560542949297932[243] = 0.0;
   out_128560542949297932[244] = 0.0;
   out_128560542949297932[245] = 0.0;
   out_128560542949297932[246] = 0.0;
   out_128560542949297932[247] = 1.0;
   out_128560542949297932[248] = 0.0;
   out_128560542949297932[249] = 0.0;
   out_128560542949297932[250] = 0.0;
   out_128560542949297932[251] = 0.0;
   out_128560542949297932[252] = 0.0;
   out_128560542949297932[253] = 0.0;
   out_128560542949297932[254] = 0.0;
   out_128560542949297932[255] = 0.0;
   out_128560542949297932[256] = 0.0;
   out_128560542949297932[257] = 0.0;
   out_128560542949297932[258] = 0.0;
   out_128560542949297932[259] = 0.0;
   out_128560542949297932[260] = 0.0;
   out_128560542949297932[261] = 0.0;
   out_128560542949297932[262] = 0.0;
   out_128560542949297932[263] = 0.0;
   out_128560542949297932[264] = 0.0;
   out_128560542949297932[265] = 0.0;
   out_128560542949297932[266] = 1.0;
   out_128560542949297932[267] = 0.0;
   out_128560542949297932[268] = 0.0;
   out_128560542949297932[269] = 0.0;
   out_128560542949297932[270] = 0.0;
   out_128560542949297932[271] = 0.0;
   out_128560542949297932[272] = 0.0;
   out_128560542949297932[273] = 0.0;
   out_128560542949297932[274] = 0.0;
   out_128560542949297932[275] = 0.0;
   out_128560542949297932[276] = 0.0;
   out_128560542949297932[277] = 0.0;
   out_128560542949297932[278] = 0.0;
   out_128560542949297932[279] = 0.0;
   out_128560542949297932[280] = 0.0;
   out_128560542949297932[281] = 0.0;
   out_128560542949297932[282] = 0.0;
   out_128560542949297932[283] = 0.0;
   out_128560542949297932[284] = 0.0;
   out_128560542949297932[285] = 1.0;
   out_128560542949297932[286] = 0.0;
   out_128560542949297932[287] = 0.0;
   out_128560542949297932[288] = 0.0;
   out_128560542949297932[289] = 0.0;
   out_128560542949297932[290] = 0.0;
   out_128560542949297932[291] = 0.0;
   out_128560542949297932[292] = 0.0;
   out_128560542949297932[293] = 0.0;
   out_128560542949297932[294] = 0.0;
   out_128560542949297932[295] = 0.0;
   out_128560542949297932[296] = 0.0;
   out_128560542949297932[297] = 0.0;
   out_128560542949297932[298] = 0.0;
   out_128560542949297932[299] = 0.0;
   out_128560542949297932[300] = 0.0;
   out_128560542949297932[301] = 0.0;
   out_128560542949297932[302] = 0.0;
   out_128560542949297932[303] = 0.0;
   out_128560542949297932[304] = 1.0;
   out_128560542949297932[305] = 0.0;
   out_128560542949297932[306] = 0.0;
   out_128560542949297932[307] = 0.0;
   out_128560542949297932[308] = 0.0;
   out_128560542949297932[309] = 0.0;
   out_128560542949297932[310] = 0.0;
   out_128560542949297932[311] = 0.0;
   out_128560542949297932[312] = 0.0;
   out_128560542949297932[313] = 0.0;
   out_128560542949297932[314] = 0.0;
   out_128560542949297932[315] = 0.0;
   out_128560542949297932[316] = 0.0;
   out_128560542949297932[317] = 0.0;
   out_128560542949297932[318] = 0.0;
   out_128560542949297932[319] = 0.0;
   out_128560542949297932[320] = 0.0;
   out_128560542949297932[321] = 0.0;
   out_128560542949297932[322] = 0.0;
   out_128560542949297932[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_7884286617494058224) {
   out_7884286617494058224[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_7884286617494058224[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_7884286617494058224[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_7884286617494058224[3] = dt*state[12] + state[3];
   out_7884286617494058224[4] = dt*state[13] + state[4];
   out_7884286617494058224[5] = dt*state[14] + state[5];
   out_7884286617494058224[6] = state[6];
   out_7884286617494058224[7] = state[7];
   out_7884286617494058224[8] = state[8];
   out_7884286617494058224[9] = state[9];
   out_7884286617494058224[10] = state[10];
   out_7884286617494058224[11] = state[11];
   out_7884286617494058224[12] = state[12];
   out_7884286617494058224[13] = state[13];
   out_7884286617494058224[14] = state[14];
   out_7884286617494058224[15] = state[15];
   out_7884286617494058224[16] = state[16];
   out_7884286617494058224[17] = state[17];
}
void F_fun(double *state, double dt, double *out_2375412256629136437) {
   out_2375412256629136437[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2375412256629136437[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2375412256629136437[2] = 0;
   out_2375412256629136437[3] = 0;
   out_2375412256629136437[4] = 0;
   out_2375412256629136437[5] = 0;
   out_2375412256629136437[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2375412256629136437[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2375412256629136437[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_2375412256629136437[9] = 0;
   out_2375412256629136437[10] = 0;
   out_2375412256629136437[11] = 0;
   out_2375412256629136437[12] = 0;
   out_2375412256629136437[13] = 0;
   out_2375412256629136437[14] = 0;
   out_2375412256629136437[15] = 0;
   out_2375412256629136437[16] = 0;
   out_2375412256629136437[17] = 0;
   out_2375412256629136437[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2375412256629136437[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2375412256629136437[20] = 0;
   out_2375412256629136437[21] = 0;
   out_2375412256629136437[22] = 0;
   out_2375412256629136437[23] = 0;
   out_2375412256629136437[24] = 0;
   out_2375412256629136437[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2375412256629136437[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_2375412256629136437[27] = 0;
   out_2375412256629136437[28] = 0;
   out_2375412256629136437[29] = 0;
   out_2375412256629136437[30] = 0;
   out_2375412256629136437[31] = 0;
   out_2375412256629136437[32] = 0;
   out_2375412256629136437[33] = 0;
   out_2375412256629136437[34] = 0;
   out_2375412256629136437[35] = 0;
   out_2375412256629136437[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2375412256629136437[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2375412256629136437[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2375412256629136437[39] = 0;
   out_2375412256629136437[40] = 0;
   out_2375412256629136437[41] = 0;
   out_2375412256629136437[42] = 0;
   out_2375412256629136437[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2375412256629136437[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_2375412256629136437[45] = 0;
   out_2375412256629136437[46] = 0;
   out_2375412256629136437[47] = 0;
   out_2375412256629136437[48] = 0;
   out_2375412256629136437[49] = 0;
   out_2375412256629136437[50] = 0;
   out_2375412256629136437[51] = 0;
   out_2375412256629136437[52] = 0;
   out_2375412256629136437[53] = 0;
   out_2375412256629136437[54] = 0;
   out_2375412256629136437[55] = 0;
   out_2375412256629136437[56] = 0;
   out_2375412256629136437[57] = 1;
   out_2375412256629136437[58] = 0;
   out_2375412256629136437[59] = 0;
   out_2375412256629136437[60] = 0;
   out_2375412256629136437[61] = 0;
   out_2375412256629136437[62] = 0;
   out_2375412256629136437[63] = 0;
   out_2375412256629136437[64] = 0;
   out_2375412256629136437[65] = 0;
   out_2375412256629136437[66] = dt;
   out_2375412256629136437[67] = 0;
   out_2375412256629136437[68] = 0;
   out_2375412256629136437[69] = 0;
   out_2375412256629136437[70] = 0;
   out_2375412256629136437[71] = 0;
   out_2375412256629136437[72] = 0;
   out_2375412256629136437[73] = 0;
   out_2375412256629136437[74] = 0;
   out_2375412256629136437[75] = 0;
   out_2375412256629136437[76] = 1;
   out_2375412256629136437[77] = 0;
   out_2375412256629136437[78] = 0;
   out_2375412256629136437[79] = 0;
   out_2375412256629136437[80] = 0;
   out_2375412256629136437[81] = 0;
   out_2375412256629136437[82] = 0;
   out_2375412256629136437[83] = 0;
   out_2375412256629136437[84] = 0;
   out_2375412256629136437[85] = dt;
   out_2375412256629136437[86] = 0;
   out_2375412256629136437[87] = 0;
   out_2375412256629136437[88] = 0;
   out_2375412256629136437[89] = 0;
   out_2375412256629136437[90] = 0;
   out_2375412256629136437[91] = 0;
   out_2375412256629136437[92] = 0;
   out_2375412256629136437[93] = 0;
   out_2375412256629136437[94] = 0;
   out_2375412256629136437[95] = 1;
   out_2375412256629136437[96] = 0;
   out_2375412256629136437[97] = 0;
   out_2375412256629136437[98] = 0;
   out_2375412256629136437[99] = 0;
   out_2375412256629136437[100] = 0;
   out_2375412256629136437[101] = 0;
   out_2375412256629136437[102] = 0;
   out_2375412256629136437[103] = 0;
   out_2375412256629136437[104] = dt;
   out_2375412256629136437[105] = 0;
   out_2375412256629136437[106] = 0;
   out_2375412256629136437[107] = 0;
   out_2375412256629136437[108] = 0;
   out_2375412256629136437[109] = 0;
   out_2375412256629136437[110] = 0;
   out_2375412256629136437[111] = 0;
   out_2375412256629136437[112] = 0;
   out_2375412256629136437[113] = 0;
   out_2375412256629136437[114] = 1;
   out_2375412256629136437[115] = 0;
   out_2375412256629136437[116] = 0;
   out_2375412256629136437[117] = 0;
   out_2375412256629136437[118] = 0;
   out_2375412256629136437[119] = 0;
   out_2375412256629136437[120] = 0;
   out_2375412256629136437[121] = 0;
   out_2375412256629136437[122] = 0;
   out_2375412256629136437[123] = 0;
   out_2375412256629136437[124] = 0;
   out_2375412256629136437[125] = 0;
   out_2375412256629136437[126] = 0;
   out_2375412256629136437[127] = 0;
   out_2375412256629136437[128] = 0;
   out_2375412256629136437[129] = 0;
   out_2375412256629136437[130] = 0;
   out_2375412256629136437[131] = 0;
   out_2375412256629136437[132] = 0;
   out_2375412256629136437[133] = 1;
   out_2375412256629136437[134] = 0;
   out_2375412256629136437[135] = 0;
   out_2375412256629136437[136] = 0;
   out_2375412256629136437[137] = 0;
   out_2375412256629136437[138] = 0;
   out_2375412256629136437[139] = 0;
   out_2375412256629136437[140] = 0;
   out_2375412256629136437[141] = 0;
   out_2375412256629136437[142] = 0;
   out_2375412256629136437[143] = 0;
   out_2375412256629136437[144] = 0;
   out_2375412256629136437[145] = 0;
   out_2375412256629136437[146] = 0;
   out_2375412256629136437[147] = 0;
   out_2375412256629136437[148] = 0;
   out_2375412256629136437[149] = 0;
   out_2375412256629136437[150] = 0;
   out_2375412256629136437[151] = 0;
   out_2375412256629136437[152] = 1;
   out_2375412256629136437[153] = 0;
   out_2375412256629136437[154] = 0;
   out_2375412256629136437[155] = 0;
   out_2375412256629136437[156] = 0;
   out_2375412256629136437[157] = 0;
   out_2375412256629136437[158] = 0;
   out_2375412256629136437[159] = 0;
   out_2375412256629136437[160] = 0;
   out_2375412256629136437[161] = 0;
   out_2375412256629136437[162] = 0;
   out_2375412256629136437[163] = 0;
   out_2375412256629136437[164] = 0;
   out_2375412256629136437[165] = 0;
   out_2375412256629136437[166] = 0;
   out_2375412256629136437[167] = 0;
   out_2375412256629136437[168] = 0;
   out_2375412256629136437[169] = 0;
   out_2375412256629136437[170] = 0;
   out_2375412256629136437[171] = 1;
   out_2375412256629136437[172] = 0;
   out_2375412256629136437[173] = 0;
   out_2375412256629136437[174] = 0;
   out_2375412256629136437[175] = 0;
   out_2375412256629136437[176] = 0;
   out_2375412256629136437[177] = 0;
   out_2375412256629136437[178] = 0;
   out_2375412256629136437[179] = 0;
   out_2375412256629136437[180] = 0;
   out_2375412256629136437[181] = 0;
   out_2375412256629136437[182] = 0;
   out_2375412256629136437[183] = 0;
   out_2375412256629136437[184] = 0;
   out_2375412256629136437[185] = 0;
   out_2375412256629136437[186] = 0;
   out_2375412256629136437[187] = 0;
   out_2375412256629136437[188] = 0;
   out_2375412256629136437[189] = 0;
   out_2375412256629136437[190] = 1;
   out_2375412256629136437[191] = 0;
   out_2375412256629136437[192] = 0;
   out_2375412256629136437[193] = 0;
   out_2375412256629136437[194] = 0;
   out_2375412256629136437[195] = 0;
   out_2375412256629136437[196] = 0;
   out_2375412256629136437[197] = 0;
   out_2375412256629136437[198] = 0;
   out_2375412256629136437[199] = 0;
   out_2375412256629136437[200] = 0;
   out_2375412256629136437[201] = 0;
   out_2375412256629136437[202] = 0;
   out_2375412256629136437[203] = 0;
   out_2375412256629136437[204] = 0;
   out_2375412256629136437[205] = 0;
   out_2375412256629136437[206] = 0;
   out_2375412256629136437[207] = 0;
   out_2375412256629136437[208] = 0;
   out_2375412256629136437[209] = 1;
   out_2375412256629136437[210] = 0;
   out_2375412256629136437[211] = 0;
   out_2375412256629136437[212] = 0;
   out_2375412256629136437[213] = 0;
   out_2375412256629136437[214] = 0;
   out_2375412256629136437[215] = 0;
   out_2375412256629136437[216] = 0;
   out_2375412256629136437[217] = 0;
   out_2375412256629136437[218] = 0;
   out_2375412256629136437[219] = 0;
   out_2375412256629136437[220] = 0;
   out_2375412256629136437[221] = 0;
   out_2375412256629136437[222] = 0;
   out_2375412256629136437[223] = 0;
   out_2375412256629136437[224] = 0;
   out_2375412256629136437[225] = 0;
   out_2375412256629136437[226] = 0;
   out_2375412256629136437[227] = 0;
   out_2375412256629136437[228] = 1;
   out_2375412256629136437[229] = 0;
   out_2375412256629136437[230] = 0;
   out_2375412256629136437[231] = 0;
   out_2375412256629136437[232] = 0;
   out_2375412256629136437[233] = 0;
   out_2375412256629136437[234] = 0;
   out_2375412256629136437[235] = 0;
   out_2375412256629136437[236] = 0;
   out_2375412256629136437[237] = 0;
   out_2375412256629136437[238] = 0;
   out_2375412256629136437[239] = 0;
   out_2375412256629136437[240] = 0;
   out_2375412256629136437[241] = 0;
   out_2375412256629136437[242] = 0;
   out_2375412256629136437[243] = 0;
   out_2375412256629136437[244] = 0;
   out_2375412256629136437[245] = 0;
   out_2375412256629136437[246] = 0;
   out_2375412256629136437[247] = 1;
   out_2375412256629136437[248] = 0;
   out_2375412256629136437[249] = 0;
   out_2375412256629136437[250] = 0;
   out_2375412256629136437[251] = 0;
   out_2375412256629136437[252] = 0;
   out_2375412256629136437[253] = 0;
   out_2375412256629136437[254] = 0;
   out_2375412256629136437[255] = 0;
   out_2375412256629136437[256] = 0;
   out_2375412256629136437[257] = 0;
   out_2375412256629136437[258] = 0;
   out_2375412256629136437[259] = 0;
   out_2375412256629136437[260] = 0;
   out_2375412256629136437[261] = 0;
   out_2375412256629136437[262] = 0;
   out_2375412256629136437[263] = 0;
   out_2375412256629136437[264] = 0;
   out_2375412256629136437[265] = 0;
   out_2375412256629136437[266] = 1;
   out_2375412256629136437[267] = 0;
   out_2375412256629136437[268] = 0;
   out_2375412256629136437[269] = 0;
   out_2375412256629136437[270] = 0;
   out_2375412256629136437[271] = 0;
   out_2375412256629136437[272] = 0;
   out_2375412256629136437[273] = 0;
   out_2375412256629136437[274] = 0;
   out_2375412256629136437[275] = 0;
   out_2375412256629136437[276] = 0;
   out_2375412256629136437[277] = 0;
   out_2375412256629136437[278] = 0;
   out_2375412256629136437[279] = 0;
   out_2375412256629136437[280] = 0;
   out_2375412256629136437[281] = 0;
   out_2375412256629136437[282] = 0;
   out_2375412256629136437[283] = 0;
   out_2375412256629136437[284] = 0;
   out_2375412256629136437[285] = 1;
   out_2375412256629136437[286] = 0;
   out_2375412256629136437[287] = 0;
   out_2375412256629136437[288] = 0;
   out_2375412256629136437[289] = 0;
   out_2375412256629136437[290] = 0;
   out_2375412256629136437[291] = 0;
   out_2375412256629136437[292] = 0;
   out_2375412256629136437[293] = 0;
   out_2375412256629136437[294] = 0;
   out_2375412256629136437[295] = 0;
   out_2375412256629136437[296] = 0;
   out_2375412256629136437[297] = 0;
   out_2375412256629136437[298] = 0;
   out_2375412256629136437[299] = 0;
   out_2375412256629136437[300] = 0;
   out_2375412256629136437[301] = 0;
   out_2375412256629136437[302] = 0;
   out_2375412256629136437[303] = 0;
   out_2375412256629136437[304] = 1;
   out_2375412256629136437[305] = 0;
   out_2375412256629136437[306] = 0;
   out_2375412256629136437[307] = 0;
   out_2375412256629136437[308] = 0;
   out_2375412256629136437[309] = 0;
   out_2375412256629136437[310] = 0;
   out_2375412256629136437[311] = 0;
   out_2375412256629136437[312] = 0;
   out_2375412256629136437[313] = 0;
   out_2375412256629136437[314] = 0;
   out_2375412256629136437[315] = 0;
   out_2375412256629136437[316] = 0;
   out_2375412256629136437[317] = 0;
   out_2375412256629136437[318] = 0;
   out_2375412256629136437[319] = 0;
   out_2375412256629136437[320] = 0;
   out_2375412256629136437[321] = 0;
   out_2375412256629136437[322] = 0;
   out_2375412256629136437[323] = 1;
}
void h_4(double *state, double *unused, double *out_5426853226755395774) {
   out_5426853226755395774[0] = state[6] + state[9];
   out_5426853226755395774[1] = state[7] + state[10];
   out_5426853226755395774[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_1069386938933600172) {
   out_1069386938933600172[0] = 0;
   out_1069386938933600172[1] = 0;
   out_1069386938933600172[2] = 0;
   out_1069386938933600172[3] = 0;
   out_1069386938933600172[4] = 0;
   out_1069386938933600172[5] = 0;
   out_1069386938933600172[6] = 1;
   out_1069386938933600172[7] = 0;
   out_1069386938933600172[8] = 0;
   out_1069386938933600172[9] = 1;
   out_1069386938933600172[10] = 0;
   out_1069386938933600172[11] = 0;
   out_1069386938933600172[12] = 0;
   out_1069386938933600172[13] = 0;
   out_1069386938933600172[14] = 0;
   out_1069386938933600172[15] = 0;
   out_1069386938933600172[16] = 0;
   out_1069386938933600172[17] = 0;
   out_1069386938933600172[18] = 0;
   out_1069386938933600172[19] = 0;
   out_1069386938933600172[20] = 0;
   out_1069386938933600172[21] = 0;
   out_1069386938933600172[22] = 0;
   out_1069386938933600172[23] = 0;
   out_1069386938933600172[24] = 0;
   out_1069386938933600172[25] = 1;
   out_1069386938933600172[26] = 0;
   out_1069386938933600172[27] = 0;
   out_1069386938933600172[28] = 1;
   out_1069386938933600172[29] = 0;
   out_1069386938933600172[30] = 0;
   out_1069386938933600172[31] = 0;
   out_1069386938933600172[32] = 0;
   out_1069386938933600172[33] = 0;
   out_1069386938933600172[34] = 0;
   out_1069386938933600172[35] = 0;
   out_1069386938933600172[36] = 0;
   out_1069386938933600172[37] = 0;
   out_1069386938933600172[38] = 0;
   out_1069386938933600172[39] = 0;
   out_1069386938933600172[40] = 0;
   out_1069386938933600172[41] = 0;
   out_1069386938933600172[42] = 0;
   out_1069386938933600172[43] = 0;
   out_1069386938933600172[44] = 1;
   out_1069386938933600172[45] = 0;
   out_1069386938933600172[46] = 0;
   out_1069386938933600172[47] = 1;
   out_1069386938933600172[48] = 0;
   out_1069386938933600172[49] = 0;
   out_1069386938933600172[50] = 0;
   out_1069386938933600172[51] = 0;
   out_1069386938933600172[52] = 0;
   out_1069386938933600172[53] = 0;
}
void h_10(double *state, double *unused, double *out_9020263373970964705) {
   out_9020263373970964705[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_9020263373970964705[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_9020263373970964705[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_1175983645882290527) {
   out_1175983645882290527[0] = 0;
   out_1175983645882290527[1] = 9.8100000000000005*cos(state[1]);
   out_1175983645882290527[2] = 0;
   out_1175983645882290527[3] = 0;
   out_1175983645882290527[4] = -state[8];
   out_1175983645882290527[5] = state[7];
   out_1175983645882290527[6] = 0;
   out_1175983645882290527[7] = state[5];
   out_1175983645882290527[8] = -state[4];
   out_1175983645882290527[9] = 0;
   out_1175983645882290527[10] = 0;
   out_1175983645882290527[11] = 0;
   out_1175983645882290527[12] = 1;
   out_1175983645882290527[13] = 0;
   out_1175983645882290527[14] = 0;
   out_1175983645882290527[15] = 1;
   out_1175983645882290527[16] = 0;
   out_1175983645882290527[17] = 0;
   out_1175983645882290527[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_1175983645882290527[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_1175983645882290527[20] = 0;
   out_1175983645882290527[21] = state[8];
   out_1175983645882290527[22] = 0;
   out_1175983645882290527[23] = -state[6];
   out_1175983645882290527[24] = -state[5];
   out_1175983645882290527[25] = 0;
   out_1175983645882290527[26] = state[3];
   out_1175983645882290527[27] = 0;
   out_1175983645882290527[28] = 0;
   out_1175983645882290527[29] = 0;
   out_1175983645882290527[30] = 0;
   out_1175983645882290527[31] = 1;
   out_1175983645882290527[32] = 0;
   out_1175983645882290527[33] = 0;
   out_1175983645882290527[34] = 1;
   out_1175983645882290527[35] = 0;
   out_1175983645882290527[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_1175983645882290527[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_1175983645882290527[38] = 0;
   out_1175983645882290527[39] = -state[7];
   out_1175983645882290527[40] = state[6];
   out_1175983645882290527[41] = 0;
   out_1175983645882290527[42] = state[4];
   out_1175983645882290527[43] = -state[3];
   out_1175983645882290527[44] = 0;
   out_1175983645882290527[45] = 0;
   out_1175983645882290527[46] = 0;
   out_1175983645882290527[47] = 0;
   out_1175983645882290527[48] = 0;
   out_1175983645882290527[49] = 0;
   out_1175983645882290527[50] = 1;
   out_1175983645882290527[51] = 0;
   out_1175983645882290527[52] = 0;
   out_1175983645882290527[53] = 1;
}
void h_13(double *state, double *unused, double *out_7873459457849635199) {
   out_7873459457849635199[0] = state[3];
   out_7873459457849635199[1] = state[4];
   out_7873459457849635199[2] = state[5];
}
void H_13(double *state, double *unused, double *out_4281660764265932973) {
   out_4281660764265932973[0] = 0;
   out_4281660764265932973[1] = 0;
   out_4281660764265932973[2] = 0;
   out_4281660764265932973[3] = 1;
   out_4281660764265932973[4] = 0;
   out_4281660764265932973[5] = 0;
   out_4281660764265932973[6] = 0;
   out_4281660764265932973[7] = 0;
   out_4281660764265932973[8] = 0;
   out_4281660764265932973[9] = 0;
   out_4281660764265932973[10] = 0;
   out_4281660764265932973[11] = 0;
   out_4281660764265932973[12] = 0;
   out_4281660764265932973[13] = 0;
   out_4281660764265932973[14] = 0;
   out_4281660764265932973[15] = 0;
   out_4281660764265932973[16] = 0;
   out_4281660764265932973[17] = 0;
   out_4281660764265932973[18] = 0;
   out_4281660764265932973[19] = 0;
   out_4281660764265932973[20] = 0;
   out_4281660764265932973[21] = 0;
   out_4281660764265932973[22] = 1;
   out_4281660764265932973[23] = 0;
   out_4281660764265932973[24] = 0;
   out_4281660764265932973[25] = 0;
   out_4281660764265932973[26] = 0;
   out_4281660764265932973[27] = 0;
   out_4281660764265932973[28] = 0;
   out_4281660764265932973[29] = 0;
   out_4281660764265932973[30] = 0;
   out_4281660764265932973[31] = 0;
   out_4281660764265932973[32] = 0;
   out_4281660764265932973[33] = 0;
   out_4281660764265932973[34] = 0;
   out_4281660764265932973[35] = 0;
   out_4281660764265932973[36] = 0;
   out_4281660764265932973[37] = 0;
   out_4281660764265932973[38] = 0;
   out_4281660764265932973[39] = 0;
   out_4281660764265932973[40] = 0;
   out_4281660764265932973[41] = 1;
   out_4281660764265932973[42] = 0;
   out_4281660764265932973[43] = 0;
   out_4281660764265932973[44] = 0;
   out_4281660764265932973[45] = 0;
   out_4281660764265932973[46] = 0;
   out_4281660764265932973[47] = 0;
   out_4281660764265932973[48] = 0;
   out_4281660764265932973[49] = 0;
   out_4281660764265932973[50] = 0;
   out_4281660764265932973[51] = 0;
   out_4281660764265932973[52] = 0;
   out_4281660764265932973[53] = 0;
}
void h_14(double *state, double *unused, double *out_3056352778676871730) {
   out_3056352778676871730[0] = state[6];
   out_3056352778676871730[1] = state[7];
   out_3056352778676871730[2] = state[8];
}
void H_14(double *state, double *unused, double *out_2013401493361772124) {
   out_2013401493361772124[0] = 0;
   out_2013401493361772124[1] = 0;
   out_2013401493361772124[2] = 0;
   out_2013401493361772124[3] = 0;
   out_2013401493361772124[4] = 0;
   out_2013401493361772124[5] = 0;
   out_2013401493361772124[6] = 1;
   out_2013401493361772124[7] = 0;
   out_2013401493361772124[8] = 0;
   out_2013401493361772124[9] = 0;
   out_2013401493361772124[10] = 0;
   out_2013401493361772124[11] = 0;
   out_2013401493361772124[12] = 0;
   out_2013401493361772124[13] = 0;
   out_2013401493361772124[14] = 0;
   out_2013401493361772124[15] = 0;
   out_2013401493361772124[16] = 0;
   out_2013401493361772124[17] = 0;
   out_2013401493361772124[18] = 0;
   out_2013401493361772124[19] = 0;
   out_2013401493361772124[20] = 0;
   out_2013401493361772124[21] = 0;
   out_2013401493361772124[22] = 0;
   out_2013401493361772124[23] = 0;
   out_2013401493361772124[24] = 0;
   out_2013401493361772124[25] = 1;
   out_2013401493361772124[26] = 0;
   out_2013401493361772124[27] = 0;
   out_2013401493361772124[28] = 0;
   out_2013401493361772124[29] = 0;
   out_2013401493361772124[30] = 0;
   out_2013401493361772124[31] = 0;
   out_2013401493361772124[32] = 0;
   out_2013401493361772124[33] = 0;
   out_2013401493361772124[34] = 0;
   out_2013401493361772124[35] = 0;
   out_2013401493361772124[36] = 0;
   out_2013401493361772124[37] = 0;
   out_2013401493361772124[38] = 0;
   out_2013401493361772124[39] = 0;
   out_2013401493361772124[40] = 0;
   out_2013401493361772124[41] = 0;
   out_2013401493361772124[42] = 0;
   out_2013401493361772124[43] = 0;
   out_2013401493361772124[44] = 1;
   out_2013401493361772124[45] = 0;
   out_2013401493361772124[46] = 0;
   out_2013401493361772124[47] = 0;
   out_2013401493361772124[48] = 0;
   out_2013401493361772124[49] = 0;
   out_2013401493361772124[50] = 0;
   out_2013401493361772124[51] = 0;
   out_2013401493361772124[52] = 0;
   out_2013401493361772124[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_6021173093259519341) {
  err_fun(nom_x, delta_x, out_6021173093259519341);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_3203995659568275494) {
  inv_err_fun(nom_x, true_x, out_3203995659568275494);
}
void pose_H_mod_fun(double *state, double *out_128560542949297932) {
  H_mod_fun(state, out_128560542949297932);
}
void pose_f_fun(double *state, double dt, double *out_7884286617494058224) {
  f_fun(state,  dt, out_7884286617494058224);
}
void pose_F_fun(double *state, double dt, double *out_2375412256629136437) {
  F_fun(state,  dt, out_2375412256629136437);
}
void pose_h_4(double *state, double *unused, double *out_5426853226755395774) {
  h_4(state, unused, out_5426853226755395774);
}
void pose_H_4(double *state, double *unused, double *out_1069386938933600172) {
  H_4(state, unused, out_1069386938933600172);
}
void pose_h_10(double *state, double *unused, double *out_9020263373970964705) {
  h_10(state, unused, out_9020263373970964705);
}
void pose_H_10(double *state, double *unused, double *out_1175983645882290527) {
  H_10(state, unused, out_1175983645882290527);
}
void pose_h_13(double *state, double *unused, double *out_7873459457849635199) {
  h_13(state, unused, out_7873459457849635199);
}
void pose_H_13(double *state, double *unused, double *out_4281660764265932973) {
  H_13(state, unused, out_4281660764265932973);
}
void pose_h_14(double *state, double *unused, double *out_3056352778676871730) {
  h_14(state, unused, out_3056352778676871730);
}
void pose_H_14(double *state, double *unused, double *out_2013401493361772124) {
  H_14(state, unused, out_2013401493361772124);
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
