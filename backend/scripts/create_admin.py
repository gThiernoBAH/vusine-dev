#!/usr/bin/env python3
"""
create_admin.py -- Crée le premier compte administrateur (ou réinitialise son mot de passe).

*** AJOUT 2026-09-24 *** : remplace le compte 'admin' qui était inséré par params.sql avec
un hash de mot de passe versionné. Le mot de passe n'est jamais écrit dans un fichier :
il est saisi au clavier (masqué), ou lu dans la variable d'environnement ADMIN_PASSWORD
pour un usage non interactif (ex. reset_vusinedb_dev.sh).

Usage (depuis backend/) :
    python3 -m scripts.create_admin
    python3 -m scripts.create_admin --username admin --matricule 3318 --nom "Admin" \\
        --email prenom.nom@exemple.ci --telephone 0700000000
    python3 -m scripts.create_admin --reset-password     # compte existant : nouveau mot de passe

Le compte créé est is_admin ET is_super_admin (accès au Labo). Les autres comptes se
créent ensuite depuis l'écran Personnel.
"""
import argparse
import getpass
import os
import sys

from app.core import auth
from app.core.database import SessionLocal
from app.core.models import User

MIN_LONGUEUR = 10


def _lire_mot_de_passe() -> str:
    depuis_env = os.environ.get("ADMIN_PASSWORD")
    if depuis_env:
        mdp = depuis_env
    else:
        mdp = getpass.getpass("Mot de passe : ")
        if mdp != getpass.getpass("Confirmer le mot de passe : "):
            sys.exit("Les deux saisies diffèrent. Abandon.")
    if len(mdp) < MIN_LONGUEUR:
        sys.exit(f"Mot de passe trop court (minimum {MIN_LONGUEUR} caractères). Abandon.")
    return mdp


def main() -> None:
    p = argparse.ArgumentParser(description="Crée le compte administrateur initial.")
    p.add_argument("--username", default="admin")
    p.add_argument("--matricule", default=None)
    p.add_argument("--nom", default="Admin")
    p.add_argument("--email", default=None)
    p.add_argument("--telephone", default=None)
    p.add_argument("--reset-password", action="store_true",
                   help="Si le compte existe déjà, change son mot de passe (invalide ses sessions).")
    args = p.parse_args()

    db = SessionLocal()
    try:
        existant = db.query(User).filter(User.username == args.username).first()
        if existant and not args.reset_password:
            sys.exit(f"Le compte '{args.username}' existe déjà. Utilisez --reset-password pour changer son mot de passe.")

        mot_de_passe = _lire_mot_de_passe()
        hash_ = auth.get_password_hash(mot_de_passe)

        if existant:
            existant.password_hash = hash_
            existant.is_active = True
            db.commit()
            print(f"Mot de passe du compte '{args.username}' mis à jour (ses sessions ouvertes sont invalidées).")
            return

        db.add(User(
            username=args.username,
            matricule=args.matricule or None,
            password_hash=hash_,
            nom=args.nom,
            email=(args.email or None) and args.email.lower(),
            telephone=args.telephone or None,
            user_type="direction",
            categorie_personnel="CDI",
            is_active=True,
            is_admin=True,
            is_super_admin=True,
            departement_id=1,
        ))
        db.commit()
        print(f"Compte administrateur '{args.username}' créé.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
