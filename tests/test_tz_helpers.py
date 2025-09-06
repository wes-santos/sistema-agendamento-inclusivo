from datetime import date, datetime, time

import pytest

from app.utils.tz import (
    BR_TZ,
    UTC,
    combine_local_to_utc,
    ensure_aware_utc,
    iso_utc,
    split_utc_to_local,
    to_local,
    to_utc,
)


@pytest.mark.parametrize(
    "d,t",
    [
        (date(2025, 1, 15), time(0, 0)),
        (date(2025, 3, 10), time(9, 45)),
        (date(2025, 6, 21), time(12, 0)),
        (date(2025, 9, 10), time(18, 30)),
    ],
)
def test_round_trip_local_to_utc_and_back(d, t):
    # local -> UTC -> local
    dt_utc = combine_local_to_utc(d, t, BR_TZ)
    assert dt_utc.tzinfo == UTC

    d2, t2 = split_utc_to_local(dt_utc, BR_TZ)
    # time retornado é aware; compare os componentes
    assert d2 == d
    assert (t2.hour, t2.minute, t2.second, t2.microsecond) == (
        t.hour,
        t.minute,
        t.second,
        t.microsecond,
    )


def test_to_utc_from_aware_and_naive():
    # aware local -> UTC
    local = datetime(2025, 9, 10, 14, 0, tzinfo=BR_TZ)
    u = to_utc(local)
    assert u.tzinfo == UTC

    # naive interpretado como BR
    local_naive = datetime(2025, 9, 10, 14, 0)
    u2 = to_utc(local_naive, BR_TZ)
    assert u2.tzinfo == UTC
    assert u2 == u  # mesma hora convertida


def test_to_local_requires_aware_utc():
    with pytest.raises(ValueError):
        to_local(datetime(2025, 9, 10, 17, 0))  # naive


def test_ensure_aware_utc_errors_on_naive():
    with pytest.raises(ValueError):
        ensure_aware_utc(datetime(2025, 9, 10, 17, 0))


def test_iso_utc_has_Z_suffix():
    dtu = datetime(2025, 9, 10, 17, 0, tzinfo=UTC)
    s = iso_utc(dtu)
    assert s.endswith("Z")
