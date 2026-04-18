import numpy as np
import random
from LRFHSS.base.base import dBm2mW
from ProjectConfig import EARTRH_G, EARTRH_R, SAT_H

def get_coverageTime(r):

	R = 6371000 # m
	H = 600000  # m, satellite altitude
	v = 7562    # m/s

	x = (R**2 + (R+H)**2 - r**2) / (2*R*(R+H))
	theta = np.arccos(x)

	return theta * (R+H) / v





def get_visibility_time(d):
    
    E = np.arcsin( (SAT_H**2 + 2*SAT_H*EARTRH_R - d**2) / (2*d*EARTRH_R) ) # elevation angle
    dg = EARTRH_R * np.arcsin( d*np.cos(E) / (EARTRH_R+SAT_H) )            # ground range
    v = np.sqrt( EARTRH_G*EARTRH_R / (1 + SAT_H/EARTRH_R) )                # satellite velocity
    tau = dg / v                                                           # half satellite visibility time
    
    return tau

def get_FS_pathloss(d, f):
    c = 299792458  # m/s
    return (c / (4*np.pi*d*f))**2


def get_distance(sensitivity_dBm):

	c = 299792458  # m/s
	fc = 868000000 # hz, carrier frequency

	sensitivity_mW = dBm2mW(sensitivity_dBm)
	TXpower = dBm2mW(14)
	Txgain = dBm2mW(0)
	RXgain = dBm2mW(5)
	
	a = np.sqrt(sensitivity_mW/(TXpower*Txgain*RXgain))

	return c/(4*np.pi*a*fc)

def get_coverageRadius(maxRange):

	R = 6371000 # m
	H = 600000  # m, satellite altitude

	x = 2*R*R + 2*H*R

	z = (x + H**2 - maxRange**2) / x
	beta = np.arccos(z)

	return beta*R


def dopplerShift(t):

	c = 299792458  # m/s
	g = 9.80665    # m/s2
	R = 6371000    # m
	H = 600000     # m,  satellite altitude
	fc = 868000000 # hz, carrier frequency

	x = 1 + H/R

	a = fc / c

	b = np.sqrt(g*R/x)

	psi = t * np.sqrt(g/R) / np.sqrt(np.power(x, 3))

	c = np.sin(psi) / np.sqrt(np.power(x,2) - 2*x*np.cos(psi) + 1)

	return a*b*c


def get_randomDoppler() -> float:

    sensitivity = -137
    maxRange = get_distance(sensitivity)
    Rcov = get_coverageRadius(maxRange)
    Tcov = get_coverageTime(Rcov)

    r0 =  np.sqrt(random.uniform(0,1))
    theta0 = 2 * np.pi * random.uniform(0,1)

    t0 = r0 * np.cos(theta0) * Tcov

    return dopplerShift(t0)
