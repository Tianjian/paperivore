"""Post-processing checks for the GetDP full-stack AFPM model (no solver needed).

The GetDP run itself is not part of CI (it needs an external binary); these tests
pin the geometry and the flux/Kt post-processing on synthetic tables so that a
regression in the analysis code is caught without a solver.
"""
from __future__ import annotations

import math

import pytest

import afpm_getdp as ag


def _table_row(x, bx, by):
    # GetDP 'Format Table' layout: [tag, id, x, y, z, x, y, z, bx, by, bz]
    return [15.0, 1.0, x, 0.0, 0.0, x, 0.0, 0.0, bx, by, 0.0]


def test_pole_pitch_and_area_match_the_annulus():
    r_m, P = ag.pole_geometry()
    assert r_m == pytest.approx((ag.R_O + ag.R_I) / 2)
    assert P == pytest.approx(2 * math.pi * r_m / (2 * ag.P_PAIRS))
    # the 2D pole area P*(R_O-R_I) equals the annular pole area
    assert P * (ag.R_O - ag.R_I) == pytest.approx(
        math.pi * (ag.R_O**2 - ag.R_I**2) / (2 * ag.P_PAIRS), rel=1e-12)


def test_parse_ba_extracts_x_and_by():
    rows = [_table_row(0.0, 0.0, 0.5), _table_row(0.001, 0.0, -0.5)]
    x, by = ag.parse_ba(rows)
    assert list(x) == [0.0, 0.001]
    assert list(by) == [0.5, -0.5]


def test_layer_average_flux_and_kt():
    _, P = ag.pole_geometry()
    Lr = ag.R_O - ag.R_I
    # constant By = 1 T over the pole, at every layer -> cumulative flux = P
    rows = [_table_row(x, 0.0, 1.0) for x in (0.0, P / 2, P)]
    layers = [(0.0, rows), (0.5, rows), (0.75, rows), (0.9, rows), (1.0, rows)]
    meta = {"r_m": (ag.R_O + ag.R_I) / 2, "P": P, "Lx": P,
            "y_pcb": ag.PCB_T / 2, "y_gap": ag.PCB_T / 2 + ag.GAP,
            "y_mag": 0.0, "y_top": 0.0, "h_m": 0.001, "arc": 1.0, "xs": [0.0, P]}
    out = ag.analyse_slice(meta, layers, [], 216.0)
    assert out["flux_per_m_layer_avg_Wb_per_m"] == pytest.approx(P, rel=1e-6)
    assert out["flux_per_pole_Wb"] == pytest.approx(P * Lr, rel=1e-6)
    assert out["Kt_mNm_A"] == pytest.approx(1.5 * ag.P_PAIRS * 216 * (P * Lr) * 1e3, rel=1e-6)


def test_bh_secant_effective_mur():
    from afpm_getdp import _mur_from_BH
    # at 0.57 T the FeSi curve is far from saturation -> high mur (capped)
    assert 2000 < _mur_from_BH(0.57, 1000) <= 5000
    # at 1.8 T it must be much lower
    assert _mur_from_BH(1.8, 1000) < 1500


def test_3d_pole_pitch_matches_2d():
    import afpm_getdp3d as ag3
    _, p3 = ag3.pole_pitch()
    _, p2 = ag.pole_geometry()
    assert p3 == pytest.approx(p2, rel=1e-12)


def test_sector_pole_angles():
    import afpm_getdp3d_sector as sec
    assert sec.POLE_DEG == pytest.approx(36.0)
    assert sec.HALF_DEG == pytest.approx(18.0)
