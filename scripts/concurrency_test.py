"""
Concurrency test for appointment creation.

- Logs in as a FAMILY user
- Finds a valid slot via /api/v1/slots for a given professional
- Fires N concurrent POST /api/v1/appointments for the same slot
- Prints the status codes (expect 201 for a single winner, 409 for others)
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
from typing import Optional

import httpx


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--email", default="family1@example.com")
    p.add_argument("--password", default="secret")
    p.add_argument("--student-id", type=int, default=1)
    p.add_argument("--professional-id", type=int, default=1)
    p.add_argument("--slot-minutes", type=int, default=30)
    p.add_argument("--n", type=int, default=5, help="number of concurrent requests")
    return p.parse_args()


async def find_valid_slot(
    client: httpx.AsyncClient,
    base: str,
    professional_id: int,
    slot_minutes: int,
    headers: dict[str, str],
) -> Optional[str]:
    """Fetches the first available slot from /slots over the next 14 days.
    Returns an ISO-8601 UTC string with Z suffix.
    """
    today_local = dt.datetime.now().date()
    for day in range(0, 14):
        d = (today_local + dt.timedelta(days=day)).isoformat()
        r = await client.get(
            f"{base}/api/v1/slots",
            params={
                "professional_id": str(professional_id),
                "date": d,
                "slot_minutes": str(slot_minutes),
            },
            headers=headers,
        )
        if r.status_code != 200:
            continue
        data = r.json()
        slots = data.get("slots") or []
        if slots:
            return slots[0]
    return None


async def run():
    args = parse_args()

    async with httpx.AsyncClient(timeout=10) as c:
        # login
        r = await c.post(
            f"{args.base}/api/v1/auth/login",
            json={"email": args.email, "password": args.password},
            headers={"accept": "application/json"},
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        jwt = f"Bearer {token}"
        auth_headers = {"Authorization": jwt}

        # find a valid slot via slots endpoint
        starts_at_iso = await find_valid_slot(
            c, args.base, args.professional_id, args.slot_minutes, auth_headers
        )
        if not starts_at_iso:
            raise RuntimeError("Could not find a valid slot in the next 14 days.")

        payload = {
            "student_id": str(args.student_id),
            "professional_id": str(args.professional_id),
            "starts_at_iso": starts_at_iso,
            "slot_minutes": args.slot_minutes,
            "location": "Sala 2",
        }

        async def hit(i: int):
            resp = await c.post(
                f"{args.base}/api/v1/appointments", json=payload, headers=auth_headers
            )
            text = resp.text[:200]
            return i, resp.status_code, text

        results = await asyncio.gather(*(hit(i) for i in range(args.n)))
        print("payload:", payload)
        for i, code, body in results:
            print(f"req#{i}: {code} {body}")


if __name__ == "__main__":
    asyncio.run(run())
