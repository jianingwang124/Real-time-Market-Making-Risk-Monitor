from __future__ import annotations

import asyncio

from risk_monitor.engine import RiskEngine


async def _main() -> None:
    engine = RiskEngine()
    await engine.run()


if __name__ == "__main__":
    asyncio.run(_main())

