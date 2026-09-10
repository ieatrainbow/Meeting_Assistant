import datetime
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from outlook_client import _naive, _validate_candidates

# 1. tz-aware UTC -> локальное наивное (UTC+3: 11:37Z -> 14:37)
utc_dt = datetime.datetime(2026, 9, 10, 11, 37, tzinfo=datetime.timezone.utc)
got = _naive(utc_dt)
assert got == datetime.datetime(2026, 9, 10, 14, 37), f"aware convert broken: {got}"
print("aware->naive OK:", got)

# 2. naive проходит без изменений
assert _naive(datetime.datetime(2026, 9, 10, 14, 37)) == datetime.datetime(2026, 9, 10, 14, 37)
print("naive passthrough OK")


class FakeItem:
    pass


ss = datetime.datetime(2026, 9, 10, 14, 7)
se = datetime.datetime(2026, 9, 11, 2, 7)

# a: идёт сейчас (UTC-aware, сдвиг был бы -3ч без фикса) -> должен попасть
a = FakeItem()
a.Start = datetime.datetime(2026, 9, 10, 11, 37, tzinfo=datetime.timezone.utc)
a.End = datetime.datetime(2026, 9, 10, 12, 30, tzinfo=datetime.timezone.utc)
# b: misparse из будущего -> отбраковка как future
b = FakeItem()
b.Start = datetime.datetime(2026, 10, 9, 12, 0)
b.End = datetime.datetime(2026, 9, 9, 13, 0)
# c: давно закончилась -> ended_past
c = FakeItem()
c.Start = datetime.datetime(2026, 9, 9, 10, 0)
c.End = datetime.datetime(2026, 9, 9, 11, 0)
# d: отменённая по MeetingStatus -> canceled
d = FakeItem()
d.MeetingStatus = 5
d.Start = datetime.datetime(2026, 9, 10, 14, 30)
d.End = datetime.datetime(2026, 9, 10, 15, 30)
# e: отменённая префиксом в теме -> canceled
e = FakeItem()
e.MeetingStatus = 1
e.Subject = "Canceled: Ретроспектива"
e.Start = datetime.datetime(2026, 9, 10, 15, 0)
e.End = datetime.datetime(2026, 9, 10, 16, 0)

valid, stats = _validate_candidates([a, b, c, d, e], ss, se)
assert len(valid) == 1 and valid[0] is a, f"kept wrong: {len(valid)}"
assert stats == {"future": 1, "ended": 1, "canceled": 2}, f"stats wrong: {stats}"
print("validation OK: kept=1, future=1, ended=1, canceled=2")
print("ALL_CHECKS_PASSED")
