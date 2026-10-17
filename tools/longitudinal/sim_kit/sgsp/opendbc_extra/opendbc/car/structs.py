import os
import capnp
from opendbc.car.common.basedir import BASEDIR

capnp.remove_import_hook()
from cereal import car  # replay: our schema (CarParams come from our logs); same capnp IDs, loading both aborts

CarState = car.CarState
RadarData = car.RadarData
CarControl = car.CarControl
CarParams = car.CarParams

CarStateT = capnp.lib.capnp._StructModule
RadarDataT = capnp.lib.capnp._StructModule
CarControlT = capnp.lib.capnp._StructModule
CarParamsT = capnp.lib.capnp._StructModule
