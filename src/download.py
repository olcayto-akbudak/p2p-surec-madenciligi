"""BPIC 2019 olay günlüğünü indirir ve bütünlüğünü SHA-256 ile doğrular.

Resmî kaynak: 4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1
Resmî sayfa tarayıcı ile indirme gerektirdiği için betik, orijinal CSV'yi barındıran
herkese açık bir GitHub aynasını kullanır. İndirilen dosyanın resmî veriyle aynı
olduğu olay (1.595.923) ve vaka (251.734) sayılarıyla ve aşağıdaki özetle doğrulanır.

Kullanım:  python -m src.download
"""
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MIRROR = ("https://raw.githubusercontent.com/mrsonuk/BPI_Challenge_2019/"
          "master/Dataset/BPIChallenge2019_Original.zip")
CSV_SHA256 = "7d592fb425690d13011d1b874fe2af63f61a66acfc368ecf87b4ed266e6cdb00"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    csv = RAW / "BPI_Challenge_2019.csv"
    if not csv.exists():
        zpath = RAW / "BPIChallenge2019_Original.zip"
        if not zpath.exists():
            print("İndiriliyor (~37 MB)…")
            urllib.request.urlretrieve(MIRROR, zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extract("BPI_Challenge_2019.csv", RAW)
    digest = sha256(csv)
    if digest != CSV_SHA256:
        sys.exit(f"SHA-256 uyuşmuyor: {digest}. Dosyayı resmî DOI üzerinden indirip {csv} konumuna koyun.")
    print(f"Doğrulandı: {csv}")


if __name__ == "__main__":
    main()
