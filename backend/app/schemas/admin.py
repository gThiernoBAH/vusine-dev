from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


class EquipementCreate(BaseModel):
    type: str
    marque: Optional[str] = None
    modele: Optional[str] = None
    numero_interne: Optional[str] = None
    capacite: Optional[str] = None
    statut: str = "disponible"
    derniere_maintenance: Optional[date] = None
    prochaine_maintenance: Optional[date] = None


class EquipementUpdate(BaseModel):
    type: Optional[str] = None
    marque: Optional[str] = None
    modele: Optional[str] = None
    numero_interne: Optional[str] = None
    capacite: Optional[str] = None
    statut: Optional[str] = None
    derniere_maintenance: Optional[date] = None
    prochaine_maintenance: Optional[date] = None


class EquipementAdminOut(BaseModel):
    id: int
    type: str
    marque: Optional[str] = None
    modele: Optional[str] = None
    numero_interne: Optional[str] = None
    capacite: Optional[str] = None
    statut: str
    derniere_maintenance: Optional[date] = None
    prochaine_maintenance: Optional[date] = None
    ligne_actuelle_code: Optional[str] = None  # dénormalisé pour l'affichage admin

    class Config:
        from_attributes = True


class AffectationEquipementCreate(BaseModel):
    equipement_id: int
    ligne_id: int
    date_debut: Optional[datetime] = None  # défaut : maintenant


class AffectationPersonnelCreate(BaseModel):
    user_id: int
    ligne_id: int
    date_debut: Optional[datetime] = None  # défaut : maintenant


class AffectationOut(BaseModel):
    id: int
    ligne_id: int
    date_debut: datetime
    date_fin: Optional[datetime] = None

    class Config:
        from_attributes = True


class CauseArretAdminOut(BaseModel):
    """Liste ADMIN des causes d'arrêt. CORRIGÉ 2026-09-24 : la route renvoyait
    schemas.entities.CauseArretOut (id + libelle seulement) -- actif et ordre_affichage
    disparaissaient, et l'écran affichait toutes les causes « Désactivée »."""
    id: int
    libelle: str
    actif: bool
    ordre_affichage: int
    imputable_equipe: bool = False

    class Config:
        from_attributes = True


class CauseArretCreate(BaseModel):
    libelle: str
    ordre_affichage: int = 0
    imputable_equipe: bool = False


class CauseArretUpdate(BaseModel):
    libelle: Optional[str] = None
    actif: Optional[bool] = None
    ordre_affichage: Optional[int] = None
    imputable_equipe: Optional[bool] = None
