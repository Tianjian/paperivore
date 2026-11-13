"""Round 4: exhaust-pipe thermal reference solutions.

The 1D radial solution is exact; the fin solution adds axial conduction. Both are
what the CalculiX deck is compared against, so they are pinned here.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

import thermal_pipe as tp


def test_segment_solution_matches_report():
    seg = tp.analytic_segment(0.01, 0.02)
    assert seg["T_gas_C"] == pytest.approx(492.5, abs=0.01)
    assert seg["T_wall_inner_C"] == pytest.approx(446.359, abs=0.01)
    assert seg["T_wall_outer_C"] == pytest.approx(445.916, abs=0.01)


def test_wall_is_nearly_isothermal():
    """Bi << 1 for a 1.5 mm steel wall: inner and outer differ by < 1 K."""
    seg = tp.analytic_segment(0.05, 0.02)
    assert abs(seg["T_wall_inner_C"] - seg["T_wall_outer_C"]) < 1.0


def test_uniform_gas_fin_solution_is_flat():
    x, T = tp.fin_reference(t_in=500.0, t_out=500.0)
    assert T.min() == pytest.approx(T.max(), abs=1e-6)
    assert T.mean() == pytest.approx(453.083, abs=0.01)


def test_gradient_fin_solution_endpoints():
    x, T = tp.fin_reference(t_in=500.0, t_out=350.0)
    assert T[0] == pytest.approx(443.242, abs=0.05)
    assert T[-1] == pytest.approx(327.585, abs=0.05)
    assert T[0] > T[-1]


def test_fin_parameter_is_large_enough_to_matter():
    """mL ~ 14 means a per-segment 1D model is wrong by ~1.7 % - the lesson of the case."""
    A_c = math.pi * (tp.R_O**2 - tp.R_I**2)
    P_o, P_i = 2 * math.pi * tp.R_O, 2 * math.pi * tp.R_I
    m = math.sqrt((tp.H_O * P_o + tp.H_I * P_i) / (tp.K_W_MK * A_c))
    assert m * tp.L == pytest.approx(13.8, abs=0.6)


def test_resistance_ratio_sanity():
    """Outer convection dominates: R_o >> R_wall."""
    R_o = 1.0 / (tp.H_O * 2 * math.pi * tp.R_O * tp.L)
    R_w = math.log(tp.R_O / tp.R_I) / (2 * math.pi * tp.K_W_MK * tp.L)
    assert R_o / R_w > 500
