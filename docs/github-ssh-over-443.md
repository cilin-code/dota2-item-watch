# GitHub 443 网络报错解决方案：改用 SSH over 443

## 适用情况

当 GitHub 网页或 API 偶尔能打开，但 `git fetch` / `git push` 经常报下面这些错误时，可以改用 SSH over 443：

```text
Failed to connect to github.com port 443
Recv failure: Connection was reset
RPC failed; curl 28
```

这类问题通常不是 GitHub 账号权限问题，而是 HTTPS Git 传输在当前网络环境里被重置或超时。

## 核心思路

不要继续使用 HTTPS remote：

```text
https://github.com/<user>/<repo>.git
```

改用 SSH remote：

```text
git@github.com:<user>/<repo>.git
```

同时把 GitHub SSH 固定走 `ssh.github.com:443`，绕开不稳定的 HTTPS Git 通道。

## 1. 生成 SSH Key

在 PowerShell 或 CMD 中执行：

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
cmd /c "ssh-keygen -t ed25519 -C 你的邮箱 -f %USERPROFILE%\.ssh\id_ed25519_github -N """
```

生成后会得到：

```text
C:\Users\<用户名>\.ssh\id_ed25519_github
C:\Users\<用户名>\.ssh\id_ed25519_github.pub
```

## 2. 配置 SSH 走 443 端口

编辑或创建：

```text
C:\Users\<用户名>\.ssh\config
```

写入：

```sshconfig
Host github.com
    HostName ssh.github.com
    Port 443
    User git
    IdentityFile ~/.ssh/id_ed25519_github
    IdentitiesOnly yes
```

## 3. 把公钥添加到 GitHub 账号

打开：

```text
https://github.com/settings/keys
```

点击 **New SSH key**。

建议：

```text
Title: codex-ssh-over-443
Key type: Authentication Key
```

Key 内容来自：

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519_github.pub"
```

注意：同一把 SSH key 不能同时作为某个仓库的 Deploy key 和账号级 SSH key。如果 GitHub 提示 `Key is already in use`，先删除对应仓库里的 Deploy key，再添加到账户 SSH keys。

## 4. 测试 SSH 连接

执行：

```bash
ssh -T git@github.com
```

成功时会看到类似：

```text
Hi <username>! You've successfully authenticated, but GitHub does not provide shell access.
```

这表示 SSH key 已经生效。

## 5. 修改仓库 remote

进入项目目录，查看当前 remote：

```bash
git remote -v
```

如果当前是 HTTPS：

```text
https://github.com/<user>/<repo>.git
```

改成 SSH：

```bash
git remote set-url origin git@github.com:<user>/<repo>.git
```

例如：

```bash
git remote set-url origin git@github.com:cilin-code/dota2-item-watch.git
```

## 6. 测试 Git 远端读取和推送

```bash
git ls-remote --heads origin main
git push
```

如果输出：

```text
Everything up-to-date
```

说明当前仓库同步链路已经正常。

## 新项目使用方式

以后新项目直接使用 SSH remote：

```bash
git remote add origin git@github.com:<user>/<new-repo>.git
git push -u origin main
```

不要再使用 HTTPS remote，除非当前网络下 HTTPS Git 已经稳定。

## 本项目当前配置

当前项目已经使用 SSH remote：

```text
git@github.com:cilin-code/dota2-item-watch.git
```

当前 SSH 配置会把 `github.com` 转到：

```text
ssh.github.com:443
```

