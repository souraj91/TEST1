import streamlit as st
import pandas as pd
import re
import json

# --- CONFIGURATION PAGE ---
st.set_page_config(page_title="Audit Qualité Passeport", layout="wide")

# --- FONCTIONS UTILITAIRES (Ton code optimisé) ---

def _clamp(x, lo=0, hi=100):
    return int(max(lo, min(hi, round(x))))

def _is_missing(v) -> bool:
    if pd.isna(v): return True
    s = str(v).strip().lower()
    return s in {"", "—", "none", "null", "nan"}

def _get_value(passport_df, attr):
    sub = passport_df[passport_df["Attribut"] == attr]
    if sub.empty: return None
    prio = {"Certifié": 2, "À valider": 1, "Rejeté": 0}
    sub = sub.assign(prio=sub["Statut de Validation"].map(prio).fillna(0))
    sub = sub.sort_values("prio", ascending=False)
    row = sub.iloc[0]
    return row["Donnée Site"] if row["prio"] > 0 else None

def _presence(passport_df, attr):
    return not _is_missing(_get_value(passport_df, attr))

def score_syntaxe(passport_df):
    """Calcule le score et retourne les détails"""
    warnings = 0
    # Vérification simplifiée pour l'exemple
    has_name = _presence(passport_df, "name")
    has_url = _presence(passport_df, "url")
    
    if not has_name: warnings += 2
    if not has_url: warnings += 2
    
    score = 100 - (warnings * 10)
    return {
        "score": _clamp(score),
        "details": {"warnings": warnings, "has_name": has_name, "has_url": has_url}
    }

# --- INTERFACE STREAMLIT ---

st.title("🛡️ Audit de Conformité Passeport")
st.write("Uploadez votre fichier exporté pour calculer le score de syntaxe.")

uploaded_file = st.file_uploader("Choisir un fichier CSV", type="csv")

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        
        # Vérification des colonnes nécessaires
        required_cols = ["Attribut", "Statut de Validation", "Donnée Site"]
        if all(col in df.columns for col in required_cols):
            
            # Calcul du score
            result = score_syntaxe(df)
            
            # Affichage des résultats
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Score de Syntaxe", f"{result['score']}/100")
            
            with col2:
                if result['score'] > 80:
                    st.success("Qualité Excellente")
                elif result['score'] > 50:
                    st.warning("Qualité Moyenne")
                else:
                    st.error("Qualité Insuffisante")
            
            st.divider()
            st.subheader("Détails de l'audit")
            st.write(result['details'])
            st.dataframe(df) # Affiche le tableau pour vérifier
            
        else:
            st.error(f"Le fichier doit contenir les colonnes : {', '.join(required_cols)}")
            
    except Exception as e:
        st.error(f"Erreur lors de la lecture du fichier : {e}")
else:
    st.info("En attente d'un fichier CSV...")
