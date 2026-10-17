#!/bin/bash
# Rebuild the SGSP long MPC for x86_64 (the .so files are gitignored). Run from the repo root.
#   tools/longitudinal/sim_kit/sgsp_tools/build_mpc.sh
set -e
R=$PWD; A=$R/third_party/acados
export ACADOS_SOURCE_DIR=$A ACADOS_PYTHON_INTERFACE_PATH=$A/acados_template TERA_PATH=$A/x86_64/t_renderer LD_LIBRARY_PATH=$A/x86_64/lib
PYTHONPATH=.:tools:third_party/acados .venv/bin/python tools/longitudinal/sim_kit/sgsp_tools/gen_mpc.py
cd tools/longitudinal/sim_kit/sgsp/openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code
SRC="acados_solver_long.c $(ls long_model/*.c long_cost/*.c long_constraints/*.c)"
gcc -O2 -fPIC -shared -DACADOS_WITH_QPOASES -Wno-unused -I. -I$A/include -I$A/include/acados -I$A/include/blasfeo/include \
  -I$A/include/hpipm/include -I$A/include/qpOASES_e -o libacados_ocp_solver_long.so $SRC -L$A/x86_64/lib \
  -lacados -lhpipm -lblasfeo -lqpOASES_e -lm -Wl,--disable-new-dtags -Wl,-rpath,$A/x86_64/lib
$R/.venv/bin/cython -o acados_ocp_solver_pyx.c -I . -I $A/acados_template $A/acados_template/acados_ocp_solver_pyx.pyx
PI=$($R/.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['include'])")
NI=$($R/.venv/bin/python -c "import numpy; print(numpy.get_include())")
gcc -O2 -fPIC -shared -I. -I$PI -I$NI -I$A/include -I$A/include/acados -I$A/include/blasfeo/include -I$A/include/hpipm/include \
  -I$A/acados_template -o acados_ocp_solver_pyx.so acados_ocp_solver_pyx.c -L. -lacados_ocp_solver_long \
  -Wl,--disable-new-dtags -Wl,-rpath,'$ORIGIN' -Wl,-rpath,$A/x86_64/lib
ls -la *.so
