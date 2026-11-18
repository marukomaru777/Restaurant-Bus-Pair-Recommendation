"""統一設定入口：所有程式都從這裡拿設定，不要自己讀檔或讀環境變數。

來源優先順序（前面的蓋過後面的）：
    1. 環境變數        ← 部署（例如 AWS）時在平台上設定
    2. .env            ← 本機機密，例如 TDX 金鑰（已列入 .gitignore，範本見 .env.example）
    3. config.toml     ← 一般設定與預設值（進 git，大家共用）

用法：
    from settings import secret, setting
    secret("TDX_CLIENT_ID")                 # 機密：只從環境變數／.env 讀
    setting("defaults", "meal_min")         # 一般設定：可用環境變數 DEFAULTS_MEAL_MIN 覆寫
"""
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent


def _load_dotenv(path=ROOT / ".env"):
    """KEY=VALUE 一行一個；# 開頭為註解。不覆寫已存在的環境變數。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()
_config = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))


def secret(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"缺少 {name}：請在 {ROOT / '.env'} 加一行 {name}=...（格式見 .env.example）")
    return value


def setting(section, key):
    env = os.environ.get(f"{section}_{key}".upper())
    default = _config[section][key]
    return type(default)(env) if env is not None else default


if __name__ == "__main__":
    # 自我檢查：.env 解析、環境變數覆寫與型別轉換
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".env"
        p.write_text('﻿# 註解\nSETTINGS_TEST_A = "x y"\n\nSETTINGS_TEST_B=1=2\n', encoding="utf-8")
        _load_dotenv(p)
    assert os.environ["SETTINGS_TEST_A"] == "x y" and os.environ["SETTINGS_TEST_B"] == "1=2"
    os.environ["DEFAULTS_MEAL_MIN"] = "120"
    assert setting("defaults", "meal_min") == 120
    print("settings selftest ok")
