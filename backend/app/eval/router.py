from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import CurrentUser, get_db, require_admin
from app.eval.ragas_runner import run_ragas

router = APIRouter()


@router.post("/ragas")
def eval_ragas(admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    scores = run_ragas(db, admin.tenant_id)
    return {"scores": scores}
