# Energy-Aware LR-FHSS Multi-Beam Reception Under Satellite Power Constraints: A Derivation-Driven System Model

## Abstract
Long-range frequency-hopping spread spectrum (LR-FHSS) reception on satellites is jointly constrained by demodulator availability and onboard electrical power limits. This draft presents a unified communication-energy model that couples traffic-dependent demodulator utilization, mode-dependent receiver power, electrical power subsystem (EPS) balance, and battery state-of-charge (SoC) evolution. The formulation starts from established equations in energy-proportional computing, queueing-based utilization, EPS power balance, and battery charging/discharging dynamics, and then derives a tractable recurrence suitable for time-step simulation. The resulting model enables joint analysis of decoding capacity and energy feasibility, which is essential when multi-beam operation must adapt to visibility and battery conditions. In reporting, we use decoded headers (header-only) as the primary KPI and decoded headers including payload-decoded packets as a secondary KPI.

## 1. Introduction
Multi-beam LR-FHSS reception improves uplink scalability, but each additional active demodulator increases receiver load and power demand. In orbit, available generation varies with visibility and operating state, making communication performance and energy feasibility inseparable. Existing studies provide strong component models for utilization-power relations [2], [3], spacecraft EPS balance [4], [5], and battery SoC propagation [1], [6], yet these components are often treated independently.

This work integrates these strands into one control-oriented recurrence that can be executed at simulation time steps. The receiver selects an operating mode, allocates demodulators, computes utilization and consumption, applies EPS balance, and propagates SoC to the next step. The key objective is not electrochemical detail, but a first-order model that preserves physically meaningful couplings between link activity and energy state.

The main contributions of this draft are:
1. A unified LR-FHSS communication-energy model for demodulator-constrained multi-beam reception under satellite power limits.
2. A transparent derivation linking literature-based equations into one implementable recurrence.
3. A battery-aware mode-control policy (`sleep`, `idle`, `busy`) that feeds back into decoding capacity and future energy state.

## 2. Problem Formulation
At each discrete time step $t$, the simulator receives node load $N_t$, requested demodulators $D_{\mathrm{req},t}$, satellite visibility $V_t \in \{0,1\}$, and battery SoC $B_t$. The task is to compute:
1. operating mode $m_t \in \{\mathrm{sleep}, \mathrm{idle}, \mathrm{busy}\}$,
2. allocated demodulators $D_t$,
3. receiver consumption power $P_{\mathrm{cons},t}$,
4. battery net power $P_{\mathrm{net},t}$,
5. updated SoC $B_{t+1}$.

The overall state transition is:
$$
(N_t, D_{\mathrm{req},t}, V_t, B_t)\rightarrow (m_t, D_t, P_{\mathrm{cons},t}, P_{\mathrm{net},t}, B_{t+1}).
$$

## 3. Model Derivation

### 3.1 Receiver Consumption Model From Energy-Proportional Form
Energy-proportional systems are commonly approximated by an affine law in utilization [2], [3]:
$$
P(u)=P_{\mathrm{idle}}+\left(P_{\mathrm{peak}}-P_{\mathrm{idle}}\right)u,\quad u\in[0,1].
$$
For LR-FHSS reception, we apply this principle per allocated demodulator and allow mode-conditioned coefficients:
$$
P_{\mathrm{demod}}(u\mid m_t)=a_{m_t}+b_{m_t}u_t.
$$
The total receiver consumption becomes:
$$
P_{\mathrm{cons},t}=
\begin{cases}
P_0, & m_t=\mathrm{sleep},\\
P_0 + D_t\left(a_{m_t}+b_{m_t}u_t\right), & m_t\in\{\mathrm{idle},\mathrm{busy}\},
\end{cases}
$$
where $P_0$ is baseline platform power.

### 3.2 Utilization From Demand-Capacity Ratio
Queueing models use demand-to-capacity ratio as a utilization proxy:
$$
\rho=\frac{\lambda}{c\mu}.
$$
Using per-step traffic demand $T_t$, demodulator count $D_t$, and per-demodulator step capacity $k$, we define:
$$
u_t=\min\left(1,\frac{T_t}{kD_t}\right),\quad D_t>0,
$$
and set $u_t=0$ when $D_t=0$. This clipping captures saturation while preserving bounded power behavior.

### 3.3 EPS Balance Under Visibility-Dependent Generation
Spacecraft EPS analysis uses generation-minus-load balance [4], [5]:
$$
S_t=P_{\mathrm{gen},t}-P_{\mathrm{cons},t}.
$$
Generation is modeled as:
$$
P_{\mathrm{gen},t}=V_t P_{\mathrm{solar}}\eta_{\mathrm{pc}},
$$
where $P_{\mathrm{solar}}$ is panel power in illuminated condition and $\eta_{\mathrm{pc}}$ is power-conversion efficiency. Therefore,
$$
S_t=V_t P_{\mathrm{solar}}\eta_{\mathrm{pc}}-P_{\mathrm{cons},t}.
$$

### 3.4 Battery Charge/Discharge Branches With Charge Acceptance
The CC-CV charging literature indicates tapering near full charge [6]. We represent this through an SoC-dependent acceptance factor $\alpha(B_t)\in[0,1]$, monotonically decreasing as $B_t\rightarrow 100\%$.

Charging and discharging powers are:
$$
P_{\mathrm{ch},t}=\min\left(\max(S_t,0),\,P_{\mathrm{ch,max}}\alpha(B_t)\right),
$$
$$
P_{\mathrm{dis},t}=\max(-S_t,0),
$$
$$
P_{\mathrm{net},t}=P_{\mathrm{ch},t}-P_{\mathrm{dis},t}.
$$

### 3.5 SoC Update by Energy Integration
Following standard SoC integration [1], battery energy evolves as:
$$
E_{t+1}=E_t+\Delta E_t.
$$
For a step duration $\Delta t$ (hours), with charging efficiency $\eta_{\mathrm{ch}}$ and discharging efficiency $\eta_{\mathrm{dis}}$:
$$
\Delta E_t=\eta_{\mathrm{ch}}\max(P_{\mathrm{net},t},0)\Delta t
-\frac{1}{\eta_{\mathrm{dis}}}\max(-P_{\mathrm{net},t},0)\Delta t.
$$
Given capacity $C_{\mathrm{Wh}}$ and $B_t=100E_t/C_{\mathrm{Wh}}$:
$$
B_{t+1}=\mathrm{clip}_{[0,100]}\left(B_t+100\frac{\Delta E_t}{C_{\mathrm{Wh}}}\right).
$$

### 3.6 Control Policy and Demodulator Allocation
The control layer is represented as:
$$
m_t=\pi(N_t,D_{\mathrm{req},t},V_t,B_t),
$$
with allocation rule:
$$
D_t=
\begin{cases}
0, & m_t=\mathrm{sleep},\\
D_{\mathrm{req},t}, & m_t\in\{\mathrm{idle},\mathrm{busy}\}.
\end{cases}
$$
This policy creates a closed loop in which current battery and visibility determine demodulator availability, which in turn affects utilization, power draw, and future battery state.

## 4. Final Coupled Recurrence
Combining all blocks, the per-step evolution is:
$$
(N_t,D_{\mathrm{req},t},V_t,B_t)\rightarrow m_t\rightarrow D_t\rightarrow u_t\rightarrow P_{\mathrm{cons},t}\rightarrow S_t\rightarrow P_{\mathrm{net},t}\rightarrow B_{t+1}.
$$
An equivalent compact representation is:
$$
B_{t+1}=\Psi\!\left(B_t,\;h\!\left(V_tP_{\mathrm{solar}}\eta_{\mathrm{pc}}-f(m_t,D_t,u_t),\,B_t\right)\right),
$$
where $m_t=\pi(N_t,D_{\mathrm{req},t},V_t,B_t)$ and $u_t=\min\!\left(1,\frac{T_t}{kD_t}\right)$ for $D_t>0$.

## 5. Implementation Mapping (Notation to Code)
| Symbol | Meaning | Code variable / function |
|---|---|---|
| $N_t$ | Node load | `nodes` in `run_workflow(...)` |
| $D_{\mathrm{req},t}$ | Requested demodulators | `requested_demods` |
| $D_t$ | Allocated demodulators | `allocated_demods = allocate_demodulators(...)` |
| $m_t$ | Power mode | `p_mode = select_satellite_power_mode(...)` |
| $V_t$ | Visibility | `visible = check_satellite_visibility(...)` |
| $T_t$ | Traffic demand proxy | `tx_count = transmit_fragments(packet_count, visible)` |
| $H_{\mathrm{hdr},t}$ | Header-only decoded count | `decoded_headers` |
| $H_{\mathrm{inc},t}$ | Headers including payload-decoded count | `decoded_headers_including_payloads` |
| $u_t$ | Utilization | `compute_demod_utilization(tx_count, allocated_demods)` |
| $P_{\mathrm{cons},t}$ | Consumption power | `power_consumption = compute_power_consumption(...)` |
| $P_{\mathrm{gen},t}$ | Generated power | `available_generation_watts` in `compute_power_balance(...)` |
| $P_{\mathrm{ch},t}$ | Charging power | `charging_power_watts` |
| $P_{\mathrm{dis},t}$ | Discharging power | `discharging_power_watts` |
| $P_{\mathrm{net},t}$ | Net battery power | `net_power_watts` |
| $B_t,B_{t+1}$ | Battery SoC | `battery_percent_scenario`, `updated_battery_percent` |
| $\Delta t$ | Step duration | `SIM_STEP_SECONDS / 3600.0` |
| $C_{\mathrm{Wh}}$ | Battery capacity | `BATTERY_CAPACITY_WH` |

## 6. Scope and Limitations
The model is intentionally first-order and aimed at system-level tradeoff analysis. It does not explicitly include temperature-dependent internal resistance, detailed electrochemical states, or orbital-angle-resolved irradiance. These effects can be incorporated by replacing the generation and battery submodels while preserving the high-level recurrence and control-policy interface.

## 7. References
[1] S. H. Movassagh et al., "A Critical Look at Coulomb Counting Approach for State of Charge Estimation in Batteries," *Energies*, 2021. DOI: `10.3390/en14144074`

[2] X. Fan, W.-D. Weber, L. A. Barroso, "Power Provisioning for a Warehouse-Sized Computer," *ISCA*, 2007. DOI: `10.1145/1273440.1250665`

[3] L. A. Barroso, U. Holzle, "The Case for Energy-Proportional Computing," *IEEE Computer*, 2007/2008. DOI: `10.1109/MC.2007.443`

[4] F. Porras-Hermoso et al., "Simple solar panels/battery modeling for spacecraft power distribution systems and some applications to UPMSat-2 mission," *Acta Astronautica*, 2021. DOI: `10.1016/j.actaastro.2020.10.036`

[5] A. Shakoor et al., "Comprehensive analysis of CubeSat electrical power systems for efficient energy management," *Discover Energy*, 2025. Link: `https://link.springer.com/article/10.1007/s43937-025-00069-5`

[6] K. Liu et al., "An analytical model for the CC-CV charge of Li-ion batteries with application to degradation analysis," *Journal of Energy Storage*, 2020. DOI: `10.1016/j.est.2020.101342`
