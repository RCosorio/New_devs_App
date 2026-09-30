from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List

async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int, db_session=None) -> Decimal:
    """
    Calculates revenue for a specific month.

    Month boundaries are evaluated in the property's local timezone (properties.timezone),
    not UTC, so a check-in at 2024-02-29 23:30 UTC for a Paris property counts towards March.
    """

    # Naive local-time boundaries; compared against check_in_date converted to the property's timezone
    start_date = datetime(year, month, 1)
    if month < 12:
        end_date = datetime(year, month + 1, 1)
    else:
        end_date = datetime(year + 1, 1, 1)

    from sqlalchemy import text
    from app.core.database_pool import db_pool

    query = text("""
        SELECT COALESCE(SUM(r.total_amount), 0) as total
        FROM reservations r
        JOIN properties p ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.property_id = :property_id
        AND r.tenant_id = :tenant_id
        AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_date
        AND (r.check_in_date AT TIME ZONE p.timezone) < :end_date
    """)
    params = {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    if db_session is not None:
        result = await db_session.execute(query, params)
    else:
        await db_pool.initialize()
        async with db_pool.get_session() as session:
            result = await session.execute(query, params)

    return Decimal(str(result.scalar()))

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    # Use the shared pool (creating a new engine per request leaks connections)
    from app.core.database_pool import db_pool

    await db_pool.initialize()

    if not db_pool.session_factory:
        # Never fall back to placeholder figures: showing made-up (or another tenant's)
        # numbers is worse than showing an error.
        raise RuntimeError("Database pool not available")

    async with db_pool.get_session() as session:
        # Use SQLAlchemy text for raw SQL
        from sqlalchemy import text

        query = text("""
            SELECT
                property_id,
                SUM(total_amount) as total_revenue,
                COUNT(*) as reservation_count
            FROM reservations
            WHERE property_id = :property_id AND tenant_id = :tenant_id
            GROUP BY property_id
        """)

        result = await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id
        })
        row = result.fetchone()

        if row:
            total_revenue = Decimal(str(row.total_revenue))
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": str(total_revenue),
                "currency": "USD",
                "count": row.reservation_count
            }
        else:
            # No reservations found for this property
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": "0.00",
                "currency": "USD",
                "count": 0
            }
