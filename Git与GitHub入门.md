# 把这个项目传到 GitHub

Git 在电脑上保存项目版本，GitHub 存放你推送上去的版本。`commit` 只是本地保存，执行 `push` 后才上传。代码的每次修改可以有记录，不用反复复制“最终版”文件夹。

## 先认识几个命令

| 命令 | 做什么 |
| --- | --- |
| git status | 看哪些文件改了，哪些已准备提交 |
| git add | 选中本次要保存的改动，放进暂存区 |
| git commit | 把暂存区保存成一个有说明的本地版本 |
| git push | 把本地提交上传到 GitHub |
| git pull --ff-only | 把远端的新提交取回本地；有分叉时停止，留待处理 |
| git log --oneline | 查看已有提交记录 |

## 第一次上传，按顺序操作

### 1. 打开项目的 PowerShell

在项目文件夹空白处右键，选择“在终端中打开”。确认这一层有 README.md、运行项目.ps1 和03_程序，再运行：

```powershell
git --version
git status
```

找不到 git 时，从 [Git 官方安装页](https://git-scm.com/install/windows) 安装 Git for Windows，关闭终端后重新打开。

这份本地项目已初始化 Git，上传准备时还没有提交和远程仓库，不需要再执行 `git init`。以后 clone 下载仓库时也不需要重新初始化。

### 2. 设置提交署名

把引号里的示意文字换成自己的信息，每行单独执行：

```powershell
git config user.name "你的署名"
git config user.email "你的GitHub已验证邮箱或GitHub提供的noreply邮箱"
```

这是提交记录的署名，不是登录账号或密码；这里只设置当前项目。若不想显示个人邮箱，可以在 GitHub 的 Settings → Emails 找到 GitHub 提供的 noreply 邮箱，再填进命令。不要照抄示意文字。

### 3. 在本地保存第一个版本

```powershell
git add .
git status
git diff --cached --stat
```

`git add .` 按 `.gitignore` 选择文件。当前规则只放行程序、规则和通用说明；真实数据、标注、运行日志和修改前备份不上传。核对清单，确认没有原始 train.json 或真实对话文件，再继续：

```powershell
git commit -m "建立客服交接研究项目，保存程序和研究说明"
git branch -M main
```

第一行建立本地版本，第二行把主分支命名为 main。此时还没有上传。

### 4. 在 GitHub 建一个空仓库

登录后打开 [新建仓库页面](https://github.com/new)。仓库名例如 `customer-service-handoff-study`，也可自己取。研究还在进行，建议先选 Private，后续再决定是否公开。

不要勾选添加 README、.gitignore 或许可证，让它保持空仓库。本地已有说明和忽略规则，空仓库方便第一次连接。建好后复制 HTTPS 地址，形式类似 `https://github.com/你的用户名/仓库名.git`。

### 5. 连接远端并上传

把第一行的网址换成刚复制的真实地址：

```powershell
git remote add origin https://github.com/你的用户名/仓库名.git
git remote -v
git push -u origin main
```

origin 是远程仓库的简称；main 是分支名；`-u` 让这个分支记住以后推送的位置。

首次推送可能弹出浏览器，请在自己的浏览器中登录授权。GitHub 的 HTTPS Git 操作不接受账号密码作为 Git 密码；优先使用凭据管理器完成浏览器认证，不要把令牌或密码发到聊天里。

成功后刷新仓库网页，应该能看到 README 和代码，最新提交说明与刚才一致。再执行 `git status`，正常情况下工作区是干净的。push 失败不会取消已保存的本地 commit，不需要重做所有步骤。

## 以后改了代码怎样保存？

在项目根目录运行：

```powershell
git status
git diff
git add .
git diff --cached --stat
git commit -m "写清这次具体改了什么"
git push
```

说明可以写“修正从不同目录启动时的路径”或“补充未决事项的判断标准”。一次提交尽量对应一件讲得清楚的改动。`git log --oneline` 看版本记录，`git diff` 看尚未暂存的变化；暂存内容用 `git diff --cached` 看。

新增文件没有出现在 `git status` 时，用 `git check-ignore -v "文件的相对路径"` 查看原因。本项目根目录的新文件默认不上传；需要共享的新规则或说明先在 `.gitignore` 放行，再提交。真实客服材料继续留在本地。

如果在另一台电脑或网页改过仓库，开始本机工作前、工作区干净时先运行 `git pull --ff-only`。远端和本地分叉、出现冲突时先看报错，不要强制推送覆盖。

## 在另一台电脑继续

在准备放项目的位置运行，网址替换成自己的仓库：

```powershell
git clone https://github.com/你的用户名/仓库名.git
```

进入下载的文件夹，按 [项目首页](README.md) 准备 Python 和数据。GitHub 只保存被提交的内容，原电脑的数据、标注和实验记录需要单独备份或传输，不会因为 clone 自动回来。

## 常见提示怎样理解？

| 提示 | 怎么处理 |
| --- | --- |
| Author identity unknown | 回到署名步骤，填好姓名和邮箱 |
| remote origin already exists | 用 `git remote -v` 看是否已连接；正确就跳过 add，错误时用 `git remote set-url origin 真实地址` 修改 |
| nothing to commit | 没有新的可提交改动；若已有提交尚未上传，仍可 push |
| rejected / non-fast-forward | 远端已有本地没有的提交；保留报错，检查双方历史，不强推 |

操作顺序参考 [GitHub 官方上传说明](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)；忽略规则见 [官方说明](https://docs.github.com/en/get-started/git-basics/ignoring-files)；认证方式见 [官方认证说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github)。
