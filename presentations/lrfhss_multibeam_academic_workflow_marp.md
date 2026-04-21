---
marp: true
paginate: true
math: katex
---

# LR-FHSS in LEO
### Cross Layered Simulation

- Focus: equations, assumptions, and measurable outputs
- Inputs: updated population data + satellite geometry
- Outputs: nodes, demod states, decoded packets, elevation effects, energy

---

# Problem Statement
### What Is Estimated at Each Step

Given satellite state at step $t$, estimate:

1. covered population $P_{\text{cov}}(t)$
2. calculated nodes $N_{\text{node}}(t)$
3. calculated demodulators $N_{\text{demod}}(t)$
4. elevation-conditioned load and decoding behavior
5. busy/idle/sleep demod split and power

---

# Workflow

- Orbit propagation gives future satellite position.
- Satellite position gives footprint size on Earth.
- Footprint over population map gives covered population.
- Population base is multiplied by ratios to get calculated nodes and demodulators.
- Elevation scenarios convert load to busy/idle/sleep demod states.
- Demod states are converted to predicted energy and decode behavior.

---

# Orbit Mean Motion

$$
n=\sqrt{\frac{\mu}{a^3}}
$$

- Symbols: $n$ mean motion, $\mu$ Earth gravitational parameter, $a$ semi-major axis.
- Ref: Orbital mechanics (Vallado) https://doi.org/10.1007/978-1-4939-0802-8

---

# Mean Anomaly Update

$$
M(t)=M_0+n(t-t_0)
$$

- Symbols: $M(t)$ anomaly at time $t$, $M_0$ anomaly at reference epoch $t_0$, $n$ mean motion.
- Ref: Orbital mechanics (Vallado) https://doi.org/10.1007/978-1-4939-0802-8

---

# Horizon Central Angle

$$
\psi_h=\arccos\left(\frac{R_E}{r_{\text{orb}}}\right)
$$

- Symbols: $\psi_h$ horizon central angle, $R_E$ Earth radius, $r_{\text{orb}}$ orbital radius.
- Ref: NTN geometry context https://www.3gpp.org/DynaReport/38.811.htm

---

# Geometric Footprint Radius

$$
R_{\text{geo}}=R_E\psi_h
$$

- Symbols: $R_{\text{geo}}$ geometric footprint radius, $R_E$ Earth radius, $\psi_h$ horizon central angle.
- Ref: NTN geometry context https://www.3gpp.org/DynaReport/38.811.htm

---

# Effective Footprint Radius

$$
R_{\text{fp}}(t)=\min\left(R_{\text{geo}}(t),\;R_{\text{cfg}}\frac{h(t)}{h_{\text{cfg}}}\right)
$$

- Symbols: $R_{\text{fp}}(t)$ effective footprint radius, $R_{\text{cfg}}$ configured radius.
- Symbols: $h(t)$ current altitude, $h_{\text{cfg}}$ reference altitude.
- Ref: Implementation rule in `modules/satellite_stepper.py`

---

# Covered Population

$$
P_{\text{cov}}(t)=\sum_i p_i \,\mathbf{1}[d_i(t)\le R_{\text{fp}}(t)]
$$

- Symbols: $P_{\text{cov}}(t)$ covered population, $p_i$ population at catalog point $i$.
- Symbols: $d_i(t)$ distance from footprint center to point $i$, $\mathbf{1}[\cdot]$ indicator.
- Ref: Natural Earth populated places https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip

---


# Node Mapping

$$
N_{\text{node}}(t)=P_{\text{pop}}\rho_{\text{node}}
$$

- Symbols: $N_{\text{node}}(t)$ calculated nodes, $P_{\text{pop}}$ population base, $\rho_{\text{node}}$ node/population ratio.
- Ref: Implementation rule in `modules/satellite_stepper.py`

---

# Demod Mapping

$$
N_{\text{demod}}(t)=P_{\text{pop}}\rho_{\text{demod}}
$$

- Config values (current defaults): $\rho_{\text{node}}=10^{-7}$, $\rho_{\text{demod}}=10^{-7}$.
- Symbols: $N_{\text{demod}}(t)$ calculated demodulators, $P_{\text{pop}}$ population base, $\rho_{\text{demod}}$ demod/population ratio.
- Ref: Implementation rule in `modules/satellite_stepper.py`

---

# Mean Slant Range per Elevation

$$
\bar d_e(t)=\frac{1}{N_e(t)}\sum_{u=1}^{N_e(t)} d_{u,e}(t)
$$

- Symbols: $e$ elevation bin, $N_e(t)$ users in that bin.
- Symbols: $d_{u,e}(t)$ user-$u$ slant range, $\bar d_e(t)$ mean slant range.
- Ref: Slant-range impact concept (Friis distance dependence) https://doi.org/10.1109/JRPROC.1946.234568

---

# Demod States (Simple View)
### Input -> Load -> Busy

1. For each elevation $e$, compute offered load:
$$
A_e=\max(1,N_e)\alpha_{\text{act}}\left(\frac{\bar d_e}{d_{\text{ref}}}\right)^2
$$
2. Use Erlang-B with:
   - servers $c=N_{\text{demod}}$
   - offered load $A_e$
   - blocking probability $B(c,A_e)$
3. Busy demodulators:
$$
N_{\text{busy},e}=\operatorname{round}\left(\min\left(N_{\text{demod}},A_e(1-B(c,A_e))\right)\right)
$$

- Intuition: more users and longer distance increase offered load, which increases busy usage.
- Ref: implemented in `modules/satellite_stepper.py`

---

# Demod States (Simple Split)
### Busy -> Sleep -> Idle

$$
N_{\text{rem},e}=N_{\text{demod}}-N_{\text{busy},e}
$$
$$
N_{\text{sleep},e}=\operatorname{round}\left(\beta_{\text{sleep}}N_{\text{rem},e}\right),\quad
N_{\text{idle},e}=N_{\text{rem},e}-N_{\text{sleep},e}
$$

- Current setting: $\beta_{\text{sleep}}=0.3$.
- Conservation check:
$$
N_{\text{busy},e}+N_{\text{sleep},e}+N_{\text{idle},e}=N_{\text{demod}}
$$
- Ref: implemented in `modules/satellite_stepper.py`

---

# Power Model

$$
P_e(t)=P_0+N_{\text{idle},e}(t)P_{\text{idle}}+N_{\text{busy},e}(t)P_{\text{busy}}
$$

- Symbols: $P_e(t)$ total modeled power for elevation scenario $e$.
- Symbols: $P_0$ baseline power, $P_{\text{idle}}$ idle demod power, $P_{\text{busy}}$ busy demod power.
- Symbols: $N_{\text{idle},e}(t)$ and $N_{\text{busy},e}(t)$ are stepwise demod state counts.
- Current constants: $P_0=2$ mW, $P_{\text{idle}}=9$ mW, $P_{\text{busy}}=100$ mW.
- Ref: power-state modeling basis https://tnm.engin.umich.edu/wp-content/uploads/sites/353/2017/12/2006.10.Reducing-idle-mode-power-in-software-defined-radio-terminals_ISLPED-2006.pdf


---

# Future Prediction 
### Predicting Next Time Steps

Goal: predict busy demodulators and energy at future horizon $t+\Delta$.

1. Generate future satellite states by stepping orbit index forward.
2. For each future step, recompute footprint and covered population.
3. Map population base to future `calculated_nodes` and `calculated_demodulators` using ratios.
4. For each elevation (90/55/25), estimate future busy/idle/sleep states.
5. Convert those states to future energy using the same power constants.

---

# one_pos* Flow
### Single-Position Decode Pipeline

1. Fix one satellite/user geometry snapshot as input scenario.
2. Set demod budget and PHY parameters for LR-FHSS decode simulation.
3. Run per-elevation decode (`90/55/25 deg`) for the same position.
4. Save per-elevation decode/link-budget aggregates to `results/one_pos*`.
5. Render per-elevation decode plots for comparison across geometry.

---

# satellite_stepper Flow
### Time-Series Resource Pipeline

1. Initialize `SatelliteStepper` with orbit track, population map, and ratios.
2. For each step, compute footprint and covered population on Earth.
3. Compute `calculated_nodes` and `calculated_demodulators` from population base and ratios.
4. For each elevation, compute distance-based loss, load, and busy/idle/sleep demod states.
5. Write step outputs to CSV/JSON and generate plots (population, demod, energy, combined).

---
# One-Position Decode Results
### Elevation Curves (90 deg)

![h:300px](../results/one_pos_lrfhss/lrfhss_demod_42_elev90.png)

---
# One-Position Decode Results
### Elevation Curves (55 deg)

![h:300px](../results/one_pos_lrfhss/lrfhss_demod_42_elev55.png)

---

# One-Position Decode Results
### Elevation Curve (25 deg)

![h:360px](../results/one_pos_lrfhss/lrfhss_demod_42_elev25.png)

- Same demod budget, stronger geometry penalty at lower elevation.

---

# Satellite Stepper Outputs
### Population and Resource Dynamics

![h:330px](../results/one_pos_satellite/plots/satellite_stepper_population.png)

- Per step: covered population, nodes, and demod count.

---

# Demodulator State Evidence
### Busy/Idle vs Orbit Timestamp (90 deg)

![h:330px](../results/one_pos_satellite/plots/satellite_stepper_demodulators_90deg.png)

---

# Demodulator State Results
### Busy/Idle vs Orbit Timestamp (55 deg)

![h:330px](../results/one_pos_satellite/plots/satellite_stepper_demodulators_55deg.png)

---

# Demodulator State Results
### Busy/Idle vs Orbit Timestamp (25 deg)

![h:290px](../results/one_pos_satellite/plots/satellite_stepper_demodulators_25deg.png)

---

# Energy Model Results (90, 55 and 25 deg)

![h:350px](../results/one_pos_satellite/plots/satellite_stepper_energy_all_elevations.png)

- Energy follows geometry-driven demod state transitions.

---

# Main Takeaways

1. Geometry controls coverage and distance.
2. Coverage controls node/demod provisioning.
3. Elevation changes distance and busy occupancy.
4. Busy occupancy is the main power driver.
5. One-position decode plots are consistent with this chain.

---

# Citable Paper Sources (URLs)

- LR-FHSS overview paper: https://doi.org/10.1109/MCOM.001.2000627
- 3GPP NTN reference (TR 38.811): https://www.3gpp.org/DynaReport/38.811.htm
- Friis transmission formula: https://doi.org/10.1109/JRPROC.1946.234568
- Shannon communication theory: https://doi.org/10.1002/j.1538-7305.1948.tb01338.x
- ALOHA system paper: https://doi.org/10.1145/1478462.1478502

---

# Citable Data Sources (URLs)

- Natural Earth populated places: https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip
- Natural Earth countries: https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip
- Natural Earth lakes: https://naciscdn.org/naturalearth/10m/physical/ne_10m_lakes.zip
- Natural Earth rivers: https://naciscdn.org/naturalearth/10m/physical/ne_10m_rivers_lake_centerlines.zip
- Demod power baseline reference: https://tnm.engin.umich.edu/wp-content/uploads/sites/353/2017/12/2006.10.Reducing-idle-mode-power-in-software-defined-radio-terminals_ISLPED-2006.pdf


