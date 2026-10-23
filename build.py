#!/usr/bin/env python3
"""
build.py — 生成 iOS 越狱软件源（APT 仓库）索引文件
"""

import argparse
import bz2
import gzip
import hashlib
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
    "Architectures": "iphoneos-arm iphoneos-arm64 iphoneos-arm64e",
    "Components": "main",
    "Description": "My personal iOS tweak repository.",
}

# 若 repo.conf 存在则覆盖上面的默认值（Architectures 除外，强制保证 ARCHES）
CONF_PATH = os.path.join(REPO_ROOT, "repo.conf")
if os.path.exists(CONF_PATH):
    with open(CONF_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, _, v = line.partition(":")
            if k.strip().lower() == "architectures":
                continue
            META[k.strip()] = v.strip()

# ---------- 强制输出的架构列表（不再依赖配置文件） ----------
ARCHES = ["iphoneos-arm", "iphoneos-arm64", "iphoneos-arm64e"]


def log(msg):
    print(f"[build] {msg}", flush=True)


def file_hashes(path):
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
    r = subprocess.run(["dpkg-deb", "-f", deb_path],
                       capture_output=True, text=True, check=True)
    return parse_control(r.stdout)


def build_packages(out_dir, deb_dir, rel_prefix="debs"):
    deb_files = sorted(f for f in os.listdir(deb_dir) if f.lower().endswith(".deb"))
    stanzas, archs = [], []
    for name in deb_files:
        path = os.path.join(deb_dir, name)
        fields = control_of(path)
        h = file_hashes(path)

        arch = next((v.strip() for k, v in fields if k.lower() == "architecture"), "")
        if arch and arch not in archs:
            archs.append(arch)

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
        stanzas.append("\n".join(f"{k}: {v}" for k, v in fields))
        ver = next((v for k, v in fields if k.lower() == "version"), "?")
        log(f"已收录 {pkg_name} {ver} [{arch or '未声明架构'}] {h['size']} 字节")

    content = ("\n\n".join(stanzas) + "\n") if stanzas else ""
    with open(os.path.join(out_dir, "Packages"), "w", encoding="utf-8") as f:
        f.write(content)
    raw = content.encode("utf-8")
    with gzip.open(os.path.join(out_dir, "Packages.gz"), "wb") as f:
        f.write(raw)
    with bz2.open(os.path.join(out_dir, "Packages.bz2"), "wb") as f:
        f.write(raw)
    return len(deb_files), archs


def build_release(out_dir, deb_archs=None):
    index_files = ["Packages", "Packages.gz", "Packages.bz2"]
    existing = [n for n in index_files if os.path.exists(os.path.join(out_dir, n))]

    arch_list = list(ARCHES)
    for a in (deb_archs or []):
        for one in a.split():
            if one not in arch_list:
                arch_list.append(one)
    arch_field = " ".join(arch_list)

    lines = [
        f"Origin: {META['Origin']}",
        f"Label: {META['Label']}",
        f"Suite: {META['Suite']}",
        f"Version: {META['Version']}",
        f"Codename: {META['Codename']}",
        f"Date: {formatdate(time.time(), usegmt=True)}",
        f"Architectures: {arch_field}",
        f"Components: {META['Components']}",
        f"Description: {META['Description']}",
    ]
    log(f"Release 架构列表：{arch_field}")

    for algo, key in (("MD5Sum", "MD5sum"), ("SHA1", "SHA1"),
                      ("SHA256", "SHA256"), ("SHA512", "SHA512")):
        lines.append(f"{algo}:")
        for name in existing:
            h = file_hashes(os.path.join(out_dir, name))
            lines.append(f" {h[key]} {h['size']} {name}")

    with open(os.path.join(out_dir, "Release"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log("Release 已生成")


def gpg_available():
    return shutil.which("gpg") is not None


def build_dists(out_dir, deb_archs):
    """额外生成标准 Debian 布局 dists/stable/...，兼容性兜底"""
    suite = META["Suite"]
    arch_list = list(ARCHES)
    for a in (deb_archs or []):
        for one in a.split():
            if one not in arch_list:
                arch_list.append(one)

    pkg_src = os.path.join(out_dir, "Packages")
    if not os.path.exists(pkg_src):
        return
    raw = open(pkg_src, "rb").read()

    for arch in arch_list:
        d = os.path.join(out_dir, "dists", suite, "main", f"binary-{arch}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "Packages"), "wb") as f:
            f.write(raw)
        with gzip.open(os.path.join(d, "Packages.gz"), "wb") as f:
            f.write(raw)
        with bz2.open(os.path.join(d, "Packages.bz2"), "wb") as f:
            f.write(raw)

    dist_dir = os.path.join(out_dir, "dists", suite)
    lines = [
        f"Origin: {META['Origin']}",
        f"Label: {META['Label']}",
        f"Suite: {suite}",
        f"Version: {META['Version']}",
        f"Codename: {META['Codename']}",
        f"Date: {formatdate(time.time(), usegmt=True)}",
        f"Architectures: {' '.join(arch_list)}",
        f"Components: main",
        f"Description: {META['Description']}",
    ]
    for algo, key in (("MD5Sum", "MD5sum"), ("SHA1", "SHA1"),
                      ("SHA256", "SHA256"), ("SHA512", "SHA512")):
        lines.append(f"{algo}:")
        for arch in arch_list:
            for name in ("Packages", "Packages.gz", "Packages.bz2"):
                p = os.path.join(dist_dir, "main", f"binary-{arch}", name)
                h = file_hashes(p)
                lines.append(f" {h[key]} {h['size']} main/binary-{arch}/{name}")
    with open(os.path.join(dist_dir, "Release"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    icon = os.path.join(out_dir, "CydiaIcon.png")
    if os.path.isfile(icon):
        shutil.copy2(icon, os.path.join(dist_dir, "CydiaIcon.png"))

    key = os.environ.get("GPG_PRIVATE_KEY", "").strip()
    if key and gpg_available():
        passphrase = os.environ.get("GPG_PASSPHRASE", "")
        base = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback"]
        if passphrase:
            base += ["--passphrase", passphrase]
        rel = os.path.join(dist_dir, "Release")
        subprocess.run(base + ["--detach-sign", "--armor",
                               "-o", os.path.join(dist_dir, "Release.gpg"), rel],
                       capture_output=True, text=True)
        subprocess.run(base + ["--clearsign",
                               "-o", os.path.join(dist_dir, "InRelease"), rel],
                       capture_output=True, text=True)
    log(f"dists/{suite}/ 兜底结构已生成 ({len(arch_list)} 个架构)")


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

    src_debs = os.path.join(REPO_ROOT, "debs")
    dst_debs = os.path.join(out_dir, "debs")
    os.makedirs(dst_debs, exist_ok=True)
    if os.path.isdir(src_debs):
        for name in sorted(os.listdir(src_debs)):
            if name.lower().endswith(".deb"):
                shutil.copy2(os.path.join(src_debs, name), os.path.join(dst_debs, name))

    for item in ["depictions", "index.html", "CydiaIcon.png", "RepoIcon.png",
                 "sileo-featured.json", "styles.css"]:
        src = os.path.join(REPO_ROOT, item)
        dst = os.path.join(out_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)

    count, deb_archs = build_packages(out_dir, dst_debs)
    if count == 0:
        log("警告：debs/ 里没有找到 .deb，源会是空的")
    build_release(out_dir, deb_archs)
    build_dists(out_dir, deb_archs)

    if gpg_available() and os.environ.get("GPG_PRIVATE_KEY"):
        try:
            r = subprocess.run(["gpg", "--armor", "--export", META["Origin"]],
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
