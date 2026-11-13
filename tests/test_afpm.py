"""Round 5: PCB axial-flux motor — magnetic circuit and the honest failure.

The point of these tests is to freeze the *known* state: the circuit is internally
consistent, and it disagrees with the measured Kt by a factor of two. If a future
change makes the disagreement vanish, that change needs explaining, not applause.
"""
from __future__ import annotations

import math

import pytest

import afpm_model as am


def test_pole_area():
    expect = math.pi * (0.0095**2 - 0.0035**2) / (2 * 5)
    assert am.pole_area() == pytest.approx(expect, rel=1e-12)
    assert am.pole_area() == pytest.approx(2.45044e-05, rel=1e-4)


def test_airgap_flux_density_matches_report():
    """Dual-rotor (TORUS) 1-D circuit: 2 magnets in series + 2 gaps + 1 PCB."""
    assert am.circuit_Bg(0.001)["B_g_T"] == pytest.approx(0.30935, abs=1e-4)


def test_circuit_flux_uses_the_same_Bg():
    """flux_per_pole must be derived from the circuit Bg (no mixed bases)."""
    c = am.circuit_Bg(0.001)
    assert c["flux_per_pole_Wb"] == pytest.approx(c["B_g_T"] * am.pole_area(), rel=1e-12)
    assert c["flux_per_pole_Wb"] == pytest.approx(7.5804e-06, rel=1e-4)


def test_kt_from_the_circuit_needs_more_turns_than_the_paper_states():
    """Even the (optimistic) 2-D FEA Bg needs ~459 turns; the correct 1-D
    circuit (0.309 T) needs ~563 turns, while Table I implies 216."""
    Bg = am.circuit_Bg(0.001)["B_g_T"]
    implied = am.KT_MEAS / (1.5 * am.P_PAIRS * Bg * am.pole_area())
    assert implied == pytest.approx(562.9, abs=3.0)
    assert am.kt_from_Bg(Bg, 216.0) * 1e3 == pytest.approx(12.28, abs=0.02)


def test_flux_density_drops_with_thinner_magnet():
    thin = am.circuit_Bg(0.0005)["B_g_T"]      # 0.5 mm magnet
    thick = am.circuit_Bg(0.002)["B_g_T"]      # 2.0 mm magnet
    assert thick > thin
    assert 0.0 < thin < 0.6 and 0.0 < thick < 0.6


def test_kt_at_table_turns_matches_report():
    # 216 series turns inferred from Table I, with the 2D-FEA flux density
    assert am.kt_from_Bg(0.379, 216.0) == pytest.approx(0.015045, abs=1e-5)


def test_measured_kt_needs_more_turns_than_the_paper_states():
    """The published failure: measured 32 mNm/A cannot be reached with 216 turns."""
    implied = am.KT_MEAS / (1.5 * am.P_PAIRS * 0.379 * am.pole_area())
    assert implied == pytest.approx(459.4, abs=2.0)
    assert implied > 2 * 216


def test_stall_point_implied_kt_is_below_small_signal():
    """158 mNm / 5.95 A = 26.6 mNm/A < 32 mNm/A - saturation, physically sensible."""
    stall_kt = am.T_STALL_MEAS / am.I_STALL_MEAS
    assert stall_kt == pytest.approx(0.02655, abs=1e-4)
    assert stall_kt < am.KT_MEAS


def test_winding_geometry_is_consistent_with_measured_resistance_order():
    """The naive trace-geometry resistance lands within a factor 2 of the measurement."""
    r_m = (am.R_O + am.R_I) / 2
    turn_len = 2 * (am.R_O - am.R_I) + 2 * math.pi * r_m / am.SLOTS
    area = am.TRACE_W * am.CU_T
    R = am.RHO_CU * 216 * turn_len / area
    assert 1.0 < R < 10.0
    assert R == pytest.approx(2.84, abs=0.1)
