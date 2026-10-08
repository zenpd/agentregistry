"""Builds the Agent Registry manual test cases, the field guide and the defect log
(the test-maker format) in the repo root:

    python3 tools/test_cases/build_cases.py     # writes the three CSV files
    python3 tools/test_cases/build_xlsx.py      # then Agent-Registry-Test-Cases-v1.xlsx (needs openpyxl)

Rules that keep ids and results stable:
* Add a new case at the END of its module block. Ids are positional: never insert in the middle or reorder.
* When steps or the expected result change, pass ver="v2". A changed case goes back to "Not Run".
  An unchanged case keeps the tester's status, notes, name, date and build from the existing CSV.
"""
import csv
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "Agent-Registry-Test-Cases-v1.csv")
FIELDS_OUT = os.path.join(ROOT, "Agent-Registry-Test-Case-Fields-v1.csv")
DEFECT_OUT = os.path.join(ROOT, "Agent-Registry-Defect-Log-v1.csv")

APP = "Backend on http://127.0.0.1:8002 and UI on http://localhost:5174 are running"
ADM = f"{APP}. Signed in as admin@airegistry.local / admin123 (Registry Admin)"
PROBE = f"{ADM}. A test agent exists: AI Registry, + Register new AI application, name 'Test Agent', stage Ideation"
RUN = "Browser check of 2026-10-08: Pass"

COLUMNS = ["Test ID", "Module", "Feature", "Role", "Priority", "Type", "Preconditions", "Test Steps", "Expected Result",
           "Needs Setup", "Automated Coverage", "Last Automated Result", "Manual Status", "Actual Result", "Failure Description",
           "Defect ID", "Tested By", "Test Date", "Build / Version", "Case Version", "Recheck Result", "Tester Tip"]

MODULES = {
    "AUTH": "Sign-in, roles and demo agents", "AUD": "Audit trail and decision log", "NTF": "Notifications, away and deputy",
    "DIS": "Discovery, import, API keys and connectors", "OWN": "Ownership", "GOV": "Governance lifecycle",
    "CLS": "Classification and approved tools", "CTL": "Controls", "VER": "Versions", "RET": "Retirement",
    "EVD": "AssureAI evidence and tool calls", "REU": "Reuse", "VAL": "Value and cost", "CMP": "Compliance and incidents",
}

rows = []
counters = {}


def T(mod, feature, role, prio, typ, pre, steps, expected, setup="None", auto="Manual only", auto_res="", ver="v1", recheck="", tip=""):
    counters[mod] = counters.get(mod, 0) + 1
    tid = f"{mod}-{counters[mod]:03d}"
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    rows.append([tid, MODULES[mod], feature, role, prio, typ, pre, steps, expected, setup, auto, auto_res,
                 "Not Run", "", "", "", "", "", "", ver, recheck, tip])


# ── Sign-in, roles and demo agents ───────────────────────────────────────────
T("AUTH", "Sign in with the local account", "Admin", "P1", "Functional", APP,
  ["Open http://localhost:5174.", "Enter admin@airegistry.local / admin123 and click Sign in."],
  "The Executive page opens. The top bar shows Registry Admin with the role under it.",
  auto="ui/checks/phase0.mjs", auto_res="Pass", recheck=RUN)
T("AUTH", "Demo agents are shown by default", "Admin", "P1", "Functional", ADM,
  ["Open AI Registry.", "Look at the top bar."],
  "18 agents are listed, 12 with a Demo badge. The top bar shows no demo label.",
  auto="tests/test_demo_scope.py, ui/checks/phase0.mjs, ui/checks/demo_agents.mjs", auto_res="Pass", ver="v2", recheck=RUN)
T("AUTH", "Hide the demo agents", "Admin", "P2", "Functional", ADM,
  ["Settings, Demo agents, untick Show the demo agents on every page.", "Open AI Registry."],
  "Only the 6 real agents are listed. Ticking the box again shows the demo agents.",
  auto="ui/checks/phase0.mjs", auto_res="Pass", ver="v2", recheck=RUN)
T("AUTH", "A role cannot do what it is not allowed to", "Executive Viewer", "P1", "Security",
  f"{APP}. A user with the role Executive Viewer exists (Settings, Users, Add user)",
  ["Sign in as that user.", "Open any agent, Governance tab.", "Look for the decision buttons."],
  "The decision buttons are not offered. A line says the role cannot change records.",
  auto="tests/test_roles.py", auto_res="Pass")
T("AUTH", "An Auditor needs an end date", "Admin", "P1", "Security", ADM,
  ["Settings, Users, Add user.", "Choose the role Auditor.", "Leave Access until empty and look at Add user."],
  "An Access until date is asked for. Add user stays disabled until a date is chosen.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("AUTH", "An Auditor's access ends on the date", "Auditor", "P1", "Security",
  f"{APP}. An Auditor whose Access until date is yesterday",
  ["Sign in as the Auditor.", "Open AI Registry."],
  "The registry refuses with 'Your auditor access ended on <date>'.",
  auto="tests/test_compliance.py", auto_res="Pass")
T("AUTH", "Every Auditor request is logged", "Admin+Auditor", "P1", "Security",
  f"{APP}. An Auditor with a future Access until date",
  ["Sign in as the Auditor and open two agents.", "Sign in as the admin.", "Open Audit Trail and filter the action 'Auditor viewed'."],
  "One row per page the Auditor opened, with the address.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("AUTH", "Archived agents are left out and can be brought back", "Admin", "P2", "Functional", ADM,
  ["Settings, Demo agents, read the Archived list.", "Click Bring back on one agent.", "Open AI Registry."],
  "The list names the 10 archived agents with the reason. The agent brought back is listed again. Its records are unchanged.",
  auto="tests/test_archived_agents.py, ui/checks/demo_agents.mjs", auto_res="Pass")
T("AUTH", "Demo agents turned off for the installation", "Developer", "P2", "Functional",
  "Backend started with DEMO_AGENTS_ENABLED=false (backend/.env), UI running, signed in as the admin",
  ["Open AI Registry and Dependencies.", "Open a demo agent's address, for example /agents/inv-recon.", "Settings, Demo agents."],
  "Only the 6 real agents and their graph are shown. The demo agent's page does not open. Settings says the demo agents are turned off for this installation.",
  setup="Backend restart", auto="tests/test_demo_setting.py", auto_res="Pass")

# ── Audit trail and decision log ─────────────────────────────────────────────
T("AUD", "Audit trail lists events by people", "Admin", "P1", "Functional", ADM,
  ["Open Audit Trail from the left menu."],
  "Events by people are listed, newest first, with who, what and when.",
  auto="tests/test_audit_trail.py, ui/checks/phase0.mjs", auto_res="Pass", recheck=RUN)
T("AUD", "Audit trail CSV export", "Admin", "P2", "Functional", ADM,
  ["Open Audit Trail.", "Click Export CSV."],
  "A CSV file downloads. The export itself appears in the trail.",
  auto="ui/checks/phase0.mjs", auto_res="Pass", recheck=RUN)
T("AUD", "Decision log check", "Admin", "P1", "Security", ADM,
  ["Open Compliance.", "Read the Decision log card."],
  "It says all N sealed decisions match, the date sealing started, and the last hash.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("AUD", "A decision becomes part of the decision log", "Admin", "P2", "Functional", PROBE,
  ["Note the count in Compliance, Decision log.", "Open the test agent, Governance tab, set the Architecture Review Board to Approved and confirm.",
   "Open Compliance again and click Check again."],
  "The count of sealed decisions is one higher and the check still says they match.",
  auto="tests/test_compliance.py", auto_res="Pass")
T("AUD", "A changed decision is found", "Developer", "P1", "Security",
  "A throwaway database copy without the append-only triggers",
  ["Change the actor of an early gate decision directly in the audit_log table.", "Open Compliance, Decision log, Check again."],
  "It names the first entry that no longer matches: 'the decision was changed after it was sealed'.",
  setup="Database access", auto="tests/test_compliance.py", auto_res="Pass")

# ── Notifications, away and deputy ───────────────────────────────────────────
T("NTF", "Send a test notification", "Admin", "P2", "Functional", ADM,
  ["Settings, Notifications, click Send me a test message.", "Open the bell in the top bar."],
  "The bell count goes up and the panel lists the test message.",
  auto="tests/test_notifications.py, ui/checks/phase0.mjs", auto_res="Pass", recheck=RUN)
T("NTF", "Mark yourself away with a deputy", "Admin", "P2", "Functional", f"{ADM}. A second user exists",
  ["Settings, Away and deputy.", "Choose a date in Away until and a Deputy, click Save."],
  "A message says until when you are away and who receives your notices. 'I am back' appears.",
  auto="tests/test_ownership.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("NTF", "I am back", "Admin", "P3", "Functional", f"{ADM}. You are marked away",
  ["Settings, Away and deputy, click I am back."],
  "'Saved. You are not marked as away.' The I am back button disappears.",
  auto="ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("NTF", "Away reviewer's notices go to the deputy", "Security Reviewer", "P2", "Functional",
  f"{APP}. Two Security Reviewers, one away with the other as deputy, a Security Review In Review for 6 days",
  ["Pipelines, run Daily notifications.", "Sign in as the deputy and open the bell."],
  "The deputy's digest says 'For <name>, who is away until <date>' and that the review is overdue.",
  auto="tests/test_notifications.py", auto_res="Pass")

# ── Discovery, import, API keys and connectors ───────────────────────────────
T("DIS", "Discovered page tiles and triage", "Admin", "P2", "Functional", f"{ADM}. Phoenix is reachable over the VPN",
  ["Open Discovered.", "In an inbox row choose Assigned to: Registry Admin."],
  "Five tiles are shown, including Other sources and Evaluation runs. The assignment is saved.",
  setup="Phoenix", auto="tests/test_identity_attention.py, ui/checks/phase1.mjs", auto_res="Pass", recheck=RUN)
T("DIS", "A project shared by two records is flagged", "Admin", "P2", "Functional", ADM,
  ["Discovered, click the Registered tile."],
  "A warning names the project linked to more than one record.",
  setup="Phoenix", auto="ui/checks/phase1.mjs", auto_res="Pass", recheck=RUN)
T("DIS", "Import agents from CSV", "Admin", "P2", "Functional", ADM,
  ["AI Registry, click Import.", "Choose a CSV with one new agent and one that exists.", "Click Import."],
  "The preview says '1 to create, 1 skipped'. The new agent appears at Ideation.",
  auto="tests/test_bulk_import.py, ui/checks/phase1.mjs", auto_res="Pass", recheck=RUN)
T("DIS", "Issue an API key and use the CI check", "Admin", "P1", "Integration", ADM,
  ["Settings, API keys, type a label and click Issue.", "Copy the key shown once.",
   "Run: python3 tools/registry_cli.py check '<agent>' --stage Production with REGISTRY_API_KEY set."],
  "The CLI prints BLOCKED with the reasons and exits with 1 for an agent that is not ready.",
  auto="tests/test_ci_keys.py, ui/checks/phase1.mjs", auto_res="Pass", recheck=RUN)
T("DIS", "A revoked key stops working", "Admin", "P1", "Security", f"{ADM}. An API key exists",
  ["Settings, API keys, revoke the key.", "Call the CI check with it again."],
  "The call is refused (401).", auto="ui/checks/phase1.mjs", auto_res="Pass", recheck=RUN)
T("DIS", "GitHub connector finds agent repositories", "Admin", "P2", "Integration", ADM,
  ["Settings, Connectors, add a GitHub connector for a public organisation.", "Click Scan now.", "Discovered, Other sources."],
  "The connector reports what it found. Other sources lists the repositories.",
  setup="GitHub", auto="tests/test_connectors.py, ui/checks/phase1.mjs", auto_res="Pass", recheck=RUN)
T("DIS", "Test the Phoenix connection", "Admin", "P2", "Integration", ADM,
  ["Settings, Phoenix, click Test connection."],
  "It names the result, for example 'Connected. Phoenix 20.7.0, 72 projects.'",
  setup="Phoenix", auto="tests/test_phoenix_connection.py, ui/checks/phase0.mjs", auto_res="Pass", recheck=RUN)

# ── Ownership ────────────────────────────────────────────────────────────────
T("OWN", "Set the owner and the backup owner", "Admin", "P1", "Functional", f"{PROBE}. A second user exists",
  ["Open the test agent, Overview.", "Click Change owner or backup.", "Choose an Owner and a different Backup owner, click Save."],
  "Owner and Backup owner show the two people. The Audit Trail has 'Owner changed'.",
  auto="tests/test_ownership.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("OWN", "Owner and backup must differ", "Admin", "P3", "Negative", PROBE,
  ["Change owner or backup, pick the same person in both."],
  "The backup list leaves out the person chosen as owner.", auto="tests/test_ownership.py", auto_res="Pass")
T("OWN", "The backup takes over when the owner is deactivated", "Admin", "P1", "Functional",
  f"{PROBE}. Owner A and backup B are set",
  ["Settings, Users, Deactivate A.", "Open the test agent, Overview."],
  "B is the owner. The message on deactivation says how many agents went to the backup owner.",
  auto="tests/test_ownership.py", auto_res="Pass")
T("OWN", "Agents without an owner are listed", "Admin", "P2", "Functional", f"{ADM}. An agent has no owner",
  ["Open Executive.", "Read Lifecycle signals."],
  "The agent is listed with 'No owner'.", auto="tests/test_ownership.py, ui/checks/phase1.mjs", auto_res="Pass")

# ── Governance lifecycle ─────────────────────────────────────────────────────
T("GOV", "Record completeness and weeks in stage", "Admin", "P2", "UI", PROBE,
  ["Open the test agent, Governance tab."],
  "'Record N% complete', 'In Ideation for N weeks' and the missing fields are shown.",
  auto="tests/test_lifecycle.py", auto_res="Pass")
T("GOV", "The stage list has no Deprecated", "Admin", "P1", "Functional", PROBE,
  ["Governance tab, open Change stage to."],
  "Deprecated is not in the list. A line says 'To retire it, use Retire this agent below.'",
  auto="tests/test_retirement_versions_evidence.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("GOV", "Governance rules by risk tier", "Admin", "P1", "Functional", ADM,
  ["Settings, Governance rules.", "For LOW set the reviews to Architecture and Security and the rule to block, click Save the rules.",
   "Open a LOW agent, Governance tab."],
  "The tab says the rules for LOW: block, two reviews. Production readiness no longer asks for Data Protection.",
  auto="tests/test_lifecycle.py", auto_res="Pass")
T("GOV", "A change after approval reopens the reviews it affects", "Admin", "P1", "Functional",
  f"{PROBE}. All three reviews are Approved",
  ["Add an MCP server to the record (Overview, edit).", "Pipelines, run Governance checks.", "Governance tab."],
  "Security and Data Protection are back In Review with 'Reopened by the registry'. The Architecture approval stays.",
  auto="tests/test_lifecycle.py", auto_res="Pass")
T("GOV", "A waiver needs two different signers", "Data Protection Officer", "P1", "Security",
  f"{APP}. Two Data Protection Officers, a test agent",
  ["As the first, Governance tab, Waivers, + Add a waiver for Data Protection with a reason of 20 characters.",
   "As the same person, try to sign it.", "As the second, sign it."],
  "The first signer cannot sign twice. After the second signature the waiver covers the gate.",
  auto="tests/test_lifecycle.py", auto_res="Pass")
T("GOV", "A failed Security Review cannot be waived", "Admin", "P1", "Negative", PROBE,
  ["Waivers, + Add a waiver, choose Security."],
  "It is refused: 'A failed Security Review cannot be waived. Fix the finding instead.'",
  auto="tests/test_lifecycle.py", auto_res="Pass")
T("GOV", "The review queue is ranked and names who can decide", "Admin", "P1", "Functional",
  f"{ADM}. Reviews In Review on agents with and without critical findings",
  ["Open Approvals."],
  "Reviews with open critical findings come first, then high findings, then risk tier, then the longest wait. Each row says who can decide now and who is away.",
  auto="tests/test_ownership.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("GOV", "Overdue reviews are marked", "Admin", "P2", "UI", f"{ADM}. A review In Review for more than 5 days",
  ["Open Approvals."], "The row shows 'Overdue: more than 5 days'.", auto="tests/test_ownership.py", auto_res="Pass")
T("GOV", "Decided history", "Admin", "P2", "Functional", ADM,
  ["Approvals, click Decided."],
  "Gate decisions, access decisions, waivers, classifications, retirements and stage changes are listed, newest first.",
  auto="tests/test_ownership.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)

# ── Classification and approved tools ────────────────────────────────────────
T("CLS", "Answer the classification questions", "Admin", "P1", "Functional", PROBE,
  ["Governance tab, Classification, Answer the classification questions.",
   "Choose None of these, Yes, Only people inside the organisation, Personal data, Up to 1 year, It only suggests."],
  "Suggested: Limited Risk, risk level MEDIUM, with the reasons.",
  auto="tests/test_classification.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("CLS", "A proposal waits in Approvals", "Product Owner+Admin", "P1", "Functional",
  f"{APP}. A Product Owner and the admin, a test agent",
  ["As the Product Owner, classify and click Save as a proposal.", "As the admin, open Approvals."],
  "The classification appears under Reviews awaiting decision. The agent's category has not changed yet.",
  auto="tests/test_classification.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("CLS", "Confirm a classification", "Admin", "P1", "Functional", f"{PROBE}. A proposal waits",
  ["Governance tab, Classification, Confirm this classification."],
  "The classification shows 'confirmed by Registry Admin on <date>'. Overview says Confirmed by. The checklist item 'EU AI Act risk tier confirmed' passes.",
  auto="tests/test_classification.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("CLS", "A result below the suggestion needs a reason", "Admin", "P2", "Negative", f"{PROBE}. A proposal waits",
  ["Choose a lower risk level than suggested.", "Leave the note short."],
  "Confirm stays disabled. The note asks for at least 20 characters.",
  auto="tests/test_classification.py", auto_res="Pass")
T("CLS", "Approved tool list from what agents declare", "Admin", "P2", "Functional", f"{ADM}. An agent declares an MCP server",
  ["Settings, Approved tools.", "Click the declared tool under 'Declared by agents but not on the list'.", "Choose HIGH and click Add to the list."],
  "The tool is listed as HIGH with the number of agents that use it.",
  auto="tests/test_classification.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("CLS", "Tool class raises the suggestion", "Admin", "P1", "Functional", f"{PROBE}. The agent declares a tool approved as HIGH",
  ["Governance tab, Classification, answer the questions for a low-risk agent."],
  "'Tool class: HIGH from <tool>'. The suggestion says 'Raised to HIGH: it uses a tool approved as HIGH'.",
  auto="tests/test_classification.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)

# ── Controls ─────────────────────────────────────────────────────────────────
T("CTL", "Controls list in Settings", "Admin", "P2", "UI", ADM,
  ["Settings, Controls."],
  "16 controls, each Enforced, Recorded only or Off, with what it does now and where it is set.",
  auto="tests/test_retirement_versions_evidence.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("CTL", "A control follows its setting", "Admin", "P2", "Functional", ADM,
  ["Settings, Governance rules, set every tier to block and save.", "Settings, Controls."],
  "'Reviews before a stage change' is Enforced.", auto="Manual only")

# ── Versions ─────────────────────────────────────────────────────────────────
T("VER", "Release a version", "Admin", "P2", "Functional", PROBE,
  ["Integrate tab, Versions, Release a version.", "Version 1.0, What changed: 'First release', click Release."],
  "Version 1.0 is listed with its changelog and the current version is 1.0.",
  auto="tests/test_retirement_versions_evidence.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("VER", "Teams see which version they use", "Admin", "P2", "Functional", f"{PROBE}. A team has approved access on 1.0, 1.1 is released",
  ["Integrate tab, Versions."],
  "The team uses 1.0, '1 version behind', and 'Since then' names what changed.",
  auto="tests/test_retirement_versions_evidence.py", auto_res="Pass")

# ── Retirement ───────────────────────────────────────────────────────────────
T("RET", "Retire through the checked steps", "Admin", "P1", "Functional", PROBE,
  ["Governance tab, Retire this agent, Start retiring this agent, give a reason of 20 characters.",
   "Confirm the traffic step with how you checked.", "Click Revoke keys and access.", "Click Finish: set the stage to Deprecated."],
  "Each step turns done. The stage becomes Deprecated. Decided in Approvals lists 'Agent retired'.",
  auto="tests/test_retirement_versions_evidence.py, ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("RET", "Finish waits for 7 days without calls", "Admin", "P1", "Negative", f"{ADM}. A traced agent called 3 days ago",
  ["Start retiring it, confirm consumers, revoke access, click Finish."],
  "It is refused. The traffic step says when it completes.", auto="tests/test_retirement_versions_evidence.py", auto_res="Pass")

# ── AssureAI evidence and tool calls ─────────────────────────────────────────
T("EVD", "No AssureAI connector yet", "Admin", "P3", "UI", PROBE,
  ["Governance tab, read the AssureAI line."],
  "'No AssureAI verdict recorded' and a link to add an AssureAI connector in Settings.",
  auto="ui/checks/phase2.mjs", auto_res="Pass", recheck=RUN)
T("EVD", "Record an AssureAI run", "Admin", "P2", "Integration", f"{PROBE}. An AssureAI connector with a run key",
  ["Governance tab, AssureAI, Record a run, paste the run id, click Read the verdict."],
  "Pass or Fail with the run date and a link. No scores are shown.",
  setup="AssureAI", auto="tests/test_retirement_versions_evidence.py (recorded answers)", auto_res="Pass")
T("EVD", "AssureAI verdict before Production", "Admin", "P2", "Functional", f"{ADM}. An agent with a failed verdict",
  ["Settings, Governance rules, tick AssureAI verdict before Production, save.", "Open the agent, Governance tab."],
  "Production readiness lists 'The latest AssureAI verdict is fail'.",
  auto="tests/test_retirement_versions_evidence.py", auto_res="Pass")
T("EVD", "Tool calls against the approved set", "Admin", "P2", "Functional", f"{ADM}. A traced agent with a Security Review approval",
  ["Governance tab, read Tool calls."],
  "The share of traced tool calls that went to tools approved at the last Security Review, and the ones that were not approved.",
  setup="Phoenix", auto="tests/test_retirement_versions_evidence.py", auto_res="Pass")

# ── Reuse ────────────────────────────────────────────────────────────────────
T("REU", "Consumers marked approved, seen or both", "Admin", "P2", "Functional", f"{ADM}. A traced agent",
  ["Integrate tab, Consumers, click Read callers now."],
  "'Callers read from the latest traces.' Each consumer has a status. Callers without approval are named.",
  setup="Phoenix", auto="tests/test_reuse_ops.py, ui/checks/phase3.mjs", auto_res="Pass", recheck=RUN)
T("REU", "Teams hear about a contract change", "Admin+Product Owner", "P2", "Functional", f"{ADM}. A team has approved access",
  ["Integrate tab, change the service level and save.", "Sign in as the team's requester and open the bell."],
  "A notice says the agent changed its service level.", auto="tests/test_reuse_ops.py", auto_res="Pass")
T("REU", "Programme Health", "Admin", "P2", "UI", ADM,
  ["Open Programme Health."],
  "Four figures: known agents, owned by a person, review decision time, reuse rate. Reuse by unit and searches not found.",
  auto="tests/test_reuse_ops.py, ui/checks/phase3.mjs", auto_res="Pass", recheck=RUN)
T("REU", "A search that finds nothing becomes a search gap", "Admin", "P3", "Functional", ADM,
  ["AI Registry, search for 'payroll reconciler xyz'.", "Open Programme Health."],
  "The term is listed under Searched for and not found.",
  auto="tests/test_reuse_ops.py, ui/checks/phase3.mjs", auto_res="Pass", recheck=RUN)
T("REU", "Start from a certified agent", "Admin", "P2", "Functional", f"{ADM}. A certified agent exists",
  ["AI Registry, + Register new AI application.", "Start from a certified agent: pick it."],
  "Empty fields fill from its contract. The note names the agent.",
  auto="tests/test_reuse_ops.py, ui/checks/phase3.mjs", auto_res="Pass", recheck=RUN)
T("REU", "Chargeback", "Admin", "P2", "Functional", ADM,
  ["Open an agent, Tokenomics tab, Chargeback.", "Programme Health, Chargeback, click CSV."],
  "The month's token cost and who pays which share. The CSV downloads.",
  auto="tests/test_reuse_ops.py, ui/checks/phase3.mjs", auto_res="Pass", recheck=RUN)

# ── Value and cost ───────────────────────────────────────────────────────────
T("VAL", "Declare value with a method", "Admin", "P1", "Functional", PROBE,
  ["Revenue tab, Declare the value.", "Cost avoidance, 2000, a basis of 20 characters, Save."],
  "'Declared by the owner' with the method Cost avoidance.",
  auto="tests/test_value_ops.py, ui/checks/phase4.mjs", auto_res="Pass", recheck=RUN)
T("VAL", "Finance adjusts the value", "Finance Reviewer", "P1", "Functional", f"{PROBE}. Value declared",
  ["Revenue tab, Finance check, Adjust to another figure, 1500, a note of 20 characters, Record the check."],
  "'Adjusted by finance'. Business Impact and Executive use 1500.",
  auto="tests/test_value_ops.py, ui/checks/phase4.mjs", auto_res="Pass", recheck=RUN)
T("VAL", "A Product Owner cannot attest", "Product Owner", "P1", "Security", f"{APP}. A Product Owner, a test agent with value",
  ["Revenue tab."], "Finance check is not offered.", auto="tests/test_value_ops.py", auto_res="Pass")
T("VAL", "Measured outcomes", "Admin", "P2", "Functional", PROBE,
  ["Revenue tab, Measured outcomes, outcome 'item matched', count 40, Add."],
  "The outcome is listed with a cost per outcome.",
  auto="tests/test_value_ops.py, ui/checks/phase4.mjs", auto_res="Pass", recheck=RUN)
T("VAL", "Usage entered by hand", "Admin", "P2", "Functional", f"{PROBE}. No tracing link",
  ["Tokenomics tab, Usage entered by hand, model gpt-4o, calls 25, input tokens 2000000, Add."],
  "The row is listed. The cost source says 'Entered by hand'.",
  auto="tests/test_value_ops.py, ui/checks/phase4.mjs", auto_res="Pass", recheck=RUN)
T("VAL", "The same work on other models", "Admin", "P3", "Functional", f"{PROBE}. Usage exists",
  ["Revenue tab, The same work on other models, move the price slider to -20%."],
  "Each model's cost of the same tokens, and 'Answer quality was not compared'.",
  auto="tests/test_value_ops.py, ui/checks/phase4.mjs", auto_res="Pass", recheck=RUN)
T("VAL", "Scenario and scorecard", "Admin", "P2", "Functional", ADM,
  ["Business Impact, If these agents move to Production, untick one agent.", "Scorecard, Download PDF."],
  "The totals change. A one-page PDF downloads.",
  auto="tests/test_value_ops.py, ui/checks/phase4.mjs", auto_res="Pass", recheck=RUN)
T("VAL", "Azure cost setup", "Admin", "P2", "Integration", ADM,
  ["Settings, Cost settings, enter tenant, client, secret and scope, Save.", "Click Test the connection."],
  "The result names what happened, for example signed in and the number of rows read.",
  setup="Azure", auto="tests/test_value_ops.py (saving only)", auto_res="Pass")
T("VAL", "Agreed build cost values reuse", "Admin", "P3", "Functional", ADM,
  ["Settings, Cost settings, Agreed cost of building an agent: 40000, Save.", "Open Programme Health."],
  "The reuse figure says the builds avoided are worth the count times $40,000.",
  auto="ui/checks/phase4.mjs", auto_res="Pass", recheck=RUN)

# ── Compliance and incidents ─────────────────────────────────────────────────
T("CMP", "Pack coverage", "Admin", "P1", "Functional", ADM,
  ["Open Compliance.", "Click ISO/IEC 42001."],
  "'ISO/IEC 42001: N of 38 controls evidenced.' Each control has a status.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "Missing evidence is named per agent", "Admin", "P1", "Functional", ADM,
  ["Compliance, ISO/IEC 42001, click A.6.2.8."],
  "The agents without a tracing link are named with 'Runtime tracing is linked'.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "Regulatory dates", "Admin", "P3", "Functional", ADM,
  ["Compliance, EU AI Act, Change the dates, change one, Save."], "The new date is shown.", auto="tests/test_compliance.py", auto_res="Pass")
T("CMP", "Evidence pack and its hash", "Admin", "P1", "Security", PROBE,
  ["Governance tab, Evidence, click PDF.", "Compliance, Check an evidence file, choose the downloaded file."],
  "'Unchanged: this is the pdf Evidence pack of <agent> exported by Registry Admin.' A changed copy is not recognised.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "Control evidence export", "Admin", "P2", "Functional", ADM,
  ["Compliance, a control row, click CSV."], "A CSV with one row per agent the control applies to.",
  auto="ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "Data and retention report", "Admin", "P2", "Functional", ADM,
  ["Compliance, Personal data and how long it is kept, click CSV."],
  "Each agent with the personal data it uses and how long it is kept, or 'Not recorded'.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "GRC export", "Admin", "P3", "Functional", ADM,
  ["Compliance, Export to a GRC tool, OneTrust, Controls and evidence."], "A CSV downloads with framework, control and status columns.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "Link an incident", "Admin", "P2", "Functional", PROBE,
  ["Risk tab, Incidents and stop requests, Link an incident.", "Paste https://acme.pagerduty.com/incidents/Q1W2E3, severity high, Link."],
  "The incident shows PagerDuty Q1W2E3. The owner and backup owner are told.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "Ask the owner to stop the agent", "Admin", "P1", "Functional", f"{PROBE}. An open incident",
  ["Type a reason of 20 characters, click Ask the owner to stop it.", "Open Executive."],
  "'Waiting for the owner.' Executive lists the agent as 'Asked to stop, not acknowledged'.",
  auto="tests/test_compliance.py, ui/checks/phase5.mjs", auto_res="Pass", recheck=RUN)
T("CMP", "Only the owner, backup or an admin acknowledges", "Product Owner", "P1", "Security",
  f"{APP}. A Product Owner who is not the owner, a stop request waiting",
  ["Risk tab, look for Acknowledge the stop."], "It is not offered. The server refuses if called.",
  auto="tests/test_compliance.py", auto_res="Pass")


# ── Field guide and defect log ───────────────────────────────────────────────
FIELDS = [
    ["Field", "Meaning", "Allowed values / example", "Filled by"],
    ["Test ID", "Unique id: MODULE-number. Never reuse an id. Retire a case by setting Manual Status to N/A.", "e.g. GOV-004", "Author"],
    ["Module", "Area of the product.", ", ".join(MODULES.values()), "Author"],
    ["Feature", "One-line name of what is tested.", "Confirm a classification", "Author"],
    ["Role", "Who performs the test.", "Admin, Product Owner, Finance Reviewer, Auditor, Developer", "Author"],
    ["Priority", "How important if it fails.", "P1 = blocks use or security, P2 = important, P3 = nice to have", "Author"],
    ["Type", "Kind of test.", "Functional, Negative, Security, Integration, UI", "Author"],
    ["Preconditions", "What must be true before step 1.", ADM, "Author"],
    ["Test Steps", "Numbered actions in order. Each line is one action.", "1. Open Compliance. 2. Click ...", "Author"],
    ["Expected Result", "Exactly what you should see if it works.", "'ISO/IEC 42001: 4 of 38 controls evidenced.'", "Author"],
    ["Needs Setup", "Outside system needed, if any.", "None, Phoenix, GitHub, Azure, AssureAI, Database access", "Author"],
    ["Automated Coverage", "The automated test(s) that check the same thing, or 'Manual only'. tests/ is the backend suite, ui/checks/ the browser checks.",
     "tests/test_compliance.py, ui/checks/phase5.mjs", "Author"],
    ["Last Automated Result", "Result of those automated tests in the last full run (2026-10-08). Rows needing an outside system are checked against recorded answers.",
     "Pass, Fail, blank", "Automation"],
    ["Manual Status", "Your result when you run the steps by hand.", "Not Run, Pass, Fail, Blocked, N/A", "Tester"],
    ["Actual Result", "What really happened (especially when it is different).", "Finish stayed disabled", "Tester"],
    ["Failure Description", "If Fail or Blocked: what went wrong, the message shown, and how to repeat it.", "Clicked Finish after all steps, nothing happened", "Tester"],
    ["Defect ID", "Id of the entry in Agent-Registry-Defect-Log-v1.csv for a failure.", "DEF-012", "Tester"],
    ["Tested By", "Name of the tester.", "A. Kumar", "Tester"],
    ["Test Date", "Date of the manual run (YYYY-MM-DD).", "2026-10-12", "Tester"],
    ["Build / Version", "App version or commit tested.", "main @ abc1234", "Tester"],
    ["Case Version", "Version of this case's wording. Raise it when steps or the expected result change.", "v1", "Author"],
    ["Recheck Result", "What the browser checks of 2026-10-08 found for this case.", "Browser check of 2026-10-08: Pass", "Author"],
    ["Tester Tip", "A hint for running the case: exact button names or where a control is.", "Step 2: the button is under Waivers.", "Author"],
]

DEFECTS = [
    ["Defect ID", "Title", "Test ID", "Severity", "Steps to Reproduce", "Expected", "Actual", "Screenshot / Link", "Status", "Owner",
     "Found In Build", "Fixed In Build", "Retest Result", "Date Raised", "Date Closed", "Notes"],
]
D = "plan v2 work 2026-10-08"


def defect(title, test, sev, steps, expected, actual, notes):
    DEFECTS.append([f"DEF-{len(DEFECTS):03d}", title, test, sev, steps, expected, actual, "", "Fixed", "Development", D, D, "Pass",
                    "2026-10-08", "2026-10-08", notes])


defect("Governance overview counted reviews of hidden demo agents", "AUTH-002", "Medium",
       "1. Hide demo agents. 2. Open Governance.", "Only real agents are counted.", "Review counts included demo agents.",
       "The overview now leaves out agents the demo switch hides.")
defect("Approvals counted access requests on hidden demo agents", "AUTH-002", "Medium",
       "1. Hide demo agents. 2. Open Approvals.", "Only real agents' requests are counted.", "Demo requests were counted.",
       "The request query now joins the agent so the demo filter applies.")
defect("Database migrations could not run from an empty database", "AUD-001", "High",
       "1. Create an empty PostgreSQL database. 2. Run alembic upgrade head.", "Every migration runs.",
       "Migration 0002 pointed to a revision that does not exist, and 12 tables and 19 columns had no migration.",
       "Fixed the pointer and added catch-up migration 0002a. tests/test_migrations.py checks the chain. Checked on PostgreSQL 18.")
defect("Away and deputy card did not show 'I am back' after saving", "NTF-003", "Medium",
       "1. Settings, Away and deputy. 2. Choose a date and a deputy, Save.", "'I am back' appears at once.",
       "The card kept showing the state from before the save.", "The card now shows what the save returned.")
defect("Insight agents could not list agents after the search change", "REU-004", "High",
       "1. Ask the Registry a question that needs the agent list.", "The answer lists agents.",
       "The agent list call failed inside the insight tools.",
       "The tools called the list with an old parameter name. Found by tests/test_insights.py.")
defect("Scenario list lost agents after unticking one", "VAL-007", "Medium",
       "1. Business Impact, If these agents move to Production. 2. Untick an agent.", "The agent stays in the list, unticked.",
       "The agent disappeared and could not be ticked again.", "The list now keeps every agent not in Production.")
defect("Executive and Business Impact summed declared values while economics used the finance figure", "VAL-002", "High",
       "1. Adjust an agent's value as finance. 2. Compare Executive, Business Impact and the Revenue tab.",
       "One figure everywhere.", "Executive and Business Impact still summed the declared value.",
       "Both pages now use the attested or adjusted figure and say which.")
defect("Langfuse usage was labelled as Phoenix in economics", "VAL-005", "Low",
       "1. Link an agent to Langfuse. 2. Open the Revenue tab.", "Source: Langfuse traces.", "Source: Phoenix traces.",
       "The cost source now follows the usage rows.")
defect("Offboarding call sent the step where the server does not read it", "RET-001", "Low",
       "1. Call offboardAgent from the UI client.", "The step is read.", "The server read the step from the address, the client sent it in the body.",
       "Fixed in the client. The final step now points to the retirement steps.")
defect("Classification reasons showed two different risk levels", "CLS-006", "Low",
       "1. Classify an agent that uses a HIGH tool and personal data.", "One risk level, with how it was raised.",
       "'Risk level MEDIUM' and 'Risk level HIGH' both appeared.",
       "Now 'Risk level from the answers: MEDIUM' and 'Raised to HIGH: it uses a tool approved as HIGH'.")
defect("Governance history left out classification, ownership, version and retirement events", "AUD-004", "Medium",
       "1. Confirm a classification. 2. Governance tab, Decision history.", "The confirmation is listed.",
       "'No governance decisions recorded for this agent yet.'", "The history now reads every lifecycle decision.")
defect("Scheduler test failed now and then with 'database is locked'", "AUD-001", "Low",
       "1. Run tests/test_job_runner.py several times.", "Every run passes.", "About one run in four failed at setup.",
       "A cancelled scheduler read released its connection late. The test setup now waits for the lock. Test-only.")
defect("Scorecard showed '$-80.02' and a return of -100% when no value was declared", "VAL-007", "Low",
       "1. Business Impact, Scorecard, Download PDF with no value declared on any agent.", "'-$80.02' and 'No value is declared yet'.",
       "'$-80.02' and 'Return on cost -100.0%'.", "Fixed in the scorecard. The value state now reads 'not declared' instead of 'none'.")
defect("Evidence files joined missing items with semicolons", "CMP-004", "Low",
       "1. Governance tab, Evidence, PDF. 2. Read the Controls table.", "Each missing item as a sentence.", "Items were joined with semicolons.",
       "Items are now separate sentences.")
defect("The two older Playwright specs no longer matched the app", "AUTH-001", "Medium",
       "1. From ui/, npx playwright test onboarding-verify.spec.cjs graph-vis-verify.spec.cjs.", "Both pass.",
       "The onboarding spec looked for the old agent detail window. The graph spec expected counts from the demo agents, which are now hidden by default.",
       "The onboarding spec now checks the agent page and deletes its probe agent. The graph spec shows the demo agents and checks the form of the counts.")
defect("Pages failed with 500 when many agent tabs were opened quickly", "AUTH-008", "High",
       "1. Open the seven tabs of several agents in quick succession.", "Every tab opens.",
       "Some tabs showed no heading. The server answered 500: the database connection pool timed out.",
       "The sign-in check held a database session for the whole request, so slow AI insight runs kept connections busy. It now uses a short session of its own.")
defect("The dependency graph showed hidden agents as unregistered Shadow AI", "AUTH-008", "Medium",
       "1. Archive an agent that another agent calls (or hide the demo agents when a real agent calls one). 2. Open Dependencies.",
       "The call is left out of the graph.", "The called agent appeared as 'Unregistered (Shadow AI)'.",
       "The graph now skips calls to agents the page does not show.")


def main() -> None:
    old = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                old[r["Test ID"]] = r
    keep = ["Manual Status", "Actual Result", "Failure Description", "Defect ID", "Tested By", "Test Date", "Build / Version"]
    for row in rows:
        prev = old.get(row[0])
        if prev and prev.get("Case Version") == row[19]:
            for k in keep:
                row[COLUMNS.index(k)] = prev.get(k, "") or row[COLUMNS.index(k)]
    for path, data in ((OUT, [COLUMNS] + rows), (FIELDS_OUT, FIELDS), (DEFECT_OUT, DEFECTS)):
        assert ";" not in "".join("".join(r) for r in data), f"a semicolon in {os.path.basename(path)}"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f, quoting=csv.QUOTE_ALL).writerows(data)
    print(f"cases: {len(rows)}, defects: {len(DEFECTS) - 1}")


if __name__ == "__main__":
    main()
