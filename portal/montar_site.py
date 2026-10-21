# monta o site estático (GitHub Pages): python montar_site.py <pasta_portal> <destino>
import pathlib, shutil, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
for f in dst.iterdir():
    if f.name != ".git":
        shutil.rmtree(f) if f.is_dir() else f.unlink()
shutil.copytree(src / "dados", dst / "dados")
(dst / ".nojekyll").touch()
s = (src / "index.html").read_text()
(dst / "index.html").write_text(
    '<!doctype html>\n<html lang="pt-BR"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
    '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
    'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n'
    + s.replace('<header class="topo">', '</head><body>\n<header class="topo">', 1) + '\n</body></html>\n')
print("site em", dst)
