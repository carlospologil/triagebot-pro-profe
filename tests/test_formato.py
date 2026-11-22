from datetime import UTC, datetime

import pytest

from app.services.formato import antiguedad

AHORA = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("iso", "esperado"),
    [
        ("2026-03-02T12:00:00Z", "hace un momento"),
        ("2026-03-02T11:59:30Z", "hace un momento"),
        ("2026-03-02T12:00:30Z", "hace un momento"),
        ("2026-03-02T11:55:00Z", "hace 5 min"),
        ("2026-03-02T09:00:00Z", "hace 3 h"),
        ("2026-03-01T12:00:00Z", "hace 1 d"),
        ("2026-02-20T12:00:00Z", "hace 10 d"),
        ("2026-01-31T12:00:00Z", "hace 1 mes"),
        ("2025-12-02T12:00:00Z", "hace 3 meses"),
        ("2025-03-02T12:00:00Z", "hace 1 año"),
        ("2023-03-02T12:00:00Z", "hace 3 años"),
    ],
)
def test_antiguedad_legible(iso, esperado):
    assert antiguedad(iso, AHORA) == esperado
