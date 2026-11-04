//! 战舰棋桌面壳：一个原生窗口，加载官方线上网页。
//!
//! 游戏本体永远在服务端网页里——壳只负责“像软件一样打开”：
//! 独立窗口、任务栏/开始菜单图标、站外链接转交系统浏览器。
//! 不打包任何游戏逻辑，因此服务端更新即全员生效。

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let entry = entry_url();
    let parsed: tauri::Url = entry
        .parse()
        .unwrap_or_else(|_| "http://8.133.180.159:5000/lobby".parse().unwrap());

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            let handle = app.handle().clone();
            let nav_handle = handle.clone();
            tauri::WebviewWindowBuilder::new(
                &handle,
                "main",
                tauri::WebviewUrl::External(parsed),
            )
            .title("战舰棋")
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
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running battleship desktop shell");
}
