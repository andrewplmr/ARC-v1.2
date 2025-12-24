def apply_matching(bank_df, ledger_df, gateway_df):
    bank_df = bank_df.copy(); bank_df["source"] = "Bank"
    ledger_df = ledger_df.copy(); ledger_df["source"] = "Ledger"
    gateway_df = gateway_df.copy(); gateway_df["source"] = "Gateway"

    master = pd.concat([bank_df, ledger_df, gateway_df], ignore_index=True)
    master = prepare_dataframe(master)

    # Preserve original index for correct self-join handling
    master["_idx"] = master.index

    # --- Self-join on amount to find candidate matches ---
    candidates = master.merge(
        master,
        on="amount_cent",
        suffixes=("", "_other")
    )

    # Remove self matches
    candidates = candidates[candidates["_idx"] != candidates["_idx_other"]]

    # Only cross-source comparisons
    candidates = candidates[candidates["source"] != candidates["source_other"]]

    # Classify matches
    def row_reason(row):
        amount_ok = True  # Same amount_cent by construction
        date_ok = date_matches(row["date"], row["date_other"])
        ref_ok = reference_matches(row["ref_norm"], row["ref_norm_other"])
        return classify_match(amount_ok, date_ok, ref_ok)

    classified = candidates.apply(
        lambda r: pd.Series(row_reason(r), index=["final_status", "reason"]),
        axis=1
    )

    candidates = pd.concat([candidates, classified], axis=1)

    # Best result per row (prefer strongest match)
    priority = {
        "Matched": 3,
        "Partially Matched": 2,
        "Unmatched": 1
    }
    candidates["priority"] = candidates["final_status"].map(priority)

    # Group by original transaction index (_idx)
    best = (
        candidates.sort_values("priority", ascending=False)
        .groupby("_idx")
        .first()
    )

    # Assign best match back to master
    master.loc[best.index, "final_status"] = best["final_status"]
    master.loc[best.index, "reason"] = best["reason"]

    # Fill unmatched
    master["final_status"].fillna("Unmatched", inplace=True)
    master["reason"].fillna("Exception – No Match Found", inplace=True)

    return (
        master,
        master[master["final_status"] == "Matched"],
        master[master["final_status"] == "Partially Matched"],
        master[master["final_status"] == "Unmatched"]
    )
