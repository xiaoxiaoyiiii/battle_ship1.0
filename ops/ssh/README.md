# Muse 线上监控 SSH 公钥

`muse-monitor.pub` 是 Muse（小弈的个人助手）的 SSH **公钥**，用于只读查看战舰线上日志。
公钥可以公开，泄露没有任何风险；对应的私钥只保存在 Muse 的运行环境里，从不外发。

## 在服务器上启用（由小弈本人执行）

建一个低权限只读账号，把公钥加到这个账号，不要加到 root 或日常账号：

```bash
sudo useradd -m -s /bin/bash muse-ro
sudo mkdir -p /home/muse-ro/.ssh
# 把 muse-monitor.pub 的内容（带限制选项）写成一行：
echo 'no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMoX/r1uqolklpsfbOYh1ZEpGqN/sJfuHj8ba6QTyIXZ hatch' | sudo tee /home/muse-ro/.ssh/authorized_keys
sudo chmod 700 /home/muse-ro/.ssh && sudo chmod 600 /home/muse-ro/.ssh/authorized_keys
sudo chown -R muse-ro:muse-ro /home/muse-ro/.ssh
# 允许读错误日志和 systemd 日志（二选一即可，两个都给最省事）：
sudo setfacl -m u:muse-ro:r /var/lib/battleship/logs/errors.log
sudo usermod -aG systemd-journal muse-ro
```

这个账号没有 sudo、不能改任何文件，最多只能看日志。

## 撤销

删掉服务器上 `/home/muse-ro/.ssh/authorized_keys` 里这一行（或直接删掉 muse-ro 账号），
Muse 立刻就登不进来了，不影响任何其他东西。
