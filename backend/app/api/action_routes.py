from datetime import datetime, date, timedelta
from typing import Optional
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..core.database import get_db
from ..core.models import User
from ..models.production import (
    LigneCache, ProduitCache, Palette, Arret, CauseArret, PlanningDetailCache, PaletteCorrection,
)
from ..schemas.actions import PaletteCreate, PaletteUpdate, PaletteOut, ArretCreate, ArretOut
from .auth_routes import get_current_user, require_permission

router = APIRouter(prefix="/actions", tags=["actions"])


# =============================================================
# PALETTES
# =============================================================

def _generer_numero_palette(db: Session, ligne: LigneCache) -> str:
    """Format PAL-{code_ligne}-{YYYYMMDD}-{seq du jour, 4 chiffres}, cf. maquettes
    (ex: "PAL-L12-20260907-0008"). La séquence repart à 1 chaque jour, par ligne."""
    aujourd_hui = date.today()
    debut_jour = datetime.combine(aujourd_hui, datetime.min.time())
    nb_deja_creees = (
        db.query(func.count(Palette.id))
        .filter(Palette.ligne_id == ligne.id, Palette.created_at >= debut_jour)
        .scalar()
    )
    seq = nb_deja_creees + 1
    return f"PAL-{ligne.code}-{aujourd_hui.strftime('%Y%m%d')}-{seq:04d}"


@router.post("/palettes", response_model=PaletteOut, status_code=201)
def valider_palette(
    payload: PaletteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ligne = db.query(LigneCache).filter(LigneCache.id == payload.ligne_id).first()
    if not ligne:
        raise HTTPException(status_code=404, detail="Ligne introuvable.")

    # *** REVU 2026-09-17 *** : date d'expiration calculée depuis produits_cache via le
    # produit de l'item de planning choisi -- plus depuis of_cache (of_id supprimé du
    # flux normal, cf. schemas/actions.py). planning_detail_id reste optionnel (saisie
    # manuelle possible si aucun item de planning n'existe pour la ligne ce jour-là).
    date_expiration = None
    if payload.planning_detail_id:
        item = db.query(PlanningDetailCache).filter(PlanningDetailCache.id == payload.planning_detail_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item de planning introuvable.")
        if item.produit_id:
            produit = db.query(ProduitCache).filter(ProduitCache.id == item.produit_id).first()
            if produit and produit.duree_vie_mois:
                date_expiration = date.today() + relativedelta(months=produit.duree_vie_mois)

    numero_palette = _generer_numero_palette(db, ligne)
    quantite_totale = payload.nb_cartons * payload.colisage_carton

    palette = Palette(
        numero_palette=numero_palette,
        ligne_id=payload.ligne_id,
        planning_detail_id=payload.planning_detail_id,
        numero_lot=payload.numero_lot,
        date_expiration=date_expiration,
        nb_cartons=payload.nb_cartons,
        colisage_carton=payload.colisage_carton,
        quantite_totale=quantite_totale,
        complete=payload.complete,
        motif_partielle=payload.motif_partielle,
        nb_rebuts=payload.nb_rebuts,
        operateur_id=current_user.id,
    )
    db.add(palette)
    try:
        db.commit()
        db.refresh(palette)
    except Exception:
        db.rollback()
        # Cas quasi impossible en pratique (2 validations à la même seconde exacte sur la
        # même ligne, collision sur numero_palette) -- géré proprement plutôt qu'un 500
        # brut, mais pas besoin de logique de retry pour un cas aussi rare.
        raise HTTPException(status_code=409, detail="Conflit lors de la génération du numéro de palette, réessayer.")

    return palette


@router.get("/palettes/recentes", response_model=list[PaletteOut])
def palettes_recentes(
    ligne_id: int,
    limit: int = 5,
    jour: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Panneau "Palettes récentes" des maquettes cockpit/tablette. *** ÉTENDU
    2026-09-18 *** : jour optionnel -- sans lui, comportement inchangé (les N dernières
    palettes tous jours confondus, pour l'écran tablette qui n'a jamais besoin d'un
    autre jour que maintenant). Avec jour renseigné (écran cockpit + filtre par date),
    limite aux palettes de CE jour précis -- sinon consulter "hier" afficherait quand
    même les palettes d'aujourd'hui en tête de liste, ce qui n'aurait aucun sens."""
    query = db.query(Palette).filter(Palette.ligne_id == ligne_id)
    if jour is not None:
        debut_jour = datetime.combine(jour, datetime.min.time())
        fin_jour = debut_jour + timedelta(days=1)
        query = query.filter(Palette.created_at >= debut_jour, Palette.created_at < fin_jour)
    return query.order_by(Palette.created_at.desc()).limit(limit).all()


@router.patch("/palettes/{palette_id}", response_model=PaletteOut)
def corriger_palette(
    palette_id: int,
    payload: PaletteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("correction_palette")),
):
    """*** NOUVEAU 2026-09-17 *** : n'existait pas -- le bouton "Corriger" de
    LigneDetailView.vue appelait déjà cette route, mais elle n'était jamais définie.
    Chaque champ modifié est journalisé dans palettes_corrections (slide 18 du CDC,
    "journal d'audit"), avec l'ancienne et la nouvelle valeur -- jamais un simple UPDATE
    silencieux, une correction de palette doit rester traçable."""
    palette = db.query(Palette).filter(Palette.id == palette_id).first()
    if not palette:
        raise HTTPException(status_code=404, detail="Palette introuvable.")

    donnees = payload.dict(exclude_unset=True, exclude={"motif"})
    if not donnees:
        raise HTTPException(status_code=422, detail="Aucun champ à corriger fourni.")

    for champ, nouvelle_valeur in donnees.items():
        ancienne_valeur = getattr(palette, champ)
        if str(ancienne_valeur) == str(nouvelle_valeur):
            continue  # pas de changement réel -- pas de ligne d'audit inutile
        db.add(PaletteCorrection(
            palette_id=palette.id, corrige_par=current_user.id, champ_modifie=champ,
            ancienne_valeur=str(ancienne_valeur), nouvelle_valeur=str(nouvelle_valeur),
            motif=payload.motif,
        ))
        setattr(palette, champ, nouvelle_valeur)

    # Recalcul de la quantité totale si cartons/colisage ont changé.
    if "nb_cartons" in donnees or "colisage_carton" in donnees:
        palette.quantite_totale = palette.nb_cartons * palette.colisage_carton

    db.commit()
    db.refresh(palette)
    return palette


# =============================================================
# ARRÊTS
# =============================================================

def _arret_out(arret: Arret) -> ArretOut:
    out = ArretOut.model_validate(arret)
    out.cause_libelle = arret.cause.libelle if arret.cause else None
    return out


@router.get("/arrets/en-cours", response_model=Optional[ArretOut])
def arret_en_cours(
    ligne_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Utilisé par la tablette pour savoir, à l'ouverture de l'écran ligne, si un arrêt
    est déjà en cours (affichage du chrono "Arrêt en cours", écran 9 des maquettes)."""
    arret = (
        db.query(Arret)
        .filter(Arret.ligne_id == ligne_id, Arret.heure_fin.is_(None))
        .order_by(Arret.heure_debut.desc())
        .first()
    )
    return _arret_out(arret) if arret else None


@router.post("/arrets/demarrer", response_model=ArretOut, status_code=201)
def demarrer_arret(
    payload: ArretCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ligne = db.query(LigneCache).filter(LigneCache.id == payload.ligne_id).first()
    if not ligne:
        raise HTTPException(status_code=404, detail="Ligne introuvable.")
    cause = db.query(CauseArret).filter(CauseArret.id == payload.cause_id).first()
    if not cause:
        raise HTTPException(status_code=404, detail="Cause d'arrêt introuvable.")

    deja_en_cours = (
        db.query(Arret)
        .filter(Arret.ligne_id == payload.ligne_id, Arret.heure_fin.is_(None))
        .first()
    )
    if deja_en_cours:
        raise HTTPException(status_code=409, detail="Un arrêt est déjà en cours sur cette ligne.")

    arret = Arret(
        ligne_id=payload.ligne_id,
        cause_id=payload.cause_id,
        equipement_id=payload.equipement_id,
        commentaire=payload.commentaire,
        heure_debut=datetime.now(),
        operateur_id=current_user.id,
    )
    db.add(arret)
    db.commit()
    db.refresh(arret)
    return _arret_out(arret)


@router.post("/arrets/{arret_id}/terminer", response_model=ArretOut)
def terminer_arret(
    arret_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    arret = db.query(Arret).filter(Arret.id == arret_id).first()
    if not arret:
        raise HTTPException(status_code=404, detail="Arrêt introuvable.")
    if arret.heure_fin is not None:
        raise HTTPException(status_code=409, detail="Cet arrêt est déjà terminé.")

    arret.heure_fin = datetime.now()
    db.commit()
    db.refresh(arret)
    return _arret_out(arret)