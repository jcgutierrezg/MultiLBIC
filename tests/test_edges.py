"""The error-function edge fit: where an edge is and how sharp."""

import math

import numpy as np
import pytest

from multilbic.scan.edges import (
    WIDTH_10_90_PER_SIGMA,
    NoEdge,
    RowEdge,
    edge_shift,
    fit_edge,
    fit_rows,
    phi,
)


def edge(x, x0, sigma, low, step, slope=0.0):
    return low + slope * (x - x0) + step * phi((x - x0) / sigma)


def test_phi_matches_known_values():
    assert phi(np.array([0.0]))[0] == pytest.approx(0.5)
    assert phi(np.array([1.2815515655446004]))[0] == pytest.approx(0.9)
    assert phi(np.array([-1.2815515655446004]))[0] == pytest.approx(0.1)


@pytest.mark.parametrize("step", [1e-6, -1e-6])
def test_recovers_position_and_width_through_noise(step):
    rng = np.random.default_rng(1)
    x = np.sort(rng.uniform(0.0, 2.0, 3000))
    sigma = 0.016  # laser 2's 41 um 10-90 width
    y = edge(x, 0.7312, sigma, 2e-7, step) + rng.normal(0, 5e-8, x.size)
    fit = fit_edge(x, y)
    assert fit.position_mm == pytest.approx(0.7312, abs=1.5e-3)
    assert fit.width_mm == pytest.approx(WIDTH_10_90_PER_SIGMA * sigma,
                                         rel=0.1)
    assert fit.rising == (step > 0)
    # The reported error is honest: the miss is within a few of them.
    assert abs(fit.position_mm - 0.7312) < 4 * fit.position_err_mm


def test_a_leaning_background_does_not_move_the_edge():
    x = np.linspace(-1.0, 1.0, 2000)
    y = edge(x, 0.1, 0.05, 1e-6, -1e-6, slope=4e-7)
    fit = fit_edge(x, y)
    assert fit.position_mm == pytest.approx(0.1, abs=1e-5)
    assert fit.sigma_mm == pytest.approx(0.05, rel=1e-3)
    assert fit.slope_a_per_mm == pytest.approx(4e-7, rel=1e-2)


def test_a_broad_edge_and_a_sharp_one():
    x = np.linspace(0.0, 3.0, 4000)
    for sigma in (0.002, 0.1):
        fit = fit_edge(x, edge(x, 1.5, sigma, 0.0, 1.0))
        assert fit.position_mm == pytest.approx(1.5, abs=1e-4)
        assert fit.sigma_mm == pytest.approx(sigma, rel=0.05)


def test_x_range_and_near_choose_between_two_edges():
    x = np.linspace(0.0, 2.0, 4000)
    # A finger: down at 0.6, up at 0.8; the deeper cell edge at 1.5.
    y = (edge(x, 0.6, 0.01, 1.0, -0.3) + 0.3 * phi((x - 0.8) / 0.01)
         - phi((x - 1.5) / 0.01))
    assert fit_edge(x, y).position_mm == pytest.approx(1.5, abs=1e-3)
    assert fit_edge(x, y, x_range=(0.4, 0.7)).position_mm == pytest.approx(
        0.6, abs=1e-3)
    assert fit_edge(x, y, near=0.75).position_mm == pytest.approx(
        0.8, abs=1e-3)


def test_no_edge_in_noise_is_refused():
    rng = np.random.default_rng(2)
    x = np.linspace(0.0, 1.0, 2000)
    with pytest.raises(NoEdge):
        fit_edge(x, rng.normal(0, 1e-8, x.size))
    with pytest.raises(NoEdge):
        fit_edge(x[:5], x[:5])


def test_the_model_reproduces_the_fit():
    x = np.linspace(0.0, 1.0, 500)
    y = edge(x, 0.4, 0.03, 0.5, 2.0, slope=0.1)
    fit = fit_edge(x, y)
    assert np.max(np.abs(fit.model(x) - y)) < 1e-6
    assert fit.as_dict()["width_um"] == pytest.approx(
        WIDTH_10_90_PER_SIGMA * 30, rel=1e-3)


def _rows(shift_mm, lean_mm_per_mm=0.0, n=9):
    """Rows of one edge that leans across B; forward rows see it
    shift/2 further along A, reverse rows shift/2 less."""
    rng = np.random.default_rng(3)
    rows = []
    for k in range(n):
        b = 10.0 + 0.05 * k
        direction = 1 if k % 2 == 0 else -1
        x0 = 0.5 + lean_mm_per_mm * (b - 10.0) + direction * shift_mm / 2
        x = np.linspace(0.0, 1.0, 800)
        y = edge(x, x0, 0.02, 0.0, -1e-6) + rng.normal(0, 2e-8, x.size)
        rows.append((k, direction, b, x, y))
    return rows


def test_edge_shift_cancels_a_lean_across_rows():
    edges, failed = fit_rows(_rows(0.020, lean_mm_per_mm=0.3))
    assert not failed
    shift = edge_shift(edges)
    assert shift is not None
    assert shift.shift_mm == pytest.approx(0.020, abs=1e-3)
    assert shift.count == 7  # the first and last rows lack a neighbour


def test_edge_shift_needs_alternating_neighbours():
    edges, _ = fit_rows(_rows(0.0))
    assert edge_shift([e for e in edges if e.direction > 0]) is None
    still = [RowEdge(e.row, 0, e.b_mm, e.fit) for e in edges]
    assert edge_shift(still) is None


def test_fit_rows_brings_a_stray_row_back_to_the_edge():
    rows = _rows(0.0)
    k, direction, b, x, y = rows[4]
    # A deep dip far from the edge would win on its own.
    y = y - 3e-6 * np.exp(-0.5 * ((x - 0.1) / 0.01) ** 2)
    rows[4] = (k, direction, b, x, y)
    edges, failed = fit_rows(rows)
    assert not failed
    assert all(math.isclose(e.fit.position_mm, 0.5, abs_tol=2e-3)
               for e in edges)
