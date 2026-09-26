"""reports/results.json ve tablolardan README grafiklerini üretir.

Kullanım:  python -m src.figures
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
FIG = REPORTS / "figures"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#b9b8b3"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 10.5, "text.color": INK,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
})

TR_ACT = {
    "Create Purchase Order Item": "Sipariş kalemi",
    "Record Goods Receipt": "Mal kabul",
    "Record Invoice Receipt": "Fatura kaydı",
    "Vendor creates invoice": "Satıcı faturası",
    "Clear Invoice": "Ödeme (kapama)",
    "Remove Payment Block": "Bloke kaldırma",
    "Change Quantity": "Miktar değişikliği",
}


def title(ax, t, sub):
    ax.set_title(t, loc="left", fontsize=13, fontweight="bold", color=INK, pad=26)
    ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=10, color=INK2, va="bottom")


def hbar(ax, labels, values, colors, fmt):
    y = range(len(labels))[::-1]
    ax.barh(list(y), values, color=colors, height=0.62)
    ax.set_yticks(list(y), labels)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    xmax = max(values)
    for yi, v in zip(y, values):
        ax.text(v + xmax * 0.01, yi, fmt(v), va="center", fontsize=10, color=INK)
    ax.set_xlim(0, xmax * 1.15)


def fig_bottlenecks(r):
    t = pd.DataFrame(r["bottlenecks_top10"]).head(7)
    labels = [f"{TR_ACT.get(a, a)} → {TR_ACT.get(b, b)}" for a, b in zip(t.activity, t.next_act)]
    policy = [(a == "Record Invoice Receipt" and b == "Clear Invoice") or
              (a == "Remove Payment Block" and b == "Clear Invoice")
              for a, b in zip(t.activity, t.next_act)]
    colors = [MUTED if p else BLUE for p in policy]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    hbar(ax, labels, t.share_of_total_wait_pct.tolist(), colors, lambda v: f"%{v:.1f}".replace(".", ","))
    ax.set_xlabel("Toplam bekleme süresindeki payı (%)")
    title(ax, "Bekleme süresinin nereye gittiği",
          "Gri: ödeme vadesi ve haftalık ödeme koşusuna bağlı bekleme. Mavi: süreç içi bekleme.")
    fig.tight_layout()
    fig.savefig(FIG / "01_darbogaz.png", dpi=160)


def fig_weekday(r):
    d = r["payment_run"]["clear_weekday_pct"]
    days = list(d.keys())
    vals = list(d.values())
    fig, ax = plt.subplots(figsize=(8, 3.8))
    colors = [BLUE if v == max(vals) else MUTED for v in vals]
    ax.bar(days, vals, color=colors, width=0.62)
    for i, v in enumerate(vals):
        ax.text(i, v + 1.2, f"%{v:.1f}".replace(".", ","), ha="center", fontsize=10, color=INK)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(vals) * 1.15)
    ax.tick_params(axis="x", length=0)
    ax.set_ylabel("Ödemelerin payı (%)")
    title(ax, "Ödemeler haftanın hangi günü yapılıyor",
          f"Faturası kapatılan {r['payment_run']['cases']:,} kalem. Ödemelerin büyük kısmı perşembe günü.".replace(",", "."))
    fig.tight_layout()
    fig.savefig(FIG / "02_odeme_gunu.png", dpi=160)


def fig_block(r):
    b = r["payment_run"]["block_effect"]
    labels = ["Naif karşılaştırma\n(tüm satıcılar birlikte)", "Aynı satıcı içinde\nkarşılaştırma"]
    vals = [b["naive_median_diff_days"], b["vendor_matched_median_diff_days"]]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    hbar(ax, labels, vals, [MUTED, BLUE], lambda v: f"+{v:.0f} gün")
    ax.set_xlabel("Blokeli faturanın ödenmesindeki ek süre (medyan, gün)")
    title(ax, "Ödeme blokesi ödemeyi ne kadar geciktiriyor",
          f"Satıcıya özgü vade farkı kontrol edilince etki {vals[0]:.0f} günden {vals[1]:.0f} güne iniyor ({b['vendors_matched']} satıcı).")
    fig.tight_layout()
    fig.savefig(FIG / "03_bloke_etkisi.png", dpi=160)


def fig_k2(r):
    k = r["compliance"]["K2_paid_without_gr"]
    labels = ["Kural ile işaretlenen", "Düzeltme akışı (dekont, iptal)", "Gerçek istisna",
              "…bloke elle kaldırılmış"]
    vals = [k["flagged"], k["correction_flows"], k["real_exceptions"],
            k["real_exceptions_with_manual_block_release"]]
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    hbar(ax, labels, vals, [MUTED, MUTED, ORANGE, ORANGE], lambda v: f"{v:,}".replace(",", "."))
    ax.set_xlabel("Kalem sayısı")
    title(ax, "Mal kabul olmadan ödenen faturalar",
          f"3'lü eşleşme kalemleri. {k['flagged']} işaretten {k['real_exceptions']} tanesi gerçek istisna.")
    fig.tight_layout()
    fig.savefig(FIG / "04_malkabulsuz_odeme.png", dpi=160)


def fig_area():
    t = pd.read_csv(REPORTS / "tables" / "harcama_alani_cevrim.csv")
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    hbar(ax, t.spend_area.tolist(), t.median_days.tolist(), [BLUE] * len(t), lambda v: f"{v:.0f} gün")
    ax.set_xlabel("Siparişten ödemeye medyan süre (gün)")
    title(ax, "Harcama alanına göre çevrim süresi",
          "3'lü eşleşme (fatura önce) kalemleri, en az 1.000 kalemi olan alanlar.")
    fig.tight_layout()
    fig.savefig(FIG / "05_harcama_alani.png", dpi=160)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    r = json.loads((REPORTS / "results.json").read_text(encoding="utf-8"))
    fig_bottlenecks(r)
    fig_weekday(r)
    fig_block(r)
    fig_k2(r)
    fig_area()
    print("Grafikler:", sorted(p.name for p in FIG.glob("*.png")))


if __name__ == "__main__":
    main()
