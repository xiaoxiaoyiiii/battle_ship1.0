# 战舰棋桌面壳（desktop/）

Tauri 2 壳：原生窗口加载官方线上网页，不含任何游戏逻辑。游戏/服务器更新对壳零影响。

## 更新提示（方案 A，仅桌面壳）

- 壳启动 3 秒后静默请求**所加载站点**的 `/static/clients/latest.json`（5 秒超时，任何失败静默跳过，绝不影响启动）；
- 清单里的 `version` **只代表壳的版本号**：**只在发布新壳时修改它并替换安装包链接**；
- 服务器日常更新（网页/后端/活动）**绝不修改 latest.json**——服务器更新在壳里实时可见，不需要也不应该弹更新窗；
- 比对结果为“清单版本 > 壳内置版本”时弹原生对话框“检测到新版本，是否立即更新？”，“立即更新”用系统浏览器打开安装包下载链接。

### latest.json 格式与发布流程

```json
{
  "version": "1.0.1",
  "notes": "修复与体验优化",
  "win": "/static/clients/battleship-setup.exe",
  "apk": "/static/clients/battleship.apk"
}
```

发新壳时：改 `tauri.conf.json`/`Cargo.toml` 的 version → 重打安装包 → 上传安装包到服务器 `/static/clients/` → 更新 latest.json 的 version/notes。生产服务器路径为 `/opt/battleship/static/clients/`（与现有 static 托管同根，部署时需授权 SSH 上传）。

## 构建与分发

- Windows：`npm --prefix desktop run build`（NSIS 安装包）；安卓 APK 见仓库交接记录的手动流水线（cargo → jniLibs → gradle → zipalign → apksigner）。
- 安卓壳 v1 不做更新对话框（系统不允许静默自装，且原生消息框支持有限）；安卓的更新提示后续走网页层（UA 已携带 `BattleshipClient/android`）。
- APK 更新必须用同一签名密钥（F:/android-tools/keystores/，不入仓），否则手机需卸载重装。
