from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Machine
from schemas import MachineCreate, MachineRead, MachineIssueUpdate
from deps import require_manager_or_admin, require_caposquadra_or_above

router = APIRouter(prefix="/machines", tags=["machines"])


@router.post("/", response_model=MachineRead)
def create_machine(
    machine_in: MachineCreate,
    db: Session = Depends(get_db),
    user=Depends(require_manager_or_admin),
):
    machine = Machine(
        name=machine_in.name,
        model=machine_in.model,
        type=machine_in.type,
        current_site_id=machine_in.current_site_id,
        notes=machine_in.notes,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine


@router.get("/", response_model=list[MachineRead])
def list_machines(
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    # prima quelli con problemi
    machines = (
        db.query(Machine)
        .order_by(Machine.has_issue.desc(), Machine.name.asc())
        .all()
    )
    return machines


@router.patch("/{machine_id}/issue", response_model=MachineRead)
def update_machine_issue(
    machine_id: int,
    issue: MachineIssueUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Macchinario non trovato")

    machine.issue_notes = issue.issue_notes
    machine.has_issue = issue.has_issue

    db.commit()
    db.refresh(machine)
    return machine