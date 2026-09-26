"""BPIC 2019 ham CSV'yi okur, kolonları sadeleştirir ve parquet olarak kaydeder.

Kullanım:  python -m src.load
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "BPI_Challenge_2019.csv"
OUT = ROOT / "data" / "processed" / "events.parquet"

RENAME = {
    "case concept:name": "case_id",
    "event concept:name": "activity",
    "event time:timestamp": "ts",
    "event Cumulative net worth (EUR)": "net_worth",
    "event User": "user",
    "event org:resource": "resource",
    "case Item Category": "item_category",
    "case Spend area text": "spend_area",
    "case Sub spend area text": "sub_spend_area",
    "case Vendor": "vendor",
    "case Company": "company",
    "case Document Type": "doc_type",
    "case Purchasing Document": "po",
    "case Item Type": "item_type",
    "case GR-Based Inv. Verif.": "gr_based_iv",
    "case Goods Receipt": "goods_receipt_flag",
}

CATEGORICAL = [
    "activity", "user", "resource", "item_category", "spend_area",
    "sub_spend_area", "vendor", "company", "doc_type", "item_type",
]


def load() -> pd.DataFrame:
    df = pd.read_csv(RAW, dtype=str, encoding="latin-1")
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=RENAME)[list(RENAME.values())]
    df["ts"] = pd.to_datetime(df["ts"], format="%d-%m-%Y %H:%M:%S.%f")
    df["net_worth"] = pd.to_numeric(df["net_worth"])
    for c in ("gr_based_iv", "goods_receipt_flag"):
        df[c] = df[c].str.lower().eq("true")
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    # Kaynak dosyadaki satır sırası, aynı zaman damgalı olaylar için kararlı sıralama anahtarı
    df["row"] = range(len(df))
    return df.sort_values(["case_id", "ts", "row"]).reset_index(drop=True)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    events = load()
    events.to_parquet(OUT, index=False)
    print(f"{len(events):,} olay, {events.case_id.nunique():,} vaka -> {OUT}")
