---
marp: true
size: 16:9
paginate: true
---

# LR-FHSS Power Model
## Clear Theory Slides

<!--
Speech script:
Today I will explain a compact energy-aware LR-FHSS model.
I will focus on three things: what we model, how the equations are combined, and why each equation is justified by prior research.
-->

---

## What We Model
- Satellite LR-FHSS receiver
- Limited demodulators
- Battery + solar power
- Load-dependent decoding

State:
- $N$: node load
- $D_{\text{req}}$: requested demods
- $B_t$: battery SoC
- $V$: visibility (0/1)

<!--
Speech script:
This slide defines the system boundary.
The communication side is node load and demodulator budget.
The power side is solar generation and battery state.
These four state variables are enough to drive the one-step model.
-->

---

## Code Trace (Quick)
- $N$ -> `nodes`
- $D_{\text{req}}$ -> `requested_demods`
- $D$ -> `allocated_demods`
- $m_t$ -> `p_mode`
- $V$ -> `visible`
- $T$ -> `tx_count`
- $P_{\text{cons}}$ -> `power_consumption`
- $P_{\text{net}}$ -> `net_power_watts`
- $B_{t+1}$ -> `updated_battery_percent`

<!--
Speech script:
This is a quick bridge from equations to code names.
It makes implementation auditing straightforward.
-->

---

## Why We Need This
- Decode performance alone is not enough.
- Energy limits change operating mode.
- We need decode + power in one loop.

Goal:
$$
\text{maximize decode utility subject to battery feasibility}
$$

<!--
Speech script:
If we optimize only decoding, we may choose infeasible operating points.
If we optimize only energy, we ignore communication utility.
So we frame a constrained objective: maximize decoding while keeping battery operation feasible.
-->

---

## Step 1: Mode Policy
$$
m_t=
\begin{cases}
\text{sleep}, & B_t\le B_{\text{low}} \;\text{or}\; V=0 \;\text{or}\; N=0 \;\text{or}\; D=0\\
\text{idle}, & B_t< B_{\text{idle}}\\
\text{idle}, & N<200 \;\text{and}\; D\le D_{\text{hi}}\\
\text{busy}, & \text{otherwise}
\end{cases}
$$

<!--
Speech script:
First we choose operating mode.
Sleep is enforced when battery is low, no visibility, no traffic, or no allocated demods.
Idle and busy separate conservative and aggressive operation, including a low-load idle branch.
This is a control policy, not a physical law.
-->

---

## Step 2: Demod Allocation
$$
D=
\begin{cases}
0, & m_t=\text{sleep}\\
D_{\text{req}}, & \text{idle/busy}
\end{cases}
$$

<!--
Speech script:
Mode directly determines active decoding hardware.
In sleep we force zero demodulators.
In active modes we allocate the requested demodulators.
This creates the coupling from policy to communication capacity.
-->

---

## Step 3: Utilization
$$
u=\min\!\left(1,\frac{T}{kD}\right), \quad u\in[0,1]
$$

- $T$: traffic demand per step
- $kD$: decode capacity per step

<!--
Speech script:
Now we map demand to utilization.
The ratio T over kD tells us how loaded the demodulator pool is.
Clipping at 1 means saturation.
This variable drives both power consumption and performance stress.
-->

---

## Step 4: Power Consumption
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
Consumption has a baseline plus an active demodulator term.
The active term is affine in utilization.
Busy mode uses larger coefficients than idle mode.
This follows energy-proportional modeling ideas adapted to demodulators.
-->

---

## Step 5: Solar Generation
$$
P_{\text{gen}} = V P_{\text{solar}}\eta_{\text{pc}}
$$

Surplus:
$$
S=P_{\text{gen}}-P_{\text{cons}}
$$

<!--
Speech script:
Generation is modeled from visibility and solar efficiency.
Subtracting load gives surplus power.
Positive surplus means charging is possible.
Negative surplus means battery must discharge.
-->

---

## Step 6: Net Battery Power
Charge taper:
$$
\alpha(B_t)\in\{1,0.5,0.25,0\}
$$

$$
P_{\text{ch}}=\min(\max(S,0),P_{\text{ch,max}}\alpha(B_t))
$$
$$
P_{\text{dis}}=\max(-S,0),\quad
P_{\text{net}}=P_{\text{ch}}-P_{\text{dis}}
$$

<!--
Speech script:
Here we add battery realism.
Near full SoC, charge acceptance tapers, so we cannot absorb all surplus.
That is why positive surplus does not always mean large positive net charging.
Net battery power is charge minus discharge branch.
-->

---

## Step 7: Battery Update
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
Battery is updated from energy, not from ad-hoc percentages.
We integrate net power over the step duration.
Charge and discharge efficiencies are handled separately.
Finally, SoC is clipped to physical limits.
-->

---

## Full Combined Chain
$$
(N,D_{\text{req}},V,B_t)
\rightarrow m_t
\rightarrow D
\rightarrow u
\rightarrow P_{\text{cons}}
\rightarrow P_{\text{net}}
\rightarrow B_{t+1}
$$

Implementation note:
- In current code, battery is reset per scenario: $B_t = B_{\text{init}}$ for each $(N,D_{\text{req}})$ point.

<!--
Speech script:
This is the full recurrence in one line.
Each block feeds the next block.
The key point is feedback: battery state affects mode, and mode affects future battery state through power.
In the current implementation, this recurrence is applied as a one-step scenario update, not as a multi-step time trajectory across the sweep.
-->

---

## When This Model Is Valid
- Early-stage mission trade studies
- Control/policy comparison
- Fast sweeps over load and demods

Not enough for:
- high-fidelity electrochemistry
- thermal-coupled battery physics

<!--
Speech script:
This is a first-order model.
It is strong for design exploration and policy comparison.
It is not a replacement for electrochemical battery simulators or detailed thermal-orbital tools.
-->

---

## Why These Equations
- SoC energy update (adapted from Coulomb-counting literature): [10.3390/en14144074](https://doi.org/10.3390/en14144074)
- Utilization-power linear model: [10.1145/1273440.1250665](https://doi.org/10.1145/1273440.1250665)
- Energy proportionality: [10.1109/MC.2007.443](https://doi.org/10.1109/MC.2007.443)

<!--
Speech script:
These references justify the foundations:
SoC integration, battery behavior, and utilization-power relationship.
We use adapted forms of these ideas for LR-FHSS receiver operation; not every equation is copied directly.
-->

---

## More Power-System References
- Spacecraft EPS balance model:
  - [10.1016/j.actaastro.2020.10.036](https://doi.org/10.1016/j.actaastro.2020.10.036)
- CubeSat EPS survey:
  - <https://link.springer.com/article/10.1007/s43937-025-00069-5>
- CC-CV charge dynamics:
  - [10.1016/j.est.2020.101342](https://doi.org/10.1016/j.est.2020.101342)

<!--
Speech script:
These papers support the spacecraft EPS energy-balance simplification and the charge-taper behavior near full SoC.
Together they justify the power-generation and battery-side parts of the model.
-->
