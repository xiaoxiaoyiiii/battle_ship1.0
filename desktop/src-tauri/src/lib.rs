//! 战舰棋桌面壳：一个原生窗口，加载官方线上网页。
//!
//! 游戏本体永远在服务端网页里——壳只负责“像软件一样打开”：
//! 独立窗口、任务栏/开始菜单图标、站外链接转交系统浏览器。
//! 不打包任何游戏逻辑，因此服务端更新即全员生效。
//!
//! 更新检查（方案 A，2026-11-05）：启动后静默请求所加载站点的
//! `/static/clients/latest.json`，比对版本号；有新版时弹原生对话框，
//! “立即更新”跳系统浏览器下载安装包。任何失败都静默跳过，绝不影响启动。

use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

/// 窗口内允许停留的站点：生产地址与本地调试栈。
/// 其余一律转交系统浏览器打开（比如“支持作者”的 GitHub 页）。
fn is_own_host(url: &tauri::Url) -> bool {
    match url.host_str() {
        Some("8.133.180.159") | Some("127.0.0.1") | Some("localhost") => {
            matches!(url.scheme(), "http" | "https")
        }
        _ => false,
    }
}

/// 初始地址：可用环境变量覆盖（本地调试栈 / 未来 HTTPS 域名）。
fn entry_url() -> String {
    std::env::var("BATTLESHIP_DESKTOP_URL")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "http://8.133.180.159:5000/lobby".to_string())
}

/// 客户端壳浏览器标识：服务端据此记录“客户端登录过”并发放奖励，
/// 前端据此不再弹下载提示。保留平台关键字供服务端分流。
#[cfg(target_os = "android")]
pub const SHELL_USER_AGENT: &str = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 Mobile Safari/537.36 BattleshipClient/android";
#[cfg(not(target_os = "android"))]
pub const SHELL_USER_AGENT: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 BattleshipClient/desktop";

/// 服务器版本清单的字段（/static/clients/latest.json）。
#[derive(serde::Deserialize, Clone, Debug)]
struct LatestRelease {
    version: String,
    #[serde(default)]
    notes: String,
    #[serde(default)]
    win: String,
    #[serde(default)]
    apk: String,
}

/// 解析三段版本号；缺段按 0，非法字符整体视为无效（None = 不提示更新）。
fn parse_version(version: &str) -> Option<(u64, u64, u64)> {
    let parts: Vec<&str> = version.trim().split('.').collect();
    if parts.is_empty() || parts.len() > 3 {
        return None;
    }
    let mut numbers = [0u64; 3];
    for (index, part) in parts.iter().enumerate() {
        if part.is_empty() || !part.chars().all(|c| c.is_ascii_digit()) {
            return None;
        }
        numbers[index] = part.parse().ok()?;
    }
    Some((numbers[0], numbers[1], numbers[2]))
}

/// 清单版本比壳自身版本新才提示；任何解析失败都视为“无需更新”。
fn is_newer_release(latest: &str, current: &str) -> bool {
    match (parse_version(latest), parse_version(current)) {
        (Some(latest), Some(current)) => latest > current,
        _ => false,
    }
}

fn current_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

fn origin_of(url: &tauri::Url) -> String {
    match (url.scheme(), url.port()) {
        (scheme, Some(port)) => format!("{scheme}://{host}:{port}", host = url.host_str().unwrap_or("")),
        (scheme, None) => format!("{scheme}://{}", url.host_str().unwrap_or("")),
    }
}

/// 检查更新：请求清单 → 比版本 → 有新版弹原生对话框。
/// “立即更新”打开系统浏览器下载对应安装包；任何一步失败静默跳过。
async fn check_for_updates(handle: tauri::AppHandle, origin: String, current: String) {
    let url = format!("{origin}/static/clients/latest.json");
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
    {
        Ok(client) => client,
        Err(_) => return,
    };
    let release: LatestRelease = match client.get(&url).send().await {
        Ok(response) => match response.error_for_status() {
            Ok(response) => match response.json().await {
                Ok(release) => release,
                Err(_) => return,
            },
            Err(_) => return,
        },
        Err(_) => return,
    };
    if !is_newer_release(&release.version, &current) {
        return;
    }
    let notes = release.notes.trim().to_string();
    let message = if notes.is_empty() {
        format!("检测到新版本 v{}，是否立即更新？", release.version)
    } else {
        format!(
            "检测到新版本 v{}：{}\n是否立即更新？",
            release.version, notes
        )
    };
    let download_url = if release.win.starts_with("http") {
        release.win.clone()
    } else {
        format!("{origin}{}", release.win)
    };

    handle
        .dialog()
        .message(message)
        .title("战舰棋更新")
        .buttons(tauri_plugin_dialog::MessageDialogButtons::OkCancelCustom(
            "立即更新".to_string(),
            "稍后".to_string(),
        ))
        .show(move |update: bool| {
            if update {
                let _ = handle.opener().open_url(&download_url, None::<&str>);
            }
        });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let entry = entry_url();
    let parsed: tauri::Url = entry
        .parse()
        .unwrap_or_else(|_| "http://8.133.180.159:5000/lobby".parse().unwrap());
    let origin = origin_of(&parsed);
    let current = current_version();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(move |app| {
            let handle = app.handle().clone();
            let nav_handle = handle.clone();
            tauri::WebviewWindowBuilder::new(
                &handle,
                "main",
                tauri::WebviewUrl::External(parsed),
            )
            .title("战舰棋")
            .user_agent(SHELL_USER_AGENT)
            .inner_size(1280.0, 820.0)
            .min_inner_size(1024.0, 640.0)
            // 站内导航放行；站外链接转交系统浏览器并阻止窗口内跳转。
            .on_navigation(move |url| {
                if is_own_host(url) {
                    true
                } else {
                    let _ = nav_handle.opener().open_url(url.as_str(), None::<&str>);
                    false
                }
            })
            .build()?;
            // 更新检查延后几秒，让游戏页面先完成加载；仅桌面壳启用。
            #[cfg(desktop)]
            {
                let check_handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    tokio::time::sleep(std::time::Duration::from_secs(3)).await;
                    check_for_updates(check_handle, origin, current).await;
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running battleship desktop shell");
}

#[cfg(all(test, desktop))]
mod tests {
    use super::*;

    #[test]
    fn parse_version_accepts_three_segments() {
        assert_eq!(parse_version("1.2.3"), Some((1, 2, 3)));
        assert_eq!(parse_version(" 1.0.0 "), Some((1, 0, 0)));
    }

    #[test]
    fn parse_version_fills_missing_segments() {
        assert_eq!(parse_version("1.2"), Some((1, 2, 0)));
        assert_eq!(parse_version("2"), Some((2, 0, 0)));
    }

    #[test]
    fn parse_version_rejects_garbage() {
        assert_eq!(parse_version("abc"), None);
        assert_eq!(parse_version("1.x.3"), None);
        assert_eq!(parse_version(""), None);
        assert_eq!(parse_version("1.2.3.4"), None);
    }

    #[test]
    fn is_newer_only_for_strictly_greater() {
        assert!(is_newer_release("1.0.1", "1.0.0"));
        assert!(is_newer_release("2.0", "1.9.9"));
        assert!(!is_newer_release("1.0.0", "1.0.0"));
        assert!(!is_newer_release("0.9.9", "1.0.0"));
        assert!(!is_newer_release("not-a-version", "1.0.0"));
    }
}
