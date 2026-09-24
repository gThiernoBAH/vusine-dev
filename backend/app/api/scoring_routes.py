from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User
from ..models.production import SuiviIndividuelAcces
from ..schemas.scoring import AccesSuiviOut, EquipeScoringOut, SuiviIndividuelOut, SuiviPersonneOut
from ..services import scoring_service as svc
from ..services.snapshot_service import snapshoter_performance_du_jour
from .auth_routes import require_permission, require_admin

router = APIRouter(prefix="/scoring", tags=["scoring"])

# *** REFONDU 2026-09-24 (Palier 2) *** : les anciennes routes GET /scoring/personnel et
# /scoring/personnel/{id} (classement NOMINATIF de chaque CDI/CDD, avec rang et score par
# personne) sont SUPPRIMÉES. Les remplacent : le score d'équipe (par ligne, sans nom) et un
# suivi individuel de formation, sous permission distincte et journalisé. Cf. scoring_service.py.


def _periode(date_debut: Optional[date], date_fin: Optional[date]) -> tuple[date, date]:
    """Défaut : les 7 derniers jours terminés. Même règle de validation que le Pareto."""
    fin = date_fin or (date.today() - timedelta(days=1))
    debut = date_debut or (fin - timedelta(days=6))
    if debut > date.today() or fin < debut:
        raise HTTPException(status_code=422, detail="Période invalide : date_debut doit précéder date_fin.")
    if (fin - debut).days > 366:
        raise HTTPException(status_code=422, detail="Période limitée à 366 jours.")
    return debut, fin


@router.post("/snapshot/run-now")
def declencher_snapshot(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Filet de sécurité manuel tant que SNAPSHOT_SCHEDULER_ENABLED=False (défaut) --
    même principe que POST /api/alerts/run-now côté SIVOX. À utiliser en fin de
    journée/poste, cf. avertissement dans snapshot_service.py."""
    nb = snapshoter_performance_du_jour(db)
    return {"message": f"Snapshot effectué pour {nb} ligne(s)."}


@router.get("/equipes", response_model=EquipeScoringOut)
def get_scores_equipes(
    date_debut: Optional[date] = None, date_fin: Optional[date] = None, ligne_id: Optional[int] = None,
    db: Session = Depends(get_db), user: User = Depends(require_permission("view_scoring")),
):
    """Score PAR ÉQUIPE (ligne), arrêts non imputables neutralisés. Aucun nom de personne.
    Un compte avec section_scope ne voit que sa section."""
    d0, d1 = _periode(date_debut, date_fin)
    return svc.scoring_equipes(db, d0, d1, ligne_id=ligne_id, section_scope=user.section_scope)


@router.get("/suivi-individuel", response_model=list[SuiviPersonneOut])
def liste_suivi_individuel(
    db: Session = Depends(get_db), user: User = Depends(require_permission("view_suivi_individuel")),
):
    """Personnes dont on peut ouvrir le suivi : ordre alphabétique, AUCUNE valeur chiffrée
    (cette liste ne peut pas servir de classement)."""
    return svc.liste_personnes_suivi(db, user.section_scope)


@router.get("/suivi-individuel/acces", response_model=list[AccesSuiviOut])
def journal_acces_suivi(limit: int = 200, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Qui a consulté le suivi de qui, et quand -- réservé à l'administrateur."""
    rows = db.query(SuiviIndividuelAcces).order_by(SuiviIndividuelAcces.consulte_le.desc()).limit(min(max(limit, 1), 1000)).all()
    noms = {u.id: u.nom for u in db.query(User).filter(User.id.in_({r.consulte_par for r in rows} | {r.user_id for r in rows})).all()} if rows else {}
    return [AccesSuiviOut(id=r.id, consulte_le=r.consulte_le, consulte_par_nom=noms.get(r.consulte_par, "?"),
                          personne_nom=noms.get(r.user_id, "?"), periode_debut=r.periode_debut, periode_fin=r.periode_fin) for r in rows]


@router.get("/suivi-individuel/{user_id}", response_model=SuiviIndividuelOut)
def get_suivi_individuel(
    user_id: int, date_debut: Optional[date] = None, date_fin: Optional[date] = None,
    db: Session = Depends(get_db), user: User = Depends(require_permission("view_suivi_individuel")),
):
    d0, d1 = _periode(date_debut, date_fin)
    cible = db.query(User).filter(User.id == user_id).first()
    if not cible or not svc.personne_dans_perimetre(db, user_id, user.section_scope):
        # même réponse pour « n'existe pas » et « hors de votre périmètre » : on ne révèle rien
        raise HTTPException(status_code=404, detail="Personne introuvable dans votre périmètre.")
    # Journalisation AVANT la réponse : pas de consultation sans trace.
    db.add(SuiviIndividuelAcces(consulte_par=user.id, user_id=cible.id, periode_debut=d0, periode_fin=d1))
    db.commit()
    return svc.suivi_individuel(db, cible, d0, d1, section_scope=user.section_scope)
