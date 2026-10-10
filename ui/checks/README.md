# Browser checks

One script per phase of the improvement plan (Agent-Registry-Improvement-Plan-v2.md). Each signs in with a
saved token, works on probe records it creates (a probe agent, user, tool or search) and removes them at the end.
Users are only deactivated by the app, never deleted, so a probe user stays as an inactive row.

Before running:

1. Start the backend on port 8002 and the UI on port 5174 (see CLAUDE.md).
2. Make a work folder with a `shots/` folder in it, and save a sign-in token for the admin account as `<folder>/ar-token`:
   `curl -s -X POST localhost:8002/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"admin@airegistry.local","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" > <folder>/ar-token`

Run one phase from `ui/`: `node checks/phase3.mjs <folder>`

Run several in a row: `node checks/run.mjs <folder> phase1.mjs phase2.mjs phase3.mjs`. It waits 65 seconds between
them, because the API allows 1,000 requests a minute per person by default and the checks click faster than a person does.

Each prints PASS or FAIL per check and ends with ALL PASSED or SOME FAILED. Screenshots go to `<folder>/shots/`.
Phase 1 reads Phoenix (VPN) and GitHub.

Phases 0 and 1 expect the development data: 6 real agents, with the 12 demo agents hidden until ticked in Settings (10 more demo agents are
archived), and the agents Iso Mapper and Digital Onboarding Test. `demo_agents.mjs` opens every tab of every demo
agent and checks the archived ones stay out of the pages.

`executive_merge.mjs` checks the menu, the Executive page with the business impact section, clickable cards, the Business Value and Tokenomics month filter, and the Digital Onboarding Prod demo agent (seed it first with `backend/scripts/seed_happy_path.py`). `consistency.mjs` checks that each action has one place and each figure one rule (Governance, Edit window, Executive against Business Impact, Platform, Playground redirect, archive). `demo_agents.mjs` checks the demo and archived agents.
