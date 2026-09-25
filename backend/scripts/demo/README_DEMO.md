# Outils de démo et de test de bout en bout de Vusine

Des opérateurs **fictifs** travaillent à travers la **vraie API** (connexion, saisie de palette, arrêts), exactement
comme la tablette le fera. On juge ensuite le résultat dans le cockpit, et un script vérifie que les chiffres
affichés sont justes.

Tout se passe sur une **base de démo séparée**. La production n'est jamais touchée : chaque script refuse de
tourner si le nom de la base ne contient pas « demo », demande de retaper ce nom, et contrôle que l'API lit bien la
même base que lui.

## Ce qu'il faut

Python (celui du backend, avec `requests`), `psql`/`pg_dump`, Node pour le frontend. Pour les captures :
`pip install playwright && playwright install chromium`. Toutes les commandes se lancent depuis `backend/`.

## 1. Préparer (une seule fois)

```bash
# a) copier la base de production vers une base de démo (la source n'est que lue)
PGUSER=... PGPASSWORD=... scripts/demo/creer_base_demo.sh vusine vusine_demo

# b) démarrer une SECONDE instance de l'application sur cette base
export DATABASE_URL=postgresql://USER:MDP@localhost/vusine_demo
uvicorn app.main:app --port 8001                      # terminal 1 (backend de démo)
cd ../frontend && VITE_PORT=5174 VITE_API_BASE_URL=http://localhost:8001 npm run dev   # terminal 2
```

Le planning vient d'Odoo (déjà dans la copie). Il n'a pas besoin d'être à jour.

## 2. Simuler l'historique (2 à 3 semaines)

```bash
export DATABASE_URL=postgresql://USER:MDP@localhost/vusine_demo   # dans CHAQUE terminal qui lance un script
export DEMO_ADMIN_PASSWORD='...'                                  # mot de passe du compte admin de la base de démo

python scripts/demo/simuler_historique.py --a-blanc     # aperçu : rien n'est écrit
python scripts/demo/simuler_historique.py --jours 15    # pour de vrai (environ 1 minute)
```

Ce que cela produit : 40 opérateurs `DEMO001`… (mot de passe `Demo2026!`), l'équipe de chaque ligne (via l'écran
Administration → Affectations), et pour chaque jour planifié : arrêts, changements de série, palettes partielles,
rebuts, erreurs de saisie refusées par le serveur. Les lignes ont du caractère : bonnes, moyennes, faibles,
en panne chronique ; certains opérateurs saisissent tout en fin de poste.

Options utiles : `--graine 7` (autre scénario, rejouable), `--max-lignes 40`, `--operateurs 40`,
`--jour-sans-scan 2026-09-10` (un jour où personne ne saisit), `--arret-oublie`, `--bonus-efficacite 1.1`
(usine plus à l'aise).

## 3. Vérifier que les chiffres sont justes

```bash
python scripts/demo/verifier_coherence.py
```

Compare `demo_reference.json` (ce qui a été simulé) au cockpit : palettes, TRS, Pareto des arrêts, score d'équipe,
écrans opérateur, cloisonnement. Trois niveaux : OK, ÉCART (chiffre faux, code de sortie 1), ALERTE (chiffre
cohérent mais discutable).

## 4. Photographier tous les écrans

```bash
python scripts/demo/captures_ecrans.py --url https://localhost:5174 --api http://localhost:8001 --sortie captures_demo
```

Un PNG par écran et par taille (TV 1920×1080, tablette portrait 820×1180, PC 1440×900) et `rapport_captures.md`.
Le script signale seul : défilement horizontal (dont les tableaux qui défilent de côté sur tablette), erreurs
JavaScript, appels API en échec, écran resté sur « Chargement… ». Il ne remplace pas un coup d'œil : ouvrez les images.

## 5. La démo en direct

```bash
# terminal 3 : la journée en cours, rejouée jusqu'à maintenant puis poursuivie au rythme réel
python scripts/demo/demo_live.py --regler-poste --cloner-planning-depuis 2026-09-23
```

* `--regler-poste` : horaire spécial pour AUJOURD'HUI seulement, qui englobe l'heure actuelle (à utiliser si la
  démo a lieu hors 7h30-17h). L'historique n'est pas touché.
* `--cloner-planning-depuis` : si Odoo n'a rien planifié aujourd'hui, recopie le planning d'un jour passé.
* `--bonus-efficacite 1.10` (défaut) donne une usine « plutôt bonne » ; `--garder-fin-de-poste` remet les
  opérateurs qui saisissent tout à la fin (l'Andon paraîtra alors très rouge en milieu de journée).
* Rythme réel : environ une palette par ligne toutes les 30 à 60 minutes. Pour animer l'écran, provoquez des
  évènements à la main (terminal 4) :

```bash
python scripts/demo/demo_actions.py arret CCL04 --cause "Manque MP"   # la ligne passe à l'arrêt sur l'Andon
python scripts/demo/demo_actions.py reprise CCL04
python scripts/demo/demo_actions.py palette CCL04 [--partielle]
python scripts/demo/demo_actions.py etat                                # l'Andon en texte
```

### Déroulé proposé (3 onglets Chrome)

1. **Andon** (`/andon`, plein écran) : « voici l'atelier en temps réel ». Lancer `arret` sur une ligne : elle passe
   en rouge avec sa cause et sa durée. `reprise` : elle repart.
2. **Direction** : Vue Usine « Par section » puis « Compact » ; Alertes ; Rapports (Pareto : première cause d'arrêt
   et son coût ; TRS ; Par ligne) ; Équipes (score d'équipe, jamais un classement de personnes).
3. **Opérateur** (connecté avec un matricule `DEMOnnn`, mot de passe `Demo2026!`) : « Mes lignes », saisie d'une
   palette, « Mon historique », « Mes performances » (heures et résultat de l'équipe, aucune note personnelle).
   La palette saisie se voit aussitôt sur l'Andon et dans la Vue Usine.

## 6. Nettoyer

```bash
python scripts/demo/nettoyer_demo.py --aujourdhui   # seulement la production du jour (pour relancer demo_live)
python scripts/demo/nettoyer_demo.py                # tout ce qui est fictif : comptes, palettes, arrêts, affectations
```

Ou simplement supprimer la base : `dropdb vusine_demo`.

## Points de configuration à connaître

* **Masquage des équipes** : Administration → Paramètres → « Effectif minimal d'une équipe affichée ». À 0 rien
  n'est masqué ; à 3, une équipe de 2 personnes est masquée (comportement voulu en régime établi).
* **Calendrier** : les jours sans production (dimanche, fériés) doivent être fermés dans Administration →
  Calendrier, sinon ils comptent comme jours de présence et de poste.
* **Police** : l'interface charge la police Inter depuis Internet ; sans accès web (réseau d'atelier isolé), elle
  retombe sur la police du système.
