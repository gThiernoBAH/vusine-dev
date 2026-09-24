from sqlalchemy.orm import Session
from typing import Optional
from . import models, schemas, auth
from .models import User, Parametre


def get_param(db: Session, key: str) -> Optional[str]:
    param = db.query(Parametre).filter(Parametre.key == key).first()
    return param.value if param else None


def set_param(db: Session, key: str, value: str):
    param = db.query(Parametre).filter(Parametre.key == key).first()
    if param:
        param.value = value
    else:
        param = Parametre(key=key, value=value)
        db.add(param)
    db.commit()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def get_user_by_matricule(db: Session, matricule: str) -> Optional[User]:
    return db.query(User).filter(User.matricule == matricule).first()


def get_user_by_identifiant(db: Session, identifiant: str) -> Optional[User]:
    """
    Connexion unifiée (cf. models.User, décision actée) : essaie d'abord `username`
    (comptes direction), puis retombe sur `matricule` (personnel terrain) si rien ne
    matche. Comportement identique pour tout le monde côté route -- seul ce que contient
    `identifiant` change selon qui se connecte.
    """
    user = get_user_by_username(db, identifiant)
    if user:
        return user
    return get_user_by_matricule(db, identifiant)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower()).first()


def get_user_by_reset_token(db: Session, token: str) -> Optional[User]:
    user = db.query(User).filter(User.reset_token == token).first()
    return user if user and user.reset_token_expires else None


def create_user(db: Session, user_create: schemas.UserCreate) -> Optional[User]:
    hashed_password = auth.get_password_hash(user_create.password)
    db_user = User(
        nom=user_create.nom,
        username=user_create.username,
        matricule=user_create.matricule,
        password_hash=hashed_password,
        user_type=user_create.user_type,
        categorie_personnel=user_create.categorie_personnel,
        email=user_create.email.lower() if user_create.email else None,
        telephone=user_create.telephone,
        departement_id=user_create.departement_id,
        section_scope=user_create.section_scope,
        # Comptes créés directement par un admin (pas d'auto-inscription publique côté
        # Vusine, contrairement à SIVOX) -- actif immédiatement, pas de validation
        # différée nécessaire.
        is_active=True,
        # *** AJOUT (chantier Labo) *** : is_admin=True autorisé seulement si le créateur
        # est is_super_admin -- vérifié dans auth_routes.create_user AVANT d'appeler
        # cette fonction, jamais ici (crud reste une simple couche de persistance).
        is_admin=user_create.is_admin or False,
    )
    db.add(db_user)
    try:
        db.commit()
        db.refresh(db_user)
        return db_user
    except Exception:
        db.rollback()
        return None


def create_password_reset_token(db: Session, email: str) -> Optional[User]:
    user = get_user_by_email(db, email)
    if not user:
        return None
    user.reset_token = auth.generate_reset_token()
    user.reset_token_expires = auth.get_reset_token_expiry()
    db.commit()
    db.refresh(user)
    return user


def reset_user_password(db: Session, user: User, new_password: str) -> User:
    user.password_hash = auth.get_password_hash(new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: int, user_update: schemas.UserUpdate) -> Optional[User]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    update_data = user_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    db.delete(user)
    db.commit()
    return True


def get_departments(db: Session):
    return db.query(models.Departement).all()
