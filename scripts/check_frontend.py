"""静态校验：前端引用的接口在 FastAPI 路由里都存在。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xquant.server import app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

routes = {r.path for r in app.routes if hasattr(r, "path")}
used = set(re.findall(r"[\"'`](/api/[a-zA-Z0-9_\-/]*)", js + html))
missing = sorted(u for u in used if u.split("?")[0] not in routes)
if missing:
    print("缺少路由:", missing)
    sys.exit(1)

# 前端引用的静态资源必须存在
for asset in re.findall(r"(?:src|href)=\"(/[^\"]+)\"", html):
    if asset.startswith("/api"):
        continue
    target = ROOT / "web" / asset.lstrip("/")
    if not target.exists():
        print("缺少静态文件:", asset)
        sys.exit(1)

print(f"OK 前端引用的接口均存在: {sorted(used)}")
print("OK 静态资源齐全")
