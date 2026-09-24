from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, Boolean, text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


class Departement(Base):
    __tablename__ = "departements"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    users = relationship("User", back_populates="departement")


class User(Base):
    """
    Table unique pour les deux usages de l'app (décision actée avec l'utilisateur, cf.
    session de cadrage) : comptes "direction" (cockpit Vue Usine, PC) ET personnel terrain
    (connexion tablette, opérateur/ouvrier).

    Connexion unifiée : POST /auth/login reçoit un champ générique `identifiant`, résolu
    d'abord contre `username`, puis contre `matricule` si le premier ne matche rien (cf.
    crud.get_user_by_identifiant). Le comportement de l'API est donc identique pour tout le
    monde -- seul ce que contient `identifiant` diffère selon qui se connecte.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # --- Identifiants de connexion : un des deux selon le type de compte ---
    username = Column(String(20), unique=True, index=True, nullable=True)   # direction / cockpit
    matricule = Column(String(20), unique=True, index=True, nullable=True)  # personnel terrain
    password_hash = Column(String(255), nullable=False)

    # --- Identité ---
    nom = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)     # optionnel (surtout direction)
    telephone = Column(String(100), nullable=True)

    # --- Type de compte : détermine l'app accessible (cockpit PC vs tablette) ---
    user_type = Column(String(20), nullable=False, default="direction")
    # valeurs : "direction" | "operateur" | "ouvrier"

    # --- RH, uniquement renseigné pour le personnel terrain (scoring CDI/CDD) ---
    categorie_personnel = Column(String(20), nullable=True)
    # valeurs : "CDI" | "CDD" | "Journalier" | "Ancien CDI" | NULL (comptes direction)
    # Aucune contrainte CHECK en base (confirmé sur le DDL réel, 2026-09-17) -- "Ancien
    # CDI" (slide 20) est donc déjà utilisable tel quel, sans migration. Journalier
    # existe en base pour l'affichage équipe, mais est EXCLU du calcul de score
    # (cf. recap : "journaliers visibles sans score") -- filtré côté scoring_service.py,
    # jamais au niveau du modèle.

    # *** AJOUT 2026-09-17 (audit CDC, slide 16 -- rôle Chef d'équipe) *** : si
    # renseigné, restreint la Vue Usine du compte à la seule section listée ici.
    # Comparaison d'égalité simple contre lignes_cache.section_nom (cf.
    # dashboard_routes.get_vue_usine) -- un chef d'équipe = une seule section, jamais
    # une liste. NULL = accès complet (comptes Production/Administrateur).
    section_scope = Column(String(100), nullable=True)

    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(TIMESTAMP(timezone=True), nullable=True)

    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    # *** AJOUT (chantier Labo) *** : drapeau orthogonal à is_admin, jamais contourné par
    # lui (cf. require_labo dans auth_routes.py, qui ne teste JAMAIS is_admin). Réservé
    # à un seul compte -- Direction peut avoir is_admin=True sans jamais voir le Labo.
    # Volontairement absent de UserCreate/UserUpdate (schemas.py) : réglable uniquement
    # par SQL direct, aucune route API ne peut le modifier.
    is_super_admin = Column(Boolean, default=False, nullable=False)

    departement_id = Column(Integer, ForeignKey("departements.id"), nullable=True)
    departement = relationship("Departement", back_populates="users")

    # *** AJOUT 2026-09-24 (Palier 1, rapport matinal) *** : canaux de diffusion du rapport --
    # colonnes qui existaient déjà en base (is_alert_*) mais jamais mappées, plus
    # telegram_chat_id (nouvelle). Les autres reliquats SIVOX (mailapi, telegramapi...) restent
    # non mappés.
    is_alert_mail = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_alert_telegram = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    telegram_chat_id = Column(String(50), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    # NB (2026-09-17) : le DDL réel de `users` contient aussi is_alert_mail,
    # is_alert_telegram, is_alert_screen, last_alerts_seen_at, user_rep, mailapi,
    # telegramapi, whatsappapi, civilite -- absents de ce modèle ORM (reliquat probable
    # d'un script copié depuis SIVOX). Laissés tels quels en base pour l'instant (décision
    # utilisateur : "ne gêne rien, peut-être exploitable plus tard" -- notamment les 4
    # colonnes is_alert_* comme canaux de diffusion par utilisateur pour le moteur
    # d'alertes). Si un jour utilisées, les ajouter ici en Column().


class Parametre(Base):
    __tablename__ = "params"
    key = Column(String(50), primary_key=True)
    value = Column(String(255), nullable=False)


class UserPermission(Base):
    """
    Système de permissions générique, même principe que SIVOX : la PRÉSENCE d'une ligne
    (user_id, permission_key) accorde l'accès -- l'ABSENCE refuse, par défaut. Concerne
    uniquement les comptes "direction" (cf. auth_routes.PERMISSION_REGISTRY) -- le
    personnel terrain (user_type="operateur"/"ouvrier") n'a jamais de ligne ici, son accès
    est déterminé par son matricule + ses lignes affectées, pas par ce système de menus.
    """
    __tablename__ = "user_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "permission_key", name="uq_user_permission"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    permission_key = Column(String(50), nullable=False)
    granted_at = Column(TIMESTAMP(timezone=True), server_default=text("CURRENT_TIMESTAMP"))

    user = relationship("User")