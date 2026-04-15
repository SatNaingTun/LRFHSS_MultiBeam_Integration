import numpy as np

# Physical / radio constants
EARTRH_G = 9.80665
EARTRH_R = 6371000
SAT_H = 600000
SAT_RANGE = 1500000
HDR_TIME = 0.233472
FRG_TIME = 0.1024
OBW_BW = 488.28125
OCW_RX_BW = 200000
OCW_FC = 868100000
GAIN_TX = 2.5
GAIN_RX = 22.6
TX_PWR_DB = 30

# Detection / collision thresholds
TH2 = 0
SYM_THRESH = 0.2

# Frame layout bounds
MIN_FRGS = 8
MAX_FRGS = 31
MAX_HDRS = 3

# Derived radio values
AWGN_VAR_DB = -174 + 6 + 10 * np.log10(OBW_BW)
MAX_FRM_TM = MAX_HDRS * HDR_TIME + MAX_FRGS * FRG_TIME

# Simulation parameters
runs = 1
simTime = 912
numOCW = 7
numOBW = 280
numGrids = 8
timeGranularity = 6
freqGranularity = 25
numDecoders = 100
CR = 1
use_earlydecode = True
use_earlydrop = True
use_headerdrop = False
linkBudgetLog = True
