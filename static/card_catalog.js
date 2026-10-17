// Phase 8：从 game.js 原样迁出；作为经典脚本共享页面作用域。
// 从 window.magicCards 里按卡名取卡；不存在返回 null
function lookupCard(name) {
    const list = window.magicCards;
    if (!Array.isArray(list) || !name) return null;
    return list.find(c => c && c.name === name) || null;
}


// Phase 8：从 game.js 原样迁出；作为经典脚本共享页面作用域。
function compendiumCards() {
    if (!window.magicCards) return [];
    const seen = new Set();
    return window.magicCards.filter(card => {
        // 失灵！在数据里有 3 条完全相同的条目（设计如此），图鉴只展示一张
        const key = card.name + '|' + card.type + '|' + card.speed + '|' + card.description;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}


// Phase 8：从 game.js 原样迁出；作为经典脚本共享页面作用域。
function codexCardByName(name) {
    const want = String(name || '');
    return compendiumCards().find(c => String(c.name) === want) || null;
}
