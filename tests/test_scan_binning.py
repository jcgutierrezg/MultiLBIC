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
    # The sines are fitted off the step, so none of it leaks into them.
    assert np.std(clean - step) < 0.01 * np.std(mains)
    assert np.abs(clean - step).max() < 1e-9


def test_a_cells_edge_puts_no_mains_into_the_row():
    # A 1 mA edge 50 um wide at 4 mm/s, beside 50 nA of mains and 20 nA
    # of noise. Fitted over the whole row, the edge put about 10 uA of
    # 50 Hz into it (bench, 2026-11-05).
    rng = np.random.default_rng(2)
    t = np.arange(0, 0.6, 1 / 800)
    edge = 1e-3 * 0.5 * (1 + np.array(
        [math.erf((x - 0.3) / (0.012 * math.sqrt(2))) for x in t]))
    mains = 5e-8 * np.sin(2 * math.pi * 50 * t + 0.4)
    noise = rng.normal(0, 2e-8, t.size)
    left = remove_mains(t, edge + mains + noise, 50.0) - edge - noise
    assert np.std(left) < 0.15 * np.std(mains)
    assert np.abs(left).max() < 1e-8


def test_features_shorter_than_a_cycle_dont_leak_either():
    # Features every 15 or 25 ms, far above the mains: the flat-only fit
    # can't see past them, the whole row's fit averages them out.
    t = np.arange(0, 0.6, 1 / 800)
    mains = 5e-8 * np.sin(2 * math.pi * 50 * t)
    for period in (0.015, 0.025):
        features = 1e-4 * np.sign(np.sin(2 * math.pi * t / period + 0.3))
        clean = remove_mains(t, features + mains, 50.0)
        assert np.std(clean - features) < 0.01 * np.std(mains)


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
