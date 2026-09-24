from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User
from ..models.production import (
    LigneCache, ProduitCache, Equipement, AffectationEquipementLigne,
    AffectationLigne, CauseArret,
)
from ..schemas.entities import (
    LigneOut, EquipementOut, CauseArretOut, PersonnelLigneOut,
    PlanningItemOut, LigneDetailOut,
)
from .auth_routes import get_current_user, require_permission
from ..services.ligne_helpers import get_planning_du_jour

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("/causes-arret", response_model=list[CauseArretOut])
def list_causes_arret(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Référentiel affiché dans le menu déroulant "Déclarer un arrêt" côté tablette --
    seule source de vérité (cf. schema.sql), jamais recopié en dur côté frontend."""
    return (
        db.query(CauseArret)
        .filter(CauseArret.actif.is_(True))
        .order_by(CauseArret.ordre_affichage)
        .all()
    )


@router.get("/lignes/mes-lignes", response_model=list[LigneOut])
def get_mes_lignes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Lignes actuellement affectées à l'opérateur connecté (écran 2 des maquettes
    tablette, "Mes lignes"). Affectation active = date_fin IS NULL."""
    lignes = (
        db.query(LigneCache)
        .join(AffectationLigne, AffectationLigne.ligne_id == LigneCache.id)
        .filter(AffectationLigne.user_id == current_user.id, AffectationLigne.date_fin.is_(None))
        .all()
    )
    return lignes


@router.get("/lignes", response_model=list[LigneOut])
def list_lignes(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_vue_usine")),
):
    """Liste complète des lignes actives -- cockpit direction uniquement (contrairement à
    /lignes/mes-lignes, réservé au personnel terrain sur ses propres affectations)."""
    return db.query(LigneCache).filter(LigneCache.actif.is_(True)).order_by(LigneCache.code).all()


@router.get("/lignes/{ligne_id}", response_model=LigneDetailOut)
def get_ligne_detail(
    ligne_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fiche détail d'une ligne : items du planning du jour (0/1/plusieurs produits),
    équipements actuellement affectés, personnel actuellement affecté (écran 4 des
    maquettes cockpit).

    *** REVU 2026-09-17 *** : remplace l'ancien "OF en cours" (of_cache, jamais
    réellement "en cours" chez SIVOP) par les items du planning hebdomadaire réel
    (planning_detail_cache, cf. ligne_helpers.get_planning_du_jour). Peut en renvoyer
    plusieurs -- l'opérateur choisit côté tablette s'il y en a plus d'un."""
    ligne = db.query(LigneCache).filter(LigneCache.id == ligne_id).first()
    if not ligne:
        raise HTTPException(status_code=404, detail="Ligne introuvable.")

    items = get_planning_du_jour(db, ligne_id)
    items_out = []
    for item in items:
        produit = (
            db.query(ProduitCache).filter(ProduitCache.id == item.produit_id).first()
            if item.produit_id else None
        )
        planning = item.planning  # relationship -- déjà chargé via la jointure de get_planning_du_jour
        items_out.append(PlanningItemOut(
            id=item.id,
            produit_id=item.produit_id,
            produit_nom=produit.nom if produit else None,
            qty_jour=float(item.qty) if item.qty is not None else None,
            reference_planning=planning.reference if planning else None,
            colisage_par_carton=produit.colisage_par_carton if produit else None,
            cartons_par_palette=produit.cartons_par_palette if produit else None,
        ))

    equipements = (
        db.query(Equipement)
        .join(AffectationEquipementLigne, AffectationEquipementLigne.equipement_id == Equipement.id)
        .filter(
            AffectationEquipementLigne.ligne_id == ligne_id,
            AffectationEquipementLigne.date_fin.is_(None),
        )
        .all()
    )

    personnel_rows = (
        db.query(User, AffectationLigne)
        .join(AffectationLigne, AffectationLigne.user_id == User.id)
        .filter(AffectationLigne.ligne_id == ligne_id, AffectationLigne.date_fin.is_(None))
        .all()
    )
    # CORRIGÉ 2026-09-24 (Palier 2, « rien de nominatif à l'écran d'atelier ») : cette liste
    # (noms, matricules, CDI/CDD des collègues) était renvoyée à TOUT compte connecté, opérateurs
    # compris -- la tablette ne l'affiche pas, mais la donnée circulait. Réservée aux comptes
    # direction (l'écran détail de ligne du cockpit).
    personnel = [
        PersonnelLigneOut(
            user_id=u.id, nom=u.nom, matricule=u.matricule,
            user_type=u.user_type, categorie_personnel=u.categorie_personnel,
        )
        for u, _affectation in personnel_rows
    ] if current_user.user_type == "direction" else []

    return LigneDetailOut(
        ligne=LigneOut.model_validate(ligne),
        items_planning_jour=items_out,
        equipements=[EquipementOut.model_validate(e) for e in equipements],
        personnel=personnel,
    )


@router.get("/lignes/{ligne_id}/equipements", response_model=list[EquipementOut])
def get_ligne_equipements(
    ligne_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Equipement)
        .join(AffectationEquipementLigne, AffectationEquipementLigne.equipement_id == Equipement.id)
        .filter(
            AffectationEquipementLigne.ligne_id == ligne_id,
            AffectationEquipementLigne.date_fin.is_(None),
        )
        .all()
    )