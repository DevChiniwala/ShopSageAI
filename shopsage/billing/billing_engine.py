"""
Billing Engine — Calculates costs based on tenant tiers and usage.

Defines pricing models for Free, Pro, and Enterprise tiers.
Calculates current month's bill and predicts end-of-month costs.
"""

import logging
from datetime import datetime, timezone
import calendar
from typing import Dict, Any

from shopsage.billing.usage_tracker import UsageTracker
from shopsage.auth.tenant_store import TenantStore
from shopsage.config import settings

logger = logging.getLogger("shopsage.billing.engine")

# Pricing Model
PRICING = {
    "free": {
        "base_fee": 0.0,
        "included_api_calls": 1000,
        "cost_per_extra_1k_api": 0.0,  # Hard capped
        "included_agent_runs": 100,
        "cost_per_extra_agent": 0.0,
    },
    "pro": {
        "base_fee": 49.00,  # $49/month
        "included_api_calls": 50000,
        "cost_per_extra_1k_api": 1.50,
        "included_agent_runs": 5000,
        "cost_per_extra_agent": 0.02,
    },
    "enterprise": {
        "base_fee": 499.00,  # $499/month
        "included_api_calls": 1000000,
        "cost_per_extra_1k_api": 0.80,
        "included_agent_runs": 50000,
        "cost_per_extra_agent": 0.01,
    },
}


class BillingEngine:
    """
    Calculates tenant bills based on usage and tier pricing.
    """

    def __init__(self, db_path: str = settings.DB_PATH):
        self.usage_tracker = UsageTracker(db_path)
        self.tenant_store = TenantStore(db_path)

    def calculate_current_bill(self, tenant_id: str, year_month: str = None) -> Dict[str, Any]:
        """
        Calculate the current bill for a given month.
        If year_month is None, uses current month (YYYY-MM).
        """
        if not year_month:
            year_month = datetime.now(timezone.utc).strftime("%Y-%m")

        tenant = self.tenant_store.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        plan = tenant["plan"].lower()
        pricing = PRICING.get(plan, PRICING["free"])

        usage = self.usage_tracker.get_monthly_usage(tenant_id, year_month)
        
        api_calls = usage.get("api_calls", 0)
        agent_runs = usage.get("agent_runs", 0)

        # Base fee
        total_cost = pricing["base_fee"]

        # Overage for API calls
        extra_api = max(0, api_calls - pricing["included_api_calls"])
        api_overage_cost = (extra_api / 1000) * pricing["cost_per_extra_1k_api"]
        total_cost += api_overage_cost

        # Overage for Agent runs
        extra_agent = max(0, agent_runs - pricing["included_agent_runs"])
        agent_overage_cost = extra_agent * pricing["cost_per_extra_agent"]
        total_cost += agent_overage_cost

        return {
            "tenant_id": tenant_id,
            "month": year_month,
            "plan": plan,
            "usage": usage,
            "breakdown": {
                "base_fee": pricing["base_fee"],
                "api_overage_cost": round(api_overage_cost, 2),
                "agent_overage_cost": round(agent_overage_cost, 2),
            },
            "total_due": round(total_cost, 2),
            "currency": "USD"
        }

    def predict_end_of_month(self, tenant_id: str) -> Dict[str, Any]:
        """
        Predict end-of-month cost based on current run rate.
        """
        now = datetime.now(timezone.utc)
        year_month = now.strftime("%Y-%m")
        day_of_month = now.day
        
        _, days_in_month = calendar.monthrange(now.year, now.month)
        
        current_bill = self.calculate_current_bill(tenant_id, year_month)
        
        if day_of_month == 0:
            return {"projected_cost": current_bill["total_due"]}

        # Simple linear projection
        multiplier = days_in_month / day_of_month
        
        # We only scale the overage, not the base fee
        projected_api = current_bill["breakdown"]["api_overage_cost"] * multiplier
        projected_agent = current_bill["breakdown"]["agent_overage_cost"] * multiplier
        
        projected_total = current_bill["breakdown"]["base_fee"] + projected_api + projected_agent

        return {
            "tenant_id": tenant_id,
            "month": year_month,
            "current_cost": current_bill["total_due"],
            "projected_cost": round(projected_total, 2),
            "days_elapsed": day_of_month,
            "days_in_month": days_in_month,
        }
