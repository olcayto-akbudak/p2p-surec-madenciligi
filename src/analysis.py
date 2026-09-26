"""P2P süreç analizi: veri kalitesi, uyum kuralları, yeniden işleme, çevrim süresi, darboğaz.

Tüm sayısal çıktılar reports/results.json ve reports/tables/*.csv dosyalarına yazılır.
README'deki her sayı bu dosyalardan gelir.

Kullanım:  python -m src.analysis
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "processed" / "events.parquet"
REPORTS = ROOT / "reports"
TABLES = REPORTS / "tables"

# Veri setinin belgelenmiş kapsamı 2018 yılıdır; bu pencere dışındaki damgalar veri kalitesi sorunudur.
WINDOW_START, WINDOW_END = pd.Timestamp("2018-01-01"), pd.Timestamp("2019-02-01")

A = {  # kısa aktivite adları
    "po": "Create Purchase Order Item",
    "gr": "Record Goods Receipt",
    "ir": "Record Invoice Receipt",
    "vci": "Vendor creates invoice",
    "clr": "Clear Invoice",
    "cir": "Cancel Invoice Receipt",
    "cgr": "Cancel Goods Receipt",
    "cp": "Change Price",
    "cq": "Change Quantity",
    "del": "Delete Purchase Order Item",
    "rpb": "Remove Payment Block",
    "spb": "Set Payment Block",
}
REWORK = ["cp", "cq", "del", "cir", "cgr"]
# Düzeltme akışı sayılan aktiviteler (alacak dekontu ve iptaller)
CORRECTION = ["Vendor creates debit memo", "Cancel Invoice Receipt",
              "Cancel Goods Receipt", "Cancel Subsequent Invoice"]
CAT_3W_BEFORE = "3-way match, invoice before GR"
CAT_3W_AFTER = "3-way match, invoice after GR"


def case_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("case_id", observed=True)
    c = g.agg(
        category=("item_category", "first"),
        spend_area=("spend_area", "first"),
        vendor=("vendor", "first"),
        company=("company", "first"),
        n_events=("activity", "size"),
        net_worth=("net_worth", "first"),
        ts_min=("ts", "min"),
        ts_max=("ts", "max"),
    )
    for k, act in A.items():
        sub = df[df.activity == act].groupby("case_id", observed=True).ts
        c[f"n_{k}"] = sub.size().reindex(c.index).fillna(0).astype(int)
        c[f"first_{k}"] = sub.min().reindex(c.index)
        c[f"last_{k}"] = sub.max().reindex(c.index)
    for c_ in ("category", "spend_area", "vendor", "company"):
        c[c_] = c[c_].astype(str)
    c["bad_ts"] = (c.ts_min < WINDOW_START) | (c.ts_max >= WINDOW_END)
    c["rework"] = c[[f"n_{k}" for k in REWORK]].sum(axis=1) > 0
    corr_cases = df.loc[df.activity.isin(CORRECTION), "case_id"].astype(str).unique()
    c["has_correction"] = c.index.isin(corr_cases)
    c["paid"] = c.n_clr > 0
    c["blocked"] = c.n_rpb > 0
    # Çevrim süresi: sipariş kalemi oluşturma -> son fatura kapama (gün)
    c["cycle_days"] = (c.last_clr - c.first_po).dt.total_seconds() / 86400
    return c


def data_quality(df, c):
    bad_ev = (df.ts < WINDOW_START) | (df.ts >= WINDOW_END)
    net_varies = df.groupby("case_id", observed=True).net_worth.nunique() > 1
    day_precision = df.ts.dt.strftime("%H:%M") == "23:59"
    by_act = (
        df.assign(dp=day_precision).groupby("activity", observed=True).dp.mean()
        .sort_values(ascending=False)
    )
    return {
        "events": int(len(df)),
        "cases": int(len(c)),
        "purchase_orders": int(df.po.nunique()),
        "vendors": int(c.vendor.nunique()),
        "activities": int(df.activity.nunique()),
        "out_of_window_events": int(bad_ev.sum()),
        "out_of_window_cases": int(c.bad_ts.sum()),
        "oldest_ts": str(df.ts.min()),
        "newest_ts": str(df.ts.max()),
        "cases_net_worth_varies_pct": round(100 * net_varies.mean(), 2),
        "day_precision_activities": {
            k: round(100 * v, 1) for k, v in by_act[by_act > 0.5].items()
        },
    }


def compliance(df_events, c):
    out = {}
    cats = c.groupby("category").size().rename("cases")
    out["category_cases"] = cats.to_dict()

    # K1: 3'lü eşleşme, faturadan önce mal kabul -> fatura kaydı ilk mal kabulden önce olmamalı
    a = c[(c.category == CAT_3W_AFTER) & (c.n_ir > 0)]
    k1 = (a.n_gr == 0) | (a.first_ir < a.first_gr)
    out["K1_ir_before_gr"] = {"checked": int(len(a)), "violations": int(k1.sum())}

    # K2: 3'lü eşleşme -> fatura, mal kabul olmadan kapatılmamalı (ödenmemeli)
    b = c[c.category.str.startswith("3-way") & c.paid]
    no_gr = b.n_gr == 0
    before_gr = (~no_gr) & (b.first_clr < b.first_gr)
    k2 = b[no_gr | before_gr].copy()
    # Düzeltme akışları: satıcı alacak dekontu veya iptal içeren vakalarda "Clear Invoice"
    # bir ödeme değil, düzeltme kaydının kapatılmasıdır. Bunlar yanlış pozitiftir.
    k2["correction"] = c.loc[k2.index, "has_correction"]
    clean = k2[~k2.correction]
    rpb = df_events[df_events.case_id.isin(clean.index)
                    & (df_events.activity == A["rpb"])]
    all_rpb = df_events[df_events.activity == A["rpb"]]
    rpb_users = rpb.user.astype(str).value_counts()
    top_user = rpb_users.index[0]
    vend = clean.vendor.value_counts()
    out["K2_paid_without_gr"] = {
        "checked": int(len(b)),
        "paid_no_gr": int(no_gr.sum()),
        "paid_before_first_gr": int(before_gr.sum()),
        "flagged": int(len(k2)),
        "correction_flows": int(k2.correction.sum()),
        "real_exceptions": int(len(clean)),
        "real_exceptions_pct_of_paid": round(100 * len(clean) / len(b), 3),
        "real_exceptions_item_value_eur": float(clean.net_worth.sum()),
        "real_exceptions_with_manual_block_release": int(
            rpb[~rpb.user.astype(str).str.startswith("batch")].case_id.nunique()),
        "release_top_user": top_user,
        "release_top_user_share_in_exceptions_pct": round(
            100 * rpb_users.iloc[0] / rpb_users.sum(), 1),
        "release_top_user_share_overall_pct": round(
            100 * (all_rpb.user.astype(str) == top_user).mean(), 1),
        "top_vendor": vend.index[0],
        "top_vendor_cases": int(vend.iloc[0]),
        "top_vendor_share_pct": round(100 * vend.iloc[0] / len(clean), 1),
        "top_spend_area": clean.spend_area.value_counts().index[0],
        "top_spend_area_cases": int(clean.spend_area.value_counts().iloc[0]),
    }
    k2.assign(rule="K2")[["rule", "correction", "category", "spend_area", "vendor", "net_worth"]].to_csv(
        TABLES / "K2_ihlal_vakalari.csv")

    # K3: Konsinye -> kalem seviyesinde fatura beklenmez
    k = c[c.category == "Consignment"]
    out["K3_consignment_invoiced"] = {
        "checked": int(len(k)), "violations": int(((k.n_ir + k.n_clr) > 0).sum())}

    # K4: Mükerrer fatura sinyali -> satıcı faturasından fazla fatura kaydı, iptal yok
    s = c[c.category.str.startswith("3-way") & (c.n_vci > 0)]
    extra_ir = s[(s.n_ir > s.n_vci) & (s.n_cir == 0)]
    extra_clr = s[(s.n_clr > s.n_vci) & (s.n_cir == 0)].copy()
    extra_clr["correction"] = c.loc[extra_clr.index, "has_correction"]
    k4_clean = extra_clr[~extra_clr.correction]
    out["K4_duplicate_signal"] = {
        "checked": int(len(s)),
        "extra_invoice_receipt": int(len(extra_ir)),
        "extra_ir_then_extra_clear": int((extra_ir.n_clr > extra_ir.n_vci).sum()),
        "extra_clear": int(len(extra_clr)),
        "extra_clear_correction_flows": int(extra_clr.correction.sum()),
        "extra_clear_clean": int(len(k4_clean)),
        "extra_clear_clean_vendors": int(k4_clean.vendor.nunique()),
        "extra_clear_clean_top10_vendor_share_pct": round(
            100 * k4_clean.vendor.value_counts().head(10).sum() / max(len(k4_clean), 1), 1),
    }
    extra_clr.assign(rule="K4")[
        ["rule", "correction", "category", "spend_area", "vendor", "n_vci", "n_ir", "n_clr", "net_worth"]
    ].to_csv(TABLES / "K4_mukerrer_odeme_sinyali.csv")
    return out


def payment_run(c):
    """Ödeme zamanlaması: haftalık ödeme koşusu ve satıcıya özgü vade izi."""
    b = c[(c.category == CAT_3W_BEFORE) & c.paid & ~c.bad_ts & (c.n_vci > 0)].copy()
    wd = b.last_clr.dt.dayofweek.value_counts(normalize=True).sort_index()
    names = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    b["term"] = (b.last_clr.dt.normalize() - b.first_vci.dt.normalize()).dt.days
    per_v = b.groupby("vendor").term.agg(["size", "std"]).query("size >= 50")
    out = {
        "cases": int(len(b)),
        "clear_weekday_pct": {names[i]: round(100 * v, 1) for i, v in wd.items()},
        "invoice_to_clear_median_days": float(b.term.median()),
        "invoice_to_clear_std_overall": round(float(b.term.std()), 1),
        "invoice_to_clear_std_within_vendor_median": round(float(per_v["std"].median()), 1),
        "vendors_used_for_std": int(len(per_v)),
    }
    # Bloke etkisi: naif karşılaştırma vs satıcı içi karşılaştırma (vade farkını kontrol eder)
    naive = b.groupby("blocked").term.median()
    g = b.groupby(["vendor", "blocked"]).term.agg(["size", "median"]).unstack()
    g = g[(g[("size", True)] >= 30) & (g[("size", False)] >= 30)]
    diff = g[("median", True)] - g[("median", False)]
    w = g[("size", True)]
    out["block_effect"] = {
        "naive_median_diff_days": float(naive[True] - naive[False]),
        "vendor_matched_median_diff_days": float(diff.median()),
        "vendor_matched_weighted_mean_diff_days": round(float((diff * w).sum() / w.sum()), 1),
        "vendors_matched": int(len(g)),
        "blocked_cases_covered": int(w.sum()),
    }
    pd.DataFrame({"blocked_cases": w, "unblocked_cases": g[("size", False)],
                  "median_diff_days": diff}).to_csv(TABLES / "bloke_etkisi_satici_ici.csv")
    return out


def rework(c):
    rows = []
    for k in REWORK + ["rpb"]:
        rows.append({"activity": A[k], "cases": int((c[f"n_{k}"] > 0).sum()),
                     "pct": round(100 * (c[f"n_{k}"] > 0).mean(), 2)})
    t = pd.DataFrame(rows).sort_values("cases", ascending=False)
    t.to_csv(TABLES / "yeniden_isleme.csv", index=False)
    by_area = (
        c.groupby("spend_area")
        .agg(cases=("rework", "size"), rework_pct=("rework", "mean"), blocked_pct=("blocked", "mean"))
        .query("cases >= 1000")
        .assign(rework_pct=lambda d: (100 * d.rework_pct).round(1),
                blocked_pct=lambda d: (100 * d.blocked_pct).round(1))
        .sort_values("rework_pct", ascending=False)
    )
    by_area.to_csv(TABLES / "harcama_alani_yeniden_isleme.csv")
    return {"by_activity": t.to_dict("records"), "any_rework_pct": round(100 * c.rework.mean(), 2)}


def block_release(df):
    r = df[df.activity == A["rpb"]]
    manual = ~r.user.astype(str).str.startswith("batch")
    return {"events": int(len(r)), "manual_events_pct": round(100 * manual.mean(), 1),
            "cases_with_manual_release": int(r[manual].case_id.nunique())}


def cycle_time(c):
    """3'lü eşleşme (fatura önce) kategorisi: en büyük akış. Pencere dışı damgalı vakalar hariç."""
    base = c[(c.category == CAT_3W_BEFORE) & c.paid & ~c.bad_ts & (c.cycle_days >= 0)].copy()
    out = {"cases": int(len(base)),
           "median_days": round(base.cycle_days.median(), 1),
           "p90_days": round(base.cycle_days.quantile(0.9), 1)}

    # Ödeme blokesi etkisi
    grp = base.groupby("blocked").cycle_days
    out["blocked"] = {
        "share_pct": round(100 * base.blocked.mean(), 1),
        "median_with": round(grp.median()[True], 1),
        "median_without": round(grp.median()[False], 1),
    }
    # Blokeli vakada: son mal kabul / fatura kaydı -> blokenin kaldırılması
    bl = base[base.blocked]
    ready = bl[["last_gr", "last_ir"]].max(axis=1)
    wait = (bl.first_rpb - ready).dt.total_seconds() / 86400
    out["blocked"]["median_ready_to_release_days"] = round(wait[wait >= 0].median(), 1)
    out["blocked"]["release_after_ready_pct"] = round(100 * (wait >= 0).mean(), 1)
    rel = (bl.first_clr - bl.first_rpb).dt.total_seconds() / 86400
    out["blocked"]["median_release_to_clear_days"] = round(rel[rel >= 0].median(), 1)

    # Yeniden işleme etkisi
    grp = base.groupby("rework").cycle_days
    out["rework"] = {"median_with": round(grp.median()[True], 1),
                     "median_without": round(grp.median()[False], 1)}

    # Fatura kaydı -> kapama (ödeme) süresi
    ir2clr = (base.last_clr - base.last_ir).dt.total_seconds() / 86400
    out["ir_to_clear_median_days"] = round(ir2clr[ir2clr >= 0].median(), 1)

    # Harcama alanına göre
    area = (base.groupby("spend_area")
            .agg(cases=("cycle_days", "size"), median_days=("cycle_days", "median"),
                 blocked_pct=("blocked", "mean"))
            .query("cases >= 1000")
            .assign(blocked_pct=lambda d: (100 * d.blocked_pct).round(1),
                    median_days=lambda d: d.median_days.round(1))
            .sort_values("median_days", ascending=False))
    area.to_csv(TABLES / "harcama_alani_cevrim.csv")
    out["by_spend_area"] = area.reset_index().to_dict("records")
    corr = np.corrcoef(area.blocked_pct, area.median_days)[0, 1]
    out["spend_area_blocked_vs_cycle_corr"] = round(float(corr), 2)
    base[["spend_area", "cycle_days", "blocked", "rework"]].to_parquet(
        ROOT / "data" / "processed" / "cycle_base.parquet")
    return out


def bottlenecks(df, c):
    """Doğrudan-takip (directly-follows) geçişlerinde bekleme süreleri."""
    keep = c.index[(c.category == CAT_3W_BEFORE) & ~c.bad_ts]
    e = df[df.case_id.isin(keep)][["case_id", "activity", "ts"]].copy()
    e["activity"] = e.activity.astype(str)
    e["next_act"] = e.groupby("case_id", observed=True).activity.shift(-1)
    e["wait"] = (e.groupby("case_id", observed=True).ts.shift(-1) - e.ts).dt.total_seconds() / 86400
    e = e.dropna(subset=["next_act"])
    t = (e.groupby(["activity", "next_act"])
         .agg(count=("wait", "size"), median_days=("wait", "median"), total_days=("wait", "sum"))
         .reset_index())
    t = t[t["count"] >= 500]
    t["share_of_total_wait_pct"] = (100 * t.total_days / e.wait.sum()).round(1)
    t = t.sort_values("total_days", ascending=False)
    t["median_days"] = t.median_days.round(1)
    t["total_days"] = t.total_days.round(0)
    t.to_csv(TABLES / "darbogaz_gecisler.csv", index=False)
    return t.head(10).to_dict("records")


def variants(df, c):
    keep = c.index[(c.category == CAT_3W_BEFORE)]
    e = df[df.case_id.isin(keep)]
    v = e.groupby("case_id", observed=True).activity.agg(lambda s: " > ".join(map(str, s)))
    vc = v.value_counts()
    top = vc.head(10).reset_index()
    top.columns = ["variant", "cases"]
    top["pct"] = (100 * top.cases / len(v)).round(2)
    top.to_csv(TABLES / "varyantlar_top10.csv", index=False)
    return {"n_variants": int(len(vc)), "top1_pct": float(top.pct.iloc[0]),
            "top10_pct": round(float(top.pct.sum()), 1),
            "singleton_variants": int((vc == 1).sum())}


def main():
    TABLES.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(EVENTS)
    c = case_table(df)
    c.to_parquet(ROOT / "data" / "processed" / "cases.parquet")
    res = {
        "data_quality": data_quality(df, c),
        "compliance": compliance(df, c),
        "payment_run": payment_run(c),
        "rework": rework(c),
        "block_release": block_release(df),
        "cycle_time": cycle_time(c),
        "bottlenecks_top10": bottlenecks(df, c),
        "variants": variants(df, c),
    }
    (REPORTS / "results.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
