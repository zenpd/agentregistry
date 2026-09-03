"""Orchestration API endpoints — workflow triggers."""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_update, require_read
from orchestrations.discovery_pipeline import run_discovery_pipeline
from orchestrations.governance_workflow import run_governance_workflow
from orchestrations.tokenomics_analysis import run_tokenomics_analysis
from orchestrations.waste_detection import run_waste_detection
from orchestrations.impact_analysis import run_impact_analysis

router = APIRouter()


@router.post("/orchestrations/discovery")
async def trigger_discovery(org_id: str = "org-default", _=Depends(require_update)):
    """Run the discovery pipeline to find unregistered agents."""
    try:
        return await run_discovery_pipeline(org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery pipeline failed: {str(e)}")


@router.post("/orchestrations/governance/{agent_id}")
async def trigger_governance(agent_id: str, org_id: str = "org-default", _=Depends(require_update)):
    """Run the governance review workflow for an agent."""
    try:
        return await run_governance_workflow(agent_id, org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Governance workflow failed: {str(e)}")


@router.post("/orchestrations/tokenomics/{agent_id}")
async def trigger_tokenomics(agent_id: str, model_name: str = "GPT-5", budget: float = 5000, _=Depends(require_read)):
    """Run tokenomics analysis for an agent."""
    try:
        return await run_tokenomics_analysis(agent_id, model_name, budget)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tokenomics analysis failed: {str(e)}")


@router.post("/orchestrations/waste-detection")
async def trigger_waste_detection(org_id: str = "org-default", _=Depends(require_update)):
    """Run waste detection across all agents."""
    try:
        return await run_waste_detection(org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Waste detection failed: {str(e)}")


@router.post("/orchestrations/impact/{node_id}")
async def trigger_impact(node_id: str, node_type: str = "agent", _=Depends(require_read)):
    """Run impact analysis for a target node."""
    try:
        return await run_impact_analysis(node_id, node_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impact analysis failed: {str(e)}")