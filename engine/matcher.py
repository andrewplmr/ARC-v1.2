import pandas as pd
import logging
from engine.fuzzy import mark_fuzzy
from engine.utils import load_config

cfg = load_config()

FX_RATES = {"GBP": 1.0, "USD": 0.79, "EUR": 0.86}

def amount_matches(a, b):
    return a == b

def date_matches(d1, d2, tolerance_days=0):
    if pd.isna(d1) or pd.isna(d2):
        return False
    return abs((d1 - d2).days) <= tolerance_days

def reference_matches(r1, r2):
    if not r1 or not r2:
        return False
    return r1 == r2

def normalise_reference(x):
    if pd.isna(x):
        return ""
    s = str(x).lower()
    return "".join(ch for ch in s if ch.isalnum())

def classify_match(amount_ok, date_ok, ref_ok):
    if amount_ok and date_ok and ref_ok:
        return "Matched", "Exact Date/Amount/Ref Match"

    if amount_ok and date_ok:
        return "Partially Matched", "Exact Amount/Date Match"

    if amount_ok and ref_ok:
        return "Partially Matched", "Exact Amount/Ref Match"

    if ref_ok:
        return "Partially Matched", "Partial Ref Match"

    return "Unmatched", "Exception – Amount/Ref"

def prepare_dataframe(df):
    df = df.copy()

    # Dates
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    # Amounts
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    else:
        df["amount"] = 0.0

    # Debit / Credit detection (NEW)
    if df["amount"].mean() < 0:
        df["polarity"] = "debit"
        df["amount"] = df["amount"].abs()
    else:
        df["polarity"] = "credit"

    # Currency conversion (NEW)
    if "currency" not in df.columns:
        df["currency"] = "GBP"
    df["amount_gbp"] = df.apply(
        lambda r: r["amount"] * FX_RATES.get(r["currency"], 1.0), axis=1
    )

    df["amount_cent"] = (df["amount_gbp"] * 100).round().astype(int)

    if "reference" not in df.columns:
        df["reference"] = ""

    df["ref_norm"] = df["reference"].apply(normalise_reference)

    return df

def make_match_key(df):
    df["match_key"] = (
        df["amount_cent"].astype(str) + "_" +
        df["ref_norm"] + "_" +
        df["date"].astype(str)
    )
    return df

def apply_matching(bank_df, ledger_df, gateway_df):
    bank_df = bank_df.copy(); bank_df["source"] = "bank"
    ledger_df = ledger_df.copy(); ledger_df["source"] = "ledger"
    gateway_df = gateway_df.copy(); gateway_df["source"] = "gateway"

    master = pd.concat([bank_df, ledger_df, gateway_df], ignore_index=True)
    master = prepare_dataframe(master)
    master = make_match_key(master)

    grouped = master.groupby("match_key")["source"].apply(set).reset_index()
    reconciled_keys = set(
        grouped[grouped["source"].apply(lambda x: x == {"bank","ledger","gateway"})]["match_key"]
    )

    master["final_status"] = "Unmatched"
    master.loc[master["match_key"].isin(reconciled_keys), "final_status"] = "Matched"

    master = mark_fuzzy(master)
    master.loc[master["final_status"]=="Matched", "fuzzy_status"] = "NotFuzzy"

    master["final_status"] = master.apply(
        lambda r: "Matched" if r["final_status"]=="Matched"
        else "FuzzyMatched" if r.get("fuzzy_status")=="FuzzyMatched"
        else "Unmatched",
        axis=1
    )

    return (
        master,
        master[master["final_status"]=="Matched"],
        master[master["final_status"]=="FuzzyMatched"],
        master[master["final_status"]=="Unmatched"]
    )


