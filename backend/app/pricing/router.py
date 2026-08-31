from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.pricing.schemas import PricingProfileUpsert, PricingSimulationRequest
from app.pricing.service import get_default_profile, serialize_profile, simulate, upsert_default_profile

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


@router.get("/profile")
def profile(channel: str = Query(default="MERCADOLIBRE"), db: Session = Depends(get_db)):
    current = get_default_profile(db, channel.strip().upper())
    return {"configured": current is not None, "profile": serialize_profile(current) if current else None}


@router.put("/profile")
def save_profile(payload: PricingProfileUpsert, db: Session = Depends(get_db)):
    return serialize_profile(upsert_default_profile(db, payload))


@router.post("/simulate")
def pricing_simulation(payload: PricingSimulationRequest, db: Session = Depends(get_db)):
    try:
        return simulate(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
