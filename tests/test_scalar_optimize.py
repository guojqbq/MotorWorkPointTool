import pytest

from calculation.scalar_optimize import minimize_scalar


def test_dependency_free_bounded_minimizer_finds_smooth_minimum():
    result = minimize_scalar(
        lambda value: (value + 2.75) ** 2 + 4.0,
        bounds=(-10.0, 5.0),
        method="bounded",
        options={"xatol": 1e-12, "maxiter": 200},
    )
    assert result.success
    assert result.x == pytest.approx(-2.75, abs=5e-8)
    assert result.fun == pytest.approx(4.0, abs=1e-12)


def test_dependency_free_bounded_minimizer_rejects_invalid_method():
    with pytest.raises(ValueError, match="bounded"):
        minimize_scalar(
            lambda value: value**2,
            bounds=(-1.0, 1.0),
            method="brent",
        )
