import re
import json
import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Any

# Configuration des priorités pour éviter les recalculs
PRIO_MAP = {"Certifié": 2, "À valider": 1, "Rejeté": 0}

def _clamp(x: float, lo: int = 0, hi: int = 100) -> int:
    """Limite une valeur entre lo et hi après arrondi."""
    return int(max(lo, min(hi, round(x))))

def _is_missing(v: Any) -> bool:
    """Vérifie si une valeur est considérée comme absente."""
    if pd.isna(v):
        return True
    s = str(v).strip().lower()
    return s in {"", "—", "none", "null", "nan"}

def _get_value(passport_df: pd.DataFrame, attr: str) -> Optional[Any]:
    """Récupère la meilleure valeur disponible selon le statut de validation."""
    sub = passport_df[passport_df["Attribut"] == attr]
    if sub.empty:
        return None

    # Tri par priorité sans créer de colonne temporaire coûteuse
    sub = sub.assign(prio=sub["Statut de Validation"].get(PRIO_MAP, 0))
    best_row = sub.sort_values("prio", ascending=False).iloc[0]
    
    return best_row["Donnée Site"] if PRIO_MAP.get(best_row["Statut de Validation"], 0) > 0 else None

def _presence(passport_df: pd.DataFrame, attr: str) -> bool:
    return not _is_missing(_get_value(passport_df, attr))

def _presence_prefix(passport_df: pd.DataFrame, prefix: str) -> bool:
    """Vérifie si au moins un attribut commençant par prefix contient une donnée."""
    attrs = passport_df.loc[passport_df["Attribut"].astype(str).str.startswith(prefix), "Attribut"].unique()
    return any(_presence(passport_df, a) for a in attrs)

def _check_format(v: str, length: int) -> bool:
    """Vérifie si une chaîne est composée de n chiffres."""
    if _is_missing(v): return False
    digits = re.sub(r"\D", "", str(v))
    return len(digits) == length

def score_syntaxe(passport_df: pd.DataFrame, jsonld_gold: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Calcule un score de qualité syntaxique et structurelle.
    """
    stats = {"warnings": 0, "errors": 0, "hard_gate": 1}
    
    # --- Validation JSON-LD (Structure)
    if jsonld_gold is not None:
        if not isinstance(jsonld_gold, dict):
            stats["hard_gate"] = 0
        else:
            ctx = jsonld_gold.get("@context", "")
            typ = jsonld_gold.get("@type", "")
            
            if not (isinstance(ctx, str) and ctx.startswith("http")):
                stats["hard_gate"] = 0
            if typ != "Organization":
                stats["hard_gate"] = 0
            
            # Warnings de structure
            if "name" not in jsonld_gold: stats["warnings"] += 1
            if "identifier" in jsonld_gold and not isinstance(jsonld_gold["identifier"], (list, dict)):
                stats["warnings"] += 1
    else:
        stats["warnings"] += 2 # Pénalité pour absence de source JSON-LD

    if stats["hard_gate"] == 0:
        return {"score": 0, "details": stats}

    # --- Validation des données (Métier)
    has_name = _presence(passport_df, "name")
    has_url = _presence(passport_df, "url") or _presence_prefix(passport_df, "subjectOf")
    has_ids = _presence(passport_df, "identifier.siren") or _presence_prefix(passport_df, "identifier.siret")

    required_ok = 1 if (has_name and has_url) else 0
    
    # Validation formats SIREN/SIRET
    siren = _get_value(passport_df, "identifier.siren")
    if siren and not _check_format(siren, 9): stats["warnings"] += 2
    
    sirets = passport_df.loc[passport_df["Attribut"].astype(str).str.startswith("identifier.siret"), "Attribut"]
    for s in sirets:
        if not _check_format(_get_value(passport_df, s), 14):
            stats["warnings"] += 1

    # --- Calcul du Score Final
    score = 100 - (15 * (1 - required_ok)) - (5 * stats["warnings"]) - (25 * stats["errors"])
    
    return {
        "score": _clamp(score),
        "details": {
            **stats,
            "required_fields_ok": required_ok,
            "has_identifiers": int(has_ids)
        }
    }
