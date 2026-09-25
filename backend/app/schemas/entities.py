from pydantic import BaseModel
from datetime import date
from typing import Optional


class LigneOut(BaseModel):
    id: int
    code: str
    nom: str
    section_nom: Optional[str] = None

    class Config:
        from_attributes = True


class EquipementOut(BaseModel):
    id: int
    type: str
    marque: Optional[str] = None
    modele: Optional[str] = None
    numero_interne: Optional[str] = None
    capacite: Optional[str] = None
    statut: str
    derniere_maintenance: Optional[date] = None
    prochaine_maintenance: Optional[date] = None

    class Config:
        from_attributes = True


class CauseArretOut(BaseModel):
    id: int
    libelle: str

    class Config:
        from_attributes = True


class PersonnelLigneOut(BaseModel):
    user_id: int
    nom: str
    matricule: Optional[str] = None
    user_type: str
    categorie_personnel: Optional[str] = None

    class Config:
        from_attributes = True


class PlanningItemOut(BaseModel):
    """*** NOUVEAU 2026-09-17, REMPLACE OfResume *** : un item du planning hebdomadaire
    (planning_detail_cache) pour cette ligne, aujourd'hui -- une ligne peut en avoir 0, 1
    ou PLUSIEURS le même jour (plusieurs produits planifiés). `id` = planning_detail_id,
    à passer tel quel lors de la validation d'une palette (POST /actions/palettes)."""
    id: int  # planning_detail_cache.id -- devient PaletteCreate.planning_detail_id
    produit_id: Optional[int] = None
    produit_nom: Optional[str] = None
    qty_jour: Optional[float] = None
    reference_planning: Optional[str] = None  # ex: "OPF01274", pour affichage/traçabilité
    # Pré-remplissage du formulaire palette -- toujours depuis produits_cache (source
    # confirmée fiable), jamais depuis planning_detail_cache.colisage/contenance qui
    # portent une signification différente (cible du planning, pas la palettisation).
    colisage_par_carton: Optional[int] = None
    cartons_par_palette: Optional[int] = None

    class Config:
        from_attributes = True


class LigneDetailOut(BaseModel):
    ligne: LigneOut
    items_planning_jour: list[PlanningItemOut] = []
    equipements: list[EquipementOut] = []
    personnel: list[PersonnelLigneOut] = []
    poste_heure_debut: Optional[str] = None   # *** AJOUT 2026-09-25 *** : heure de DÉBUT DE POSTE du jour (pas un pointage individuel), "HH:MM" ou None si usine fermée/non configurée