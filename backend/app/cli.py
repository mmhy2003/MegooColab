"""Server commands: `docker compose exec backend python -m app.cli <command>`."""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.auth import two_factor
from app.auth.models import User
from app.core.db import SessionLocal
from app.core.email import get_mailer


async def _reset_two_factor(email: str) -> int:
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
        if user is None:
            print("No account with that email.")
            return 1
        await two_factor.reset_two_factor(db, user, actor=None, via="cli", mailer=await get_mailer(db))
        await db.commit()
    print(f"Two-factor sign-in turned off for {user.email}.")
    return 0


async def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    reset = commands.add_parser(
        "reset-two-factor",
        help="turn off someone's two-factor sign-in (authenticator app and passkeys), e.g. a locked-out admin",
    )
    reset.add_argument("email")
    args = parser.parse_args(argv)
    if args.command == "reset-two-factor":
        return await _reset_two_factor(args.email)
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
