import re
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional


def _vide_vers_none(v):
    """*** AJOUT 2026-09-23 *** : un champ texte vide ('' ou espaces) venant d'un
    formulaire devient None -- jamais '' en base. Un email '' faisait échouer toute la
    liste GET /auth/users (erreur 500, écran Personnel inutilisable)."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


# *** AJOUT 2026-09-24 (Andon) *** : liste fermée des types de compte -- avant, user_type
# était une chaîne libre (une faute de frappe créait un compte « fantôme » sans espace).
# « kiosque » = écran d'atelier (Andon) : session longue, accès limité à la seule route
# GET /dashboard/andon (cf. auth_routes.get_current_user).
TYPES_COMPTE = ("direction", "operateur", "ouvrier", "kiosque")


def _valider_type_compte(v):
    if v is not None and v not in TYPES_COMPTE:
        raise ValueError(f"user_type doit être l'un de : {', '.join(TYPES_COMPTE)}.")
    return v


class UserCreate(BaseModel):
    nom: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=6, description="Mot de passe (minimum 6 caractères)")

    # Un seul des deux attendu selon le type de compte -- validé au niveau route/crud
    # (pas ici) : un compte "direction" fournit username, un compte terrain fournit
    # matricule. Les deux nullable ici pour ne pas dupliquer ce schéma.
    username: Optional[str] = Field(None, min_length=4, max_length=20)
    matricule: Optional[str] = Field(None, min_length=2, max_length=20)

    user_type: str = Field("direction", description='"direction" | "operateur" | "ouvrier" | "kiosque"')
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

    # *** AJOUT 2026-09-24 (Andon) *** : restreint le compte à UNE section (atelier) --
    # Chef d'équipe (Vue Usine, Pareto) ou écran Andon d'un atelier. Ne fait que RÉDUIRE
    # ce que le compte voit : aucun risque d'élévation de droits.
    section_scope: Optional[str] = None

    _normaliser_vides = field_validator("email", "telephone", "section_scope", mode="before")(_vide_vers_none)
    _valider_type = field_validator("user_type")(_valider_type_compte)


class UserUpdate(BaseModel):
    nom: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    departement_id: Optional[int] = None
    email: Optional[EmailStr] = None
    telephone: Optional[str] = None
    user_type: Optional[str] = None
    categorie_personnel: Optional[str] = None
    section_scope: Optional[str] = None
    # *** AJOUT 2026-09-24 (Palier 1) *** : destinataire du rapport matinal (email / Telegram).
    is_alert_mail: Optional[bool] = None
    is_alert_telegram: Optional[bool] = None
    telegram_chat_id: Optional[str] = None

    _normaliser_vides = field_validator("email", "telephone", "section_scope", "telegram_chat_id", mode="before")(_vide_vers_none)
    _valider_type = field_validator("user_type")(_valider_type_compte)

    @field_validator("telegram_chat_id")
    @classmethod
    def _chat_id_numerique(cls, v):
        # Identifiant de chat Telegram : entier (négatif pour un groupe) -- refuse une faute
        # de frappe ici plutôt que des envois qui échouent en silence chaque matin.
        if v is not None and not re.fullmatch(r"-?\d{5,20}", v.strip()):
            raise ValueError("L'identifiant Telegram doit être un nombre, par exemple 123456789 (pas un jeton ni un nom d'utilisateur).")
        return v.strip() if v else v

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
    section_scope: Optional[str] = None
    is_alert_mail: bool = False
    is_alert_telegram: bool = False
    telegram_chat_id: Optional[str] = None

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
