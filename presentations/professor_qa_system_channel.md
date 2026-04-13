# Professor Q&A (System Model and Channel Model)

## Q1. What is your system model in one sentence?
**A:** A stepwise LEO NTN model where orbit-driven geometry determines coverage, coverage determines offered LR-FHSS load and demodulator allocation, and channel/interference determines SNR/SINR and decoding outcomes.

## Q2. What is the satellite altitude and why?
**A:** The model uses \(h \approx 600\) km (LEO), consistent with the framework configuration and common NTN study scales.

## Q3. How far is the satellite from users?
**A:** Slant range depends on geometry. Near zenith, \(d \approx h \approx 600\) km. Toward horizon, \(d\) increases up to about 2830 km for \(h=600\) km.
\[
d(\psi)=\sqrt{(R_E+h)^2+R_E^2-2R_E(R_E+h)\cos\psi}
\]

## Q4. What orbit equations do you use?
**A:** Classical two-body Kepler propagation from orbital elements with Kepler equation \(M=E-e\sin E\), then coordinate transformation for Earth rotation.

## Q5. Why is this academically defendable?
**A:** Each stage uses standard, citable formulations: Kepler/Vallado/Curtis for orbit, Friis + ITU-R for propagation, 3GPP NTN framing for channel/SINR interpretation, and explicit LR-FHSS reference curves for decoding behavior.

## Q6. What is your channel model exactly?
**A:** Total loss is FSPL + atmospheric attenuation, with multi-beam interference in SINR:
\[
L_{u,\mathrm{tot}}=20\log_{10}\!\left(\frac{4\pi d_u f_c}{c}\right)+A_{\mathrm{atm},u},\quad
\mathrm{SINR}_u=\frac{|h_{u,b_u^\star}|^2}{\sum_{b\neq b_u^\star}|h_{u,b}|^2+N}
\]

## Q7. Why use a decoding surrogate instead of full packet simulation per step?
**A:** For tractability across many steps/countries. The surrogate is not hidden: it is explicitly a mapping from \((n,d)\) to decoded payload using reference LR-FHSS curves from `data-25dc-cr1.csv`, sourced from **"Enhancing LR-FHSS Scalability Through Advanced Sequence Design and Demodulator Allocation" (Diego's paper)**.

## Q8. What are the main assumptions professors may challenge?
**A:** Country-level spatial abstraction, fixed penetration ratio, fixed demod capacity, and surrogate-based decoding. These are documented and can be sensitivity-tested.

## Q9. How would you validate against real systems?
**A:** Calibrate traffic/penetration and power parameters with measured data, compare predicted and observed SNR/SINR distributions, and check decoded payload/collision trends against field trials.

## Q10. What is the core contribution?
**A:** A unified, reproducible system-level methodology connecting orbit geometry, coverage/load dynamics, LR-FHSS decoding behavior, and energy-performance tradeoffs in one framework.
