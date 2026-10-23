# 个人越狱源模板（GitHub Pages + Actions 自动构建）

把 `.deb` 丢进 `debs/`，推送到 GitHub，Actions 自动生成 `Packages`、`Release`、签名文件并部署到 Pages。
手机/电脑都能维护，不用在本地装任何工具。

---

## 一、创建仓库

1. 打开 https://github.com/new
2. Repository name 填 `repo`（想换名也行，下面所有 URL 跟着变）
3. 选 **Public**，勾选 Add a README file
4. 点 Create repository

## 二、把模板文件放进仓库

**电脑（推荐，一条命令搞定）**

```bash
git clone https://github.com/你的用户名/repo.git
cd repo
# 把本模板里的所有文件（含 .github 隐藏目录）复制进来
cp -r /path/to/repo-template/. .
git add -A
git commit -m "init repo"
git push
```

**手机 / 纯网页**

在仓库页面点 **Add file → Create new file**，文件名框里直接填完整路径，GitHub 会自动建目录：

| 依次创建的文件 | 内容来源 |
| --- | --- |
| `.github/workflows/build.yml` | 复制本模板同名文件 |
| `build.py` | 复制 |
| `repo.conf` | 复制 |
| `index.html` | 复制 |
| `sileo-featured.json` | 复制 |
| `debs/.gitkeep` | 空文件，内容随便打个空格 |

`CydiaIcon.png` 用 **Add file → Upload files** 上传（想换图标就换成自己的 512×512 PNG）。

## 三、开启 GitHub Pages（关键一步）

1. 仓库 → **Settings → Pages**
2. **Source** 选 **GitHub Actions**（不是 Deploy from a branch！）
3. 回到 **Actions** 标签，等第一次构建跑完（绿色 ✓），或手动点 **Build and Deploy Repo → Run workflow**

完成后你的源地址就是：

```
https://你的用户名.github.io/repo/
```

浏览器打开能看到首页 = 部署成功；直接访问 `.../repo/Release` 能看到文本 = 索引正常。

## 四、添加自己的 deb

1. 进仓库的 `debs/` 文件夹 → **Add file → Upload files**，把 `.deb` 拖进去
2. 底部填 commit 信息 → **Commit changes**
3. Actions 自动重新构建，约 1 分钟后源里就能搜到新包

> 每次增删 deb 都会自动重建索引，不需要手动跑任何命令。

## 五、在手机上添加源

Sileo / Zebra / Cydia → 软件源 → 右上角 `+` 或「编辑 → 添加」，输入：

```
https://你的用户名.github.io/repo/
```

添加后刷新，就能看到你的包。

## 六、签名（可选但强烈建议）

不签名的源在 Sileo 上会显示「不受信任」甚至被拒绝。生成密钥：

```bash
gpg --full-generate-key      # 选 RSA(sign only)，4096 位
gpg --armor --export-secret-keys 你的邮箱 > private.key
gpg --armor --export 你的邮箱 > public.key
```

然后：

- 仓库 **Settings → Secrets and variables → Actions → New repository secret**
- 名称 `GPG_PRIVATE_KEY`，值 = `private.key` 的**全部内容**（含首尾 `-----BEGIN/END-----` 行）
- 若设了密钥密码，再加一个 `GPG_PASSPHRASE`

下次 Actions 跑完会自动生成 `Release.gpg`、`InRelease` 和 `repo-public.key`。

## 七、个性化

| 想改什么 | 改哪里 |
| --- | --- |
| 源名字 / 描述 | `repo.conf`（会写进 Release） |
| 源图标 | 替换 `CydiaIcon.png`（512×512 PNG） |
| 网页首页 | `index.html` |
| Sileo 首页精选横幅 | `sileo-featured.json` |
| 插件展示页 | 放 `depictions/`，并在 deb 的 control 里加 `Depiction: https://你的用户名.github.io/repo/depictions/xxx.html` |

## 目录说明

```
.github/workflows/build.yml   Actions 自动构建 + 部署
build.py                      索引生成脚本（不需要 apt-ftparchive）
repo.conf                     仓库元信息
debs/                         放你的 .deb
depictions/                   插件展示页（可选）
index.html                    网页首页
CydiaIcon.png                 源图标
sileo-featured.json           Sileo 精选（可选）
```

## 注意

- 只放**你自己开发**或**已获作者授权分发**的包。转存别人的付费插件属侵权。
- GitHub Pages 单仓库建议控制在 1GB 内，deb 很多时考虑用 Release 附件托管包体。
- 免费账号的仓库是公开的，仓库里不要放私钥、密码等敏感文件（私钥只通过 Secrets 传）。
