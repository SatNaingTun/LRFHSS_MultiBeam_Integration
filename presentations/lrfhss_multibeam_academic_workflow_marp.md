---

# LR-FHSS: Overview and Performance Analysis (2021)
### N. Boquet et al.

## Problem Definition

- Evaluate LEO LR-FHSS uplink performance:
  - reliability (decoded payload)
  - interference (collision, SINR)
  - energy (power)

## Output Metrics

- decoded payload per time & region  
- collision rate  
- SNR / SINR distributions  
- power consumption  

<!--
This slide defines the research problem and evaluation metrics.
marp: true
-->

---

# End-to-End Workflow
### Based on LR-FHSS Framework and 3GPP TR 38.811

## Cross-Layer Pipeline

- Orbit → satellite position  
- Coverage → user distribution  
- Load → active devices  
- Channel → SNR / SINR  
- Decoding → successful packets  
- Power → energy consumption  

<!--
This slide explains the full workflow.
Each stage depends on the previous one.
-->

---

# Fundamentals of Astrodynamics and Applications
### D. A. Vallado

$$
n=\sqrt{\frac{\mu}{a^3}}, \quad M(t)=M_0+n(t-t_0)
$$

- $n$: mean motion  
- $a$: semi-major axis  
- $\mu$: gravitational constant  

<!--
Keplerian orbit propagation defines satellite motion.
-->

---

# Orbital Mechanics for Engineering Students
### H. D. Curtis

$$
d(\psi)=\sqrt{(R_E+h)^2+R_E^2-2R_E(R_E+h)\cos\psi}
$$

- $d$: slant distance  
- $R_E$: Earth radius  
- $h$: altitude  
- $\psi$: central angle  

<!--
Distance varies with geometry and affects signal strength.
-->

---

# Study on NR to Support NTN (TR 38.811)
### 3GPP

$$
\xi_c(t)=\frac{A_{overlap,c}}{A_c}, \quad
P_{eff}(t)=\sum_c P_c \xi_c(t)
$$

- $\xi_c$: coverage ratio  
- $P_c$: population  

<!--
Coverage maps geometry to user distribution.
-->

---

# LR-FHSS: Overview and Performance Analysis (2021)
### N. Boquet et al.

$$
N_{dev}(t)=\rho P_{eff}(t), \quad
D(t)=\left\lceil \frac{N_{dev}(t)}{C_{dev/demod}} \right\rceil
$$

- $\rho$: penetration factor  
- $D$: demodulators  

<!--
Load determines number of active devices.
-->

---

# A Note on a Simple Transmission Formula (1946)
### H. T. Friis

$$
L_{tot}=20\log_{10}\left(\frac{4\pi d f_c}{c}\right)+A_{atm}
$$

- $d$: distance  
- $f_c$: frequency  
- $A_{atm}$: atmospheric loss  

<!--
Channel loss depends on distance and environment.
-->

---

# A Mathematical Theory of Communication (1948)
### C. E. Shannon

$$
N=k_BTB F, \quad \mathrm{SNR}=\frac{P_{sig}}{N}
$$

- $k_B$: Boltzmann constant  
- $B$: bandwidth  
- $F$: noise figure  

<!--
SNR defines signal quality baseline.
-->

---

# Study on NR to Support NTN (TR 38.811)
### 3GPP

$$
\mathrm{SINR}=\frac{|h_{u,b^*}|^2}{\sum_{b\neq b^*}|h_{u,b}|^2+N}
$$

- $h_{u,b}$: channel gain  
- $b^*$: selected beam  

<!--
SINR includes interference from other beams.
-->

---

# Enhancing LR-FHSS Scalability Through Advanced Sequence Design and Demodulator Allocation
### (Diego et al.)

$$
Y_{c,t}=f_d(n_{c,t}), \quad
\gamma_{c,t}=1-\frac{Y_{c,t}}{n_{c,t}}
$$

- $Y$: decoded packets  
- $\gamma$: collision  

<!--
Decoding determines successful transmission.
-->

---

# The ALOHA System (1970)
### N. Abramson

$$
\gamma_t=1-\frac{\sum_c Y_{c,t}}{\sum_c n_{c,t}}
$$

- system-level collision  

<!--
Collision aggregated across all users.
-->

---

# Study on NR to Support NTN (TR 38.811)
### 3GPP

$$
P_{tot}=P_0+N_{idle}P_{idle}+N_{busy}P_{busy}
$$

- $P_{tot}$: total power  

<!--
Power depends on system load.
-->

---

# Conclusion — This Work

| **Contributions** | **Key Findings** |
|------------------|-----------------|
| Unified cross-layer framework | Geometry drives SNR/SINR |
| Integrated orbit, channel, decoding, power | Load drives collision |
| Stepwise, reproducible model | Power depends on demod usage |
| Defendable methodology | Reliability–energy tradeoff |

---

## Final Insight

- geometry → load → interference → decoding → energy  

<!--
Left shows contributions, right shows observations.
-->

