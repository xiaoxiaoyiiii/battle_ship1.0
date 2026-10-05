"""将已审定的完整魔法卡面导入网页资源目录。"""

import json
import re
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MAP_FILE = ROOT / "static" / "card_art_map.js"
OUTPUT_DIR = ROOT / "static" / "card_faces"


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python tools/import_card_faces.py <all-cards 文件夹>", file=sys.stderr)
        return 2
    source_dir = Path(sys.argv[1]).resolve()
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    map_text = MAP_FILE.read_text(encoding="utf-8")
    match = re.search(r"window\.CARD_ART_MAP\s*=\s*(\{.*?\});", map_text, re.S)
    if not match:
        raise ValueError("找不到 CARD_ART_MAP")
    card_map = json.loads(match.group(1))
    cards = manifest["cards"]
    if len(cards) != 48 or {item["name"] for item in cards} != set(card_map):
        raise ValueError("卡面清单与游戏卡名映射不一致，停止导入")
    targets = []
    for item in cards:
        source = source_dir / item["file"]
        mapped = card_map[item["name"]]
        if not re.fullmatch(r"cards/[a-z0-9-]+\.webp", mapped):
            raise ValueError(f"卡面路径不合法: {mapped}")
        if not source.is_file():
            raise FileNotFoundError(source)
        targets.append((source, OUTPUT_DIR / Path(mapped).name))
    if len({target for _, target in targets}) != len(targets):
        raise ValueError("卡面输出文件名重复")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for source, target in targets:
        with Image.open(source) as image:
            image = image.convert("RGB").resize((768, 1152), Image.Resampling.LANCZOS)
            image.save(target, format="WEBP", quality=92, method=6)
    total = sum(target.stat().st_size for _, target in targets)
    print(f"已导入 {len(targets)} 张卡面，共 {total / 1024 / 1024:.1f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
