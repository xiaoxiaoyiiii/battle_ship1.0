/// 解析三段版本号；缺段按 0，非法字符整体视为无效。
pub(crate) fn parse_version(version: &str) -> Option<(u64, u64, u64)> {
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

/// 清单版本比壳自身版本新才提示；解析失败时不提示更新。
pub(crate) fn is_newer_release(latest: &str, current: &str) -> bool {
    match (parse_version(latest), parse_version(current)) {
        (Some(latest), Some(current)) => latest > current,
        _ => false,
    }
}
