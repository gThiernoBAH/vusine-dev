from pydantic import BaseModel
from typing import Optional


class PersonnelScoreOut(BaseModel):
    user_id: int
    nom: str
    matricule: Optional[str] = None
    categorie_personnel: Optional[str] = None
    score_pct: Optional[int] = None
    nb_lignes: int
    heures_totales: float
