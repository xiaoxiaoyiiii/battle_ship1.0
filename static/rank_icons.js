/**
 * 段位图标（段位批）——9 个段位各一枚**矢量**图标，不依赖任何图片素材。
 *
 * 背景：段位要有"一眼看出高低"的视觉，又不想引一堆 png（本项目 static/ 下
 * 只有 avatars 与卡牌图）。所以按**海军臂章**的路子画：低段位只有一道 V 形
 * 折线，往上逐级加横杠、加星、加齿轮，船长是舵轮、大舰长是带桂冠的舵轮 ——
 * 作者的要求「段位越高需要越精致越高级」就落在这条递增的主线上。
 *
 * 用法（三段都是 window 上的全局，game.js 直接取）：
 *   window.rankIconHtml('captain')          -> '<svg class="rank-icon" …>…</svg>'
 *   window.rankIconHtml('admiral', 28)      -> 指定像素尺寸（默认 22）
 *   window.RANK_ICONS.captain               -> 纯内层路径串（自己套 <svg> 时用）
 *   window.RANK_TIER_NAMES.captain          -> '船长'
 *
 * ⚠️ **颜色不写在这里**：图标一律 `currentColor`，配色由 style.css 的
 * `.rank-icon[data-tier="…"]` 决定（低段位青铜灰、高段位鎏金）。
 * 把颜色焊进 SVG 就没法跟主题（深海/赛博/鎏金…）联动了。
 */
(function () {
    'use strict';

    // 统一的内层绘制属性：细线、圆角端点，小尺寸下不糊成一团。
    var INNER_ATTRS = 'fill="none" stroke="currentColor" stroke-width="1.5" ' +
        'stroke-linecap="round" stroke-linejoin="round"';

    // 五角星（中心 12,6.6，外径 4.2 / 内径 1.7）—— 三副~大副的"军官星"。
    var STAR = '<path d="M12 2.6l1.3 2.9 3.1.3-2.4 2 .7 3-2.7-1.6-2.7 1.6.7-3-2.4-2 3.1-.3z"/>';

    /**
     * 每个段位的内层 SVG（viewBox 一律 0 0 24 24）。
     * 从 sailor2 到 admiral 元素数单调递增，视觉复杂度也就单调递增。
     */
    var RANK_ICONS = {
        // 二级水手 —— 一道 V 形折线，最简
        sailor2:
            '<path d="M5.5 15.5l6.5-6 6.5 6"/>',

        // 一级水手 —— V 形 + 一道横杠
        sailor1:
            '<path d="M5.5 13l6.5-6 6.5 6"/>' +
            '<path d="M7.5 17.5h9"/>',

        // 水手长 —— 双 V 形 + 绳结（锚冠）
        bosun:
            '<path d="M5.5 10.5l6.5-5.5 6.5 5.5"/>' +
            '<path d="M5.5 16l6.5-5.5L18.5 16"/>' +
            '<circle cx="12" cy="19.6" r="1.4"/>',

        // 三副 —— 一颗军官星 + 一道杠
        mate3:
            STAR +
            '<rect x="6" y="15.6" width="12" height="2.6" rx="1.3"/>',

        // 二副 —— 星 + 两道杠
        mate2:
            '<g transform="translate(0,-1.4)">' + STAR + '</g>' +
            '<rect x="6" y="14" width="12" height="2.4" rx="1.2"/>' +
            '<rect x="6" y="18.2" width="12" height="2.4" rx="1.2"/>',

        // 大副 —— 星 + 三道杠
        mate1:
            '<g transform="translate(0,-2.6) scale(0.86) translate(2,1.6)">' + STAR + '</g>' +
            '<rect x="6" y="12.6" width="12" height="2.2" rx="1.1"/>' +
            '<rect x="6" y="16.3" width="12" height="2.2" rx="1.1"/>' +
            '<rect x="6" y="20" width="12" height="2.2" rx="1.1"/>',

        // 轮机长 —— 齿轮 + 三道杠（齿轮用虚线圆表现齿，省一堆 path）
        engineer:
            '<circle cx="12" cy="6.4" r="4.1"/>' +
            '<circle cx="12" cy="6.4" r="4.1" stroke-width="3.2" stroke-dasharray="1.1 1.6"/>' +
            '<circle cx="12" cy="6.4" r="1.5"/>' +
            '<rect x="6" y="12.6" width="12" height="1.9" rx="0.95"/>' +
            '<rect x="6" y="15.9" width="12" height="1.9" rx="0.95"/>' +
            '<rect x="6" y="19.2" width="12" height="1.9" rx="0.95"/>',

        // 船长 —— 八幅舵轮（轮毂 + 轮圈 + 八根辐条伸出圈外）
        captain:
            '<circle cx="12" cy="12" r="6.6"/>' +
            '<circle cx="12" cy="12" r="2.1"/>' +
            '<path d="M12 5.4V2.2M12 18.6v3.2M5.4 12H2.2M18.6 12h3.2"/>' +
            '<path d="M7.3 7.3L4.9 4.9M16.7 16.7l2.4 2.4M16.7 7.3l2.4-2.4M7.3 16.7l-2.4 2.4"/>',

        // 大舰长 —— 双环 + 舵轮 + 顶上五角星 + 桂冠两道弧
        admiral:
            '<circle cx="12" cy="12.6" r="10.6" stroke-width="0.9" opacity="0.65"/>' +
            '<circle cx="12" cy="12.6" r="8.9" stroke-width="1.1"/>' +
            '<circle cx="12" cy="12.6" r="4.5"/>' +
            '<circle cx="12" cy="12.6" r="1.5"/>' +
            '<path d="M12 8.1V6.4M12 17.1v1.7M7.5 12.6H5.8M16.5 12.6h1.7"/>' +
            '<path d="M8.8 9.4L7.6 8.2M15.2 9.4l1.2-1.2M15.2 15.8l1.2 1.2M8.8 15.8l-1.2 1.2"/>' +
            '<g transform="translate(0,-0.4) scale(0.72) translate(4.6,-0.6)">' + STAR + '</g>' +
            '<path d="M4.4 8.6C2.6 10.4 2 12.6 2.6 14.6M19.6 8.6c1.8 1.8 2.4 4 1.8 6" opacity="0.8"/>'
    };

    var RANK_TIER_NAMES = {
        sailor2: '二级水手',
        sailor1: '一级水手',
        bosun: '水手长',
        mate3: '三副',
        mate2: '二副',
        mate1: '大副',
        engineer: '轮机长',
        captain: '船长',
        admiral: '大舰长'
    };

    /**
     * 生成一枚段位图标的 HTML。
     *
     * @param {string} tierId 段位 id（sailor2 … admiral）。未知 id 返回空串 ——
     *        调用方据此"不显示图标"，而不是在页面上留一个空 `<svg>`（那会占位）。
     * @param {number} [size] 边长像素，默认 22。
     *        ⚠️ 船长 / 大舰长这两枚元素多（舵轮 + 双环 + 桂冠 + 星），
     *        **建议 ≥ 26px** 再上屏；22px 只够看清低段位的 V 形与横杠。
     *        真要挤进小胶囊，就只显示文字段位（`label`），别塞图标。
     * @returns {string}
     */
    function rankIconHtml(tierId, size) {
        var inner = RANK_ICONS[tierId];
        if (!inner) return '';
        var px = parseInt(size, 10);
        if (!(px > 0)) px = 22;
        // data-tier 是给 CSS 上色用的（.rank-icon[data-tier="captain"]）
        return '<svg class="rank-icon" data-tier="' + tierId + '" viewBox="0 0 24 24" ' +
            'width="' + px + '" height="' + px + '" role="img" aria-hidden="true" ' +
            'aria-label="' + (RANK_TIER_NAMES[tierId] || '') + '" ' + INNER_ATTRS + '>' +
            inner + '</svg>';
    }

    window.RANK_ICONS = RANK_ICONS;
    window.RANK_TIER_NAMES = RANK_TIER_NAMES;
    window.rankIconHtml = rankIconHtml;
})();
