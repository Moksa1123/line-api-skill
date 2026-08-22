#!/usr/bin/env python3
"""產生 assertion signing key，輸出可以貼進 Console 的公鑰 JWK。

## 為什麼需要這支

Console 的 Assertion Signing Key 欄位要的是「你自己產生的公鑰」——
金鑰對由你產生，公鑰交給 LINE，私鑰留在本機。它會擋掉這幾種輸入：

    Don't leave this empty / Valid JSON / Please enter a valid public key
    kid should not be included

最後那一條最容易踩到：kid 是 LINE 註冊完之後發給你的，不是你自己填的。

官方文件建議裝 jwcrypto（pip 套件），但這個專案的原則是不依賴套件。
這裡用系統的 openssl 產生金鑰，再用純 Python 解 DER 轉成 JWK——
反正 signature.py 本來就是自己做 PKCS#1 v1.5。

## 用法

    python tools/make_assertion_key.py

會輸出：
    .assertion.key       私鑰 JWK（已被 .gitignore 的 *.key 擋住）
    畫面上的公鑰 JWK      貼進 Console → Register → 拿到 kid

然後把 kid 寫進 .env 的 LINE_ASSERTION_KID。

## 規格（docs/messaging-api/generate-json-web-token.md）

    - The key must be an RSA public key（kty = RSA）
    - The RSA key must be 2048 bits long
    - Use RS256（alg = RS256）
    - State that the public key is for signing（use = sig）
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def b64u(i: int) -> str:
    n = (i.bit_length() + 7) // 8 or 1
    return base64.urlsafe_b64encode(i.to_bytes(n, "big")).rstrip(b"=").decode()


# ---- 最小的 DER 讀取器 -----------------------------------------------------
# PKCS#1 的私鑰是一個 SEQUENCE，裡面依序是
#   version, n, e, d, p, q, dp, dq, qi
# 全部都是 INTEGER。只要照順序讀出來就能轉成 JWK。
def _read_len(data: bytes, i: int) -> tuple[int, int]:
    n = data[i]
    i += 1
    if n < 0x80:
        return n, i
    count = n & 0x7F
    return int.from_bytes(data[i:i + count], "big"), i + count


def _read_int(data: bytes, i: int) -> tuple[int, int]:
    if data[i] != 0x02:
        raise ValueError(f"預期 INTEGER，讀到 tag {data[i]:#x}")
    length, i = _read_len(data, i + 1)
    return int.from_bytes(data[i:i + length], "big"), i + length


def pkcs1_der_to_jwk(der: bytes) -> dict:
    if der[0] != 0x30:
        raise ValueError("不是 DER SEQUENCE")
    _, i = _read_len(der, 1)
    values = []
    for _ in range(9):
        v, i = _read_int(der, i)
        values.append(v)
    _ver, n, e, d, p, q, dp, dq, qi = values
    return {
        "alg": "RS256",
        "kty": "RSA",
        "use": "sig",
        "n": b64u(n), "e": b64u(e), "d": b64u(d),
        "p": b64u(p), "q": b64u(q),
        "dp": b64u(dp), "dq": b64u(dq), "qi": b64u(qi),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / ".assertion.key"),
                    help="私鑰 JWK 要寫到哪（預設 .assertion.key）")
    ap.add_argument("--bits", type=int, default=2048,
                    help="官方規定 2048，除非規格改了不要動")
    args = ap.parse_args()

    try:
        pem = subprocess.run(
            ["openssl", "genrsa", str(args.bits)],
            capture_output=True, check=True).stdout
    except FileNotFoundError:
        raise SystemExit(
            "找不到 openssl。Git for Windows 內附一份（Git Bash 裡的 openssl），"
            "或用 winget install ShiningLight.OpenSSL")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"openssl 產生金鑰失敗：{e.stderr.decode(errors='replace')[:200]}")

    # openssl 3 預設輸出 PKCS#8，轉成 PKCS#1 的 DER 才好逐欄位讀
    der = subprocess.run(
        ["openssl", "rsa", "-traditional", "-outform", "DER"],
        input=pem, capture_output=True, check=True).stdout

    private = pkcs1_der_to_jwk(der)
    bits = int.from_bytes(base64.urlsafe_b64decode(
        private["n"] + "=" * (-len(private["n"]) % 4)), "big").bit_length()
    if bits != args.bits:
        raise SystemExit(f"產出來是 {bits} 位元，不是 {args.bits}")

    out = Path(args.out)
    out.write_text(json.dumps(private, indent=2), encoding="utf-8")
    try:
        out.chmod(0o600)
    except Exception:
        pass

    # 公鑰只留這四個欄位。kid 一定不能有——那是 LINE 註冊完發給你的，
    # 自己填會被擋下「kid should not be included」
    public = {k: private[k] for k in ("alg", "e", "kty", "n", "use")}

    print(f"私鑰已寫入 {out}（{bits} 位元，.gitignore 的 *.key 有擋）\n")
    print("把下面整段貼進 Console 的 Assertion Signing Key 欄位：")
    print("-" * 66)
    print(json.dumps(public, indent=2, sort_keys=True))
    print("-" * 66)
    print("\n貼上後按 Register，LINE 會給你一個 kid。然後把這兩行放進 .env：\n")
    print(f"  LINE_ASSERTION_PRIVATE_KEY={out}")
    print("  LINE_ASSERTION_KID=<Console 給的 kid>\n")
    print("接著跑：python line-api/scripts/test_line.py --live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
