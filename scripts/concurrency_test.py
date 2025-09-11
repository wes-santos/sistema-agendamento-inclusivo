# scripts/concurrency_test.py
import asyncio
import datetime as dt

import httpx

BASE = "http://localhost:8000"
START = (dt.datetime.now(dt.UTC) + dt.timedelta(days=-2, hours=-11)).replace(
    minute=0, second=0, microsecond=0
)

print(START)

token = httpx.post(
    f"{BASE}/auth/login",
    json={"email": "maria.luiza@example.com", "password": "Passw0rd!"},
).json()["access_token"]


jwt_token = f"Bearer {token}"


payload = {
    "student_id": "2",
    "professional_id": "1",
    "starts_at_iso": START.isoformat(timespec="seconds").replace("+00:00", "Z"),
    "slot_minutes": 30,
    "location": "Sala 2",
}


async def hit(i):
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.post(
            f"{BASE}/appointments", json=payload, headers={"Authorization": jwt_token}
        )
        return i, r.status_code, r.text


async def main():
    res = await asyncio.gather(*(hit(i) for i in range(5)))
    for r in res:
        print(r)


asyncio.run(main())
