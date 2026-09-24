from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional


def _vide_vers_none(v):
    """*** AJOUT 2026-09-23 *** : un champ texte vide ('' ou espaces) venant d'un
    formulaire devient None -- jamais '' en base. Un email '' faisait échouer toute la
    liste GET /auth/users (erreur 500, écran Personnel inutilisable)."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


class UserCreate(BaseModel):
    nom: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=6, description="Mot de passe (minimum 6 caractères)")

    # Un seul des deux attendu selon le type de compte -- validé au niveau route/crud
    # (pas ici) : un compte "direction" fournit username, un compte terrain fournit
    # matricule. Les deux nullable ici pour ne pas dupliquer ce schéma.
    username: Optional[str] = Field(None, min_length=4, max_length=20)
    matricule: Optional[str] = Field(None, min_length=2, max_length=20)

    user_type: str = Field("direction", description='"direction" | "operateur" | "ouvrier"')
    categorie_personnel: Optional[str] = Field(
        None, description='"CDI" | "CDD" | "Journalier" -- uniquement si user_type != "direction"'
    )

    email: Optional[EmailStr] = None
    telephone: Optional[str] = None
    departement_id: Optional[int] = None

    # *** AJOUT (chantier Labo) *** : permet de créer directement un compte Admin (le
    # Directeur, par ex.) en une seule opération. Contrôlé côté route (auth_routes.py) :
    # seul un compte is_super_admin peut fournir is_admin=True, sinon 403. Défaut à
    # False pour ne rien changer au comportement existant (création d'un compte
    # direction/opérateur classique).
    is_admin: Optional[bool] = False

    _normaliser_vides = field_validator("email", "telephone", mode="before")(_vide_vers_none)


class UserUpdate(BaseModel):
    nom: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    departement_id: Optional[int] = None
    email: Optional[EmailStr] = None
    telephone: Optional[str] = None
    user_type: Optional[str] = None
    categorie_personnel: Optional[str] = None

    _normaliser_vides = field_validator("email", "telephone", mode="before")(_vide_vers_none)

    class Config:
        from_attributes = True


class DepartementResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: int
    nom: str
    username: Optional[str] = None
    matricule: Optional[str] = None
    # *** CORRIGÉ 2026-09-23 *** : str et non EmailStr en RÉPONSE. Le format est validé
    # à l'écriture (UserCreate/UserUpdate) ; revalider en lecture faisait échouer toute
    # la liste dès qu'UN compte avait une valeur atypique en base (cas réel : '').
    email: Optional[str] = None
    telephone: Optional[str] = None
    user_type: str
    categorie_personnel: Optional[str] = None
    is_active: bool = True
    is_admin: bool = False
    # *** AJOUT (chantier Labo) *** : en LECTURE seule -- absent de UserUpdate,
    # jamais modifiable via l'API (cf. models.py pour la justification).
    is_super_admin: bool = False
    departement_id: Optional[int] = None
    departement: Optional[DepartementResponse] = None

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    # Champ générique volontairement (pas "username" figé comme chez SIVOX) : peut
    # contenir un username (compte direction) ou un matricule (personnel terrain) --
    # cf. crud.get_user_by_identifiant pour la résolution.
    identifiant: str
    password: str


class ParamUpdate(BaseModel):
    key: str
    value: str

    class Config:
        from_attributes = True


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: str
    new_password: str
