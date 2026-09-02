import asyncio
from sqlalchemy import select, func, case
from db.base import get_db_session
from db.models import Agent, WasteFinding

async def test_queries():
    async with get_db_session() as db:
        # Test value_summary query
        print("=== Testing value/summary query ===")
        try:
            result = await db.execute(
                select(
                    func.count(Agent.id),
                    func.sum(case((Agent.lifecycle_stage == "Production", 1), else_=0)),
                    func.sum(case((Agent.lifecycle_stage == "Production", Agent.value_amount), else_=0)),
                    func.sum(Agent.value_amount),
                    func.sum(Agent.hours_saved_monthly),
                    func.sum(case((Agent.at_risk == True, 1), else_=0)),
                )
            )
            total, in_prod, realized, total_val, hours, at_risk = result.one()
            print(f"Success: total={total}, in_prod={in_prod}, realized={realized}, total_val={total_val}, hours={hours}, at_risk={at_risk}")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")

        # Test waste_summary query
        print("\n=== Testing waste/summary query ===")
        try:
            result = await db.execute(
                select(func.count(WasteFinding.id), func.sum(WasteFinding.monthly_waste_cents))
            )
            total, waste = result.one()
            print(f"Success: total={total}, waste={waste}")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")

asyncio.run(test_queries())
