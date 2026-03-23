---
marp: true
size: 16:9
paginate: true
---

# Detailed Theory
## LR-FHSS + Power Coupling

<!--
Speech script:
This detailed deck is equation-first.
I will define symbols, derive each block, and then combine the blocks into a final recurrence.
-->

---

## Symbols (Core)
- $N$: node load
- $D_{\text{req}}$: requested demods
- $D$: allocated demods
- $T$: traffic demand per step
- $u$: utilization
- $V$: visibility (0/1)
- $B_t$: battery SoC

<!--
Speech script:
These are the communication and state variables.
They form the input to each simulation step.
-->

---

## Symbols (Power)
- $P_0$: baseline platform power
- $P_{\text{cons}}$: consumption power
- $P_{\text{solar}}$: solar array rating
- $\eta_{\text{pc}}$: power conditioning efficiency
- $P_{\text{gen}}$: generated power
- $P_{\text{net}}$: battery-side net power
- $C_{\text{Wh}}$: battery capacity

<!--
Speech script:
These are the power-system parameters and outputs.
Keep this slide as reference for the remaining equations.
-->

---

## Code Trace (Symbols to `workflow.py`)
- $N$ -> `nodes`
- $D_{\text{req}}$ -> `requested_demods`
- $D$ -> `allocated_demods`
- $m_t$ -> `p_mode`
- $V$ -> `visible`
- $T$ -> `tx_count`
- $u$ -> `compute_demod_utilization(...)`
- $P_{\text{cons}}$ -> `power_consumption`
- $P_{\text{net}}$ -> `net_power_watts`
- $B_t, B_{t+1}$ -> `battery_percent_scenario`, `updated_battery_percent`

<!--
Speech script:
This slide maps each equation symbol to the exact implementation variable.
It helps reviewers verify that the math and code are consistent.
-->

---

## 1) Policy Equation
$$
m_t=
\begin{cases}
\text{sleep}, & B_t\le B_{\text{low}} \;\text{or}\; V=0 \;\text{or}\; N=0 \;\text{or}\; D=0\\
\text{idle}, & B_t<B_{\text{idle}}\\
\text{idle}, & N<200 \;\text{and}\; D\le D_{\text{hi}}\\
\text{busy}, & \text{otherwise}
\end{cases}
$$

<!--
Speech script:
Mode is decided first.
Battery safety, visibility, no traffic, or no allocated demods can force sleep.
Otherwise, threshold logic separates idle and busy operation, including low-load idle.
-->

---

## 2) Allocation Equation
$$
D=
\begin{cases}
0, & m_t=\text{sleep}\\
D_{\text{req}}, & \text{idle/busy}
\end{cases}
$$

Why:
- Sleep disables demods.
- Active modes use requested capacity.

<!--
Speech script:
Mode becomes hardware allocation here.
This is the bridge from policy to decoding capability.
-->

---

## 3) Utilization Equation
$$
u=\min\!\left(1,\frac{T}{kD}\right)
$$

Interpretation:
- $u\approx 0$: underloaded
- $u\approx 1$: saturated

<!--
Speech script:
Utilization compares demand to demod capacity.
This gives a normalized stress variable between zero and one.
-->

---

## 4) Consumption Equation
$$
P_{\text{cons}}=
\begin{cases}
P_0, & \text{sleep}\\
P_0 + D(a_i+b_i u), & \text{idle}\\
P_0 + D(a_b+b_b u), & \text{busy}
\end{cases}
$$

<!--
Speech script:
Sleep is baseline-only power.
Idle and busy add demod power, scaled by utilization.
Busy coefficients are larger than idle by design.
-->

---

## 5) Generation Equation
$$
P_{\text{gen}}=V P_{\text{solar}}\eta_{\text{pc}}
$$

Surplus:
$$
S=P_{\text{gen}}-P_{\text{cons}}
$$

<!--
Speech script:
Visibility gates generation.
Surplus is the key sign variable:
positive means potential charging, negative means required discharging.
-->

---

## 6) Charge Acceptance
$$
\alpha(B_t)=
\begin{cases}
1, & B_t<90\\
0.5, & 90\le B_t<95\\
0.25, & 95\le B_t<99\\
0, & B_t\ge 99
\end{cases}
$$

<!--
Speech script:
This captures CV-like taper near full battery.
It limits accepted charging power as SoC approaches 100 percent.
-->

---

## 7) Battery-Side Power Branch
$$
P_{\text{ch}}=\min(\max(S,0),P_{\text{ch,max}}\alpha(B_t))
$$
$$
P_{\text{dis}}=\max(-S,0)
$$
$$
P_{\text{net}}=P_{\text{ch}}-P_{\text{dis}}
$$

<!--
Speech script:
This is a piecewise branch written compactly.
Only one branch is active at a time:
charging branch for positive surplus, discharging branch for negative surplus.
-->

---

## 8) Battery Energy Update
$$
\Delta E=
\eta_{\text{ch}}\max(P_{\text{net}},0)\Delta t
-\frac{1}{\eta_{\text{dis}}}\max(-P_{\text{net}},0)\Delta t
$$

$$
B_{t+1}=\text{clip}_{[0,100]}
\left(B_t+100\frac{\Delta E}{C_{\text{Wh}}}\right)
$$

<!--
Speech script:
We integrate power over step duration to get energy change.
Then convert energy to SoC percentage.
Clip ensures physically valid SoC bounds.
-->

---

## 9) Combined Derivation
$$
(N,D_{\text{req}},V,B_t)
\rightarrow m_t
\rightarrow D
\rightarrow u
\rightarrow P_{\text{cons}}
\rightarrow S
\rightarrow P_{\text{net}}
\rightarrow B_{t+1}
$$

Implementation note:
- Current code evaluates one-step SoC per scenario and resets battery to initial value for each sweep point.

<!--
Speech script:
This one-line chain is the full algorithm.
Every block is deterministic once parameters are set.
In code, this chain is applied as a one-step scenario update rather than a multi-step temporal rollout across scenarios.
-->

---

## 10) Piecewise Net Power Result
From $S=P_{\text{gen}}-P_{\text{cons}}$:

$$
P_{\text{net}}=
\begin{cases}
\min(S,P_{\text{ch,max}}\alpha(B_t)), & S\ge 0\\
S, & S<0
\end{cases}
$$

Meaning:
- Positive surplus may still be charge-limited.

<!--
Speech script:
This is the most important derived simplification.
When surplus is positive, charging can still be capped by acceptance.
When surplus is negative, net power simply follows deficit.
-->

---

## 11) Applicability
Use when:
- fast trade studies are needed
- policy comparisons are needed
- interpretable model is preferred

Avoid alone when:
- thermal-electrochemical detail is required
- high-fidelity orbit irradiance is required

<!--
Speech script:
This model is intentionally lightweight.
It is great for control and system-level trade space analysis.
It should be complemented by high-fidelity models for final verification.
-->

---

## 12) Validation Checklist
1. Sleep consumption is constant.
2. Active-mode consumption rises with $u$ and $D$.
3. If $V=0$, then $P_{\text{gen}}=0$.
4. $B_{t+1}$ always in $[0,100]$.

<!--
Speech script:
These checks are quick sanity tests for implementation correctness.
If any fail, either parameters or code logic should be reviewed.
-->

---

## 13) Why These Formulas
- Battery SoC update literature:
  - [10.3390/en14144074](https://doi.org/10.3390/en14144074)
- Utilization-power model:
  - [10.1145/1273440.1250665](https://doi.org/10.1145/1273440.1250665)
  - [10.1109/MC.2007.443](https://doi.org/10.1109/MC.2007.443)

<!--
Speech script:
These references justify the foundational equations.
Our contribution is how we combine and adapt them for LR-FHSS demodulator-constrained operation; some blocks are inspired approximations.
-->

---

## 14) EPS + Charging References
- Spacecraft EPS balance:
  - [10.1016/j.actaastro.2020.10.036](https://doi.org/10.1016/j.actaastro.2020.10.036)
- CubeSat EPS survey:
  - <https://link.springer.com/article/10.1007/s43937-025-00069-5>
- CC-CV charge model:
  - [10.1016/j.est.2020.101342](https://doi.org/10.1016/j.est.2020.101342)

<!--
Speech script:
These references support the EPS generation-load balance and the charge taper concept near full SoC.
They underpin the power and battery blocks of our recurrence.
-->
