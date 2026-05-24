"""
Tests for Billing Engine and Usage Tracker.
"""

import pytest
from datetime import datetime

from shopsage.billing.usage_tracker import UsageTracker
from shopsage.billing.billing_engine import BillingEngine
from shopsage.auth.tenant_store import TenantStore


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_billing.db")


@pytest.fixture
def usage_tracker(db_path):
    return UsageTracker(db_path)


@pytest.fixture
def tenant_store(db_path):
    return TenantStore(db_path)


@pytest.fixture
def billing_engine(db_path):
    return BillingEngine(db_path)


def test_record_and_get_usage(usage_tracker):
    """Should correctly aggregate daily usage."""
    usage_tracker.record_usage("t1", api_calls=10, agent_runs=2, date_str="2026-05-01")
    usage_tracker.record_usage("t1", api_calls=5, searches=1, date_str="2026-05-01")
    
    # Another day
    usage_tracker.record_usage("t1", api_calls=20, date_str="2026-05-02")
    
    usage = usage_tracker.get_monthly_usage("t1", "2026-05")
    assert usage["api_calls"] == 35
    assert usage["agent_runs"] == 2
    assert usage["searches"] == 1

def test_daily_breakdown(usage_tracker):
    """Should return usage broken down by day."""
    usage_tracker.record_usage("t2", api_calls=100, date_str="2026-05-10")
    usage_tracker.record_usage("t2", api_calls=150, date_str="2026-05-11")
    
    breakdown = usage_tracker.get_daily_breakdown("t2", "2026-05")
    assert len(breakdown) == 2
    assert breakdown[0]["date"] == "2026-05-10"
    assert breakdown[0]["api_calls"] == 100


def test_billing_calculation_free_tier(billing_engine, tenant_store, usage_tracker):
    """Free tier should just be base fee (0) unless hard limits are somehow breached (but capped)."""
    tenant = tenant_store.create_tenant("Free Co", plan="free")
    
    usage_tracker.record_usage(tenant["id"], api_calls=500, agent_runs=50, date_str="2026-05-01")
    
    bill = billing_engine.calculate_current_bill(tenant["id"], "2026-05")
    assert bill["total_due"] == 0.0


def test_billing_calculation_pro_overage(billing_engine, tenant_store, usage_tracker):
    """Pro tier should charge base fee + overages."""
    tenant = tenant_store.create_tenant("Pro Co", plan="pro")
    
    # Pro includes 50k API calls. We use 52k (2k overage = 2 * $1.50 = $3.00)
    # Pro includes 5k agent runs. We use 5.1k (100 overage = 100 * $0.02 = $2.00)
    usage_tracker.record_usage(tenant["id"], api_calls=52000, agent_runs=5100, date_str="2026-05-01")
    
    bill = billing_engine.calculate_current_bill(tenant["id"], "2026-05")
    
    assert bill["breakdown"]["base_fee"] == 49.0
    assert bill["breakdown"]["api_overage_cost"] == 3.0
    assert bill["breakdown"]["agent_overage_cost"] == 2.0
    assert bill["total_due"] == 54.0


def test_predict_end_of_month(billing_engine, tenant_store, usage_tracker):
    """Should predict EOM cost based on current usage."""
    tenant = tenant_store.create_tenant("Pro Co 2", plan="pro")
    
    # We need to insert for the current month so `predict_end_of_month` finds it
    now = datetime.utcnow()
    year_month = now.strftime("%Y-%m")
    today_str = now.strftime("%Y-%m-%d")
    
    # Big overage to make prediction obvious
    usage_tracker.record_usage(tenant["id"], api_calls=100000, agent_runs=10000, date_str=today_str)
    
    prediction = billing_engine.predict_end_of_month(tenant["id"])
    assert "projected_cost" in prediction
    assert prediction["projected_cost"] >= prediction["current_cost"]
