import pandas as pd
import logging
from engine.fuzzy import mark_fuzzy
from engine.utils import load_config

cfg = load_config()

FX_RATES = {"GBP": 1.0, "USD": 0.79, "EUR": 0.86}


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


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # -------------------------
    # Dates (FIXED)
    # -------------------------
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    else:
        df["date"] = pd.NaT

    df["date_missing"] = df["date"].isna()

    # -------------------------
    # Amounts
    # -------------------------
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    else:
        df["amount"] = 0.0

    # Debit / Credit detection
    if df["amount"].mean() < 0:
        df["polarity"] = "debit"
        df["amount"] = df["amount"].abs()
    else:
        df["polarity"] = "credit"

    # -------------------------
    # Currency
    # -------------------------
    if "currency" not in df.columns:
        df["currency"] = "GBP"

    df["amount_gbp"] = df.apply(
        lambda r: r["amount"] * FX_RATES.get(r["currency"], 1.0),
        axis=1
    )

    df["amount_cent"] = (df["amount_gbp"] * 100).round().astype(int)

    # -------------------------
    # References
    # -------------------------
    if "reference" not in df.columns:
        df["reference"] = ""

    df["ref_norm"] = df["reference"].apply(normalise_reference)

    return df


def apply_matching(bank_df, ledger_df, gateway_df):
    bank_df = bank_df.copy(); bank_df["source"] = "Bank"
    ledger_df = ledger_df.copy(); ledger_df["source"] = "Ledger"
    gateway_df = gateway_df.copy(); gateway_df["source"] = "Gateway"

    master = pd.concat([bank_df, ledger_df, gateway_df], ignore_index=True)
    master = prepare_dataframe(master)

    # Preserve original index
    master["_idx"] = master.index

    # -------------------------
    # Self-join on amount
    # -------------------------
    candidates = master.merge(
        master,
        on="amount_cent",
        suffixes=("", "_other")
    )

    # Remove self matches
    candidates = candidates[candidates["_idx"] != candidates["_idx_other"]]

    # Cross-source only
    candidates = candidates[candidates["source"] != candidates["source_other"]]

    # -------------------------
    # Classify
    # -------------------------
    def row_reason(row):
        amount_ok = True
        date_ok = date_matches(row["date"], row["date_other"])
        ref_ok = reference_matches(row["ref_norm"], row["ref_norm_other"])
        return classify_match(amount_ok, date_ok, ref_ok)

    classified = candidates.apply(
        lambda r: pd.Series(row_reason(r), index=["final_status", "reason"]),
        axis=1
    )

    candidates = pd.concat([candidates, classified], axis=1)

    # Priority
    priority = {
        "Matched": 3,
        "Partially Matched": 2,
        "Unmatched": 1
    }
    candidates["priority"] = candidates["final_status"].map(priority)

    best = (
        candidates.sort_values("priority", ascending=False)
        .groupby("_idx")
        .first()
    )

    master.loc[best.index, "final_status"] = best["final_status"]
    master.loc[best.index, "reason"] = best["reason"]

    master["final_status"].fillna("Unmatched", inplace=True)
    master["reason"].fillna("Exception – No Match Found", inplace=True)

    return (
        master,
        master[master["final_status"] == "Matched"],
        master[master["final_status"] == "Partially Matched"],
        master[master["final_status"] == "Unmatched"],
    )
