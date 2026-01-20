import re
import json
import numpy as np
import pandas as pd

STATUSES = ["Certifié", "À valider", "Rejeté"]

def _clamp(x, lo=0, hi=100):
    return int(max(lo, min(hi, round(x))))

def _norm_str(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)  # retire ponctuation simple
    return s

def _is_missing(v) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s == "—" or s.lower() in {"none", "null", "nan"}

def _get_value(passport_df: pd.DataFrame, attr: str):
    """Renvoie la meilleure valeur (Certifié > À valider) pour un attribut exact."""
    sub = passport_df[passport_df["Attribut"] == attr]
    if sub.empty:
        return None

    prio = {"Certifié": 2, "À valider": 1, "Rejeté": 0}
    sub = sub.copy()
    sub["__prio"] = sub["Statut de Validation"].map(prio).fillna(0)
    sub = sub.sort_values("__prio", ascending=False)
    row = sub.iloc[0]
    if row["__prio"] == 0:
        return None
    return row["Donnée Site"]

def _has_any_attr_prefix(passport_df: pd.DataFrame, prefix: str) -> bool:
    return passport_df["Attribut"].astype(str).str.startswith(prefix).any()

def _iter_attrs_by_prefix(passport_df: pd.DataFrame, prefix: str):
    return passport_df.loc[passport_df["Attribut"].astype(str).str.startswith(prefix), "Attribut"].tolist()

def _cert_ratio(passport_df: pd.DataFrame) -> float:
    if passport_df.empty:
        return 0.0
    return float((passport_df["Statut de Validation"] == "Certifié").sum()) / float(len(passport_df))

def _presence(passport_df: pd.DataFrame, attr: str) -> bool:
    v = _get_value(passport_df, attr)
    return not _is_missing(v)

def _presence_prefix(passport_df: pd.DataFrame, prefix: str) -> bool:
    for a in _iter_attrs_by_prefix(passport_df, prefix):
        if _presence(passport_df, a):
            return True
    return False

def _has_source_wikidata(passport_df: pd.DataFrame) -> bool:
    col = "Source Wikidata (ID)"
    if col not in passport_df.columns:
        return False
    return (passport_df[col].astype(str).str.strip() != "—").any()

def _has_source_insee(passport_df: pd.DataFrame) -> bool:
    siren_col = "Source INSEE/SIREN"
    siret_col = "Source INSEE/SIRET"
    ok1 = siren_col in passport_df.columns and (passport_df[siren_col].astype(str).str.strip() != "—").any()
    ok2 = siret_col in passport_df.columns and (passport_df[siret_col].astype(str).str.strip() != "—").any()
    return bool(ok1 or ok2)

def _looks_like_siren(v: str) -> bool:
    if _is_missing(v):
        return False
    digits = re.sub(r"\D", "", str(v))
    return len(digits) == 9

def _looks_like_siret(v: str) -> bool:
    if _is_missing(v):
        return False
    digits = re.sub(r"\D", "", str(v))
    return len(digits) == 14
1.2 Syntaxe (0–100)
On ne “re-parse” pas forcément le JSON-LD ici (tu peux le faire si tu veux).
On calcule des flags à partir du passeport : présence de name, url (ou subjectOf), @type implicite (toujours Organization dans ton produit), identifiants, champs critiques non vides.

Copydef score_syntaxe(passport_df: pd.DataFrame, jsonld_gold: dict | None = None) -> dict:
    """
    Retourne: {"score": int, "details": {...}}
    hard_gate: JSON valide + context + type.
    Si tu fournis jsonld_gold, on s'en sert pour valider JSON/structure.
    """
    # --- hard gate
    is_valid_json = 1
    has_context = 1
    has_type = 1

    warnings = 0
    errors = 0

    if jsonld_gold is not None:
        # JSON parsable = hard gate
        try:
            json.dumps(jsonld_gold)
        except Exception:
            is_valid_json = 0

        ctx = jsonld_gold.get("@context") if isinstance(jsonld_gold, dict) else None
        typ = jsonld_gold.get("@type") if isinstance(jsonld_gold, dict) else None
        has_context = 1 if (isinstance(ctx, str) and ctx.startswith("http")) else 0
        has_type = 1 if (typ == "Organization") else 0

        # warnings simples
        if has_type and "name" not in jsonld_gold:
            warnings += 1
        if has_type and "identifier" in jsonld_gold and not isinstance(jsonld_gold["identifier"], list):
            warnings += 1

    else:
        # sans JSON-LD, on n'a pas de vrai parse check -> on suppose OK mais fragile
        warnings += 2

    hard_gate = min(is_valid_json, has_context, has_type)
    if hard_gate == 0:
        return {"score": 0, "details": {"hard_gate": 0, "warnings": warnings, "errors": errors}}

    # --- required fields
    has_name = _presence(passport_df, "name")
    has_url = _presence(passport_df, "url")
    has_subjectof = _presence_prefix(passport_df, "subjectOf")
    has_identifier = _presence(passport_df, "identifier.siren") or _presence_prefix(passport_df, "identifier.siret")

    required_fields_ok = 1 if (has_name and (has_url or has_subjectof)) else 0
    no_empty_critical = 1 if (has_name and (has_url or has_subjectof) and (has_identifier or True)) else 1  # identifiant pas forcément obligatoire

    # cohérence format siren/siret = warnings
    siren = _get_value(passport_df, "identifier.siren")
    if siren and not _looks_like_siren(siren):
        warnings += 2
    for a in _iter_attrs_by_prefix(passport_df, "identifier.siret"):
        v = _get_value(passport_df, a)
        if v and not _looks_like_siret(v):
            warnings += 2

    score = 100 \
        - 15 * (1 - required_fields_ok) \
        - 15 * (1 - no_empty_critical) \
        - 5 * warnings \
        - 25 * errors

    return {
        "score": _clamp(score),
        "details": {
            "hard_gate": 1,
            "required_fields_ok": required_fields_ok,
            "no_empty_critical": no_empty_critical,
            "warnings_count": warnings,
            "errors_count": errors,
        }
    }
