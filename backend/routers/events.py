"""Authentication event history and live buffers."""

from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, delete, select

from backend.database import get_session
from backend.db_models import AuthEvent
from backend.hub import hub

router = APIRouter(prefix="/api/events", tags=["Events"])


@router.get("", response_model=List[AuthEvent])
def list_events(limit: int = 200, verdict: Optional[str] = None, session: Session = Depends(get_session)):
    q = select(AuthEvent).order_by(AuthEvent.timestamp.desc()).limit(min(limit, 2000))
    if verdict:
        q = q.where(AuthEvent.verdict == verdict)
    return session.exec(q).all()


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    rows = session.exec(select(AuthEvent)).all()
    return {"total": len(rows), "by_verdict": Counter(r.verdict for r in rows),
            "by_device": Counter(r.claimed_device_id or "-" for r in rows),
            "by_source": Counter(r.source for r in rows)}


@router.delete("", status_code=204)
def clear(session: Session = Depends(get_session)):
    session.exec(delete(AuthEvent))
    session.commit()
    hub.verdicts.clear()


@router.get("/live")
def live():
    """Recent frames/decisions held in memory (for page reloads)."""
    return {"frames": list(hub.recent_frames)[-60:], "decisions": list(hub.recent_decisions)}
