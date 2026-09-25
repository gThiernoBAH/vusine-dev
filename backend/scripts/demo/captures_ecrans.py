"""
captures_ecrans.py -- visite chaque écran de Vusine aux tailles réelles (TV, tablette, PC), le photographie et
signale automatiquement ce qu'un oeil humain remarquerait :

  - défilement horizontal (la page déborde de l'écran) et éléments qui dépassent à droite ;
  - erreurs de console JavaScript et exceptions de la page ;
  - appels API en échec (statut >= 400) ;
  - écran resté sur « Chargement… ».

  pip install playwright && playwright install chromium          # une seule fois
  cd backend
  python scripts/demo/captures_ecrans.py --url http://localhost:5174 --api http://localhost:8001 \\
      --admin-password '***'

Sortie : screenshots/<horodatage>/ (un sous-dossier par exécution, jamais d'écrasement) -- un PNG par écran
et par taille, plus rapport_captures.md. `--sortie` change le dossier PARENT (défaut : screenshots/). Les
captures montrent la base de DÉMO : lancez d'abord simuler_historique.py (et demo_live.py pour une journée
en cours).

--url : l'adresse du FRONTEND de démo (ex. https://localhost:5174 ; les certificats auto-signés sont acceptés).
--api : l'adresse de l'API de démo, utilisée uniquement pour se connecter sans passer par l'écran de login.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

TAILLES = {
    "tv": {"viewport": {"width": 1920, "height": 1080}, "has_touch": False},
    "tablette": {"viewport": {"width": 820, "height": 1180}, "has_touch": True},     # portrait, comme une tablette d'atelier
    "pc": {"viewport": {"width": 1440, "height": 900}, "has_touch": False},
}

JS_DEBORDEMENT = """() => {
  const w = window.innerWidth, out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.right > w + 2 && !el.closest('[style*="overflow"]')) {
      let ancetre = el.parentElement, coupe = false;
      while (ancetre && ancetre !== document.body) {
        const o = getComputedStyle(ancetre).overflowX;
        if (o === 'auto' || o === 'scroll' || o === 'hidden') { coupe = true; break; }
        ancetre = ancetre.parentElement;
      }
      if (!coupe) out.push((el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/)[0] : '')) + ' (' + Math.round(r.right - w) + ' px)');
    }
  }
  // Zones qui défilent horizontalement (tableau plus large que son cadre) : c'est ce qui gênait sur tablette.
  const defile = [];
  for (const el of document.querySelectorAll('body *')) {
    const o = getComputedStyle(el).overflowX;
    if ((o === 'auto' || o === 'scroll') && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0) {
      defile.push(el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/)[0] : '') + ' (' + (el.scrollWidth - el.clientWidth) + ' px cachés)');
    }
  }
  return { debord_page: document.documentElement.scrollWidth - w, elements: [...new Set(out)].slice(0, 4), defile: [...new Set(defile)].slice(0, 3), texte: document.body.innerText.slice(0, 4000) };
}"""


def ecrans(profil: str, ligne_id: int | None):
    """(nom, chemin, actions) par profil. Une action = ('clic', sélecteur) ou ('attendre', ms)."""
    tab = lambda t: ("clic", f".tab-btn:has-text('{t}')")
    if profil == "direction":
        return [
            ("vue_usine_a_plat", "/cockpit/vue-usine", []),
            ("vue_usine_par_section", "/cockpit/vue-usine", [("clic", "button:has-text('Par section')")]),
            ("vue_usine_compact", "/cockpit/vue-usine", [("clic", "button:has-text('Par section')"), ("clic", "button:has-text('Compact')")]),
            ("alertes", "/cockpit/alertes", []),
            ("alertes_par_ligne_depliees", "/cockpit/alertes", [("clic", "button:has-text('tout déplier')")]),
            ("scoring_equipes", "/cockpit/scoring", []),
            ("rapports_par_ligne", "/cockpit/rapports", []),
            ("rapports_par_produit", "/cockpit/rapports", [tab("Par produit")]),
            ("rapports_vue_direction", "/cockpit/rapports", [tab("Vue Direction")]),
            ("rapports_historique", "/cockpit/rapports", [tab("Historique")]),
            ("rapports_pareto", "/cockpit/rapports", [tab("Pareto")]),
            ("rapports_smed", "/cockpit/rapports", [tab("Changements")]),
            ("rapports_trs", "/cockpit/rapports", [tab("TRS")]),
            ("admin_affectations", "/cockpit/admin", [tab("Affectations")]),
            ("admin_rapport_matinal", "/cockpit/admin", [tab("Rapport matinal")]),
            ("admin_parametres", "/cockpit/admin", [tab("Paramètres")]),
            ("labo_stock_produits", "/cockpit/labo/simulation-productible", []),
            ("andon", "/andon", [("attendre", 1500)]),
        ]
    if profil == "operateur":
        e = [("mes_lignes", "/operateur", []), ("mon_historique", "/operateur/historique", []), ("mes_performances", "/operateur/performances", [])]
        if ligne_id:
            e.append(("ecran_ligne", f"/operateur/lignes/{ligne_id}", []))
        return e
    return []


PLAN = [  # (profil de compte, tailles d'écran)
    ("direction", ["pc", "tv"]),
    ("operateur", ["tablette"]),
]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="https://localhost:5174")
    p.add_argument("--api", default="http://localhost:8001")
    p.add_argument("--admin", default=os.getenv("DEMO_ADMIN_USER", "admin"))
    p.add_argument("--admin-password", default=os.getenv("DEMO_ADMIN_PASSWORD"))
    p.add_argument("--operateur", default=None, help="matricule d'un opérateur fictif (défaut : le premier qui a une équipe)")
    p.add_argument("--sortie", default="screenshots", help="dossier PARENT ; chaque exécution crée dedans un sous-dossier horodaté (jamais d'écrasement)")
    p.add_argument("--reference", default="demo_reference.json")
    p.add_argument("--tailles", default="", help="restreindre (ex. tv,tablette)")
    a = p.parse_args()
    # *** AJOUT 2026-09-25 (demande utilisateur) *** : un sous-dossier horodaté par
    # exécution sous le dossier parent --sortie (backend/screenshots/ par défaut), pour
    # pouvoir relancer plusieurs séries de captures sans écraser les précédentes.
    sortie = Path(a.sortie) / datetime.now().strftime("%Y%m%d-%H%M%S")
    sortie.mkdir(parents=True, exist_ok=True)

    def connexion(ident, mdp):
        r = requests.post(f"{a.api.rstrip('/')}/auth/login", json={"identifiant": ident, "password": mdp}, timeout=30)
        r.raise_for_status()
        return r.json()

    ligne_id = None
    if Path(a.reference).exists():
        ref = json.loads(Path(a.reference).read_text(encoding="utf-8"))
        if not a.operateur:
            a.operateur = next(iter(ref["equipes"].values()))[0]
        ligne_id = next((int(k) for k, v in ref["equipes"].items() if a.operateur in v), None)
    a.operateur = a.operateur or "DEMO001"
    comptes = {"direction": connexion(a.admin, a.admin_password), "operateur": connexion(a.operateur, "Demo2026!")}
    # Les alertes sont calculées par un job : on le déclenche pour que l'écran Alertes ait du contenu.
    try:
        requests.post(f"{a.api.rstrip('/')}/alertes/run-now", headers={"Authorization": "Bearer " + comptes["direction"]["access_token"]}, timeout=120)
    except Exception:
        pass
    print(f"Opérateur photographié : {a.operateur} (ligne {ligne_id})")

    lignes_rapport, problemes, externes = [], 0, set()
    restreint = {t for t in a.tailles.split(",") if t}
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for profil, tailles in PLAN:
            for taille in tailles:
                if restreint and taille not in restreint:
                    continue
                ctx = nav.new_context(ignore_https_errors=True, **TAILLES[taille])
                c = comptes[profil]
                ctx.add_init_script(f"try {{ sessionStorage.setItem('token', {json.dumps(c['access_token'])}); sessionStorage.setItem('user', {json.dumps(json.dumps(c['user']))}); }} catch (e) {{ /* iframe isolée */ }}")
                for nom, chemin, actions in ecrans(profil, ligne_id):
                    if nom == "andon" and taille != "tv":
                        continue
                    page = ctx.new_page()
                    erreurs_console, echecs = [], []
                    page.on("console", lambda m, L=erreurs_console: L.append(m.text[:140]) if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
                    page.on("pageerror", lambda e, L=erreurs_console: L.append("exception : " + str(e)[:140]))
                    page.on("response", lambda r, L=echecs: (L.append(f"{r.status} {r.url.split('/api')[-1][:70]}") if "/api/" in r.url else externes.add(r.url.split('/')[2])) if r.status >= 400 else None)
                    page.goto(a.url.rstrip("/") + chemin, wait_until="networkidle", timeout=45000)
                    for genre, valeur in actions:
                        try:
                            if genre == "clic":
                                page.locator(valeur).first.click(timeout=4000)
                                page.wait_for_load_state("networkidle")
                            else:
                                page.wait_for_timeout(valeur)
                        except Exception as e:                    # bouton absent : on le note, on photographie quand même
                            echecs.append(f"action impossible {valeur} ({str(e).splitlines()[0][:60]})")
                    page.wait_for_timeout(500)
                    mesure = page.evaluate(JS_DEBORDEMENT)
                    fichier = sortie / f"{taille}_{profil}_{nom}.png"
                    page.screenshot(path=str(fichier), full_page=(taille != "tv"))
                    notes = []
                    if mesure["debord_page"] > 2:
                        notes.append(f"DÉFILEMENT HORIZONTAL de {mesure['debord_page']} px")
                    if mesure["defile"] and taille == "tablette":       # sur tablette, aucun tableau ne doit défiler de côté
                        notes.append("DÉFILEMENT HORIZONTAL dans : " + ", ".join(mesure["defile"]))
                    if mesure["elements"]:
                        notes.append("dépasse à droite : " + ", ".join(mesure["elements"]))
                    if erreurs_console:
                        notes.append("erreurs JS : " + " | ".join(erreurs_console[:2]))
                    if echecs:
                        notes.append("échecs API/actions : " + " | ".join(echecs[:3]))
                    if "Chargement" in mesure["texte"]:
                        notes.append("reste sur « Chargement… »")
                    problemes += bool(notes)
                    lignes_rapport.append((taille, profil, nom, fichier.name, notes))
                    print(f"{'⚠' if notes else '✓'} {taille:<9}{nom:<28}" + (" ; ".join(notes) if notes else ""))
                    page.close()
                ctx.close()
        nav.close()

    md = [f"# Captures d'écran — {datetime.now():%d/%m/%Y %H:%M}", "", f"{len(lignes_rapport)} écrans, {problemes} avec remarque(s).", "",
          "| Taille | Compte | Écran | Fichier | Remarques |", "|---|---|---|---|---|"]
    for t, pr, n, f, notes in lignes_rapport:
        md.append(f"| {t} | {pr} | {n} | {f} | {'; '.join(notes) or 'RAS'} |")
    if externes:
        md += ["", f"Ressources externes indisponibles : {', '.join(sorted(externes))} (polices chargées depuis Internet : sans accès web, "
               "les écrans retombent sur la police système -- vérifier sur le réseau de l'atelier)."]
        print("Ressources externes indisponibles :", ", ".join(sorted(externes)))
    (sortie / "rapport_captures.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n{len(lignes_rapport)} captures dans {sortie}/ — {problemes} écran(s) avec remarque(s). Détail : {sortie}/rapport_captures.md")


if __name__ == "__main__":
    main()