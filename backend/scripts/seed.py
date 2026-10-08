"""Seed script for Agent Registry — populates database with prototype data."""
import asyncio
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import select, func

from db.base import get_db_session, create_all_tables
from db.models import (
    Organization, Department, Agent, GovernanceReview, Discovery,
    AgentTokenUsage, ModelTokenPrice, AgentBudget, User, AgentIdentity
)
from api.auth import hash_password


SEED_DEPARTMENTS = [
    {"id": "dept-finance", "name": "Finance", "cost_center": "CC-1000"},
    {"id": "dept-legal", "name": "Legal", "cost_center": "CC-2000"},
    {"id": "dept-hr", "name": "HR", "cost_center": "CC-3000"},
    {"id": "dept-sales", "name": "Sales", "cost_center": "CC-4000"},
    {"id": "dept-cx", "name": "Customer Support", "cost_center": "CC-5000"},
    {"id": "dept-supply-chain", "name": "Supply Chain", "cost_center": "CC-6000"},
    {"id": "dept-it-ops", "name": "IT Operations", "cost_center": "CC-7000"},
    {"id": "dept-marketing", "name": "Marketing", "cost_center": "CC-8000"},
    {"id": "dept-engineering", "name": "Engineering", "cost_center": "CC-9000"},
]

SEED_AGENTS = [
    {"id": "inv-recon", "name": "Invoice Reconciliation Agent", "dept_id": "dept-finance", "owner": "Finance Ops Engineering", "lifecycle_stage": "Production", "version": "v3.1", "time_in_stage_weeks": 34, "ai_type": "Autonomous Agent", "description": "Matches incoming vendor invoices against POs and goods-receipt records, flags mismatches, and auto-posts clean matches to the ledger.", "business_outcome": "Cut invoice processing cost and eliminated duplicate payments.", "value_amount": 186000, "value_type": "Cost avoidance", "hours_saved_monthly": 640, "enterprise_systems": ["SAP S/4HANA"], "databases": ["Snowflake"], "knowledge_bases": ["AP Policy KB"], "mcp_servers": ["SAP MCP Server", "PDF Extraction MCP"], "calls": ["expense-audit"], "consumers": ["AP Leadership Dashboard", "SAP Payment Run"], "inputs": ["Vendor invoice (PDF/EDI)", "Purchase order record", "Goods receipt record"], "outputs": ["Match disposition", "Exception queue item", "Ledger posting"], "api_endpoint": "/agents/v1/invoice-reconciliation", "sla": "99.5% uptime", "tags": ["finance", "ap", "automation"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "onboarding", "name": "Employee Onboarding Concierge", "dept_id": "dept-hr", "owner": "People Experience Engineering", "lifecycle_stage": "Production", "version": "v1.6", "time_in_stage_weeks": 52, "ai_type": "Autonomous Agent", "description": "Guides new hires through day-one tasks and answers policy questions.", "business_outcome": "Freed HR business partners from routine onboarding questions.", "value_amount": 21000, "value_type": "Cost avoidance", "hours_saved_monthly": 180, "enterprise_systems": ["Workday", "ServiceNow"], "knowledge_bases": ["HR Policy KB"], "mcp_servers": ["Slack MCP Server", "ServiceNow MCP Server"], "calls": ["access-review"], "consumers": ["New Hire Slack Channel"], "inputs": ["New hire record", "Policy knowledge base"], "outputs": ["Answer / response", "Provisioning ticket"], "api_endpoint": "/agents/v1/onboarding-concierge", "sla": "99% uptime", "tags": ["hr", "onboarding"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "lead-scoring", "name": "Lead Scoring Agent", "dept_id": "dept-sales", "owner": "RevOps Engineering", "lifecycle_stage": "Production", "version": "v4.0", "time_in_stage_weeks": 61, "ai_type": "Predictive / ML Model", "description": "Scores and prioritizes inbound leads using firmographic, intent, and engagement signals.", "business_outcome": "Influenced pipeline by directing SDR effort toward highest-propensity leads.", "value_amount": 210000, "value_type": "Revenue influenced", "hours_saved_monthly": 90, "enterprise_systems": ["Salesforce"], "databases": ["Snowflake"], "mcp_servers": ["Salesforce MCP Server"], "calls": ["proposal-drafter"], "consumers": ["SDR Queue", "Sales Leadership Dashboard"], "inputs": ["Lead record", "Firmographic data", "Engagement events"], "outputs": ["Lead score", "Priority tier"], "api_endpoint": "/agents/v1/lead-scoring", "sla": "99.9% uptime", "tags": ["sales", "revops"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved with Conditions"}},
    {"id": "proposal-drafter", "name": "Sales Proposal Drafter", "dept_id": "dept-sales", "owner": "Sales Enablement Engineering", "lifecycle_stage": "Development", "version": "v0.3", "time_in_stage_weeks": 5, "ai_type": "Copilot / Assistant", "description": "Drafts first-pass customer proposals from CRM opportunity data.", "business_outcome": "Projected to cut proposal drafting time from 3 hours to 20 minutes.", "value_amount": 35000, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["Salesforce", "Microsoft 365"], "knowledge_bases": ["Pricing & Discount KB"], "mcp_servers": ["Salesforce MCP Server", "Email MCP"], "consumers": ["Deal Desk"], "inputs": ["Opportunity record", "Pricing table"], "outputs": ["Draft proposal document"], "api_endpoint": "/agents/v1/proposal-drafter (pre-release)", "sla": "Not yet defined", "tags": ["sales", "proposals"], "model_name": "GPT-5", "reviews": {"arb": "In Review", "security": "Not Submitted", "dp": "Not Submitted"}},
    {"id": "support-triage", "name": "Customer Support Triage Agent", "dept_id": "dept-cx", "owner": "CX Automation", "lifecycle_stage": "Production", "version": "v3.5", "time_in_stage_weeks": 58, "ai_type": "Autonomous Agent", "description": "Classifies and routes inbound tickets, drafts first-response replies.", "business_outcome": "Cut average first-response time from 4 hours to 12 minutes.", "value_amount": 124000, "value_type": "Cost avoidance", "hours_saved_monthly": 980, "enterprise_systems": ["Zendesk"], "knowledge_bases": ["Support Macros KB"], "mcp_servers": ["Slack MCP Server", "Zendesk MCP Server"], "calls": ["refund-adjudication"], "consumers": ["Support Queue", "CX Leadership Dashboard"], "inputs": ["Support ticket", "Customer history"], "outputs": ["Ticket category", "Draft response", "Routing decision"], "api_endpoint": "/agents/v1/support-triage", "sla": "99.9% uptime", "tags": ["support", "cx"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "refund-adjudication", "name": "Refund Adjudication Agent", "dept_id": "dept-cx", "owner": "CX Platform", "lifecycle_stage": "Testing", "version": "v0.9", "time_in_stage_weeks": 4, "at_risk": True, "risk_level": "HIGH", "risk_note": "Depends on both Zendesk and SAP S/4HANA and carries direct financial exposure.", "ai_type": "Autonomous Agent", "description": "Evaluates refund requests against policy and order history.", "business_outcome": "Projected to resolve 70% of refund requests without human review.", "value_amount": 30000, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["Zendesk", "SAP S/4HANA"], "knowledge_bases": ["Support Macros KB"], "mcp_servers": ["Zendesk MCP Server", "SAP MCP Server"], "consumers": ["Refund Queue"], "inputs": ["Refund request", "Order record", "Policy ruleset"], "outputs": ["Approval decision", "Refund transaction"], "api_endpoint": "/agents/v1/refund-adjudication", "sla": "Target 99.5% uptime", "tags": ["support", "finance", "risk"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Changes Requested", "dp": "In Review"}},
    {"id": "demand-forecast", "name": "Demand Forecasting Agent", "dept_id": "dept-supply-chain", "owner": "Supply Chain Analytics", "lifecycle_stage": "Production", "version": "v5.2", "time_in_stage_weeks": 70, "ai_type": "Predictive / ML Model", "description": "Forecasts SKU-level demand from sales history, seasonality, and macro signals.", "business_outcome": "Reduced stockouts and excess inventory carrying cost.", "value_amount": 310000, "value_type": "Cost avoidance", "hours_saved_monthly": 400, "enterprise_systems": ["SAP S/4HANA"], "databases": ["Snowflake", "Databricks"], "knowledge_bases": ["Inventory Planning KB"], "mcp_servers": ["Snowflake MCP Server"], "consumers": ["Replenishment Planning", "Supply Chain Dashboard"], "inputs": ["Sales history", "Seasonality index", "Macro signals"], "outputs": ["SKU demand forecast", "Replenishment recommendation"], "api_endpoint": "/agents/v1/demand-forecasting", "sla": "99.5% uptime", "tags": ["supply-chain", "forecasting"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "incident-copilot", "name": "Incident Response Copilot", "dept_id": "dept-it-ops", "owner": "Site Reliability Engineering", "lifecycle_stage": "Production", "version": "v2.9", "time_in_stage_weeks": 46, "ai_type": "Copilot / Assistant", "description": "Correlates alerts, suggests root cause, and drafts incident timelines.", "business_outcome": "Cut mean time to resolution by 38% across P1/P2 incidents.", "value_amount": 95000, "value_type": "Cost avoidance", "hours_saved_monthly": 520, "enterprise_systems": ["ServiceNow"], "databases": ["Databricks"], "knowledge_bases": ["Runbook KB"], "mcp_servers": ["Slack MCP Server", "GitHub MCP Server"], "calls": ["access-review"], "consumers": ["Incident Bridge", "SRE Postmortem Log"], "inputs": ["Alert stream", "Service topology"], "outputs": ["Root cause suggestion", "Draft incident timeline"], "api_endpoint": "/agents/v1/incident-copilot", "sla": "99.95% uptime", "tags": ["it-ops", "sre"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "change-validator", "name": "Change Request Validator", "dept_id": "dept-it-ops", "owner": "IT Service Management", "lifecycle_stage": "Deprecated", "version": "v1.2 (final)", "time_in_stage_weeks": 12, "at_risk": True, "risk_note": "Superseded by Incident Response Copilot. Pending decommission on 2026-09-30.", "ai_type": "Autonomous Agent", "description": "Validated change requests against a static risk checklist.", "business_outcome": "Superseded by Incident Response Copilot; scheduled for shutdown.", "value_amount": 0, "value_type": "Retired", "hours_saved_monthly": 0, "enterprise_systems": ["ServiceNow"], "mcp_servers": ["ServiceNow MCP Server"], "api_endpoint": "/agents/v1/change-validator (sunset 2026-09-30)", "sla": "n/a", "tags": ["it-ops", "retired"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "access-review", "name": "Access Review Agent", "dept_id": "dept-it-ops", "owner": "Identity & Access Engineering", "lifecycle_stage": "Testing", "version": "v0.7", "time_in_stage_weeks": 3, "ai_type": "Autonomous Agent", "description": "Reviews entitlement grants against role baselines.", "business_outcome": "Projected to cut quarterly access-review effort by 60%.", "value_amount": 48000, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["ServiceNow", "Workday", "Microsoft 365"], "knowledge_bases": ["Access Policy KB"], "mcp_servers": ["ServiceNow MCP Server", "Workday MCP Server"], "consumers": ["Access Review Queue"], "inputs": ["Entitlement record", "Role baseline"], "outputs": ["Excess-access flag", "Sign-off request"], "api_endpoint": "/agents/v1/access-review", "sla": "Target 99% uptime", "tags": ["it-ops", "security", "iam"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "In Review", "dp": "In Review"}},
    {"id": "campaign-copy", "name": "Campaign Copy Generator", "dept_id": "dept-marketing", "owner": "Marketing Automation", "lifecycle_stage": "Production", "version": "v2.1", "time_in_stage_weeks": 44, "ai_type": "Generative AI Feature", "description": "Generates on-brand copy variants for campaigns.", "business_outcome": "Cut campaign copy turnaround from days to hours.", "value_amount": 27000, "value_type": "Cost avoidance", "hours_saved_monthly": 260, "enterprise_systems": ["Microsoft 365"], "knowledge_bases": ["Brand Voice KB"], "mcp_servers": ["Slack MCP Server"], "consumers": ["Campaign Ops Queue"], "inputs": ["Creative brief", "Brand voice guide"], "outputs": ["Copy variants"], "api_endpoint": "/agents/v1/campaign-copy", "sla": "99% uptime", "tags": ["marketing", "content"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "expense-audit", "name": "Expense Report Auditor", "dept_id": "dept-finance", "owner": "Finance Ops Engineering", "lifecycle_stage": "Production", "version": "v2.7", "time_in_stage_weeks": 50, "ai_type": "Autonomous Agent", "description": "Audits expense reports against policy, flags violations.", "business_outcome": "Cut policy-violation leakage and manual audit workload.", "value_amount": 64000, "value_type": "Cost avoidance", "hours_saved_monthly": 410, "enterprise_systems": ["SAP S/4HANA", "Microsoft 365"], "knowledge_bases": ["Expense Policy KB"], "mcp_servers": ["SAP MCP Server", "Email MCP"], "consumers": ["Finance Audit Queue"], "inputs": ["Expense report", "Policy ruleset"], "outputs": ["Approval decision", "Violation flag"], "api_endpoint": "/agents/v1/expense-auditor", "sla": "99.5% uptime", "tags": ["finance", "compliance"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "churn-predictor", "name": "Customer Churn Prediction Model", "dept_id": "dept-cx", "owner": "Data Science", "lifecycle_stage": "Production", "version": "v6.0", "time_in_stage_weeks": 66, "ai_type": "Predictive / ML Model", "description": "Scores active accounts weekly on churn probability.", "business_outcome": "Retention team prioritizes outreach on highest-risk accounts.", "value_amount": 145000, "value_type": "Revenue retained", "hours_saved_monthly": 0, "enterprise_systems": ["Salesforce"], "databases": ["Snowflake"], "consumers": ["Customer Success Dashboard", "Retention Campaign Queue"], "inputs": ["Usage telemetry", "Support ticket history", "Billing history"], "outputs": ["Churn probability score", "Risk tier"], "api_endpoint": "/models/v1/churn-prediction", "sla": "Weekly batch scoring", "tags": ["cx", "ml", "retention"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved with Conditions"}},
    {"id": "fraud-detection", "name": "Transaction Fraud Detection Model", "dept_id": "dept-finance", "owner": "Risk & Fraud Analytics", "lifecycle_stage": "Production", "version": "v8.3", "time_in_stage_weeks": 88, "risk_level": "HIGH", "ai_type": "Predictive / ML Model", "description": "Scores transactions in real time for fraud risk.", "business_outcome": "Reduced confirmed fraud losses.", "value_amount": 220000, "value_type": "Cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["Payment Gateway"], "databases": ["Snowflake", "Databricks"], "knowledge_bases": ["Fraud Pattern KB"], "consumers": ["Fraud Ops Queue", "Finance Risk Dashboard"], "inputs": ["Transaction event", "Device fingerprint", "Account history"], "outputs": ["Fraud risk score", "Hold decision"], "api_endpoint": "/models/v1/fraud-detection", "sla": "99.99% uptime", "tags": ["finance", "risk", "ml"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved with Conditions", "dp": "Approved"}},
    {"id": "hr-chatbot", "name": "HR Policy Chatbot", "dept_id": "dept-hr", "owner": "People Experience Engineering", "lifecycle_stage": "Production", "version": "v2.0", "time_in_stage_weeks": 48, "ai_type": "Conversational AI / Chatbot", "description": "Answers employee questions about benefits, leave, and policy.", "business_outcome": "Deflected routine HR inquiries away from HR business partners.", "value_amount": 33000, "value_type": "Cost avoidance", "hours_saved_monthly": 210, "enterprise_systems": ["Workday", "Microsoft 365"], "knowledge_bases": ["HR Policy KB"], "mcp_servers": ["Slack MCP Server"], "consumers": ["Employee Self-Service Portal"], "inputs": ["Employee question", "Policy knowledge base"], "outputs": ["Conversational answer", "Escalation to HR partner"], "api_endpoint": "/chat/v1/hr-policy-bot", "sla": "99% uptime", "tags": ["hr", "chatbot", "genai"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "defect-vision", "name": "Visual Defect Inspection Model", "dept_id": "dept-supply-chain", "owner": "Manufacturing Analytics", "lifecycle_stage": "Testing", "version": "v0.6", "time_in_stage_weeks": 8, "ai_type": "Computer Vision Model", "description": "Classifies product images from the line camera to flag visual defects.", "business_outcome": "Projected to cut the defect escape rate to customers.", "value_amount": 0, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["MES System"], "databases": ["Databricks"], "consumers": ["Line Quality Dashboard"], "inputs": ["Line camera image stream"], "outputs": ["Defect classification", "Line-stop signal"], "api_endpoint": "/models/v1/defect-vision", "sla": "Target P95 < 300ms", "tags": ["supply-chain", "vision", "ml"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "In Review", "dp": "Not Submitted"}},
]

SEED_DISCOVERIES = [
    {"id": "disc-2", "suspected_name": "Legal Slack bot (unregistered)", "suspected_dept": "Legal", "suspected_type": "Generative AI Feature", "source": "Slack app directory", "confidence": 91, "signal": "OAuth app with chat:write scopes posting auto-generated clause summaries.", "shadow_ai_risk": "HIGH", "first_seen": "2026-07-29"},
    {"id": "disc-4", "suspected_name": "auto-pr-reviewer (GitHub App)", "suspected_dept": "Engineering", "suspected_type": "Copilot / Assistant", "source": "GitHub App installation logs", "confidence": 88, "signal": "Installed app posts AI-generated review comments on pull requests.", "shadow_ai_risk": "MEDIUM", "first_seen": "2026-08-10"},
]

SEED_MODEL_PRICES = [
    {"id": "price-gpt5", "model_name": "GPT-5", "provider": "openai", "input_price_per_1m": 1.25, "output_price_per_1m": 10.00, "cache_read_price_per_1m": 0.125, "tier": "frontier"},
    {"id": "price-gpt5-mini", "model_name": "GPT-5-mini", "provider": "openai", "input_price_per_1m": 0.25, "output_price_per_1m": 2.00, "cache_read_price_per_1m": 0.025, "tier": "mid"},
    {"id": "price-gpt5-nano", "model_name": "GPT-5-nano", "provider": "openai", "input_price_per_1m": 0.05, "output_price_per_1m": 0.40, "cache_read_price_per_1m": 0.005, "tier": "lightweight"},
    {"id": "price-sonnet", "model_name": "Claude Sonnet 4.5", "provider": "anthropic", "input_price_per_1m": 3.00, "output_price_per_1m": 15.00, "cache_read_price_per_1m": 0.30, "tier": "mid"},
    {"id": "price-haiku", "model_name": "Claude Haiku 4.5", "provider": "anthropic", "input_price_per_1m": 1.00, "output_price_per_1m": 5.00, "cache_read_price_per_1m": 0.10, "tier": "lightweight"},
]


async def seed_database():
    """Seed the database with prototype data if empty. The agents are demo agents."""
    from db.scope import unfiltered
    from shared.config import get_settings

    if not get_settings().demo_agents_enabled:
        print("DEMO_AGENTS_ENABLED is false: the demo agents are not seeded.")
        return
    async with get_db_session() as db:
        # Check if already seeded: every agent row counts, demo or archived ones included.
        with unfiltered():
            result = await db.execute(select(func.count(Agent.id)))
        if result.scalar() > 0:
            print("Database already seeded, skipping.")
            return

        # Create default org, flushed alone before anything that references
        # it by FK — see scripts/init_db.py's seeding for why each FK layer
        # needs its own explicit flush under async Postgres, not one shared
        # across the whole batch.
        db.add(Organization(id="org-default", name="Default Organization", slug="default"))
        await db.flush()

        # Create departments, flushed before agents (dept_id FK)
        for dept in SEED_DEPARTMENTS:
            db.add(Department(id=dept["id"], org_id="org-default", name=dept["name"], cost_center=dept.get("cost_center", "")))
        await db.flush()

        # Create agents
        for agent_data in SEED_AGENTS:
            reviews = agent_data.pop("reviews", {})
            agent_id = agent_data["id"]
            db.add(Agent(org_id="org-default", is_demo=True, **agent_data))
            for gate, status in reviews.items():
                db.add(GovernanceReview(id=secrets.token_hex(8), agent_id=agent_id, gate=gate, status=status))
            # Seed token usage
            db.add(AgentTokenUsage(
                agent_id=agent_id, bucket=datetime.utcnow(), model_name=agent_data.get("model_name", "GPT-5"),
                invocation_count=1000, input_tokens=2400000, output_tokens=850000, cached_tokens=912000, cost_cents=3700
            ))

        # Create discoveries
        for disc in SEED_DISCOVERIES:
            db.add(Discovery(org_id="org-default", **disc))

        # Create model prices
        for price in SEED_MODEL_PRICES:
            db.add(ModelTokenPrice(**price))

        # Create admin user with random password
        admin_password = secrets.token_urlsafe(16)
        db.add(User(
            id="user-admin", org_id="org-default", email="admin@airegistry.local",
            name="Registry Admin", role="Registry Admin", password_hash=hash_password(admin_password)
        ))

        # Create agent identities
        for agent_data in SEED_AGENTS:
            agent_id = agent_data["id"]
            db.add(AgentIdentity(
                agent_id=agent_id, service_account=f"svc-{agent_id}@airegistry.local",
                entra_agent_id=f"entra-{agent_id}", permissions=["read", "write", "execute"]
            ))

        print(f"Seeded {len(SEED_AGENTS)} agents, {len(SEED_DISCOVERIES)} discoveries, {len(SEED_DEPARTMENTS)} departments")
        print(f"Admin password: {admin_password}")


if __name__ == "__main__":
    asyncio.run(seed_database())
