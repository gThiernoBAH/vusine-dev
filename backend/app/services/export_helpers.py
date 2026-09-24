"""
export_helpers.py -- mise en forme partagée de tous les exports Vusine (rapports
Direction et écrans Labo) : pied de page PDF, arrondis, feuille Excel exploitable.

*** AJOUT 2026-09-23 *** : avant ce fichier, chaque export (export_service.py,
labo_export_service.py) redéfinissait sa propre mise en page PDF/Excel, sans pied de
page ni arrondi -- des nombres comme 16494.600000000002 sortaient tels quels. Point
d'entrée unique désormais : build_pdf() et build_excel() prennent un DataFrame déjà
préparé (colonnes déjà renommées en français par l'appelant) et produisent un document
prêt à distribuer.
"""
from datetime import datetime
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

COULEUR_MARQUE = colors.HexColor("#1B4D7A")
COULEUR_BORDURE = colors.HexColor("#E2E8F0")
COULEUR_ALTERNEE = colors.HexColor("#F4F6F9")
COULEUR_MUTEE = colors.HexColor("#64748B")


def arrondir_dataframe(df: pd.DataFrame, decimales: int = 2) -> pd.DataFrame:
    """Arrondit les colonnes réellement décimales (float) -- les colonnes entières
    (dtype int) restent des entiers exacts, jamais réécrites en ",00". `16494.6000000`
    devient `16494.6`, jamais affiché avec 12 décimales parasites."""
    df = df.copy()
    for col in df.select_dtypes(include="float").columns:
        df[col] = df[col].round(decimales)
    return df


def fmt_fr(valeur, decimales: int = 2, fixe: bool = False) -> str:
    """Nombre à la française (espace des milliers, virgule décimale) pour l'affichage
    PDF. Les entiers n'affichent jamais de décimale inutile."""
    # pd.NA : valeur manquante des colonnes entières « nullables » (dtype Int64), ajoutées
    # le 2026-09-24 pour les montants entiers pouvant être absents (ex. coût non calculable).
    if valeur is None or valeur is pd.NA or (isinstance(valeur, float) and pd.isna(valeur)):
        return "—"
    # Scalaires numpy (int64, float64, bool_) -> types Python : sans cela, un entier
    # pandas n'était jamais reconnu par isinstance(int) ci-dessous et s'affichait brut
    # (« 1234567 » au lieu de « 1 234 567 »). Corrigé le 2026-09-24.
    if hasattr(valeur, "item"):
        valeur = valeur.item()
    if isinstance(valeur, bool):
        return "Oui" if valeur else "Non"
    if isinstance(valeur, (int, float)):
        arrondi = round(float(valeur), decimales)
        if fixe and decimales > 0:
            # Colonne à décimales déclarées (ex. pourcentages) : toujours le même nombre de
            # décimales, « 97,0 » et non « 97 » à côté de « 92,2 » (2026-09-24).
            return f"{arrondi:,.{decimales}f}".replace(",", " ").replace(".", ",")
        if arrondi == int(arrondi):
            return f"{int(arrondi):,}".replace(",", " ")
        texte = f"{arrondi:,.{decimales}f}".rstrip("0").rstrip(".")
        entier, _, decimale = texte.partition(".")
        return entier.replace(",", " ") + ("," + decimale if decimale else "")
    return str(valeur)


class _CanvasNumerote(pdfcanvas.Canvas):
    """Canvas ReportLab qui ajoute 'Vusine · date/heure de génération · Page X / N' en
    pied de page sur chaque page. N (le nombre total de pages) n'est connu qu'une fois
    tout le document construit -- technique standard de ReportLab en deux passes : on
    mémorise l'état de chaque page avec save(), puis on écrit le pied de page une fois
    N connu, avant de vraiment fermer chaque page."""

    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._etats_pages = []

    def showPage(self):
        self._etats_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        nb_pages = len(self._etats_pages)
        for etat in self._etats_pages:
            self.__dict__.update(etat)
            self._dessiner_pied_de_page(nb_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _dessiner_pied_de_page(self, nb_pages):
        largeur, _ = self._pagesize
        horodatage = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.setFont("Helvetica", 7)
        self.setFillColor(COULEUR_MUTEE)
        self.drawString(1.5 * cm, 1 * cm, "Vusine")
        self.drawCentredString(largeur / 2, 1 * cm, f"Généré le {horodatage}")
        self.drawRightString(largeur - 1.5 * cm, 1 * cm, f"Page {self._pageNumber} / {nb_pages}")
        self.setStrokeColor(COULEUR_BORDURE)
        self.line(1.5 * cm, 1.4 * cm, largeur - 1.5 * cm, 1.4 * cm)


def build_pdf(titre: str, df: pd.DataFrame, sous_titre: str | None = None,
               paysage: bool = True, decimales: dict[str, int] | None = None) -> bytes:
    """`decimales` : {nom_colonne: nb_decimales} pour affiner colonne par colonne (par
    défaut 2). Les colonnes non numériques sont ignorées, sans erreur."""
    decimales = decimales or {}
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4) if paysage else A4,
        topMargin=1.5 * cm, bottomMargin=2 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    elements = [Paragraph(f"Vusine — {titre}", styles["Title"])]
    if sous_titre:
        elements.append(Paragraph(sous_titre, styles["Normal"]))
    elements.append(Spacer(1, 0.5 * cm))

    entetes = list(df.columns)
    lignes = [
        [fmt_fr(v, decimales.get(col, 2), fixe=decimales.get(col, 0) > 0) for col, v in zip(entetes, row)]
        for row in df.itertuples(index=False, name=None)
    ]
    table = Table([entetes] + lignes, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COULEUR_MARQUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, COULEUR_BORDURE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COULEUR_ALTERNEE]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
    ]))
    elements.append(table)
    doc.build(elements, canvasmaker=_CanvasNumerote)
    return buffer.getvalue()


def build_excel(titre: str, df: pd.DataFrame, sous_titre: str | None = None,
                 decimales: dict[str, int] | None = None) -> bytes:
    """En-tête figé, filtres automatiques, colonnes numériques arrondies (valeurs
    réelles, toujours calculables dans Excel -- pas du texte) et largeur de colonne
    ajustée au contenu."""
    decimales = decimales or {}
    df = arrondir_dataframe(df)

    wb = Workbook()
    ws = wb.active
    ws.title = titre[:31] or "Export"

    ligne_titre = 1
    ws.cell(row=ligne_titre, column=1, value=f"Vusine — {titre}")
    ws.cell(row=ligne_titre, column=1).font = Font(bold=True, size=13)
    if sous_titre:
        ligne_titre += 1
        ws.cell(row=ligne_titre, column=1, value=sous_titre).font = Font(italic=True, color="64748B")
    ligne_horodatage = ligne_titre + 1
    ws.cell(row=ligne_horodatage, column=1, value=f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    ws.cell(row=ligne_horodatage, column=1).font = Font(size=9, color="64748B")

    ligne_entete = ligne_horodatage + 2
    entetes = list(df.columns)
    for i, nom in enumerate(entetes, start=1):
        cell = ws.cell(row=ligne_entete, column=i, value=nom)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1B4D7A", end_color="1B4D7A", fill_type="solid")
        cell.alignment = Alignment(vertical="center")

    colonnes_entieres = set(df.select_dtypes(include="integer").columns)
    colonnes_decimales = set(df.select_dtypes(include="float").columns)
    for i_ligne, row in enumerate(df.itertuples(index=False, name=None), start=ligne_entete + 1):
        for i_col, (nom, valeur) in enumerate(zip(entetes, row), start=1):
            cell = ws.cell(row=i_ligne, column=i_col, value=(None if pd.isna(valeur) else valeur))
            # Format Excel choisi par le TYPE réel de la colonne : une colonne entière
            # (ex. "Jours observés") ne montre jamais ",00" -- seules les colonnes
            # réellement décimales suivent `decimales` (2 par défaut).
            if nom in colonnes_entieres:
                cell.number_format = "#,##0"
            elif nom in colonnes_decimales:
                dec = decimales.get(nom, 2)
                cell.number_format = "#,##0" if dec == 0 else "#,##0." + "0" * dec

    derniere_ligne = ligne_entete + len(df)
    derniere_colonne = get_column_letter(len(entetes))
    ws.freeze_panes = f"A{ligne_entete + 1}"
    ws.auto_filter.ref = f"A{ligne_entete}:{derniere_colonne}{derniere_ligne}"

    colonnes_numeriques = colonnes_entieres | colonnes_decimales
    for i, nom in enumerate(entetes, start=1):
        largeur_contenu = max([len(str(nom))] + [len(fmt_fr(v) if nom in colonnes_numeriques else str(v))
                                                   for v in df[nom].head(200)] or [10])
        ws.column_dimensions[get_column_letter(i)].width = min(max(largeur_contenu + 2, 10), 45)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_csv(df: pd.DataFrame) -> bytes:
    """Séparateur ';', virgule décimale (`decimal=','`) : ouverture directe et correcte
    dans Excel en paramètres régionaux français."""
    df = arrondir_dataframe(df)
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
