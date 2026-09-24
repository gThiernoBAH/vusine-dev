from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User, UserPermission
from ..schemas.reports import RapportLigneOut, RapportDirectionOut, RapportProduitOut, HistoriqueScanOut
from ..services.reports_service import (
    rapport_par_ligne, rapport_vue_direction, rapport_par_produit, historique_scans,
)
from ..services.export_service import (
    generer_excel_rapport, generer_pdf_rapport,
    generer_excel_historique_scans, generer_pdf_historique_scans, generer_csv_historique_scans,
)
from .auth_routes import require_permission, get_current_user

router = APIRouter(prefix="/rapports", tags=["rapports"])


def _voit_tous_les_operateurs(db: Session, user: User) -> bool:
    """Même règle que require_permission("view_vue_usine") (is_admin ou permission
    explicite), réécrite ici en fonction plutôt qu'en dépendance FastAPI : la route
    historique-scans doit rester accessible à TOUT compte connecté (y compris
    Opérateur/Ouvrier, qui n'a jamais cette permission), simplement avec un
    périmètre différent selon le profil -- cf. get_historique_scans ci-dessous."""
    if getattr(user, "is_admin", False):
        return True
    return db.query(UserPermission).filter(
        UserPermission.user_id == user.id, UserPermission.permission_key == "view_vue_usine"
    ).first() is not None


@router.get("/par-ligne", response_model=list[RapportLigneOut])
def get_rapport_par_ligne(
    date_debut: date = None,
    date_fin: date = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_vue_usine")),
):
    date_fin = date_fin or date.today()
    date_debut = date_debut or (date_fin - timedelta(days=7))
    return rapport_par_ligne(db, date_debut, date_fin)


@router.get("/par-ligne/export")
def export_rapport_par_ligne(
    format: str,
    date_debut: date = None,
    date_fin: date = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_vue_usine")),
):
    """Export Excel/PDF du rapport par ligne (slide 14 -- dernier point de l'audit)."""
    if format not in ("xlsx", "pdf"):
        raise HTTPException(status_code=422, detail="format doit être 'xlsx' ou 'pdf'.")

    date_fin = date_fin or date.today()
    date_debut = date_debut or (date_fin - timedelta(days=7))
    rows = rapport_par_ligne(db, date_debut, date_fin)
    # *** CORRECTIF 2026-09-17 *** : export_service.py attend des dicts indexables
    # (r['code'], r['nom'], ...) -- rapport_par_ligne renvoie des objets Pydantic
    # (RapportLigneOut), non subscriptables tels quels. D'où le
    # "TypeError: 'RapportLigneOut' object is not subscriptable" à l'export.
    rows_dict = [r.model_dump() for r in rows]

    if format == "xlsx":
        contenu = generer_excel_rapport(rows_dict, date_debut, date_fin)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        nom_fichier = f"rapport_vusine_{date_debut}_{date_fin}.xlsx"
    else:
        contenu = generer_pdf_rapport(rows_dict, date_debut, date_fin)
        media_type = "application/pdf"
        nom_fichier = f"rapport_vusine_{date_debut}_{date_fin}.pdf"

    return Response(
        content=contenu,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@router.get("/par-produit", response_model=list[RapportProduitOut])
def get_rapport_par_produit(
    date_debut: date = None,
    date_fin: date = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_vue_usine")),
):
    """*** NOUVEAU 2026-09-18 *** : écran Rapports, onglet 'Par produit' (slide 14)."""
    date_fin = date_fin or date.today()
    date_debut = date_debut or (date_fin - timedelta(days=7))
    return rapport_par_produit(db, date_debut, date_fin)


@router.get("/vue-direction", response_model=RapportDirectionOut)
def get_rapport_vue_direction(
    date_debut: date = None,
    date_fin: date = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_vue_usine")),
):
    date_fin = date_fin or date.today()
    date_debut = date_debut or (date_fin - timedelta(days=7))
    return rapport_vue_direction(db, date_debut, date_fin)

# =============================================================
# *** AJOUT 2026-09-23 *** : historique des scans (palettes) -- écran Rapports côté
# Direction (tous les opérateurs) ET écran tablette "Mon historique" côté opérateur/
# ouvrier (restreint à ses propres scans). PAS de require_permission ici : un compte
# Opérateur/Ouvrier n'a jamais aucune UserPermission (cf. models.UserPermission), la
# route lui resterait sinon fermée pour toujours -- l'accès est ouvert à tout compte
# connecté, le PÉRIMÈTRE (tous les opérateurs, ou seulement soi-même) est déterminé
# ici, jamais laissé au choix de l'appelant.
# =============================================================

@router.get("/historique-scans", response_model=list[HistoriqueScanOut])
def get_historique_scans(
    date_debut: date = None,
    date_fin: date = None,
    operateur_id: int | None = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    date_fin = date_fin or date.today()
    date_debut = date_debut or (date_fin - timedelta(days=7))
    if not _voit_tous_les_operateurs(db, user):
        # Opérateur/Ouvrier : le paramètre operateur_id demandé, s'il y en avait un,
        # est silencieusement ignoré -- jamais une erreur 403, juste ses propres scans.
        operateur_id = user.id
    return historique_scans(db, date_debut, date_fin, operateur_id, ligne_id)


@router.get("/historique-scans/export")
def export_historique_scans(
    format: str,
    date_debut: date = None,
    date_fin: date = None,
    operateur_id: int | None = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if format not in ("xlsx", "pdf", "csv"):
        raise HTTPException(status_code=422, detail="format doit être 'xlsx', 'pdf' ou 'csv'.")
    date_fin = date_fin or date.today()
    date_debut = date_debut or (date_fin - timedelta(days=7))
    if not _voit_tous_les_operateurs(db, user):
        operateur_id = user.id
    rows = historique_scans(db, date_debut, date_fin, operateur_id, ligne_id)

    if format == "csv":
        contenu = generer_csv_historique_scans(rows, date_debut, date_fin)
        media_type = "text/csv"
    elif format == "xlsx":
        contenu = generer_excel_historique_scans(rows, date_debut, date_fin)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenu = generer_pdf_historique_scans(rows, date_debut, date_fin)
        media_type = "application/pdf"

    return Response(
        content=contenu, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="historique_scans_{date_debut}_{date_fin}.{format}"'},
    )
