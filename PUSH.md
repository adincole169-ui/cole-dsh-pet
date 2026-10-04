# 推送到 GitHub

仓库已经**提交好了**，只差建远程仓库 + 推送。这份文件就是那几步。

当前状态：

- 分支 `main`，3 个提交，83 个文件（约 0.5 MB）
- `.git` 只有 0.29 MB —— 动画素材没有进历史（见 `.gitignore` 与 `ASSETS.md`）
- 提交作者是**占位身份** `dsh-pet contributor <noreply@example.com>`，
  按下面第二节改成你自己的

> 下面的命令都在**本仓库根目录**下执行（就是含 `main.py` 与 `.git` 的那一层）。

---

## 一、先在 GitHub 上建一个空仓库

打开 <https://github.com/new>：

- **Repository name**：比如 `dsh-pet`
- **Public / Private**：自选（建议先 Private，确认内容没问题再改 Public）
- **不要**勾选 *Add a README file* / *Add .gitignore* / *Choose a license* ——
  本地已经有这些文件了，勾了会让第一次推送产生冲突

建好后把地址记下来，形如：

```
https://github.com/<你的用户名>/dsh-pet.git
```

---

## 二、改成你自己的提交身份

```powershell
git config user.name  "你的名字"
git config user.email "你的邮箱"

# 把所有提交的作者都改成上面配置的身份
git rebase --root --exec "git commit --amend --reset-author --no-edit"
```

`--reset-author` 会用刚配置的名字与邮箱重写提交作者。因为**还没推送**，
改历史没有任何副作用。

只想改最近一个提交就：

```powershell
git commit --amend --reset-author --no-edit
```

改完核对：

```powershell
git log --format="%h %an <%ae> %s"
```

每一行的作者都应当是你自己的名字与邮箱。

---

## 三、关联远程并推送

```powershell
git remote add origin https://github.com/<你的用户名>/dsh-pet.git
git push -u origin main
```

首次推送会要求**登录 GitHub**：用 Git Credential Manager 弹出的浏览器授权，
或者用 **Personal Access Token** 当密码（GitHub 不接受账户密码）。
授权一次后会记住，之后不用再登。

---

## 四、推完检查三件事

1. **仓库首页**显示 `README.md` 的内容，顶部有 **MIT** 许可标识
   （因为仓库根有 `LICENSE`）。
2. **文件列表里不该有** `webm/`、`frames/`、`assets/`、`memes/`。
   如果看到了，说明 `.gitignore` 没生效 —— 停下检查。
3. **提交作者**是你自己的名字，不是 `dsh-pet contributor`。

---

## 五、建议补上的仓库设置

- **Topics**（首页右上齿轮）：`desktop-pet`、`pyqt5`、`deepseek-harness`、
  `dsh-plugin`、`windows`
- **About → Description**：
  `PyQt5 透明桌面宠物，与 DeepSeek Harness 会话状态联动（不含美术素材）`
- **Releases**：想发"带素材的完整包"时**不要**把素材提交进仓库——git 历史会永久
  记住它，而且素材授权未明（见 `ASSETS.md`）。要发就发 Release 附件，并在说明里
  写清素材来源与授权限制。

---

## 六、之后每次改动的常规流程

```powershell
# 改完先自查：确认没有素材/私人数据混进来
python tools\audit_publish.py            # 默认审计暂存区
python tools\audit_publish.py --committed  # 审计已提交内容

git add -A
git commit -m "说明这次改了什么"
git push
```

**提交前跑一次 `audit_publish.py` 应当成为习惯**：本项目的素材目录
（`webm/`、`frames/`、`assets/`、`memes/`）就在仓库根下面，很容易误加。

---

## 七、如果推送失败

| 现象 | 原因与处理 |
|---|---|
| `remote origin already exists` | 已关联过：`git remote set-url origin <地址>` |
| `failed to push some refs` | 远程仓库不是空的（建仓库时勾了 README）。先 `git pull --rebase origin main` 再推 |
| 一直提示密码错误 | GitHub 不接受账户密码，要用 **Personal Access Token**（Settings → Developer settings → Tokens） |
| 卡在认证窗口 | `git config --global credential.helper manager` 后重试 |
| 推送体积异常大 | `.git` 里混进了大文件。用 `git count-objects -vH` 看 `size-pack`；本仓库应当只有几百 KB |

---

## 八、关于素材与分发包

**不要把上游素材提交进仓库**（`webm/`、`frames/`、`assets/`、`memes/`），原因见
[ASSETS.md](ASSETS.md)：上游仓库未授予再分发权，且解码后的帧有 2.56 GB / 25423 个文件。

带素材的完整包（`dsh-pet-share.zip`）与更新补丁（`dsh-pet-update.zip`）适合**私下**
交给已经装过的人，不适合放进公开仓库或 Release。
