"""Copia portal_dados/<recorte>/ para portal/dados/<recorte>/ no formato servido pela hospedagem.

Arquivos .json.gz viram .b64.txt (gzip em base64). Atualiza dados/index.json.
Uso: python preparar.py <pasta portal_dados> [recorte ...]
"""
import base64
import json
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).parent / "dados"


def rotulo(meta):
    return f"{meta['uf']} · {meta['ano']}" + (" (demonstração)" if meta.get("demo") else "")


def main():
    origem = Path(sys.argv[1])
    recortes = sys.argv[2:] or sorted(p.name for p in origem.iterdir() if (p / "meta.json").exists())
    for r in recortes:
        src, dst = origem / r, AQUI / r
        if dst.exists():
            shutil.rmtree(dst)
        for f in src.rglob("*"):
            if not f.is_file() or f.suffix not in (".json", ".gz"):
                continue
            rel = f.relative_to(src)
            alvo = dst / rel
            alvo.parent.mkdir(parents=True, exist_ok=True)
            if f.name.endswith(".json.gz"):
                alvo = alvo.with_name(f.name[: -len(".json.gz")] + ".b64.txt")
                alvo.write_text(base64.b64encode(f.read_bytes()).decode())
            else:
                shutil.copy(f, alvo)
    idx = []
    for d in sorted(AQUI.iterdir(), reverse=True):
        if (d / "meta.json").exists():
            m = json.loads((d / "meta.json").read_text())
            idx.append({"id": d.name, "rotulo": rotulo(m), "demo": bool(m.get("demo"))})
    idx.sort(key=lambda x: (x["demo"], x["id"]))  # dados reais primeiro
    (AQUI / "index.json").write_text(json.dumps(idx, ensure_ascii=False))
    print(json.dumps(idx, ensure_ascii=False))


if __name__ == "__main__":
    main()
