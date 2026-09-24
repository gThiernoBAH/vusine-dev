#!/usr/bin/env python3
"""investigate_usine.py -- LECTURE SEULE.
python3 investigate_usine.py                     -> sections 1 et 2
python3 investigate_usine.py --fields follow.production follow.production.line mrp.planning"""
import os, sys, argparse, xmlrpc.client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.settings import settings as S

common = xmlrpc.client.ServerProxy(f"{S.ODOO_CLOUD_URL}/xmlrpc/2/common")
uid = common.authenticate(S.ODOO_CLOUD_DB, S.ODOO_CLOUD_USER, S.ODOO_CLOUD_API_KEY, {})
proxy = xmlrpc.client.ServerProxy(f"{S.ODOO_CLOUD_URL}/xmlrpc/2/object")

def call(model, method, args, kw=None):
    kw = dict(kw or {}); kw.setdefault("context", {"active_test": False})
    return proxy.execute_kw(S.ODOO_CLOUD_DB, uid, S.ODOO_CLOUD_API_KEY, model, method, args, kw)

def menus():
    print("=== 1. MENUS -> MODÈLES ===")
    dom = ["|", "|", ("complete_name", "ilike", "Fabrication"),
           ("complete_name", "ilike", "Manufactur"), ("complete_name", "ilike", "Rapports impressions")]
    rows = call("ir.ui.menu", "search_read", [dom], {"fields": ["complete_name", "action"]})
    act = {r["id"]: int(r["action"].split(",")[1]) for r in rows
           if r.get("action") and r["action"].startswith("ir.actions.act_window,")}
    res = {a["id"]: a["res_model"] for a in call("ir.actions.act_window", "read",
           [list(set(act.values()))], {"fields": ["res_model"]})} if act else {}
    for r in sorted(rows, key=lambda x: x["complete_name"]):
        if r.get("action"):
            print(f"{r['complete_name']:70s} -> {res.get(act.get(r['id']), r['action'])}")

def modeles():
    print("\n=== 2. MODÈLES CANDIDATS (nb d'enregistrements) ===")
    vus = {}
    for kw in ["rebut", "scrap", "recycl", "ravitaill", "follow", "saisie", "moule", "mold", "loss", "perte", "waste"]:
        for m in call("ir.model", "search_read", [["|", ("model", "ilike", kw), ("name", "ilike", kw)]],
                      {"fields": ["model", "name", "transient"]}):
            if not m["transient"]:
                vus[m["model"]] = m["name"]
    for model, nom in sorted(vus.items()):
        try:
            n = call(model, "search_count", [[]])
        except Exception as e:
            n = f"erreur: {str(e)[:40]}"
        print(f"{model:45s} {nom:40s} {n}")

def champs(liste):
    for mod in liste:
        print(f"\n=== 3. CHAMPS de {mod} -- {call(mod, 'search_count', [[]])} enregistrement(s) ===")
        f = call(mod, "fields_get", [], {"attributes": ["string", "type", "relation"]})
        for name, d in sorted(f.items()):
            rel = f" -> {d['relation']}" if d.get("relation") else ""
            print(f"{name:35s} {d['type']:10s} {d['string']}{rel}")

def echantillon(model, n, champs):
    for r in call(model, "search_read", [[]], {"fields": champs.split(","), "limit": int(n), "order": "id desc"}):
        print(r)

def groupe(model, champ):
    for g in call(model, "read_group", [[], [champ], [champ]], {"lazy": False}):
        print(f"{str(g.get(champ)):50s} {g['__count']}")            

STANDARD = {"base", "mail", "product", "uom", "stock", "mrp", "account", "resource", "web",
            "purchase", "sale", "sale_stock", "purchase_stock", "stock_account", "mrp_account",
            "analytic", "portal", "rating", "utm", "digest", "sms", "iap", "calendar", "hr",
            "contacts", "base_setup", "spreadsheet", "board"}

def custom(model):
    rows = call("ir.model.fields", "search_read", [[("model", "=", model)]],
                {"fields": ["name", "field_description", "ttype", "relation", "modules"]})
    print(f"\n=== CHAMPS NON STANDARD sur {model} ===")
    for r in sorted(rows, key=lambda x: x["name"]):
        mods = {m.strip() for m in (r.get("modules") or "").split(",") if m.strip()}
        if not mods or (mods - STANDARD):
            rel = f" -> {r['relation']}" if r.get("relation") else ""
            print(f"{r['name']:35s} {r['ttype']:10s} {r['field_description']}{rel}  [{r.get('modules')}]")

import json

def recherche(model, domain, champs, n):
    dom = json.loads(domain)
    print(f"--- {model} : {call(model, 'search_count', [dom])} enregistrement(s) correspondant(s), {n} affichés ---")
    for r in call(model, "search_read", [dom], {"fields": champs.split(","), "limit": int(n), "order": "id desc"}):
        print(r)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fields", nargs="*", default=[])
    ap.add_argument("--custom", nargs="*", default=[])
    ap.add_argument("--sample", nargs=3, metavar=("MODELE", "N", "CHAMPS"))
    ap.add_argument("--group", nargs=2, metavar=("MODELE", "CHAMP"))
    ap.add_argument("--search", nargs=4, metavar=("MODELE", "DOMAINE_JSON", "CHAMPS", "N"))
    a = ap.parse_args()
    if not uid: sys.exit("Authentification Odoo refusée")
    if a.search: recherche(*a.search)
    elif a.sample: echantillon(*a.sample)
    elif a.group: groupe(*a.group)
    elif a.custom: [custom(m) for m in a.custom]
    elif a.fields: champs(a.fields)
    else: menus(); modeles()