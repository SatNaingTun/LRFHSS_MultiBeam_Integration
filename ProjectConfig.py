import numpy as np

# Physical / radio constants
EARTRH_G = 9.80665
EARTRH_R = 6371000
SAT_H = 600000
SAT_RANGE = 1500000
R_FOOTPRINT = 100000.0
V_SATELLITE = 7560.0
# T_FRAME = 0.01
T_FRAME = 1.0
SPEED_OF_LIGHT = 299792458.0
CENTER_FREQUENCY_HZ = 30000000000.0
ANTENNA_SPACING_M = SPEED_OF_LIGHT / CENTER_FREQUENCY_HZ / 2.0
N_ANTENNA_X = 32
N_ANTENNA_Y = 32
N_BEAMS_X = 5
N_BEAMS_Y = 4
LATITUDE_CENTER_DEG = 35.6761919
LONGITUDE_CENTER_DEG = 139.6503106
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

# Atmospheric parameters for ITU model
p = 0.5  # Precipitation probability (%)
D = 1.0  # Rain drop diameter (mm)

# Channel fading parameters
rician_k = 10.0  # Rician K-factor for satellite channel fading

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

node_population_ratio = 0.00001
demd_population_ratio = 0.000001

baseline_power=35
idle_demodulator_power=0.12
busy_demodulator_power=0.8

elev_list = [90.0, 55.0, 25.0]