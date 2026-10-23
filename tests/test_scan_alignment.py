"""The serpentine shift, measured from rows whose shift is known."""

import numpy as np
import pytest

from multilbic.scan.alignment import RowSamples, estimate_shift
from multilbic.sim.sample import SyntheticSample


def rows(shift_mm, n=6, noise_a=20e-9, sample=None, seed=0):
    """Serpentine rows across the synthetic sample, every forward row
    seeing features `shift_mm / 2` further along A than they are, and
    every reverse row the same amount less."""
    sample = sample or SyntheticSample.default(1.0, 0.4)
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        v = 0.1 + 0.04 * k
        direction = 1 if k % 2 == 0 else -1
        # 4 µm between samples, with the sample times not on a grid.
        true_u = np.sort(rng.uniform(-0.1, 1.1, 300))
        values = np.array([sample.current(650, u, v) for u in true_u])
        values += rng.normal(0, noise_a, values.size)
        out.append(RowSamples(direction, true_u + direction * shift_mm / 2,
                              values))
    return out


@pytest.mark.parametrize("shift_um", [-23.0, -7.5, 0.0, 3.3, 20.0, 41.0])
def test_finds_the_shift(shift_um):
    found = estimate_shift(rows(shift_um / 1000))
    assert found.found
    assert found.pairs == 5
    assert found.shift_mm * 1000 == pytest.approx(shift_um, abs=0.5)


def test_correction_puts_rows_back():
    found = estimate_shift(rows(0.02))
    a = np.array([1.0, 2.0])
    assert found.corrected(a, 1) == pytest.approx(a - found.shift_mm / 2)
    assert found.corrected(a, -1) == pytest.approx(a + found.shift_mm / 2)


def test_offsets_and_slow_drift_between_rows_do_not_matter():
    shifted = rows(0.015)
    drifting = [
        RowSamples(r.direction, r.a_mm,
                   r.values + 3e-7 * k + 2e-7 * np.sin(r.a_mm * 3))
        for k, r in enumerate(shifted)
    ]
    assert estimate_shift(drifting).shift_mm * 1000 == pytest.approx(
        15.0, abs=0.5
    )


def test_featureless_rows_are_not_guessed():
    flat = SyntheticSample(1.0, 0.4, ())  # nothing on it but noise
    found = estimate_shift(rows(0.01, sample=flat))
    assert not found.found
    a = np.array([1.0])
    assert found.corrected(a, 1) == pytest.approx(a)


def test_one_direction_scans_have_nothing_to_compare():
    same_way = [
        RowSamples(1, r.a_mm, r.values) for r in rows(0.01)
    ]
    assert not estimate_shift(same_way).found


def test_a_broad_spot_gets_the_smoothing_it_needs():
    """A 50 µm spot with bench-like noise, as laser 2 on the bench
    (2026-10-23): 2 µm smoothing only correlates noise, so a coarser one
    is chosen and still finds the shift."""
    broad = SyntheticSample.default(1.0, 0.4, spot_sigma_mm=0.05)
    found = estimate_shift(rows(0.03, sample=broad, noise_a=1.5e-7, n=10))
    assert found.found
    assert found.smooth_mm >= 0.01
    assert found.shift_mm * 1000 == pytest.approx(30.0, abs=5.0)


def test_a_sharp_spot_keeps_fine_smoothing():
    found = estimate_shift(rows(0.0123))
    assert found.smooth_mm == 0.002
    assert found.shift_mm * 1000 == pytest.approx(12.3, abs=0.5)
