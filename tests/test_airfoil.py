"""Round 1/2: NACA geometry and thin-airfoil theory.

These are the exact numbers the reports are built on. If someone "fixes" the
airfoil generator, this file is what stops the change from silently moving the
baseline of every downstream case.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

import polar_validate as pv
import airfoil_validate as av


def naca_stats(m: float, p: float, t: float):
    up, lo = pv.naca4(m, p, t, 240)
    x = lo[:, 0]
    thick = up[::-1, 1] - lo[:, 1]
    camber = 0.5 * (up[::-1, 1] + lo[:, 1])
    return (
        float(thick.max()), float(x[int(np.argmax(thick))]),
        float(camber.max()), float(x[int(np.argmax(camber))]),
    )


def test_naca4412_thickness_and_camber():
    thick, x_t, camber, x_c = naca_stats(0.04, 0.40, 0.12)
    assert thick == pytest.approx(0.119888, abs=1e-5)
    assert x_t == pytest.approx(0.3077, abs=2e-3)
    assert camber == pytest.approx(0.04, abs=1e-5)
    assert x_c == pytest.approx(0.3989, abs=2e-3)


def test_naca2412_thickness_and_camber():
    thick, _, camber, _ = naca_stats(0.02, 0.40, 0.12)
    assert thick == pytest.approx(0.119996, abs=1e-5)
    assert camber == pytest.approx(0.02, abs=1e-5)


@pytest.mark.parametrize("m", [0.02, 0.04])
def test_zero_lift_angle(m):
    a0 = pv.thin_airfoil(m, 0.40)["alpha_L0_deg"]
    # thin-airfoil theory: alpha_L0 = -(1/pi) * integral of the camber slope
    assert -6.0 < a0 < -1.5
    if m == 0.04:
        assert a0 == pytest.approx(-4.1544, abs=2e-3)
    else:
        assert a0 == pytest.approx(-2.0772, abs=2e-3)


def test_lift_slope_is_two_pi_per_radian():
    th = pv.thin_airfoil(0.04, 0.40)
    assert th["slope_per_rad"] == pytest.approx(2 * math.pi, rel=1e-12)
    # 0.1097 per degree is the canonical value quoted in the reports
    assert th["slope_per_rad"] * math.pi / 180 == pytest.approx(0.10966, abs=1e-4)


def test_cl_at_five_degrees():
    a0 = math.radians(pv.thin_airfoil(0.04, 0.40)["alpha_L0_deg"])
    assert pv.cl_thin(5.0, a0) == pytest.approx(1.0039, abs=1e-4)


def test_s2_ordinates_are_evaluated_not_interpolated():
    """S2 used to interpolate the reversed TE->LE polyline and returned 0.0
    for every upper station.  The check must evaluate the NACA equations."""
    table = {
        0.10: (0.0638, -0.0288), 0.30: (0.0974, -0.0224),
        0.50: (0.0918, -0.0140), 0.70: (0.0666, -0.0066),
        0.90: (0.0266, -0.0022), 1.00: (0.0012, -0.0012),
    }
    for xc, (yu_ref, yl_ref) in table.items():
        yu, yl = av.naca4_ordinates(0.04, 0.40, 0.12, xc)
        assert yu == pytest.approx(yu_ref, abs=1e-4)
        assert yl == pytest.approx(yl_ref, abs=1e-4)


def test_symmetric_section_has_zero_lift_at_zero_incidence():
    a0 = math.radians(pv.thin_airfoil(0.0, 0.40)["alpha_L0_deg"])
    assert pv.cl_thin(0.0, a0) == pytest.approx(0.0, abs=1e-9)
