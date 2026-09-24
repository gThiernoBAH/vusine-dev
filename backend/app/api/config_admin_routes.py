from datetime import datetime, date as date_type, time as time_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User
from ..models.production import (
    Equipement, AffectationEquipementLigne, AffectationLigne, LigneCache, CauseArret,
    ConfigurationPoste, JourSpecial, ProduitCache,
)
from ..schemas.admin import (
    EquipementCreate, EquipementUpdate, EquipementAdminOut,
    AffectationEquipementCreate, AffectationPersonnelCreate, AffectationOut,
    CauseArretCreate, CauseArretUpdate, CauseArretAdminOut,
)
from ..schemas.entities import CauseArretOut
from .auth_routes import require_permission

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================
# LIGNES -- interrupteur actif géré ici, cf. schema.sql
# =============================================================

# *** CORRECTIF 2026-09-17 *** : list_all_lignes/toggle_ligne_actif utilisaient
# schemas.entities.LigneOut (le schéma PUBLIC, pensé pour GET /entities/lignes qui ne
# liste QUE les lignes actives) -- ce schéma n'expose pas `actif`. Résultat : le front
# admin recevait toujours `actif: undefined`, donc `!ligne.actif` valait toujours
# `true` -- chaque clic renvoyait actif=true en boucle, jamais false, et l'affichage
# restait bloqué sur "Masquée" quel que soit l'état réel en base (le toggle
# fonctionnait bien côté backend, juste invisible côté front). D'où ce schéma dédié.
class LigneAdminOut(BaseModel):
    id: int
    code: str
    nom: str
    section_id: Optional[int] = None
    section_code: Optional[str] = None
    section_nom: Optional[str] = None
    actif: bool

    class Config:
        from_attributes = True


@router.get("/lignes", response_model=list[LigneAdminOut])
def list_all_lignes(db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    """Toutes les lignes, actives ou non -- contrairement à GET /entities/lignes qui ne
    montre que les actives. Sert l'écran d'administration pour décider lesquelles
    masquer et renseigner leur section."""
    return db.query(LigneCache).order_by(LigneCache.code).all()


@router.patch("/lignes/{ligne_id}/actif", response_model=LigneAdminOut)
def toggle_ligne_actif(ligne_id: int, actif: bool, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    ligne = db.query(LigneCache).filter(LigneCache.id == ligne_id).first()
    if not ligne:
        raise HTTPException(status_code=404, detail="Ligne introuvable.")
    ligne.actif = actif
    db.commit()
    db.refresh(ligne)
    return ligne


class LignesActifEnMasseUpdate(BaseModel):
    ligne_ids: list[int]
    actif: bool


@router.patch("/lignes/actif-en-masse")
def toggle_lignes_actif_en_masse(payload: LignesActifEnMasseUpdate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    """Bascule actif pour plusieurs lignes d'un coup (ex: 'Tout masquer' sur un
    sous-ensemble filtré côté admin) -- évite N requêtes individuelles pour 88 lignes."""
    if not payload.ligne_ids:
        raise HTTPException(status_code=422, detail="ligne_ids ne peut pas être vide.")
    db.query(LigneCache).filter(LigneCache.id.in_(payload.ligne_ids)).update(
        {"actif": payload.actif}, synchronize_session=False
    )
    db.commit()
    return {"mis_a_jour": len(payload.ligne_ids), "actif": payload.actif}
# *** RETIRÉ 2026-09-18 *** : update_ligne_section (PATCH /admin/lignes/{id}/section)
# supprimée -- section_nom/section_code sont désormais synchronisés depuis Odoo
# (sections_cache, cf. odoo_sync_service.sync_lignes), plus de saisie manuelle possible.
# Cette fonction n'avait de toute façon jamais de décorateur @router -- jamais
# réellement enregistrée comme route (bug pré-existant, confirmé 2026-09-18).


def _equipement_admin_out(db: Session, eq: Equipement) -> EquipementAdminOut:
    affectation_active = (
        db.query(AffectationEquipementLigne)
        .filter(AffectationEquipementLigne.equipement_id == eq.id, AffectationEquipementLigne.date_fin.is_(None))
        .first()
    )
    ligne_code = None
    if affectation_active:
        ligne = db.query(LigneCache).filter(LigneCache.id == affectation_active.ligne_id).first()
        ligne_code = ligne.code if ligne else None
    out = EquipementAdminOut.model_validate(eq)
    out.ligne_actuelle_code = ligne_code
    return out


# =============================================================
# ÉQUIPEMENTS
# =============================================================

@router.get("/equipements", response_model=list[EquipementAdminOut])
def list_equipements(db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    """Tous les équipements, y compris ceux actuellement non affectés à une ligne
    (contrairement à GET /entities/lignes/{id}/equipements, qui ne montre que les
    équipements actifs sur UNE ligne précise)."""
    equipements = db.query(Equipement).order_by(Equipement.type).all()
    return [_equipement_admin_out(db, e) for e in equipements]


@router.post("/equipements", response_model=EquipementAdminOut, status_code=201)
def create_equipement(payload: EquipementCreate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    eq = Equipement(**payload.dict())
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return _equipement_admin_out(db, eq)


@router.patch("/equipements/{equipement_id}", response_model=EquipementAdminOut)
def update_equipement(equipement_id: int, payload: EquipementUpdate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    eq = db.query(Equipement).filter(Equipement.id == equipement_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Équipement introuvable.")
    for key, value in payload.dict(exclude_unset=True).items():
        setattr(eq, key, value)
    db.commit()
    db.refresh(eq)
    return _equipement_admin_out(db, eq)


@router.delete("/equipements/{equipement_id}", status_code=204)
def delete_equipement(equipement_id: int, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    eq = db.query(Equipement).filter(Equipement.id == equipement_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Équipement introuvable.")
    db.delete(eq)
    db.commit()


# =============================================================
# AFFECTATIONS ÉQUIPEMENT <-> LIGNE
# =============================================================

@router.post("/affectations-equipement", response_model=AffectationOut, status_code=201)
def creer_affectation_equipement(payload: AffectationEquipementCreate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    """Affecte un équipement à une ligne. Un équipement ne peut être qu'à un seul endroit
    à la fois -- toute affectation active existante pour cet équipement est
    automatiquement clôturée (contrairement au personnel, qui peut couvrir plusieurs
    lignes en même temps, cf. creer_affectation_personnel ci-dessous)."""
    debut = payload.date_debut or datetime.now()

    active = (
        db.query(AffectationEquipementLigne)
        .filter(AffectationEquipementLigne.equipement_id == payload.equipement_id, AffectationEquipementLigne.date_fin.is_(None))
        .first()
    )
    if active:
        active.date_fin = debut

    nouvelle = AffectationEquipementLigne(equipement_id=payload.equipement_id, ligne_id=payload.ligne_id, date_debut=debut)
    db.add(nouvelle)
    db.commit()
    db.refresh(nouvelle)
    return nouvelle


@router.post("/affectations-equipement/{affectation_id}/terminer", response_model=AffectationOut)
def terminer_affectation_equipement(affectation_id: int, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    aff = db.query(AffectationEquipementLigne).filter(AffectationEquipementLigne.id == affectation_id).first()
    if not aff:
        raise HTTPException(status_code=404, detail="Affectation introuvable.")
    if aff.date_fin is not None:
        raise HTTPException(status_code=409, detail="Cette affectation est déjà terminée.")
    aff.date_fin = datetime.now()
    db.commit()
    db.refresh(aff)
    return aff


# =============================================================
# AFFECTATIONS PERSONNEL <-> LIGNE
# =============================================================

@router.post("/affectations-personnel", response_model=AffectationOut, status_code=201)
def creer_affectation_personnel(payload: AffectationPersonnelCreate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    """Affecte un membre du personnel à une ligne. Contrairement à un équipement, une
    personne peut être affectée à plusieurs lignes simultanément (ex: 1 opérateur qui
    couvre les 6 lignes d'une tablette) -- pas de clôture automatique d'une affectation
    existante ici."""
    debut = payload.date_debut or datetime.now()
    nouvelle = AffectationLigne(user_id=payload.user_id, ligne_id=payload.ligne_id, date_debut=debut)
    db.add(nouvelle)
    db.commit()
    db.refresh(nouvelle)
    return nouvelle


@router.post("/affectations-personnel/{affectation_id}/terminer", response_model=AffectationOut)
def terminer_affectation_personnel(affectation_id: int, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    aff = db.query(AffectationLigne).filter(AffectationLigne.id == affectation_id).first()
    if not aff:
        raise HTTPException(status_code=404, detail="Affectation introuvable.")
    if aff.date_fin is not None:
        raise HTTPException(status_code=409, detail="Cette affectation est déjà terminée.")
    aff.date_fin = datetime.now()
    db.commit()
    db.refresh(aff)
    return aff


@router.get("/affectations-personnel", response_model=list[AffectationOut])
def list_affectations_personnel(user_id: int, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    return (
        db.query(AffectationLigne)
        .filter(AffectationLigne.user_id == user_id)
        .order_by(AffectationLigne.date_debut.desc())
        .all()
    )


# =============================================================
# CAUSES D'ARRÊT
# =============================================================

@router.get("/causes-arret", response_model=list[CauseArretAdminOut])
def list_causes_arret_admin(db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    """Toutes les causes, y compris désactivées (contrairement à GET /entities/causes-arret,
    qui ne montre que celles actives, pour le menu déroulant tablette)."""
    return db.query(CauseArret).order_by(CauseArret.ordre_affichage).all()


@router.post("/causes-arret", status_code=201)
def create_cause_arret(payload: CauseArretCreate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    existante = db.query(CauseArret).filter(CauseArret.libelle == payload.libelle).first()
    if existante:
        raise HTTPException(status_code=400, detail="Cette cause existe déjà.")
    cause = CauseArret(libelle=payload.libelle, ordre_affichage=payload.ordre_affichage, imputable_equipe=payload.imputable_equipe)
    db.add(cause)
    db.commit()
    db.refresh(cause)
    return cause


@router.patch("/causes-arret/{cause_id}")
def update_cause_arret(cause_id: int, payload: CauseArretUpdate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    cause = db.query(CauseArret).filter(CauseArret.id == cause_id).first()
    if not cause:
        raise HTTPException(status_code=404, detail="Cause introuvable.")
    for key, value in payload.dict(exclude_unset=True).items():
        setattr(cause, key, value)
    db.commit()
    db.refresh(cause)
    return cause


# =============================================================
# RÉFÉRENTIEL CALENDRIER -- configuration_poste + jours_speciaux
# *** AJOUT 2026-09-17 *** : n'existait nulle part jusqu'ici (ni routes, ni écran) --
# performance_service.py lit désormais ces tables (cf. _bornes_poste_du_jour), mais
# restait sans aucun moyen de les renseigner autrement qu'en SQL direct.
# =============================================================

class ConfigurationPosteOut(BaseModel):
    id: int
    nom: str
    heure_debut: time_type
    heure_fin: time_type
    pause_debut: Optional[time_type] = None
    pause_fin: Optional[time_type] = None
    actif: bool

    class Config:
        from_attributes = True


class ConfigurationPosteCreate(BaseModel):
    nom: str
    heure_debut: time_type
    heure_fin: time_type
    pause_debut: Optional[time_type] = None
    pause_fin: Optional[time_type] = None
    actif: bool = True


class ConfigurationPosteUpdate(BaseModel):
    nom: Optional[str] = None
    heure_debut: Optional[time_type] = None
    heure_fin: Optional[time_type] = None
    pause_debut: Optional[time_type] = None
    pause_fin: Optional[time_type] = None
    actif: Optional[bool] = None


@router.get("/configuration-poste", response_model=list[ConfigurationPosteOut])
def list_configuration_poste(db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    return db.query(ConfigurationPoste).order_by(ConfigurationPoste.nom).all()


@router.post("/configuration-poste", response_model=ConfigurationPosteOut, status_code=201)
def create_configuration_poste(payload: ConfigurationPosteCreate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    if payload.actif:
        # Un seul poste actif à la fois (index unique partiel en base, cf. schema.sql) --
        # on désactive les autres avant d'insérer, pour ne jamais violer la contrainte.
        db.query(ConfigurationPoste).filter(ConfigurationPoste.actif.is_(True)).update({"actif": False})
    poste = ConfigurationPoste(**payload.dict())
    db.add(poste)
    db.commit()
    db.refresh(poste)
    return poste


@router.patch("/configuration-poste/{poste_id}", response_model=ConfigurationPosteOut)
def update_configuration_poste(poste_id: int, payload: ConfigurationPosteUpdate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    poste = db.query(ConfigurationPoste).filter(ConfigurationPoste.id == poste_id).first()
    if not poste:
        raise HTTPException(status_code=404, detail="Configuration de poste introuvable.")
    data = payload.dict(exclude_unset=True)
    if data.get("actif") is True:
        db.query(ConfigurationPoste).filter(
            ConfigurationPoste.id != poste_id, ConfigurationPoste.actif.is_(True)
        ).update({"actif": False})
    for key, value in data.items():
        setattr(poste, key, value)
    db.commit()
    db.refresh(poste)
    return poste


@router.delete("/configuration-poste/{poste_id}", status_code=204)
def delete_configuration_poste(poste_id: int, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    poste = db.query(ConfigurationPoste).filter(ConfigurationPoste.id == poste_id).first()
    if not poste:
        raise HTTPException(status_code=404, detail="Configuration de poste introuvable.")
    db.delete(poste)
    db.commit()


class JourSpecialOut(BaseModel):
    id: int
    date: date_type
    type: str
    heure_debut: Optional[time_type] = None
    heure_fin: Optional[time_type] = None
    pause_debut: Optional[time_type] = None
    pause_fin: Optional[time_type] = None
    commentaire: Optional[str] = None

    class Config:
        from_attributes = True


class JourSpecialCreate(BaseModel):
    date: date_type
    type: str = "ferie"  # 'ferie' | 'horaire_special' | 'ferme'
    heure_debut: Optional[time_type] = None
    heure_fin: Optional[time_type] = None
    pause_debut: Optional[time_type] = None
    pause_fin: Optional[time_type] = None
    commentaire: Optional[str] = None


class JourSpecialUpdate(BaseModel):
    type: Optional[str] = None
    heure_debut: Optional[time_type] = None
    heure_fin: Optional[time_type] = None
    pause_debut: Optional[time_type] = None
    pause_fin: Optional[time_type] = None
    commentaire: Optional[str] = None


@router.get("/jours-speciaux", response_model=list[JourSpecialOut])
def list_jours_speciaux(db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    return db.query(JourSpecial).order_by(JourSpecial.date).all()


@router.post("/jours-speciaux", response_model=JourSpecialOut, status_code=201)
def create_jour_special(payload: JourSpecialCreate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    existant = db.query(JourSpecial).filter(JourSpecial.date == payload.date).first()
    if existant:
        raise HTTPException(status_code=400, detail="Un jour spécial existe déjà pour cette date.")
    jour = JourSpecial(**payload.dict())
    db.add(jour)
    db.commit()
    db.refresh(jour)
    return jour


@router.patch("/jours-speciaux/{jour_id}", response_model=JourSpecialOut)
def update_jour_special(jour_id: int, payload: JourSpecialUpdate, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    jour = db.query(JourSpecial).filter(JourSpecial.id == jour_id).first()
    if not jour:
        raise HTTPException(status_code=404, detail="Jour spécial introuvable.")
    for key, value in payload.dict(exclude_unset=True).items():
        setattr(jour, key, value)
    db.commit()
    db.refresh(jour)
    return jour


@router.delete("/jours-speciaux/{jour_id}", status_code=204)
def delete_jour_special(jour_id: int, db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    jour = db.query(JourSpecial).filter(JourSpecial.id == jour_id).first()
    if not jour:
        raise HTTPException(status_code=404, detail="Jour spécial introuvable.")
    db.delete(jour)
    db.commit()


# =============================================================
# *** AJOUT 2026-09-24 (Palier 0, coût des pertes) *** : valeur d'une pièce par produit.
# Sert à valoriser les arrêts en FCFA (cf. pertes_service.py). Un produit sans valeur
# propre retombe sur le paramètre global valeur_piece_defaut_fcfa. Seuls les produits
# finis confirmés sont listés -- les autres (matières, semi-finis insérés à la volée
# pour satisfaire une FK) n'ont jamais de coût de perte de production.
# =============================================================

class ProduitValeurOut(BaseModel):
    id: int
    nom: str
    default_code: Optional[str] = None
    valeur_unitaire_fcfa: Optional[float] = None

    class Config:
        from_attributes = True


class ProduitValeurUpdate(BaseModel):
    # None = retirer la valeur propre (le produit retombe sur la valeur par défaut).
    valeur_unitaire_fcfa: Optional[float] = None


@router.get("/produits-valeur", response_model=list[ProduitValeurOut])
def list_produits_valeur(db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage"))):
    return (
        db.query(ProduitCache)
        .filter(ProduitCache.confirme_produit_fini.is_(True))
        .order_by(ProduitCache.nom)
        .all()
    )


@router.patch("/produits/{produit_id}/valeur", response_model=ProduitValeurOut)
def update_produit_valeur(
    produit_id: int, payload: ProduitValeurUpdate,
    db: Session = Depends(get_db), _user: User = Depends(require_permission("view_parametrage")),
):
    produit = db.query(ProduitCache).filter(ProduitCache.id == produit_id).first()
    if not produit:
        raise HTTPException(status_code=404, detail="Produit introuvable.")
    valeur = payload.valeur_unitaire_fcfa
    if valeur is not None and (valeur < 0 or valeur != valeur):  # négatif ou NaN
        raise HTTPException(status_code=422, detail="La valeur doit être un nombre positif ou nul.")
    produit.valeur_unitaire_fcfa = valeur
    db.commit()
    db.refresh(produit)
    return produit
