#!/usr/bin/env python
"""Blade-element momentum (BEM) solver for the wind-turbine blade design.

Ground truth (paper, open access)
---------------------------------
M. Imran, A. Rafai, "Aerodynamic Performance Assessment and Blade Design
Optimization of Horizontal-Axis Wind Turbines ...", RERA 7(1):117-127, 2026,
DOI 10.22044/rera.2026.17534.1520.

    R = 26.5 m (25 m blade + 1.5 m hub), B = 3, design TSR = 9
    Cp_max = 0.52 at TSR = 9
    P = 500 kW at 9 m/s, 1373 kW at 14 m/s (rated speed 25 rpm)

Outputs
-------
<job>/bem/cp_tsr.csv, power_curve.csv, bem.json
<job>/bem/cp_tsr.png, power_curve.png

Usage: python blade_bem.py --job <dir> [--rho 1.225]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

R = 26.5
B = 3
RATED_RPM = 25.0


# --------------------------------------------------------------------------- #
# airfoil polar (NACA 5512, low-Re engineering model)
# --------------------------------------------------------------------------- #
def polar(alpha_deg: float):
    a0 = -4.5
    a = alpha_deg - a0
    if a <= 0:
        cl = 0.105 * a
        cd = 0.012 + 0.02 * cl**2
        return cl, cd
    if a <= 15.0:
        cl = min(0.105 * a, 1.45)
        cd = 0.012 + 0.008 * (a / 15.0) ** 2 + 0.012 * max(0.0, cl - 1.0) ** 2
        return cl, cd
    # post-stall: lift decays, drag rises
    cl = max(0.6, 1.45 - 0.05 * (a - 15.0))
    cd = 0.06 + 0.02 * (a - 15.0)
    return cl, cd


# --------------------------------------------------------------------------- #
# BEM for one operating point
# --------------------------------------------------------------------------- #
def prandtl(r, phi):
    f_tip = 0.5 * B * (R - r) / (r * math.sin(phi))
    f_root = 0.5 * B * (r - 1.5) / (1.5 * math.sin(phi))
    F = (2.0 / math.pi) * math.acos(min(1.0, math.exp(-max(f_tip, 1e-9)))) \
        * (2.0 / math.pi) * math.acos(min(1.0, math.exp(-max(f_root, 1e-9))))
    return max(F, 1e-6)


def bem_point(tsr: float, V: float, r: np.ndarray, chord: np.ndarray, twist: np.ndarray,
              rho: float = 1.225):
    omega = tsr * V / R
    dP = 0.0
    dT = 0.0
    rows = []
    for ri, ci, ti in zip(r, chord, twist):
        sigma = B * ci / (2.0 * math.pi * ri)
        a, ap = 0.3, 0.0
        for _ in range(200):
            phi = math.atan2(V * (1.0 - a), omega * ri * (1.0 + ap))
            alpha = math.degrees(phi) - ti
            cl, cd = polar(alpha)
            F = prandtl(ri, phi)
            cn = cl * math.cos(phi) + cd * math.sin(phi)
            ct = cl * math.sin(phi) - cd * math.cos(phi)
            denom = 4.0 * F * math.sin(phi) ** 2
            a_new = 1.0 / (denom / (sigma * cn) + 1.0)
            if a_new > 0.4:
                # Glauert empirical correction, a_c = 0.2 (Wilson & Lissaman)
                K = denom / (sigma * cn)
                ac = 0.2
                rad = (K * (1 - 2 * ac) + 2) ** 2 + 4 * (K * ac**2 - 1)
                a_new = 0.5 * (2.0 + K * (1 - 2 * ac) - math.sqrt(max(rad, 0.0)))
            ap_new = 1.0 / (4.0 * F * math.sin(phi) * math.cos(phi) / (sigma * ct) - 1.0) \
                if ct > 1e-6 else 0.0
            if abs(a_new - a) < 1e-6 and abs(ap_new - ap) < 1e-6:
                a, ap = a_new, ap_new
                break
            a, ap = 0.5 * (a + a_new), 0.5 * (ap + ap_new)
        phi = math.atan2(V * (1.0 - a), omega * ri * (1.0 + ap))
        alpha = math.degrees(phi) - ti
        cl, cd = polar(alpha)
        W2 = (V * (1 - a)) ** 2 + (omega * ri * (1 + ap)) ** 2
        dP += 0.5 * rho * W2 * B * ci * (cl * math.sin(phi) - cd * math.cos(phi)) * omega * ri
        dT += 0.5 * rho * W2 * B * ci * (cl * math.cos(phi) + cd * math.sin(phi))
        rows.append({"r_m": round(float(ri), 3), "phi_deg": round(math.degrees(phi), 3),
                     "alpha_deg": round(alpha, 3), "cl": round(cl, 4), "cd": round(cd, 4),
                     "a": round(a, 5), "ap": round(ap, 5)})
    dr = float(r[1] - r[0])
    P = dP * dr
    T = dT * dr
    A = math.pi * R**2
    cp = P / (0.5 * rho * A * V**3)
    ct = T / (0.5 * rho * A * V**2)
    return {"tsr": round(tsr, 3), "cp": round(cp, 4), "ct": round(ct, 4),
            "power_kW": round(P / 1e3, 2), "thrust_kN": round(T / 1e3, 2),
            "omega_rad_s": round(omega, 4), "sections": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--rho", type=float, default=1.225)
    args = ap.parse_args()

    job = Path(args.job).resolve()
    out = job / "bem"
    out.mkdir(parents=True, exist_ok=True)

    design = json.loads((job / "blade" / "design.json").read_text(encoding="utf-8"))
    rows = design["rows"]
    r = np.array([x["r_m"] for x in rows])
    chord = np.array([x["chord_m"] for x in rows])
    twist = np.array([x["twist_deg"] for x in rows])

    # --- Cp(TSR) sweep ------------------------------------------------------
    sweep = []
    for tsr in np.arange(3.0, 12.01, 0.5):
        p = bem_point(float(tsr), 9.0, r, chord, twist, args.rho)
        sweep.append({"tsr": p["tsr"], "cp": p["cp"], "ct": p["ct"]})
    best = max(sweep, key=lambda x: x["cp"])

    # --- power curve at 25 rpm (fixed-speed) --------------------------------
    omega = RATED_RPM * 2.0 * math.pi / 60.0
    power = []
    for V in (5, 6, 7, 8, 9, 10, 11, 12, 13, 14):
        tsr = omega * R / V
        p = bem_point(tsr, V, r, chord, twist, args.rho)
        power.append({"V_m_s": V, "tsr": round(tsr, 3), "cp": p["cp"],
                      "power_kW": p["power_kW"], "thrust_kN": p["thrust_kN"]})

    at9 = next(p for p in power if p["V_m_s"] == 9)
    at14 = next(p for p in power if p["V_m_s"] == 14)

    info = {
        "paper": {"doi": "10.22044/rera.2026.17534.1520",
                  "reported": {"Cp_max": 0.52, "Cp_TSR": 9,
                               "P_9_m_s_kW": 500, "P_14_m_s_kW": 1373, "rpm": 25}},
        "cp_sweep": sweep,
        "cp_max": best,
        "power_curve": power,
        "check": {
            "cp_at_tsr9": next(x["cp"] for x in sweep if abs(x["tsr"] - 9.0) < 1e-6),
            "cp_max_rel_err": round((best["cp"] - 0.52) / 0.52 * 100, 1),
            "P9_rel_err": round((at9["power_kW"] - 500) / 500 * 100, 1),
            "P14_rel_err": round((at14["power_kW"] - 1373) / 1373 * 100, 1),
        },
        "conditions": {"R_m": R, "B": B, "rho": args.rho, "rated_rpm": RATED_RPM},
    }
    (out / "bem.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / "cp_tsr.csv").open("w", encoding="utf-8") as fh:
        fh.write("tsr,cp,ct\n")
        for s in sweep:
            fh.write(f"{s['tsr']},{s['cp']},{s['ct']}\n")
    with (out / "power_curve.csv").open("w", encoding="utf-8") as fh:
        fh.write("V_m_s,tsr,cp,power_kW\n")
        for s in power:
            fh.write(f"{s['V_m_s']},{s['tsr']},{s['cp']},{s['power_kW']}\n")

    print(json.dumps({"cp_max": best, "check": info["check"], "at9": at9, "at14": at14},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
