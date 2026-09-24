"""
labo_routes.py -- Écrans Labo (F1-F10, chantier SIVOX -> Vusine). Toutes les routes
sont protégées par require_labo (cf. auth_routes.py) au niveau du router entier --
jamais require_admin/require_permission, pour qu'un compte Direction (is_admin=True)
ne puisse jamais y accéder tant qu'une fonctionnalité n'a pas été explicitement
"graduée" vers l'usage courant (hors périmètre de ce chantier).

*** MODIFIÉ 2026-09-23 *** :
  - F1, F6, F7, F8 renvoient désormais ligne_code / produit_nom (jointures) en plus des
    identifiants : l'écran affichait les identifiants internes (ligne 86, produit 8699)
    au lieu des codes lisibles. Les identifiants restent présents (clés du bouton
    Analyser, filtres).
  - F7 au grain produit : plus de filtre ligne_id sur /prevision-volume.
  - Exports : paramètres horizon_jours / jours transmis (F2, F3) ; CSV ajouté à F5.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext

from ..core.database import get_db
from ..core import models
from ..models.production import (
    CapaciteLigneProduit, PlanOptimise, BesoinMatiereProjete, AlerteAchatProjete,
    SimulationProductible, EcartInventaireCache, PrevisionVolume, LigneProduitEligible,
    SyncState,
    # *** AJOUT (F6) ***
    AlerteEmballageLigne,
)
from ..services import labo_service, labo_export_service, export_service, labo_explication_service
from ..services.ingestors import (
    labo_eligibilite_ingestor, labo_predict_ingestor, labo_optimize_pp_ingestor,
    labo_matiere_ingestor, labo_simulation_ingestor, labo_ecritures_ingestor,
    # *** AJOUT (F6) ***
    labo_emballage_ingestor,
)
from .auth_routes import require_labo

router = APIRouter(prefix="/labo", tags=["labo"], dependencies=[Depends(require_labo)])


# =============================================================
# F1 -- Capacité démontrée
# =============================================================

@router.get("/capacite")
def get_capacite(ligne_id: int | None = None, produit_id: int | None = None, db: Session = Depends(get_db)):
    filtres, params = ["c.nb_jours_observes >= 5"], {}
    if ligne_id:
        filtres.append("c.ligne_id = :ligne_id"); params["ligne_id"] = ligne_id
    if produit_id:
        filtres.append("c.produit_id = :produit_id"); params["produit_id"] = produit_id
    return db.execute(sqltext(f"""
        SELECT c.id, c.ligne_id, l.code AS ligne_code, c.produit_id, p.default_code AS produit_code,
               p.nom AS produit_nom, c.nb_jours_observes, c.mediane_jour, c.p90_jour,
               c.dernier_jour_observe
        FROM labo_capacite_ligne_produit c
        LEFT JOIN lignes_cache l ON l.id = c.ligne_id
        LEFT JOIN produits_cache p ON p.id = c.produit_id
        WHERE {" AND ".join(filtres)}
        ORDER BY l.code, p.nom
    """), params).mappings().all()


@router.post("/capacite/recalculer")
def post_recalculer_capacite(db: Session = Depends(get_db)):
    """Filet de sécurité manuel, même principe que POST /scoring/snapshot/run-now."""
    resultats = labo_eligibilite_ingestor.run_eligibilite_cycle(db)
    return {"message": "Capacité et éligibilité recalculées.", **resultats}


# =============================================================
# F2 -- Planning réaliste ?
# =============================================================

@router.get("/planning-risque")
def get_planning_risque(horizon_jours: int = 14, db: Session = Depends(get_db)):
    return labo_service.evaluer_planning_risque(db, horizon_jours)


# =============================================================
# F3 -- Fiabilité de la saisie Odoo
# =============================================================

@router.get("/fiabilite-saisie")
def get_fiabilite_saisie(jours: int = 30, ligne_id: int | None = None, db: Session = Depends(get_db)):
    return labo_service.calculer_fiabilite_saisie(db, jours, ligne_id)


# =============================================================
# F7 -- Prévision de volume
# =============================================================

@router.get("/prevision-volume")
def get_prevision_volume(produit_id: int | None = None, db: Session = Depends(get_db)):
    filtre = "WHERE v.produit_id = :produit_id" if produit_id else ""
    return db.execute(sqltext(f"""
        SELECT v.id, v.produit_id, p.default_code AS produit_code, p.nom AS produit_nom,
               v.jour_horizon, v.qte_prevue, v.intervalle_bas, v.intervalle_haut
        FROM labo_prevision_volume v
        LEFT JOIN produits_cache p ON p.id = v.produit_id
        {filtre}
        ORDER BY v.jour_horizon, p.nom
    """), {"produit_id": produit_id} if produit_id else {}).mappings().all()


@router.post("/prevision-volume/recalculer")
def post_recalculer_prevision(db: Session = Depends(get_db)):
    return labo_predict_ingestor.run_predict_cycle(db)


# =============================================================
# F8 -- Plan de production optimisé
# =============================================================

@router.get("/plan-optimise")
def get_plan_optimise(db: Session = Depends(get_db)):
    return db.execute(sqltext("""
        SELECT o.id, o.ligne_id, l.code AS ligne_code, o.produit_id, p.default_code AS produit_code,
               p.nom AS produit_nom, o.jour, o.qte_recommandee, o.deficit_residuel
        FROM labo_plan_optimise o
        LEFT JOIN lignes_cache l ON l.id = o.ligne_id
        LEFT JOIN produits_cache p ON p.id = o.produit_id
        ORDER BY o.jour, l.code
    """)).mappings().all()


@router.get("/lignes-eligibles")
def get_lignes_eligibles(produit_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(LigneProduitEligible)
    if produit_id:
        q = q.filter(LigneProduitEligible.produit_id == produit_id)
    return q.all()


@router.post("/lignes-eligibles/manuel")
def ajouter_eligibilite_manuelle(ligne_id: int, produit_id: int, db: Session = Depends(get_db)):
    """Ajout manuel en admin, jamais retiré par le recalcul nocturne."""
    existe = db.query(LigneProduitEligible).filter(
        LigneProduitEligible.ligne_id == ligne_id, LigneProduitEligible.produit_id == produit_id).first()
    if existe:
        raise HTTPException(status_code=400, detail="Ce couple ligne/produit est déjà éligible.")
    db.add(LigneProduitEligible(ligne_id=ligne_id, produit_id=produit_id, source="manuel"))
    db.commit()
    return {"message": "Éligibilité ajoutée."}


@router.post("/plan-optimise/recalculer")
def post_recalculer_plan(horizon_jours: int = 14, db: Session = Depends(get_db)):
    return labo_optimize_pp_ingestor.run_optimize_cycle(db, horizon_jours)


# =============================================================
# F9a/F9b -- Besoins matières et alertes d'achat
# =============================================================

@router.get("/besoins-matieres")
def get_besoins_matieres(db: Session = Depends(get_db)):
    return db.query(BesoinMatiereProjete).order_by(BesoinMatiereProjete.date_rupture_projetee).all()


@router.get("/alertes-achat")
def get_alertes_achat(db: Session = Depends(get_db)):
    return db.query(AlerteAchatProjete).order_by(AlerteAchatProjete.date_limite_commande).all()


@router.post("/matieres/recalculer")
def post_recalculer_matieres(db: Session = Depends(get_db)):
    return labo_matiere_ingestor.run_matiere_cycle(db)


# =============================================================
# F10 / F10b -- Simulation productible et écarts d'inventaire
# =============================================================

@router.get("/simulation-productible")
def get_simulation_productible(db: Session = Depends(get_db)):
    return db.query(SimulationProductible).order_by(SimulationProductible.quantite_productible).all()


@router.post("/simulation-productible/recalculer")
def post_recalculer_simulation(db: Session = Depends(get_db)):
    return {"simulation_productible": labo_simulation_ingestor.recalculer_simulation_productible(db)}


@router.get("/ecarts-inventaire")
def get_ecarts_inventaire(produit_code: str | None = None, db: Session = Depends(get_db)):
    q = db.query(EcartInventaireCache)
    if produit_code:
        q = q.filter(EcartInventaireCache.produit_code == produit_code)
    return q.order_by(EcartInventaireCache.date_validation.desc()).all()


# =============================================================
# F5 -- Écritures proposées vers Odoo (export uniquement, pas d'écriture réelle)
# =============================================================

@router.get("/ecritures-proposees")
def get_ecritures_proposees(date_debut: date, date_fin: date, db: Session = Depends(get_db)):
    return labo_ecritures_ingestor.lister_ecritures_proposees(db, date_debut, date_fin)


@router.get("/comparaison-odoo")
def get_comparaison_odoo(date_debut: date, date_fin: date, db: Session = Depends(get_db)):
    return labo_ecritures_ingestor.lister_comparaison_odoo(db, date_debut, date_fin)


@router.post("/ecritures-proposees/recalculer")
def post_recalculer_ecritures(db: Session = Depends(get_db)):
    return labo_ecritures_ingestor.run_ecritures_cycle(db)


def _csv(rows) -> bytes:
    """CSV ';' (ouverture directe dans Excel en paramètres français), colonnes telles
    que renvoyées par la requête d'écran."""
    import csv, io
    buf = io.StringIO()
    lignes = [dict(r) for r in rows]
    if lignes:
        writer = csv.DictWriter(buf, fieldnames=list(lignes[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(lignes)
    return buf.getvalue().encode("utf-8-sig")


@router.get("/ecritures-proposees/export")
def export_ecritures_proposees(format: str, date_debut: date, date_fin: date, db: Session = Depends(get_db)):
    if format not in ("xlsx", "pdf", "csv"):
        raise HTTPException(status_code=422, detail="Format attendu : xlsx, pdf ou csv.")
    rows = labo_ecritures_ingestor.lister_ecritures_proposees(db, date_debut, date_fin)
    if format == "csv":
        contenu = _csv(rows)
        media = "text/csv"
    elif format == "xlsx":
        contenu = export_service.generer_excel_ecritures_proposees(rows, date_debut, date_fin)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenu = export_service.generer_pdf_ecritures_proposees(rows, date_debut, date_fin)
        media = "application/pdf"
    return Response(content=contenu, media_type=media,
                     headers={"Content-Disposition": f'attachment; filename="ecritures_proposees.{format}"'})


@router.get("/comparaison-odoo/export")
def export_comparaison_odoo(format: str, date_debut: date, date_fin: date, db: Session = Depends(get_db)):
    if format not in ("xlsx", "pdf", "csv"):
        raise HTTPException(status_code=422, detail="Format attendu : xlsx, pdf ou csv.")
    rows = labo_ecritures_ingestor.lister_comparaison_odoo(db, date_debut, date_fin)
    if format == "csv":
        contenu = _csv(rows)
        media = "text/csv"
    elif format == "xlsx":
        contenu = export_service.generer_excel_comparaison_odoo(rows, date_debut, date_fin)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenu = export_service.generer_pdf_comparaison_odoo(rows, date_debut, date_fin)
        media = "application/pdf"
    return Response(content=contenu, media_type=media,
                     headers={"Content-Disposition": f'attachment; filename="comparaison_odoo.{format}"'})


# =============================================================
# Export générique (tous les écrans sauf F5 -- cf. labo_export_service.py)
# =============================================================

@router.get("/export/{domaine}")
def export_domaine(domaine: str, format: str = "xlsx", horizon_jours: int = 14, jours: int = 30,
                    db: Session = Depends(get_db)):
    """horizon_jours (F2) et jours (F3) : mêmes paramètres qu'à l'écran, pour que
    l'export corresponde exactement à ce qui est affiché. Ignorés par les autres domaines."""
    if format not in ("csv", "xlsx", "pdf"):
        raise HTTPException(status_code=422, detail="Format attendu : csv, xlsx ou pdf.")
    try:
        contenu, nom_fichier, media_type = labo_export_service.exporter(
            db, domaine, format, {"horizon_jours": horizon_jours, "jours": jours})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=contenu, media_type=media_type,
                     headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'})


# =============================================================
# F6 -- Alertes emballage priorisées par l'historique des arrêts
# =============================================================

@router.get("/alertes-emballage")
def get_alertes_emballage(db: Session = Depends(get_db)):
    return db.execute(sqltext("""
        SELECT a.id, a.ligne_id, l.code AS ligne_code, a.matiere_code,
               a.nb_arrets_manque_historique, a.date_limite_commande, a.priorite
        FROM labo_alertes_emballage_ligne a
        LEFT JOIN lignes_cache l ON l.id = a.ligne_id
        ORDER BY a.priorite ASC, a.date_limite_commande
    """)).mappings().all()


@router.post("/alertes-emballage/recalculer")
def post_recalculer_emballage(db: Session = Depends(get_db)):
    return {"alertes_emballage": labo_emballage_ingestor.recalculer_alertes_emballage(db)}


# =============================================================
# F4 -- Explication à la demande (LLM sur chiffres déjà calculés)
# =============================================================

class ExplicationRequest(BaseModel):
    domaine: str  # 'capacite' | 'fiabilite_saisie' | 'alertes_achat'
    cle: dict
    # *** AJOUT 2026-09-23 *** : force une nouvelle analyse même si les chiffres n'ont
    # pas changé (bouton "Régénérer" côté écran) -- sinon la mémoire serveur répond
    # sans appeler OpenRouter, cf. labo_explication_service.expliquer.
    regenerer: bool = False


@router.post("/expliquer")
def post_expliquer(payload: ExplicationRequest, db: Session = Depends(get_db)):
    """*** MODIFIÉ 2026-09-23 *** : renvoie une structure (synthese/points_attention/
    action/chiffres_cles/depuis_cache), plus un texte libre -- cf. labo_explication_service."""
    try:
        resultat = labo_explication_service.expliquer(db, payload.domaine, payload.cle, payload.regenerer)
    except labo_explication_service.ExplicationIndisponible as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return resultat


# =============================================================
# Fraîcheur de la synchro (affiché dans le Labo, utile aussi pour l'admin)
# =============================================================

@router.get("/sync-state")
def get_sync_state(db: Session = Depends(get_db)):
    return db.query(SyncState).order_by(SyncState.domaine).all()
