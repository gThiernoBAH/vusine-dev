from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..core import schemas, crud, auth, models, tokens, login_throttle
from ..core.database import get_db
from ..core.settings import settings

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

# Registre central des clés de permission -- même principe que SIVOX (une permission par
# menu parent, liste blanche : présence = accès, absence = refus). Adapté aux modules
# réels de Vusine. La tablette opérateur n'est PAS concernée par ce registre : un compte
# user_type="operateur"/"ouvrier" n'a accès qu'à ses propres lignes via son matricule,
# jamais via ce système de permissions par menu (pensé pour les comptes direction/cockpit).
PERMISSION_REGISTRY = {
    "view_vue_usine": "Vue Usine (cockpit, détail ligne, palettes, arrêts)",
    "view_scoring": "Performance des équipes (score par ligne)",
    # *** AJOUT 2026-09-24 (Palier 2) *** : accès NOMINATIF, distinct et à accorder au cas par cas.
    "view_suivi_individuel": "Suivi individuel pour la formation (nominatif, consultations journalisées)",
    "view_parametrage": "Paramétrage (causes d'arrêt, seuils, équipements)",
}


# Seules routes accessibles à un compte kiosque (chemins EXACTS, méthode GET uniquement).
CHEMINS_KIOSQUE = ("/dashboard/andon",)


# --- Dépendance pour récupérer l'utilisateur courant ---
# *** REFAIT 2026-09-24 *** : l'ancien mécanisme (header X-User-ID, « même mécanisme que
# SIVOX ») n'était qu'une revendication d'identité non vérifiée : quiconque atteignait
# l'API pouvait envoyer X-User-ID: 1 et agir en admin. Remplacé par un jeton signé
# (Authorization: Bearer <jeton>, cf. core/tokens.py), émis par POST /auth/login.
# Vérifié à chaque requête : signature, expiration, compte existant ET actif, mot de
# passe inchangé depuis l'émission du jeton.
def get_current_user(request: Request, db: Session = Depends(get_db)):
    non_authentifie = HTTPException(
        status_code=401, detail="Non authentifié", headers={"WWW-Authenticate": "Bearer"},
    )
    entete = request.headers.get("Authorization", "")
    schema, _, jeton = entete.partition(" ")
    if schema.lower() != "bearer" or not jeton:
        raise non_authentifie

    payload = tokens.lire_jeton(jeton.strip())
    if not payload:
        raise non_authentifie

    user = db.query(models.User).filter(models.User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise non_authentifie
    if payload.get("pwd") != tokens.empreinte_mot_de_passe(user.password_hash):
        # Mot de passe changé depuis l'émission du jeton -> session révoquée.
        raise non_authentifie

    # *** AJOUT 2026-09-24 (Andon) *** : un compte « kiosque » (écran d'atelier, session de
    # 30 jours laissée ouverte sur une TV) ne peut appeler QUE la lecture de l'écran
    # Andon. Restriction centrale, ici, plutôt que route par route : toute route existante
    # ou future qui dépend de get_current_user lui est fermée d'office (403).
    if user.user_type == "kiosque" and not (
        request.method == "GET" and request.url.path.rstrip("/") in CHEMINS_KIOSQUE
    ):
        raise HTTPException(status_code=403, detail="Ce compte est réservé à l'affichage Andon.")
    return user


def require_admin(current_user: models.User = Depends(get_current_user)):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs.")
    return current_user


# *** AJOUT (chantier Labo) *** : dépendance dédiée aux écrans/fonctionnalités du Labo
# (F1-F10, chantiers issus de SIVOX -- capacité, prévisions, plan optimisé, matières,
# etc.). Volontairement séparée de require_admin/require_permission : ne teste JAMAIS
# is_admin, pour qu'un compte Direction (is_admin=True) ne voie jamais le Labo tant
# qu'une fonctionnalité n'a pas été explicitement "graduée" vers l'usage courant.
def require_labo(current_user: models.User = Depends(get_current_user)):
    if not getattr(current_user, "is_super_admin", False):
        raise HTTPException(status_code=403, detail="Accès non autorisé à cette fonctionnalité.")
    return current_user


def require_andon(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Écran Andon : compte kiosque, ou compte direction autorisé à voir la Vue Usine
    (même règle que require_permission("view_vue_usine"), sans la dépendance FastAPI --
    un kiosque n'a jamais aucune UserPermission)."""
    if current_user.user_type == "kiosque" or getattr(current_user, "is_admin", False):
        return current_user
    a_la_permission = db.query(models.UserPermission).filter(
        models.UserPermission.user_id == current_user.id,
        models.UserPermission.permission_key == "view_vue_usine",
    ).first()
    if not a_la_permission:
        raise HTTPException(status_code=403, detail="Accès non autorisé à cette fonctionnalité.")
    return current_user


def require_permission(permission_key: str):
    """Fabrique de dépendance FastAPI, réutilisable par toute route direction/cockpit.
    Usage : `Depends(require_permission("view_vue_usine"))`."""
    def _check(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)) -> models.User:
        if getattr(current_user, "is_admin", False):
            return current_user
        has_permission = db.query(models.UserPermission).filter(
            models.UserPermission.user_id == current_user.id,
            models.UserPermission.permission_key == permission_key,
        ).first()
        if not has_permission:
            raise HTTPException(status_code=403, detail="Accès non autorisé à cette fonctionnalité.")
        return current_user
    return _check


@router.get("/departements", status_code=status.HTTP_200_OK)
def get_all_departments(db: Session = Depends(get_db)):
    return crud.get_departments(db)


@router.get("/users", response_model=list[schemas.UserResponse])
def get_all_users(db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    users = db.query(models.User).options(joinedload(models.User.departement)).all()
    return users


# Profil : volontairement réduit par rapport à SIVOX (pas de mailapi/telegramapi chiffrés,
# ces champs n'existent pas sur le User Vusine -- cf. modèle unifié direction/terrain).
@router.patch("/profile")
def update_profile(
    telephone: str | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if telephone:
        current_user.telephone = telephone
    db.commit()
    db.refresh(current_user)
    return {"message": "Profil mis à jour"}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    if not crud.delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")
    return None


@router.patch("/users/{user_id}")
def update_user_status(user_id: int, user_update: schemas.UserUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(require_admin)):
    # *** AJOUT (chantier Labo) *** : même garde qu'à la création -- seul is_super_admin
    # peut promouvoir/rétrograder un compte Admin.
    if user_update.is_admin is not None and not getattr(current_user, "is_super_admin", False):
        raise HTTPException(status_code=403, detail="Seul l'administrateur peut modifier le statut Admin.")
    db_user = crud.update_user(db, user_id, user_update)
    if not db_user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    return db_user


# Création d'un compte (direction OU personnel terrain) : réservée à l'admin. Pas
# d'auto-inscription publique côté Vusine (contrairement à SIVOX) -- les opérateurs ne
# créent jamais leur propre compte, ils sont enregistrés par un admin avec leur matricule.
@router.post("/users", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_schema: schemas.UserCreate, db: Session = Depends(get_db), current_user: models.User = Depends(require_admin)):
    # *** AJOUT (chantier Labo) *** : seul un compte is_super_admin peut créer un
    # nouveau compte Admin (is_admin=True) -- empêche un compte Direction, même admin,
    # de se créer un pair ou de s'auto-accorder plus de droits.
    if user_schema.is_admin and not getattr(current_user, "is_super_admin", False):
        raise HTTPException(status_code=403, detail="Seul l'administrateur peut créer un compte Admin.")
    if user_schema.username and crud.get_user_by_username(db, user_schema.username):
        raise HTTPException(status_code=400, detail="Username déjà utilisé.")
    if user_schema.matricule and crud.get_user_by_matricule(db, user_schema.matricule):
        raise HTTPException(status_code=400, detail="Matricule déjà utilisé.")
    if not user_schema.username and not user_schema.matricule:
        raise HTTPException(status_code=422, detail="username ou matricule requis.")
    if user_schema.user_type == "kiosque":
        # Écran d'atelier : identifiant textuel, jamais de droits d'administration.
        if not user_schema.username:
            raise HTTPException(status_code=422, detail="Un compte kiosque se connecte avec un username.")
        if user_schema.is_admin:
            raise HTTPException(status_code=422, detail="Un compte kiosque ne peut pas être administrateur.")

    new_user = crud.create_user(db=db, user_create=user_schema)
    if not new_user:
        raise HTTPException(status_code=500, detail="Erreur interne.")
    return new_user


@router.get("/params/{key}", status_code=status.HTTP_200_OK)
def get_param(key: str, db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    value = crud.get_param(db, key)
    return {"key": key, "value": value}


@router.patch("/params", status_code=status.HTTP_200_OK)
def update_param(param_update: schemas.ParamUpdate, db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    crud.set_param(db, param_update.key, param_update.value)
    return {"message": "Paramètre mis à jour."}


@router.get("/permissions/registry")
def get_permissions_registry(_admin: models.User = Depends(require_admin)):
    return [{"key": k, "label": v} for k, v in PERMISSION_REGISTRY.items()]


@router.get("/users/{user_id}/permissions")
def get_user_permissions(user_id: int, db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    rows = db.query(models.UserPermission).filter(models.UserPermission.user_id == user_id).all()
    return {"user_id": user_id, "granted": [r.permission_key for r in rows]}


class UserPermissionsUpdate(BaseModel):
    granted: list[str]


@router.put("/users/{user_id}/permissions")
def set_user_permissions(user_id: int, payload: UserPermissionsUpdate, db: Session = Depends(get_db), _admin: models.User = Depends(require_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    unknown = set(payload.granted) - set(PERMISSION_REGISTRY.keys())
    if unknown:
        raise HTTPException(status_code=422, detail=f"Clé(s) de permission inconnue(s) : {sorted(unknown)}")

    db.query(models.UserPermission).filter(models.UserPermission.user_id == user_id).delete()
    for key in payload.granted:
        db.add(models.UserPermission(user_id=user_id, permission_key=key))
    db.commit()
    return {"user_id": user_id, "granted": payload.granted}


@router.post("/login", status_code=status.HTTP_200_OK)
def login_user(user_login: schemas.UserLogin, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "inconnue"

    attente = login_throttle.secondes_restantes(user_login.identifiant, ip)
    if attente:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Trop de tentatives. Réessayez dans {-(-attente // 60)} minute(s).",
            headers={"Retry-After": str(attente)},
        )

    db_user = crud.get_user_by_identifiant(db, user_login.identifiant)
    if not db_user or not auth.verify_password(user_login.password, db_user.password_hash):
        login_throttle.enregistrer_echec(user_login.identifiant, ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants incorrects.")
    if not db_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Compte désactivé.")
    login_throttle.effacer(user_login.identifiant, ip)

    if db_user.is_admin:
        permissions = list(PERMISSION_REGISTRY.keys())
    else:
        permissions = [
            p.permission_key for p in
            db.query(models.UserPermission).filter(models.UserPermission.user_id == db_user.id).all()
        ]

    # Compte kiosque : session longue (KIOSK_TOKEN_TTL_DAYS) -- sinon la TV d'atelier
    # demanderait une reconnexion chaque jour, sans personne devant pour la faire.
    duree = settings.KIOSK_TOKEN_TTL_DAYS * 24 if db_user.user_type == "kiosque" else None
    jeton, expire_le = tokens.creer_jeton(db_user.id, db_user.password_hash, duree_heures=duree)

    return {
        "message": "Connexion réussie.",
        "access_token": jeton,
        "token_type": "bearer",
        "expires_at": expire_le,
        "user": {
            "id": db_user.id,
            "nom": db_user.nom,
            "username": db_user.username,
            "matricule": db_user.matricule,
            "user_type": db_user.user_type,
            "categorie_personnel": db_user.categorie_personnel,
            "department": db_user.departement.name if db_user.departement else None,
            "is_admin": db_user.is_admin,
            # *** AJOUT (chantier Labo) *** : distinct de is_admin, décide seul de
            # l'affichage du menu Labo côté front (cf. router/index.js, Sidebar.vue).
            "is_super_admin": db_user.is_super_admin,
            "section_scope": db_user.section_scope,
            "email": db_user.email,
            "telephone": db_user.telephone,
            "permissions": permissions,
        }
    }
