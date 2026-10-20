"""Mains removal, the dark baseline and the pixel grid."""

import math

import numpy as np
import pytest

from multilbic.scan.binning import baseline, bin_rows, remove_mains


def test_mains_comes_out_and_a_step_stays():
    t = np.arange(0, 0.6, 1 / 400)
    step = np.where(t > 0.3, 1e-6, 0.0)
    mains = 5e-8 * np.sin(2 * math.pi * 50 * t + 0.4)
    mains += 1e-8 * np.sin(2 * math.pi * 150 * t + 1.1)
    clean = remove_mains(t, step + mains, 50.0)
    # A big feature projects a little onto the sines: about 1 % of a
    # step over 30 cycles. That is the price; the mains is 4x worse.
    assert np.std(clean - step) < 0.3 * np.std(mains)
    assert np.abs(clean - step).max() < 0.03e-6


def test_mains_on_uneven_timestamps():
    rng = np.random.default_rng(0)
    t = np.sort(rng.uniform(0, 0.5, 300))
    noisy = 1e-7 + 4e-8 * np.sin(2 * math.pi * 50 * t)
    assert remove_mains(t, noisy, 50.0) == pytest.approx(
        np.full(t.size, 1e-7), abs=2e-9
    )


def test_too_few_samples_are_left_alone():
    t = np.arange(5) / 400
    y = np.arange(5.0)
    assert remove_mains(t, y, 50.0) == pytest.approx(y)


def test_baseline_offset_and_noise():
    rng = np.random.default_rng(1)
    t = np.arange(0, 3, 1 / 500)
    y = -5e-9 + rng.normal(0, 2e-8, t.size)
    y += 2e-8 * np.sin(2 * math.pi * 50 * t)
    base = baseline(t, y, 50.0)
    assert base.offset_a == pytest.approx(-5e-9, abs=2e-9)
    # The mains is not counted as noise.
    assert base.noise_a == pytest.approx(2e-8, rel=0.1)
    assert base.samples == t.size


def test_bin_rows():
    rows = [
        (0, np.array([0.001, 0.004, 0.006, 0.0095]), np.array([1, 3, 10, 20.0])),
        (1, np.array([-0.001, 0.012, 0.0101]), np.array([7, 5, 6.0])),
        (5, np.array([0.001]), np.array([99.0])),  # no such row: ignored
    ]
    grid = bin_rows(rows, n_rows=2, width_mm=0.0125, pixel_mm=0.005,
                    pitch_mm=0.05)
    assert grid.values.shape == (2, 3)
    assert grid.values[0, 0] == pytest.approx(2.0)
    assert grid.values[0, 1] == pytest.approx(15.0)
    assert np.isnan(grid.values[0, 2])
    assert grid.values[1, 2] == pytest.approx(5.5)
    assert grid.counts.tolist() == [[2, 2, 0], [0, 0, 2]]
    assert grid.u_centres == pytest.approx([0.0025, 0.0075, 0.0125])
    assert grid.v_centres == pytest.approx([0.025, 0.075])
