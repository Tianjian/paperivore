"""Round 3: blade-element momentum solver (25 m HAWT).

Golden values come from results/wind-blade-25m/bem/bem.json, produced by the
same design law quoted in the paper (RERA 2026, doi:10.22044/rera.2026.17534.1520).
"""
from __future__ import annotations

import numpy as np
import pytest

import blade_bem as bb
import blade_geometry as bg


@pytest.fixture(scope="module")
def design():
    r, chord, twist = bg.design_distribution(26.5, 9.0, 3, 1.2, 7.0, 20, 2.5)
    chord = np.minimum(chord, 2.5)      # manufacturability cap used in the case
    return r, chord, twist


def test_airfoil_polar_anchors():
    cl, cd = bb.polar(0.0)
    assert cl == pytest.approx(0.4725, abs=1e-4)      # 0.105 * (0 - (-4.5))
    assert cd == pytest.approx(0.0127, abs=1e-4)
    # post-stall branch must stay finite and decay
    assert bb.polar(25.0)[0] < bb.polar(14.0)[0]


def test_chord_is_capped_and_monotonic_at_tip(design):
    r, chord, twist = design
    assert chord.max() == pytest.approx(2.5, abs=1e-9)
    assert twist[0] > 30.0 and twist[-1] < 1.0        # ~41 deg at root, ~-0.7 at tip


def test_bem_design_point(design):
    r, chord, twist = design
    p = bb.bem_point(9.0, 9.0, r, chord, twist)
    assert p["cp"] == pytest.approx(0.4557, abs=2e-3)
    assert p["thrust_kN"] == pytest.approx(94.25, abs=0.5)


def test_cp_curve_shape(design):
    r, chord, twist = design
    cps = {t: bb.bem_point(t, 9.0, r, chord, twist)["cp"] for t in (4.0, 6.0, 9.0, 12.0)}
    assert 0.0 < cps[4.0] < cps[6.0]
    assert cps[6.0] == pytest.approx(max(cps.values()), abs=0.03)
    assert cps[9.0] > 0.40
    # never exceed the Betz limit
    assert max(cps.values()) < 16 / 27


def test_power_scales_with_v_cubed_at_fixed_rpm(design):
    r, chord, twist = design
    omega = 25.0 * 2 * np.pi / 60.0
    p9 = bb.bem_point(omega * 26.5 / 9.0, 9.0, r, chord, twist)["power_kW"]
    p14 = bb.bem_point(omega * 26.5 / 14.0, 14.0, r, chord, twist)["power_kW"]
    assert p9 == pytest.approx(455.37, abs=8.0)
    assert p14 == pytest.approx(1077.33, abs=25.0)
