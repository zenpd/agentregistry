"""Initialize and seed the database for local development."""
import asyncio
import secrets
from datetime import datetime, date

from sqlalchemy import select, func

from db.base import create_all_tables, get_db_session, engine
from db.models import (
    Organization, Department, Agent, GovernanceReview, Discovery,
    AgentTokenUsage, ModelTokenPrice, User, AgentIdentity, Base
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
    {"id": "inv-recon", "name": "Invoice Reconciliation Agent", "dept_id": "dept-finance", "owner": "Finance Ops Engineering", "lifecycle_stage": "Production", "version": "v3.1", "time_in_stage_weeks": 34, "ai_type": "Autonomous Agent", "description": "Matches incoming vendor invoices against POs and goods-receipt records.", "business_outcome": "Cut invoice processing cost.", "value_amount": 186000, "value_type": "Cost avoidance", "hours_saved_monthly": 640, "enterprise_systems": ["SAP S/4HANA"], "databases": ["Snowflake"], "knowledge_bases": ["AP Policy KB"], "mcp_servers": ["SAP MCP Server", "PDF Extraction MCP"], "calls": ["expense-audit"], "consumers": ["AP Leadership Dashboard"], "inputs": ["Vendor invoice"], "outputs": ["Match disposition"], "api_endpoint": "/agents/v1/invoice-reconciliation", "sla": "99.5% uptime", "tags": ["finance", "ap"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "contract-review", "name": "Vendor Contract Reviewer", "dept_id": "dept-legal", "owner": "Enterprise Legal Ops", "lifecycle_stage": "Testing", "version": "v0.8", "time_in_stage_weeks": 6, "ai_type": "Autonomous Agent", "description": "Reviews vendor contracts against the standard playbook.", "business_outcome": "Projected to cut contract review turnaround.", "value_amount": 42000, "value_type": "Projected run-rate", "hours_saved_monthly": 0, "enterprise_systems": ["DocuSign", "Microsoft 365"], "knowledge_bases": ["Legal Playbook KB"], "mcp_servers": ["DocuSign MCP Server", "PDF Extraction MCP"], "consumers": ["Legal Contract Queue"], "inputs": ["Contract PDF"], "outputs": ["Redline suggestions"], "api_endpoint": "/agents/v1/contract-reviewer", "sla": "Target 99% uptime", "tags": ["legal", "contracts"], "model_name": "Claude Sonnet 4.5", "reviews": {"arb": "Approved", "security": "In Review", "dp": "Not Submitted"}},
    {"id": "candidate-screen", "name": "Candidate Screening Assistant", "dept_id": "dept-hr", "owner": "Talent Acquisition Engineering", "lifecycle_stage": "Production", "version": "v2.4", "time_in_stage_weeks": 40, "ai_type": "Autonomous Agent", "description": "Screens inbound applications against role requirements.", "business_outcome": "Reduced recruiter screening time.", "value_amount": 58000, "value_type": "Cost avoidance", "hours_saved_monthly": 310, "enterprise_systems": ["Workday", "Microsoft 365"], "knowledge_bases": ["Recruiting Criteria KB"], "mcp_servers": ["Workday MCP Server", "Email MCP"], "consumers": ["Recruiter Shortlist View"], "inputs": ["Candidate resume"], "outputs": ["Ranked shortlist"], "api_endpoint": "/agents/v1/candidate-screening", "sla": "99% uptime", "tags": ["hr", "recruiting"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "onboarding", "name": "Employee Onboarding Concierge", "dept_id": "dept-hr", "owner": "People Experience Engineering", "lifecycle_stage": "Production", "version": "v1.6", "time_in_stage_weeks": 52, "ai_type": "Autonomous Agent", "description": "Guides new hires through day-one tasks.", "business_outcome": "Freed HR business partners from routine onboarding.", "value_amount": 21000, "value_type": "Cost avoidance", "hours_saved_monthly": 180, "enterprise_systems": ["Workday", "ServiceNow"], "knowledge_bases": ["HR Policy KB"], "mcp_servers": ["Slack MCP Server", "ServiceNow MCP Server"], "calls": ["access-review"], "consumers": ["New Hire Slack Channel"], "inputs": ["New hire record"], "outputs": ["Answer / response"], "api_endpoint": "/agents/v1/onboarding-concierge", "sla": "99% uptime", "tags": ["hr", "onboarding"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "lead-scoring", "name": "Lead Scoring Agent", "dept_id": "dept-sales", "owner": "RevOps Engineering", "lifecycle_stage": "Production", "version": "v4.0", "time_in_stage_weeks": 61, "ai_type": "Predictive / ML Model", "description": "Scores and prioritizes inbound leads.", "business_outcome": "Influenced pipeline by directing SDR effort.", "value_amount": 210000, "value_type": "Revenue influenced", "hours_saved_monthly": 90, "enterprise_systems": ["Salesforce"], "databases": ["Snowflake"], "mcp_servers": ["Salesforce MCP Server"], "calls": ["proposal-drafter"], "consumers": ["SDR Queue"], "inputs": ["Lead record"], "outputs": ["Lead score"], "api_endpoint": "/agents/v1/lead-scoring", "sla": "99.9% uptime", "tags": ["sales", "revops"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved with Conditions"}},
    {"id": "proposal-drafter", "name": "Sales Proposal Drafter", "dept_id": "dept-sales", "owner": "Sales Enablement Engineering", "lifecycle_stage": "Development", "version": "v0.3", "time_in_stage_weeks": 5, "ai_type": "Copilot / Assistant", "description": "Drafts first-pass customer proposals.", "business_outcome": "Projected to cut proposal drafting time.", "value_amount": 35000, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["Salesforce", "Microsoft 365"], "knowledge_bases": ["Pricing & Discount KB"], "mcp_servers": ["Salesforce MCP Server", "Email MCP"], "consumers": ["Deal Desk"], "inputs": ["Opportunity record"], "outputs": ["Draft proposal"], "api_endpoint": "/agents/v1/proposal-drafter", "sla": "Not yet defined", "tags": ["sales", "proposals"], "model_name": "GPT-5", "reviews": {"arb": "In Review", "security": "Not Submitted", "dp": "Not Submitted"}},
    {"id": "support-triage", "name": "Customer Support Triage Agent", "dept_id": "dept-cx", "owner": "CX Automation", "lifecycle_stage": "Production", "version": "v3.5", "time_in_stage_weeks": 58, "ai_type": "Autonomous Agent", "description": "Classifies and routes inbound tickets.", "business_outcome": "Cut average first-response time.", "value_amount": 124000, "value_type": "Cost avoidance", "hours_saved_monthly": 980, "enterprise_systems": ["Zendesk"], "knowledge_bases": ["Support Macros KB"], "mcp_servers": ["Slack MCP Server", "Zendesk MCP Server"], "calls": ["refund-adjudication"], "consumers": ["Support Queue"], "inputs": ["Support ticket"], "outputs": ["Ticket category"], "api_endpoint": "/agents/v1/support-triage", "sla": "99.9% uptime", "tags": ["support", "cx"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "refund-adjudication", "name": "Refund Adjudication Agent", "dept_id": "dept-cx", "owner": "CX Platform", "lifecycle_stage": "Testing", "version": "v0.9", "time_in_stage_weeks": 4, "at_risk": True, "risk_level": "HIGH", "risk_note": "Depends on both Zendesk and SAP S/4HANA.", "ai_type": "Autonomous Agent", "description": "Evaluates refund requests against policy.", "business_outcome": "Projected to resolve 70% of refund requests.", "value_amount": 30000, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["Zendesk", "SAP S/4HANA"], "knowledge_bases": ["Support Macros KB"], "mcp_servers": ["Zendesk MCP Server", "SAP MCP Server"], "consumers": ["Refund Queue"], "inputs": ["Refund request"], "outputs": ["Approval decision"], "api_endpoint": "/agents/v1/refund-adjudication", "sla": "Target 99.5% uptime", "tags": ["support", "finance", "risk"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Changes Requested", "dp": "In Review"}},
    {"id": "demand-forecast", "name": "Demand Forecasting Agent", "dept_id": "dept-supply-chain", "owner": "Supply Chain Analytics", "lifecycle_stage": "Production", "version": "v5.2", "time_in_stage_weeks": 70, "ai_type": "Predictive / ML Model", "description": "Forecasts SKU-level demand from sales history.", "business_outcome": "Reduced stockouts and excess inventory.", "value_amount": 310000, "value_type": "Cost avoidance", "hours_saved_monthly": 400, "enterprise_systems": ["SAP S/4HANA"], "databases": ["Snowflake", "Databricks"], "knowledge_bases": ["Inventory Planning KB"], "mcp_servers": ["Snowflake MCP Server"], "consumers": ["Replenishment Planning"], "inputs": ["Sales history"], "outputs": ["SKU demand forecast"], "api_endpoint": "/agents/v1/demand-forecasting", "sla": "99.5% uptime", "tags": ["supply-chain", "forecasting"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "supplier-risk", "name": "Supplier Risk Monitor", "dept_id": "dept-supply-chain", "owner": "Supply Chain Analytics (proposed)", "lifecycle_stage": "Ideation", "version": "n/a", "time_in_stage_weeks": 20, "at_risk": True, "risk_note": "Stalled in ideation for 20 weeks.", "ai_type": "Predictive / ML Model", "description": "Would continuously score supplier risk.", "business_outcome": "Targeted at reducing supply disruption.", "value_amount": 0, "value_type": "Not yet quantified", "hours_saved_monthly": 0, "enterprise_systems": ["SAP S/4HANA"], "knowledge_bases": ["Supplier Risk KB (proposed)"], "api_endpoint": "Not yet built", "sla": "n/a", "tags": ["supply-chain", "risk"], "model_name": "GPT-5", "reviews": {"arb": "Not Submitted", "security": "Not Submitted", "dp": "Not Submitted"}},
    {"id": "incident-copilot", "name": "Incident Response Copilot", "dept_id": "dept-it-ops", "owner": "Site Reliability Engineering", "lifecycle_stage": "Production", "version": "v2.9", "time_in_stage_weeks": 46, "ai_type": "Copilot / Assistant", "description": "Correlates alerts and suggests root cause.", "business_outcome": "Cut mean time to resolution by 38%.", "value_amount": 95000, "value_type": "Cost avoidance", "hours_saved_monthly": 520, "enterprise_systems": ["ServiceNow"], "databases": ["Databricks"], "knowledge_bases": ["Runbook KB"], "mcp_servers": ["Slack MCP Server", "GitHub MCP Server"], "calls": ["access-review"], "consumers": ["Incident Bridge"], "inputs": ["Alert stream"], "outputs": ["Root cause suggestion"], "api_endpoint": "/agents/v1/incident-copilot", "sla": "99.95% uptime", "tags": ["it-ops", "sre"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "change-validator", "name": "Change Request Validator", "dept_id": "dept-it-ops", "owner": "IT Service Management", "lifecycle_stage": "Deprecated", "version": "v1.2 (final)", "time_in_stage_weeks": 12, "at_risk": True, "risk_note": "Superseded by Incident Response Copilot.", "ai_type": "Autonomous Agent", "description": "Validated change requests against a static risk checklist.", "business_outcome": "Superseded; scheduled for shutdown.", "value_amount": 0, "value_type": "Retired", "hours_saved_monthly": 0, "enterprise_systems": ["ServiceNow"], "mcp_servers": ["ServiceNow MCP Server"], "api_endpoint": "/agents/v1/change-validator (sunset 2026-09-30)", "sla": "n/a", "tags": ["it-ops", "retired"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "access-review", "name": "Access Review Agent", "dept_id": "dept-it-ops", "owner": "Identity & Access Engineering", "lifecycle_stage": "Testing", "version": "v0.7", "time_in_stage_weeks": 3, "ai_type": "Autonomous Agent", "description": "Reviews entitlement grants against role baselines.", "business_outcome": "Projected to cut quarterly access-review effort.", "value_amount": 48000, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["ServiceNow", "Workday", "Microsoft 365"], "knowledge_bases": ["Access Policy KB"], "mcp_servers": ["ServiceNow MCP Server", "Workday MCP Server"], "consumers": ["Access Review Queue"], "inputs": ["Entitlement record"], "outputs": ["Excess-access flag"], "api_endpoint": "/agents/v1/access-review", "sla": "Target 99% uptime", "tags": ["it-ops", "security", "iam"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "In Review", "dp": "In Review"}},
    {"id": "campaign-copy", "name": "Campaign Copy Generator", "dept_id": "dept-marketing", "owner": "Marketing Automation", "lifecycle_stage": "Production", "version": "v2.1", "time_in_stage_weeks": 44, "ai_type": "Generative AI Feature", "description": "Generates on-brand copy variants.", "business_outcome": "Cut campaign copy turnaround.", "value_amount": 27000, "value_type": "Cost avoidance", "hours_saved_monthly": 260, "enterprise_systems": ["Microsoft 365"], "knowledge_bases": ["Brand Voice KB"], "mcp_servers": ["Slack MCP Server"], "consumers": ["Campaign Ops Queue"], "inputs": ["Creative brief"], "outputs": ["Copy variants"], "api_endpoint": "/agents/v1/campaign-copy", "sla": "99% uptime", "tags": ["marketing", "content"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "market-digest", "name": "Market Intelligence Digest", "dept_id": "dept-marketing", "owner": "Marketing Insights", "lifecycle_stage": "Development", "version": "v0.4", "time_in_stage_weeks": 7, "ai_type": "Generative AI Feature", "description": "Summarizes competitor moves and market signals.", "business_outcome": "Projected to replace 15 hours a week of research.", "value_amount": 18000, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "databases": ["Snowflake"], "knowledge_bases": ["Competitive Intel KB"], "mcp_servers": ["Web Search MCP", "Slack MCP Server"], "calls": ["campaign-copy"], "consumers": ["Brand Team Slack Channel"], "inputs": ["Market data feed"], "outputs": ["Weekly digest summary"], "api_endpoint": "/agents/v1/market-digest", "sla": "Not yet defined", "tags": ["marketing", "research"], "model_name": "GPT-5", "reviews": {"arb": "In Review", "security": "Not Submitted", "dp": "Not Submitted"}},
    {"id": "expense-audit", "name": "Expense Report Auditor", "dept_id": "dept-finance", "owner": "Finance Ops Engineering", "lifecycle_stage": "Production", "version": "v2.7", "time_in_stage_weeks": 50, "ai_type": "Autonomous Agent", "description": "Audits expense reports against policy.", "business_outcome": "Cut policy-violation leakage.", "value_amount": 64000, "value_type": "Cost avoidance", "hours_saved_monthly": 410, "enterprise_systems": ["SAP S/4HANA", "Microsoft 365"], "knowledge_bases": ["Expense Policy KB"], "mcp_servers": ["SAP MCP Server", "Email MCP"], "consumers": ["Finance Audit Queue"], "inputs": ["Expense report"], "outputs": ["Approval decision"], "api_endpoint": "/agents/v1/expense-auditor", "sla": "99.5% uptime", "tags": ["finance", "compliance"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "churn-predictor", "name": "Customer Churn Prediction Model", "dept_id": "dept-cx", "owner": "Data Science", "lifecycle_stage": "Production", "version": "v6.0", "time_in_stage_weeks": 66, "ai_type": "Predictive / ML Model", "description": "Scores active accounts weekly on churn probability.", "business_outcome": "Retention team prioritizes outreach.", "value_amount": 145000, "value_type": "Revenue retained", "hours_saved_monthly": 0, "enterprise_systems": ["Salesforce"], "databases": ["Snowflake"], "consumers": ["Customer Success Dashboard"], "inputs": ["Usage telemetry"], "outputs": ["Churn probability score"], "api_endpoint": "/models/v1/churn-prediction", "sla": "Weekly batch scoring", "tags": ["cx", "ml", "retention"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved with Conditions"}},
    {"id": "fraud-detection", "name": "Transaction Fraud Detection Model", "dept_id": "dept-finance", "owner": "Risk & Fraud Analytics", "lifecycle_stage": "Production", "version": "v8.3", "time_in_stage_weeks": 88, "risk_level": "HIGH", "ai_type": "Predictive / ML Model", "description": "Scores transactions in real time for fraud risk.", "business_outcome": "Reduced confirmed fraud losses.", "value_amount": 220000, "value_type": "Cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["Payment Gateway"], "databases": ["Snowflake", "Databricks"], "knowledge_bases": ["Fraud Pattern KB"], "consumers": ["Fraud Ops Queue"], "inputs": ["Transaction event"], "outputs": ["Fraud risk score"], "api_endpoint": "/models/v1/fraud-detection", "sla": "99.99% uptime", "tags": ["finance", "risk", "ml"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved with Conditions", "dp": "Approved"}},
    {"id": "hr-chatbot", "name": "HR Policy Chatbot", "dept_id": "dept-hr", "owner": "People Experience Engineering", "lifecycle_stage": "Production", "version": "v2.0", "time_in_stage_weeks": 48, "ai_type": "Conversational AI / Chatbot", "description": "Answers employee questions about benefits and policy.", "business_outcome": "Deflected routine HR inquiries.", "value_amount": 33000, "value_type": "Cost avoidance", "hours_saved_monthly": 210, "enterprise_systems": ["Workday", "Microsoft 365"], "knowledge_bases": ["HR Policy KB"], "mcp_servers": ["Slack MCP Server"], "consumers": ["Employee Self-Service Portal"], "inputs": ["Employee question"], "outputs": ["Conversational answer"], "api_endpoint": "/chat/v1/hr-policy-bot", "sla": "99% uptime", "tags": ["hr", "chatbot", "genai"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "defect-vision", "name": "Visual Defect Inspection Model", "dept_id": "dept-supply-chain", "owner": "Manufacturing Analytics", "lifecycle_stage": "Testing", "version": "v0.6", "time_in_stage_weeks": 8, "ai_type": "Computer Vision Model", "description": "Classifies product images to flag visual defects.", "business_outcome": "Projected to cut the defect escape rate.", "value_amount": 0, "value_type": "Projected cost avoidance", "hours_saved_monthly": 0, "enterprise_systems": ["MES System"], "databases": ["Databricks"], "consumers": ["Line Quality Dashboard"], "inputs": ["Line camera image stream"], "outputs": ["Defect classification"], "api_endpoint": "/models/v1/defect-vision", "sla": "Target P95 < 300ms", "tags": ["supply-chain", "vision", "ml"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "In Review", "dp": "Not Submitted"}},
    {"id": "code-review-copilot", "name": "Code Review Copilot", "dept_id": "dept-engineering", "owner": "Developer Platform Engineering", "lifecycle_stage": "Production", "version": "v3.2", "time_in_stage_weeks": 40, "ai_type": "Copilot / Assistant", "description": "Suggests review comments on pull requests.", "business_outcome": "Cut average time-to-first-review-comment.", "value_amount": 52000, "value_type": "Cost avoidance", "hours_saved_monthly": 300, "enterprise_systems": ["GitHub"], "knowledge_bases": ["Engineering Style Guide KB"], "mcp_servers": ["GitHub MCP Server"], "consumers": ["Pull Request Review Thread"], "inputs": ["Pull request diff"], "outputs": ["Suggested review comments"], "api_endpoint": "/copilots/v1/code-review", "sla": "99.5% uptime", "tags": ["engineering", "copilot", "genai"], "model_name": "GPT-5", "reviews": {"arb": "Approved", "security": "Approved", "dp": "Approved"}},
    {"id": "pricing-optimizer", "name": "Dynamic Pricing Optimizer", "dept_id": "dept-sales", "owner": "RevOps Engineering", "lifecycle_stage": "Development", "version": "v0.2", "time_in_stage_weeks": 4, "ai_type": "Predictive / ML Model", "description": "Recommends discount bands per deal.", "business_outcome": "Projected to improve win rate.", "value_amount": 60000, "value_type": "Projected revenue influenced", "hours_saved_monthly": 0, "enterprise_systems": ["Salesforce"], "databases": ["Snowflake"], "consumers": ["Deal Desk"], "inputs": ["Deal record"], "outputs": ["Recommended discount band"], "api_endpoint": "/models/v1/pricing-optimizer", "sla": "Not yet defined", "tags": ["sales", "pricing", "ml"], "model_name": "GPT-5", "reviews": {"arb": "In Review", "security": "Not Submitted", "dp": "Not Submitted"}},
]

SEED_DISCOVERIES = [
    {"id": "disc-1", "suspected_name": "bulk-uploader.py (scheduled job)", "suspected_dept": "Data & Analytics", "suspected_type": "Autonomous Agent", "source": "Snowflake query log", "confidence": 82, "signal": "Recurring service-account queries tagged agent=true.", "shadow_ai_risk": "MEDIUM", "first_seen": date(2026, 8, 1)},
    {"id": "disc-2", "suspected_name": "Legal Slack bot (unregistered)", "suspected_dept": "Legal", "suspected_type": "Generative AI Feature", "source": "Slack app directory", "confidence": 91, "signal": "OAuth app with chat:write scopes posting auto-generated clause summaries.", "shadow_ai_risk": "HIGH", "first_seen": date(2026, 7, 29)},
    {"id": "disc-3", "suspected_name": "svc_ai_ticket_bot", "suspected_dept": "IT Operations", "suspected_type": "Autonomous Agent", "source": "ServiceNow integration-user activity", "confidence": 76, "signal": "Service account creating and closing tickets at a rate inconsistent with human activity.", "shadow_ai_risk": "HIGH", "first_seen": date(2026, 8, 5)},
    {"id": "disc-4", "suspected_name": "auto-pr-reviewer (GitHub App)", "suspected_dept": "Engineering", "suspected_type": "Copilot / Assistant", "source": "GitHub App installation logs", "confidence": 88, "signal": "Installed app posts AI-generated review comments on pull requests.", "shadow_ai_risk": "MEDIUM", "first_seen": date(2026, 8, 10)},
    {"id": "disc-5", "suspected_name": "deal-qualifier flow", "suspected_dept": "Sales", "suspected_type": "Predictive / ML Model", "source": "Salesforce API call pattern", "confidence": 69, "signal": "API user generating opportunity-qualification notes.", "shadow_ai_risk": "LOW", "first_seen": date(2026, 8, 11)},
]

SEED_MODEL_PRICES = [
    {"id": "price-gpt5", "model_name": "GPT-5", "provider": "openai", "input_price_per_1m": 2.50, "output_price_per_1m": 15.00, "cache_read_price_per_1m": 0.25, "tier": "frontier"},
    {"id": "price-gpt5-mini", "model_name": "GPT-5-mini", "provider": "openai", "input_price_per_1m": 0.75, "output_price_per_1m": 4.50, "cache_read_price_per_1m": 0.08, "tier": "mid"},
    {"id": "price-gpt5-nano", "model_name": "GPT-5-nano", "provider": "openai", "input_price_per_1m": 0.20, "output_price_per_1m": 1.25, "cache_read_price_per_1m": 0.02, "tier": "lightweight"},
    {"id": "price-sonnet", "model_name": "Claude Sonnet 4.5", "provider": "anthropic", "input_price_per_1m": 3.00, "output_price_per_1m": 15.00, "cache_read_price_per_1m": 0.30, "tier": "mid"},
    {"id": "price-haiku", "model_name": "Claude Haiku 4.5", "provider": "anthropic", "input_price_per_1m": 1.00, "output_price_per_1m": 5.00, "cache_read_price_per_1m": 0.10, "tier": "lightweight"},
]


async def init_db():
    """Initialize database tables and seed data."""
    print("Creating tables...")
    await create_all_tables()

    async with get_db_session() as db:
        # Check if already seeded
        result = await db.execute(select(func.count(Agent.id)))
        if result.scalar() > 0:
            print("Database already seeded, skipping.")
            return

        print("Seeding database...")

        try:
            # Create default org
            db.add(Organization(id="org-default", name="Default Organization", slug="default"))

            # Create departments
            for dept in SEED_DEPARTMENTS:
                db.add(Department(id=dept["id"], org_id="org-default", name=dept["name"], cost_center=dept.get("cost_center", "")))

            # Create agents
            for agent_data in SEED_AGENTS:
                reviews = agent_data.pop("reviews", {})
                agent_id = agent_data["id"]
                # Use id as slug if not provided
                if "slug" not in agent_data:
                    agent_data["slug"] = agent_id
                db.add(Agent(org_id="org-default", **agent_data))
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

            # Create admin user with known dev password
            admin_password = "admin123"
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
            print(f"Admin login: admin@airegistry.local / {admin_password}")
        except Exception as e:
            print(f"ERROR during seeding: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    asyncio.run(init_db())
