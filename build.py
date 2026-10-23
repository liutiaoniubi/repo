#!/usr/bin/env python3
"""
build.py — 生成 iOS 越狱软件源（APT 仓库）索引文件

功能：
  1. 扫描 debs/ 下的 .deb 文件，生成 Packages / Packages.gz / Packages.bz2
  2. 生成 Release（含 MD5/SHA1/SHA256/SHA512 校验和）
  3. 若提供 GPG 密钥，生成 Release.gpg 与 InRelease
  4. 输出可直接部署到 GitHub Pages 的 _site/ 目录

用法：
  python3 build.py --out _site
  环境变量（可选，用于签名）：
    GPG_PRIVATE_KEY   base64/原文形式的私钥（ Secrets 中传入）
    GPG_PASSPHRASE    私钥密码，无密码可留空
"""

import argparse
import bz2
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from email.utils import formatdate

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# ---------- 仓库元信息：改这里就行 ----------
META = {
    "Origin": "My Repo",
    "Label": "My Repo",
    "Suite": "stable",
    "Version": "1.0",
    "Codename": "ios",
    "Architectures": "iphoneos-arm",
    "Components": "main",
    "Description": "My personal iOS tweak repository.",
}

# 若 repo.conf 存在则覆盖上面的默认值
CONF_PATH = os.path.join(REPO_ROOT, "repo.conf")
if os.path.exists(CONF_PATH):
    with open(CONF_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, _, v = line.partition(":")
            META[k.strip()] = v.strip()


def log(msg):
    print(f"[build] {msg}", flush=True)


def file_hashes(path):
    """一次性算出文件的多种哈希与大小"""
    md5, sha1, sha256, sha512 = hashlib.md5(), hashlib.sha1(), hashlib.sha256(), hashlib.sha512()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            size += len(chunk)
            md5.update(chunk); sha1.update(chunk); sha256.update(chunk); sha512.update(chunk)
    return {
        "size": size,
        "MD5sum": md5.hexdigest(),
        "SHA1": sha1.hexdigest(),
        "SHA256": sha256.hexdigest(),
        "SHA512": sha512.hexdigest(),
    }


def parse_control(text):
    """把 dpkg-deb -f 的输出解析成有序的 (字段, 值) 列表，保留多行值"""
    fields, key, lines = [], None, []
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and key:
            lines.append(line)
        elif ":" in line:
            if key:
                fields.append((key, "\n".join(lines)))
            key, _, val = line.partition(":")
            lines = [val.strip()]
        elif key:
            lines.append(line)
    if key:
        fields.append((key, "\n".join(lines)))
    return fields


def control_of(deb_path):
    r = subprocess.run(
        ["dpkg-deb", "-f", deb_path],
        capture_output=True, text=True, check=True,
    )
    return parse_control(r.stdout)


def build_packages(out_dir, deb_dir, rel_prefix="debs"):
    deb_files = sorted(
        f for f in os.listdir(deb_dir) if f.lower().endswith(".deb")
    )
    stanzas = []
    for name in deb_files:
        path = os.path.join(deb_dir, name)
        fields = control_of(path)
        h = file_hashes(path)

        # 去掉 control 里已存在、且我们将重新计算的字段
        drop = {"filename", "size", "md5sum", "sha1", "sha256", "sha512"}
        fields = [(k, v) for k, v in fields if k.lower() not in drop]

        pkg_name = next((v for k, v in fields if k.lower() == "package"), name)
        fields += [
            ("Filename", f"{rel_prefix}/{name}"),
            ("Size", str(h["size"])),
            ("MD5sum", h["MD5sum"]),
            ("SHA1", h["SHA1"]),
            ("SHA256", h["SHA256"]),
            ("SHA512", h["SHA512"]),
        ]
        stanza = "\n".join(f"{k}: {v}" for k, v in fields)
        stanzas.append(stanza)
        log(f"已收录 {pkg_name}  ({h['size']} 字节)")

    content = ("\n\n".join(stanzas) + "\n") if stanzas else ""
    with open(os.path.join(out_dir, "Packages"), "w", encoding="utf-8") as f:
        f.write(content)

    raw = content.encode("utf-8")
    with gzip.open(os.path.join(out_dir, "Packages.gz"), "wb") as f:
        f.write(raw)
    with bz2.open(os.path.join(out_dir, "Packages.bz2"), "wb") as f:
        f.write(raw)
    return len(deb_files)


def build_release(out_dir):
    index_files = ["Packages", "Packages.gz", "Packages.bz2"]
    existing = [n for n in index_files if os.path.exists(os.path.join(out_dir, n))]

    lines = [
        f"Origin: {META['Origin']}",
        f"Label: {META['Label']}",
        f"Suite: {META['Suite']}",
        f"Version: {META['Version']}",
        f"Codename: {META['Codename']}",
        f"Date: {formatdate(time.time(), usegmt=True)}",
        f"Architectures: {META['Architectures']}",
        f"Components: {META['Components']}",
        f"Description: {META['Description']}",
    ]

    for algo, key in (
        ("MD5Sum", "MD5sum"), ("SHA1", "SHA1"),
        ("SHA256", "SHA256"), ("SHA512", "SHA512"),
    ):
        lines.append(f"{algo}:")
        for name in existing:
            h = file_hashes(os.path.join(out_dir, name))
            lines.append(f" {h[key]} {h['size']} {name}")

    content = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "Release"), "w", encoding="utf-8") as f:
        f.write(content)
    log("Release 已生成")


def gpg_available():
    return shutil.which("gpg") is not None


def sign(out_dir):
    key = os.environ.get("GPG_PRIVATE_KEY", "").strip()
    if not key or not gpg_available():
        log("未提供 GPG 私钥，跳过签名（未签名源在 Sileo 上会提示不受信任）")
        return False

    log("导入 GPG 私钥…")
    subprocess.run(["gpg", "--batch", "--import"], input=key,
                   text=True, capture_output=True, check=False)

    passphrase = os.environ.get("GPG_PASSPHRASE", "")
    base = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback"]
    if passphrase:
        base += ["--passphrase", passphrase]

    release = os.path.join(out_dir, "Release")
    r1 = subprocess.run(base + ["--detach-sign", "--armor",
                                "-o", os.path.join(out_dir, "Release.gpg"), release],
                        capture_output=True, text=True)
    r2 = subprocess.run(base + ["--clearsign",
                                "-o", os.path.join(out_dir, "InRelease"), release],
                        capture_output=True, text=True)
    ok = r1.returncode == 0 and r2.returncode == 0
    log("Release.gpg / InRelease 已生成" if ok else
        f"签名失败：{(r1.stderr or '') + (r2.stderr or '')}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site", help="输出目录")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    # deb 文件：放到 <out>/debs
    src_debs = os.path.join(REPO_ROOT, "debs")
    dst_debs = os.path.join(out_dir, "debs")
    os.makedirs(dst_debs, exist_ok=True)
    if os.path.isdir(src_debs):
        for name in sorted(os.listdir(src_debs)):
            if name.lower().endswith(".deb"):
                shutil.copy2(os.path.join(src_debs, name), os.path.join(dst_debs, name))

    # 静态资源原样拷贝
    for item in ["depictions", "index.html", "CydiaIcon.png", "RepoIcon.png",
                 "sileo-featured.json", "styles.css"]:
        src = os.path.join(REPO_ROOT, item)
        dst = os.path.join(out_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)

    count = build_packages(out_dir, dst_debs)
    if count == 0:
        log("警告：debs/ 里没有找到 .deb，源会是空的")
    build_release(out_dir)

    if gpg_available() and os.environ.get("GPG_PRIVATE_KEY"):
        try:
            r = subprocess.run(
                ["gpg", "--armor", "--export", META["Origin"]],
                capture_output=True, text=True)
            if r.stdout.strip():
                with open(os.path.join(out_dir, "repo-public.key"), "w") as f:
                    f.write(r.stdout)
                log("已导出公钥 repo-public.key")
        except Exception:
            pass
    sign(out_dir)

    log(f"完成 → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
