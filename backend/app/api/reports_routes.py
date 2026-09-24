from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User, UserPermission
from ..schemas.reports import (
    RapportLigneOut, RapportDirectionOut, RapportProduitOut, HistoriqueScanOut, ParetoArretsOut, TrsOut, SmedOut,
)
from ..services.reports_service import (
    rapport_par_ligne, rapport_vue_direction, rapport_par_produit, historique_scans,
)
from ..services.pertes_service import pareto_arrets
from ..services.trs_service import calculer_trs
from ..services.smed_service import changements_de_serie
from ..services import rapport_matinal_service as matinal
from ..core.settings import settings
from ..services.export_service import (
    generer_excel_pareto, generer_pdf_pareto, generer_csv_pareto,
    generer_excel_trs, generer_pdf_trs, generer_csv_trs,
    generer_excel_smed, generer_pdf_smed, generer_csv_smed,
    generer_excel_rapport, generer_pdf_rapport,
    generer_excel_historique_scans, generer_pdf_historique_scans, generer_csv_historique_scans,
)
from .auth_routes import require_permission, get_current_user, require_admin

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



# =============================================================
# *** AJOUT 2026-09-24 (Palier 0) *** : Pareto des causes d'arrêt + coût estimé.
# Même permission que le reste des Rapports (view_vue_usine). Un Chef d'équipe (compte
# avec section_scope) ne voit que les lignes de sa section, comme la Vue Usine.
# NB : les autres onglets de Rapports ne filtrent PAS encore par section_scope --
# écart préexistant, signalé mais volontairement non touché ici.
# =============================================================

def _periode_pareto(date_debut, date_fin):
    date_fin = date_fin or date.today()
    date_debut = date_debut or (date_fin - timedelta(days=7))
    if date_debut > date_fin:
        raise HTTPException(status_code=422, detail="date_debut doit précéder date_fin.")
    return date_debut, date_fin


@router.get("/pareto-arrets", response_model=ParetoArretsOut)
def get_pareto_arrets(
    date_debut: date = None,
    date_fin: date = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("view_vue_usine")),
):
    date_debut, date_fin = _periode_pareto(date_debut, date_fin)
    return pareto_arrets(db, date_debut, date_fin, ligne_id=ligne_id, section_scope=user.section_scope)


@router.get("/pareto-arrets/export")
def export_pareto_arrets(
    format: str,
    date_debut: date = None,
    date_fin: date = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("view_vue_usine")),
):
    if format not in ("xlsx", "pdf", "csv"):
        raise HTTPException(status_code=422, detail="format doit être 'xlsx', 'pdf' ou 'csv'.")
    date_debut, date_fin = _periode_pareto(date_debut, date_fin)
    pareto = pareto_arrets(db, date_debut, date_fin, ligne_id=ligne_id, section_scope=user.section_scope)

    if format == "csv":
        contenu, media_type = generer_csv_pareto(pareto), "text/csv"
    elif format == "xlsx":
        contenu = generer_excel_pareto(pareto)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenu, media_type = generer_pdf_pareto(pareto), "application/pdf"

    return Response(
        content=contenu, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="pareto_arrets_{date_debut}_{date_fin}.{format}"'},
    )


# =============================================================
# *** AJOUT 2026-09-24 (Palier 1) *** : TRS décomposé (disponibilité x performance x
# qualité). Même permission et même règle de périmètre (section_scope) que le Pareto.
# =============================================================

@router.get("/trs", response_model=TrsOut)
def get_trs(
    date_debut: date = None,
    date_fin: date = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("view_vue_usine")),
):
    date_debut, date_fin = _periode_pareto(date_debut, date_fin)
    return calculer_trs(db, date_debut, date_fin, ligne_id=ligne_id, section_scope=user.section_scope)


@router.get("/trs/export")
def export_trs(
    format: str,
    date_debut: date = None,
    date_fin: date = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("view_vue_usine")),
):
    if format not in ("xlsx", "pdf", "csv"):
        raise HTTPException(status_code=422, detail="format doit être 'xlsx', 'pdf' ou 'csv'.")
    date_debut, date_fin = _periode_pareto(date_debut, date_fin)
    trs = calculer_trs(db, date_debut, date_fin, ligne_id=ligne_id, section_scope=user.section_scope)
    if format == "csv":
        contenu, media_type = generer_csv_trs(trs), "text/csv"
    elif format == "xlsx":
        contenu = generer_excel_trs(trs)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenu, media_type = generer_pdf_trs(trs), "application/pdf"
    return Response(
        content=contenu, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="trs_{date_debut}_{date_fin}.{format}"'},
    )


# =============================================================
# *** AJOUT 2026-09-24 (Palier 1) *** : changements de série (SMED), depuis les horodatages
# de palettes -- aucune saisie nouvelle. Même permission et même périmètre que le Pareto.
# =============================================================

@router.get("/changements-serie", response_model=SmedOut)
def get_changements_serie(
    date_debut: date = None,
    date_fin: date = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("view_vue_usine")),
):
    date_debut, date_fin = _periode_pareto(date_debut, date_fin)
    return changements_de_serie(db, date_debut, date_fin, ligne_id=ligne_id, section_scope=user.section_scope)


@router.get("/changements-serie/export")
def export_changements_serie(
    format: str,
    date_debut: date = None,
    date_fin: date = None,
    ligne_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("view_vue_usine")),
):
    if format not in ("xlsx", "pdf", "csv"):
        raise HTTPException(status_code=422, detail="format doit être 'xlsx', 'pdf' ou 'csv'.")
    date_debut, date_fin = _periode_pareto(date_debut, date_fin)
    smed = changements_de_serie(db, date_debut, date_fin, ligne_id=ligne_id, section_scope=user.section_scope)
    if format == "csv":
        contenu, media_type = generer_csv_smed(smed), "text/csv"
    elif format == "xlsx":
        contenu = generer_excel_smed(smed)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenu, media_type = generer_pdf_smed(smed), "application/pdf"
    return Response(
        content=contenu, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="changements_serie_{date_debut}_{date_fin}.{format}"'},
    )


# =============================================================
# *** AJOUT 2026-09-24 (Palier 1) *** : rapport matinal. Réservé aux administrateurs : le
# rapport couvre toute l'usine (coûts en FCFA compris), sans le filtre section_scope.
# =============================================================

@router.get("/matinal/apercu")
def apercu_rapport_matinal(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Le rapport tel qu'il partirait maintenant, sans rien envoyer."""
    rapport = matinal.construire_rapport(db)
    dest = matinal.destinataires(db)
    base = {
        "nb_destinataires_email": len(dest["email"]), "nb_destinataires_telegram": len(dest["telegram"]),
        "envoi_automatique_actif": bool(settings.RAPPORT_MATINAL_ENABLED and settings.SNAPSHOT_SCHEDULER_ENABLED),
    }
    if rapport is None:
        return {**base, "disponible": False,
                "message": "Aucune performance figée dans les 7 derniers jours : le rapport n'a rien à dire."}
    return {**base, "disponible": True, "jour_rapport": rapport["jour_rapport"].isoformat(),
            "sujet": matinal.sujet(rapport), "html": matinal.rendre_html(rapport), "texte": matinal.rendre_texte(rapport)}


@router.post("/matinal/envoyer")
def envoyer_rapport_matinal_maintenant(
    mode: str = "test",
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """mode=test : envoi à VOTRE seule adresse, sans marquer la journée comme envoyée.
    mode=tous : envoi immédiat à tous les destinataires (hors règles de jour et d'heure),
    et la journée est marquée envoyée pour éviter un doublon automatique."""
    if mode not in ("test", "tous"):
        raise HTTPException(status_code=422, detail="mode doit être 'test' ou 'tous'.")
    if mode == "test":
        return matinal.envoyer_rapport_matinal(db, test_user=admin)
    return matinal.envoyer_rapport_matinal(db, force=True)
