# 上传到 GitHub（Windows / cmd 语法）

本文命令按 **cmd.exe** 写法给出（路径含空格用双引号）。本机实测环境：

- `git` → `C:\Program Files\Git\cmd\git.exe`（2.49.0）
- `gh` → `C:\Program Files\GitHub CLI\gh.exe`，**已登录账号 `shrimo-1`**（scopes 含 `repo`、`workflow`）
- ⚠️ **git 全局身份未设置**（`git config --global user.name` 返回非 0）→ 不先设置，第一次 `commit` 就会失败

---

## 0. 前置检查（三条，逐条看输出）

```cmd
git --version
gh auth status
git config --global user.name
git config --global user.email
```

第 3、4 条没有输出就是没设置。**先补上**（把邮箱换成你 GitHub 账号绑定的邮箱）：

```cmd
git config --global user.name "shrimo-1"
git config --global user.email "你的邮箱@example.com"
git config --global init.defaultBranch main
```

> 提交信息建议用英文。cmd 默认代码页是 936，中文提交信息在部分终端与网页上会显示成乱码。

---

## 路线 A（推荐）：gh 一条命令建仓并推送

```cmd
cd /d F:\workingspace_deepseek\blender-ai-modeling-playbook_20260918_103637

git init -b main
git add .
git commit -m "docs: add AI Blender modeling playbook (protocols, lessons, tools)"
git log --oneline
```

确认 `git log` 有输出、`git status` 干净后再建仓：

```cmd
gh repo create blender-ai-modeling-playbook --public --source=. --remote=origin --push --description "Evidence-first playbook for AI-driven Blender modeling via MCP: verdict discipline, coordinate contracts, stage guards, silhouette verification tooling"
```

要点：

- `--public` 换成 `--private` 就是私有仓库；
- `--source=.` 要求当前目录**已经是** git 仓库且至少有一个提交；
- 命令结束后 `origin` 已自动配置好，**不需要**再 `git remote add`；
- 完成后打开看：`gh repo view --web`

验证推送结果：

```cmd
git remote -v
git log --oneline -1
gh repo view --json name,visibility,url,defaultBranchRef
```

---

## 路线 B：先网页建仓，再本地 push

1. 打开 <https://github.com/new>，仓库名 `blender-ai-modeling-playbook`；
2. **不要**勾选 "Add a README file" / "Add .gitignore" / "Choose a license"（否则远程会有一个本地没有的提交，第一次 push 会被拒）；
3. 建好后回到本地：

```cmd
cd /d F:\workingspace_deepseek\blender-ai-modeling-playbook_20260918_103637

git init
git add .
git commit -m "docs: add AI Blender modeling playbook (protocols, lessons, tools)"
git branch -M main
git remote add origin https://github.com/shrimo-1/blender-ai-modeling-playbook.git
git push -u origin main
```

如果第 2 步不小心勾了，先合并远程再推：

```cmd
git pull --rebase origin main
git push -u origin main
```

---

## 之后的日常更新

```cmd
cd /d F:\workingspace_deepseek\blender-ai-modeling-playbook_20260918_103637
git status
git add -A
git commit -m "docs: clarify coordinate round-trip pre-check"
git push
```

看历史与回退：

```cmd
git log --oneline --graph --decorate -20
rem 取消暂存（不改动文件内容）
git restore --staged "<文件>"
rem 丢弃未提交的修改（不可恢复，慎用）
git checkout -- "<文件>"
```

> 注：cmd 交互式命令行里**不要用 `::` 写注释**（会被当成参数传给命令），用 `rem`；命令串联用 `&` 而不是 `;`。

---

## 备选：没有 git / git 不可用时

只能逐文件走 GitHub API（需要 token，权限 `repo`）：

```cmd
rem 单文件上传：content 必须是 base64
gh api --method PUT /repos/shrimo-1/blender-ai-modeling-playbook/contents/README.md -f message="add README" -f content="<base64 字符串>"
```

用 Node 或 Python 写个循环遍历目录即可（注意：**token 只能从环境变量读，不要写进脚本或提交**）。
这条路适合应急；日常维护仍建议用 git。

---

## 常见错误对照

| 现象 | 原因 | 处理 |
|---|---|---|
| `Author identity unknown` / `Please tell me who you are` | 未设置 `user.name` / `user.email` | 见第 0 节 |
| `remote origin already exists` | 已经有 origin | `git remote set-url origin https://github.com/shrimo-1/blender-ai-modeling-playbook.git` |
| `! [rejected] main -> main (fetch first)` | 远程有本地没有的提交 | `git pull --rebase origin main` 后重推 |
| `fatal: not a git repository` | 不在仓库目录 / 还没 `git init` | `cd /d` 到仓库根目录；先 `git init` |
| `Authentication failed` / `403` | 凭据失效或权限不足 | `gh auth login` 重新登录；确认 token 有 `repo` scope |
| 提交信息显示成乱码 | cmd 代码页 936 | 提交信息用英文；或先 `chcp 65001` 再提交 |
| `file is 105.00 MB; this exceeds GitHub's file size limit of 100.00 MB` | 提交了大产物 | 本项目 `.gitignore` 已排除 `*.blend` / `*.stl`；确需分发用 Git LFS |
| `gh: command not found` | `gh` 不在 PATH | 用全路径 `"C:\Program Files\GitHub CLI\gh.exe"`，或改走路线 B |

---

## 推送前自检（30 秒）

```cmd
git status --short
git log --oneline -1
```

再确认三件事：

1. **没有密钥**：仓库里不应出现 `ghp_` / `gho_` / `github_pat_` 开头的字符串，也不应出现账号密码；
2. **没有私密产物**：原始参考图、客户资料、`.blend` / `.stl` 是否确实不该公开；
3. **许可明确**：`LICENSE` 与 README 的许可说明一致（本仓库默认 MIT）。

需要改许可时，直接替换 `LICENSE` 文件并同步改 README 第 7 节即可。
