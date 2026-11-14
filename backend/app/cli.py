"""Command-line helpers.

uv run shopdesk seed                 # wipe + seed with seed=42
uv run shopdesk seed --seed 7 --orders 1000
uv run shopdesk seed --anchor-date 2026-01-01   # fully reproducible timestamps
uv run shopdesk reset                # empty database
"""

import argparse
from datetime import date

from app.db import SessionLocal, init_db
from app.services.seed import SeedCounts, reset_database, seed_database


def main() -> None:
    parser = argparse.ArgumentParser(prog="shopdesk")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="Wipe the database and generate deterministic fake data")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--customers", type=int, default=60)
    s.add_argument("--products", type=int, default=40)
    s.add_argument("--orders", type=int, default=250)
    s.add_argument("--tickets", type=int, default=60)
    s.add_argument("--anchor-date", type=date.fromisoformat, default=None)

    sub.add_parser("reset", help="Delete all data")

    args = parser.parse_args()
    init_db()
    with SessionLocal() as db:
        if args.cmd == "reset":
            reset_database(db)
            print("Database reset.")
            return
        summary = seed_database(
            db,
            seed=args.seed,
            counts=SeedCounts(args.customers, args.products, args.orders, args.tickets),
            anchor_date=args.anchor_date,
        )
    print(
        f"Seeded (seed={summary.seed}): {summary.customers} customers, {summary.products} "
        f"products, {summary.orders} orders, {summary.tickets} tickets, {summary.refunds} refunds"
    )
    print("\nScenarios for agent testing:")
    for name in summary.scenarios:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
