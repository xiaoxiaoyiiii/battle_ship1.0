// 基于原 game.js 的优化：添加海洋气泡粒子动画
function initParticles() {
    const canvas = document.getElementById('particle-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--primary-rgb').trim() || '21, 101, 192';
    const particles = [];
    for (let i = 0; i < 60; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            radius: Math.random() * 3 + 1,
            speed: Math.random() * 0.6 + 0.2,
            sway: Math.random() * Math.PI * 2,
            swaySpeed: Math.random() * 0.02 + 0.005,
            alpha: Math.random() * 0.25 + 0.08
        });
    }

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
            p.y -= p.speed;
            p.sway += p.swaySpeed;
            p.x += Math.sin(p.sway) * 0.3;
            if (p.y < -10) { p.y = canvas.height + 10; p.x = Math.random() * canvas.width; }
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(${primaryColor}, ${p.alpha})`;
            ctx.lineWidth = 1;
            ctx.stroke();
        });
        requestAnimationFrame(animate);
    }
    animate();
}

// 窗口调整大小
window.addEventListener('resize', () => {
    const canvas = document.getElementById('particle-canvas');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
});

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    initParticles();
    // 原 init() 函数调用
    init();
});
// 更改密码表单逻辑
document.addEventListener('DOMContentLoaded', function () {
    const changePasswordForm = document.getElementById('change-password-form');
    const changePasswordMsg = document.getElementById('change-password-msg');
    if (changePasswordForm) {
        changePasswordForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const oldPwd = document.getElementById('old-password').value;
            const newPwd = document.getElementById('new-password').value;
            changePasswordMsg.textContent = '';
            if (!oldPwd || !newPwd) {
                changePasswordMsg.style.color = 'red';
                changePasswordMsg.textContent = '请填写原密码和新密码';
                return;
            }
            if (newPwd.length < 6) {
                changePasswordMsg.style.color = 'red';
                changePasswordMsg.textContent = '新密码长度至少6位';
                return;
            }
            const formData = new FormData();
            formData.append('old_password', oldPwd);
            formData.append('new_password', newPwd);
            fetch('/api/change_password', {
                method: 'POST',
                body: formData
            }).then(r => r.json()).then(res => {
                if (res.success) {
                    changePasswordMsg.style.color = 'green';
                    changePasswordMsg.textContent = '密码修改成功';
                    changePasswordForm.reset();
                } else {
                    changePasswordMsg.style.color = 'red';
                    changePasswordMsg.textContent = res.msg || '修改失败';
                }
            }).catch(() => {
                changePasswordMsg.style.color = 'red';
                changePasswordMsg.textContent = '请求失败，请稍后重试';
            });
        });
    }
});
// 游戏内头像元素
const myAvatarInGame = document.getElementById('my-avatar-in-game');
const opponentAvatarInGame = document.getElementById('opponent-avatar-in-game');

// 移动自己的头像到左上角，对手头像到右上角
document.addEventListener('DOMContentLoaded', function () {
    // 左上角自己的头像和用户名
    let avatarCorner = document.getElementById('avatar-corner');
    if (!avatarCorner) {
        avatarCorner = document.createElement('div');
        avatarCorner.id = 'avatar-corner';
        avatarCorner.style.position = 'fixed';
        avatarCorner.style.top = '16px';
        avatarCorner.style.left = '16px';
        avatarCorner.style.zIndex = '1000';
        avatarCorner.style.background = 'var(--glass)';
        avatarCorner.style.borderRadius = '24px';
        avatarCorner.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)';
        avatarCorner.style.padding = '4px 12px 4px 4px';
        avatarCorner.style.display = 'flex';
        avatarCorner.style.alignItems = 'center';
        // 头像
        avatarCorner.appendChild(myAvatarInGame);
        // 用户名
        let myNameSpan = document.createElement('span');
        myNameSpan.id = 'my-username-corner';
        myNameSpan.style.marginLeft = '8px';
        myNameSpan.style.fontWeight = 'bold';
        myNameSpan.style.fontSize = '1.05em';
        myNameSpan.style.color = 'var(--text)';
        avatarCorner.appendChild(myNameSpan);
        document.body.appendChild(avatarCorner);
    } else {
        avatarCorner.appendChild(myAvatarInGame);
        if (!document.getElementById('my-username-corner')) {
            let myNameSpan = document.createElement('span');
            myNameSpan.id = 'my-username-corner';
            myNameSpan.style.marginLeft = '8px';
            myNameSpan.style.fontWeight = 'bold';
            myNameSpan.style.fontSize = '1.05em';
            myNameSpan.style.color = 'var(--text)';
            avatarCorner.appendChild(myNameSpan);
        }
    }

    // 右上角对手头像和用户名
    let opponentAvatarCorner = document.getElementById('opponent-avatar-corner');
    if (!opponentAvatarCorner) {
        opponentAvatarCorner = document.createElement('div');
        opponentAvatarCorner.id = 'opponent-avatar-corner';
        opponentAvatarCorner.style.position = 'fixed';
        opponentAvatarCorner.style.top = '16px';
        opponentAvatarCorner.style.right = '16px';
        opponentAvatarCorner.style.zIndex = '1000';
        opponentAvatarCorner.style.background = 'var(--glass)';
        opponentAvatarCorner.style.borderRadius = '24px';
        opponentAvatarCorner.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)';
        opponentAvatarCorner.style.padding = '4px 4px 4px 12px';
        opponentAvatarCorner.style.display = 'flex';
        opponentAvatarCorner.style.alignItems = 'center';
        // 用户名
        let oppNameSpan = document.createElement('span');
        oppNameSpan.id = 'opponent-username-corner';
        oppNameSpan.style.marginRight = '8px';
        oppNameSpan.style.fontWeight = 'bold';
        oppNameSpan.style.fontSize = '1.05em';
        oppNameSpan.style.color = 'var(--text)';
        opponentAvatarCorner.appendChild(oppNameSpan);
        // 头像
        opponentAvatarCorner.appendChild(opponentAvatarInGame);
        document.body.appendChild(opponentAvatarCorner);
    } else {
        if (!document.getElementById('opponent-username-corner')) {
            let oppNameSpan = document.createElement('span');
            oppNameSpan.id = 'opponent-username-corner';
            oppNameSpan.style.marginRight = '8px';
            oppNameSpan.style.fontWeight = 'bold';
            oppNameSpan.style.fontSize = '1.05em';
            oppNameSpan.style.color = 'var(--text)';
            opponentAvatarCorner.insertBefore(oppNameSpan, opponentAvatarInGame);
        }
        opponentAvatarCorner.appendChild(opponentAvatarInGame);
    }

    // 自动更新用户名
    function updateCornerNames() {
        const myName = (window.gameState && window.gameState.playerName) || window.__USERNAME || '';
        const oppName = (window.gameState && window.gameState.opponentName) || '';
        const myNameSpan = document.getElementById('my-username-corner');
        const oppNameSpan = document.getElementById('opponent-username-corner');
        if (myNameSpan) myNameSpan.textContent = myName ? myName : '';
        if (oppNameSpan) oppNameSpan.textContent = oppName ? oppName : '';
    }

    updateCornerNames();
    window.addEventListener('gameStateUpdate', updateCornerNames);
    setInterval(updateCornerNames, 20000);

    // 自动更新对手头像
    function updateOpponentAvatarCorner() {
        const opponentName = (window.gameState && window.gameState.opponentName) || '';
        if (opponentName) updateOpponentAvatarInGame(opponentName);
    }

    updateOpponentAvatarCorner();
    window.addEventListener('gameStateUpdate', updateOpponentAvatarCorner);
    setInterval(updateOpponentAvatarCorner, 20000);

    // 点右上角的对手头像 / 名字 → 打开对手的个人信息（2026-09-17 作者要求：
    // 对局内看对手资料要能看到头像、签名、排行榜名次与历史战绩）。
    // 绑在容器上，头像被重新加载/替换也不受影响。
    const opponentCornerEl = document.getElementById('opponent-avatar-corner');
    if (opponentCornerEl && opponentCornerEl.dataset.profileBound !== '1') {
        opponentCornerEl.dataset.profileBound = '1';
        opponentCornerEl.style.cursor = 'pointer';
        opponentCornerEl.title = '点击查看对手个人信息';
        opponentCornerEl.addEventListener('click', () => {
            const oppName = (window.gameState && window.gameState.opponentName) || '';
            // 优先走统一的个人信息面板（init() 之后一定已就绪，不依赖
            // game_state 处理器是否已经跑过）；再兜底到游戏内那份 alias。
            if (oppName && typeof window.showUserProfile === 'function') {
                window.showUserProfile(oppName);
            } else if (typeof window.showOpponentStats === 'function') {
                window.showOpponentStats();
            } else {
                showMessage('对手信息还没准备好，请稍后再试', { type: 'warning' });
            }
        });
    }

    // 点左上角自己的头像 / 名字 → 同一份个人信息面板（2026-09-17）。
    // 此前这里挂的是`#my-avatar-in-game` 上的一段老实现：它渲染一张只有
    // 胜负/连胜的裸表格，和排行榜点名字弹出的详情完全不是一个东西，玩家实测
    // 报的「局内头像的个人信息跟排行榜里的不一样」就是它。
    const myCornerEl = document.getElementById('avatar-corner');
    if (myCornerEl && myCornerEl.dataset.profileBound !== '1') {
        myCornerEl.dataset.profileBound = '1';
        myCornerEl.style.cursor = 'pointer';
        myCornerEl.title = '点击查看我的个人信息';
        myCornerEl.addEventListener('click', () => {
            if (typeof window.showUserProfile !== 'function') return;
            // 登录用户按账号名查（能拿到名次/签名/头像）；游客没有账号记录，
            // 走不带 username 的会话查询只会 401，直接给出明确提示。
            const myName = window.__USERNAME
                || (window.gameState && window.gameState.playerName) || '';
            if (!myName) {
                showMessage('未登录，无法查看个人信息', { type: 'warning' });
                return;
            }
            window.showUserProfile(myName);
        });
    }

    // 控制游戏未开始时隐藏相关元素
    function controlGameElementsVisibility() {
        // 获取元素
        const avatarCorner = document.getElementById('avatar-corner');
        const opponentAvatarCorner = document.getElementById('opponent-avatar-corner');
        const testMagicButton = document.getElementById('test-magic-system');
        
        // 检查游戏是否开始
        // 游戏开始的条件：有房间ID或者当前屏幕是游戏相关界面（不是开始、大厅、登录等界面）
        const gameStarted = window.gameState && window.gameState.roomId;
        
        // 隐藏或显示元素
        const visibility = gameStarted ? 'block' : 'none';
        
        if (avatarCorner) {
            avatarCorner.style.display = visibility;
        }
        
        if (opponentAvatarCorner) {
            opponentAvatarCorner.style.display = visibility;
        }
        
        if (testMagicButton) {
            testMagicButton.style.display = visibility;
        }
    }
    
    // 初始调用
    controlGameElementsVisibility();
    
    // 监听游戏状态更新
    window.addEventListener('gameStateUpdate', controlGameElementsVisibility);
    
    // 每隔2秒检查一次，确保元素状态正确
    setInterval(controlGameElementsVisibility, 2000);
});

// 获取当前用户头像并显示到游戏内
function updateMyAvatarInGame() {
    fetch('/api/profile').then(r => r.json()).then(res => {
        console.log("updateMyAvatarInGame", res);
        if (res.profile && myAvatarInGame) {
            myAvatarInGame.src = res.profile.avatar || '/static/avatars/default.png';
        }
    });
}

// 获取对手头像（通过Socket或后端接口，假设有对手id）
function updateOpponentAvatarInGame(opponentId) {
    if (!opponentId) return;
    fetch(`/user_stats?username=${encodeURIComponent(opponentId)}`)
        .then(r => r.json()).then(res => {
            console.log("updateOpponentAvatarInGame", res);
            if (res.stats && opponentAvatarInGame) {
                // 兼容后端返回格式
                if (res.stats.avatar && res.stats.avatar !== '') {
                    opponentAvatarInGame.src = res.stats.avatar;
                } else {
                    opponentAvatarInGame.src = '/static/avatars/default.png';
                }
            } else if (opponentAvatarInGame) {
                opponentAvatarInGame.src = '/static/avatars/default.png';
            }
        }).catch(() => {
            if (opponentAvatarInGame) opponentAvatarInGame.src = '/static/avatars/default.png';
        });
}

// 对局内两个头像的点击入口全部走【统一的个人信息面板】（2026-09-17 修正）。
//
// ⚠️ 这里原本是两段独立的老实现（各自 fetch + renderMiniStatsTable），渲染的是一张
// 只有 用户名/胜场/负场/当前连胜/最长连胜 的裸表格，既没有头像、签名、排行榜名次，
// 也没有历史战绩 —— 与排行榜里点名字弹出来的那份详情完全不是一个东西。
// 更要命的是头像 <img> 就在角落胶囊里，点它时【自己的监听】和【胶囊的委托】会同时
// 触发：一张迷你表 + 一张详情表同时打开，玩家看到的是那张旧的。
// 现在：删掉两段老实现与 renderMiniStatsTable/getStatsModalContent（已无引用），
// 全部由 init() 里绑定的 `#avatar-corner` / `#opponent-avatar-corner` 点击 →
// window.showUserProfile() 打开与排行榜同款的面板。
// 个人信息相关元素
const showProfileBtn = document.getElementById('show-profile');
const profileModal = document.getElementById('profile-modal');
const profileModalClose = document.getElementById('profile-modal-close');
const profileForm = document.getElementById('profile-form');
const profileAvatar = document.getElementById('profile-avatar');
const avatarInput = document.getElementById('avatar-input');
const profileUsername = document.getElementById('profile-username');
const profileSignature = document.getElementById('profile-signature');
const profileSaveMsg = document.getElementById('profile-save-msg');

// 「我是谁」+ 可编辑项的池子（2026-09-17 名片批）。
// 只在 init() 里拉一次：GET /api/profile 未登录会 401，按游客处理（保持 null）。
// 用来判断"看的是不是自己" —— 只有看自己才在名片上渲染「编辑资料」。
let profileSelfName = null;
let profileCatalog = null;
// 自己视角的徽章目录（**含未解锁**）。查看面取数走的是 `/user_stats`，而按第 2 批契约
// `/user_stats` 只下发已解锁的徽章（避免暴露别人的进度）—— 所以"自己看自己"时必须
// 另外拿 `/api/profile` 那一份，否则名片上永远只有已解锁的、看不到灰掉的未解锁位。
let profileSelfAchievements = null;
let profileSelfBadgeCount = null;
let profileSelfBadgesPromise = null;

// 把 /api/profile 拿回来的自己视角数据收进缓存（init 与"临时补拉"两条路都走它）
function takeSelfProfile(profile) {
    if (!profile) return;
    profileSelfName = profile.username || profileSelfName;
    profileCatalog = profile.catalog || profileCatalog;
    if (Array.isArray(profile.achievements)) {
        profileSelfAchievements = profile.achievements;
        profileSelfBadgeCount = profile.badge_count || null;
    }
}

// 自己视角的徽章目录：已有缓存直接给，没有就补拉一次（同一个请求复用，不重复打）
function ensureSelfBadges() {
    if (Array.isArray(profileSelfAchievements)) return Promise.resolve(profileSelfAchievements);
    if (!profileSelfBadgesPromise) {
        profileSelfBadgesPromise = fetch('/api/profile')
            .then(r => (r.ok ? r.json() : null))
            .then(res => { takeSelfProfile(res && res.profile); return profileSelfAchievements; })
            .catch(() => null);
    }
    return profileSelfBadgesPromise;
}

function loadSelfIdentity() {
    if (loadSelfIdentity.done) return;
    loadSelfIdentity.done = true;
    fetch('/api/profile').then(r => (r.ok ? r.json() : null)).then(res => {
        takeSelfProfile(res && res.profile);
    }).catch(() => { /* 游客：按未登录处理 */ });
}

// 头像/签名改完之后把当前打开的那张名片刷一遍（看的是谁由 showUserProfile 记着）
function refreshViewedProfileCard() {
    const name = window.__viewedProfileName;
    if (name && typeof window.showUserProfile === 'function') window.showUserProfile(name);
}

// 页头「个人信息」= 看自己那张名片（查看态，右上角有「编辑资料」进编辑面）。
// 表单不再直接摊开：打开即干净名片，这也是这批改版的主要目的。
if (showProfileBtn) {
    showProfileBtn.onclick = (e) => {
        if (e && e.preventDefault) e.preventDefault();
        const myName = window.__USERNAME || '';
        if (myName && typeof window.showUserProfile === 'function') {
            window.showUserProfile(myName);
            return;
        }
        if (typeof showMessage === 'function') showMessage('未登录，无法查看个人信息', { type: 'warning' });
    };
}
// 编辑面的关闭：× 与点遮罩都只收起弹窗（未保存的改动由「取消」负责丢弃）
if (profileModalClose) profileModalClose.onclick = () => profileModal.classList.add('hidden');
if (profileModal) {
    profileModal.onclick = (e) => {
        if (e.target === profileModal) profileModal.classList.add('hidden');
    };
}

// 签名保存
if (profileForm) {
    profileForm.onsubmit = function (e) {
        e.preventDefault();
        const formData = new FormData();
        formData.append('signature', profileSignature.value);
        fetch('/api/profile/signature', { method: 'POST', body: formData })
            .then(r => r.json()).then(res => {
                if (res.success) {
                    profileSaveMsg.textContent = '签名已保存';
                    profileSaveMsg.style.color = '';
                    refreshViewedProfileCard();
                } else {
                    profileSaveMsg.textContent = '保存失败';
                    profileSaveMsg.style.color = 'red';
                }
            });
    };
}

// 头像上传（控件的 id 与行为都保持原样，只是成功后再把名片刷一遍）
if (avatarInput) {
    avatarInput.onchange = function () {
        const file = avatarInput.files[0];
        if (!file) return;
        const formData = new FormData();
        formData.append('avatar', file);
        fetch('/api/profile/avatar', { method: 'POST', body: formData })
            .then(r => r.json()).then(res => {
                if (res.success && res.avatar) {
                    profileAvatar.src = res.avatar + '?t=' + Date.now();
                    profileSaveMsg.textContent = '头像已更新';
                    profileSaveMsg.style.color = '';
                    refreshViewedProfileCard();
                } else {
                    profileSaveMsg.textContent = res.error || '头像上传失败';
                    profileSaveMsg.style.color = 'red';
                }
            });
    };
}
// 设置相关元素
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
const settingsModalClose = document.getElementById('settings-modal-close');
const primaryColorPicker = document.getElementById('primary-color-picker');
const settingsSaveBtn = document.getElementById('settings-save-btn');

// 设置弹窗逻辑
if (settingsBtn && settingsModal && settingsModalClose) {
    settingsBtn.onclick = () => {
        // 读取当前主色（老用户存过的自定义色不能丢）
        themePickerTouched = false;
        if (primaryColorPicker) primaryColorPicker.value = currentPrimaryHex();
        // 每次打开设置默认停在「外观与主题」（左导航第一项）
        showSettingsPane('look');
        settingsModal.classList.remove('hidden');
    };
    settingsModalClose.onclick = () => settingsModal.classList.add('hidden');
    settingsModal.onclick = (e) => {
        if (e.target === settingsModal) settingsModal.classList.add('hidden');
    };
}

// 取色器：边拖边生效（原来的行为是"点保存才生效"，现在多了一套主题预设，
// 必须知道玩家到底动没动过取色器，见下面 settingsSaveBtn 的注释）。
if (primaryColorPicker) {
    primaryColorPicker.addEventListener('input', () => {
        themePickerTouched = true;
        applyCustomPrimaryColor(primaryColorPicker.value);
    });
}

if (settingsSaveBtn && primaryColorPicker) {
    settingsSaveBtn.onclick = () => {
        // ⚠️ 只有玩家真的动过取色器才写 battleship_primary_color。
        // 否则"选了主题预设 → 点保存"会把取色器里那个还没更新的旧自定义色当成
        // 新的自定义色写回去，预设当场被覆盖（等于选了个寂寞）。
        if (themePickerTouched) {
            applyCustomPrimaryColor(primaryColorPicker.value);
        }
        if (settingsModal) settingsModal.classList.add('hidden');
    };
}

// 设置页左导航：每次只显示一个 .settings-pane（pane 名与 data-pane 一致）
function showSettingsPane(pane) {
    const name = pane || 'look';
    document.querySelectorAll('#settings-modal .settings-pane[data-pane]').forEach(section => {
        section.classList.toggle('hidden', section.dataset.pane !== name);
    });
    document.querySelectorAll('#settings-modal .settings-nav-item[data-pane]').forEach(item => {
        item.classList.toggle('active', item.dataset.pane === name);
    });
    return name;
}

// 浮层互斥：打开一个浮层前，把不该留在它后面的关掉。
//
// ⚠️ 2026-09-17 作者实测「点编辑资料，编辑面开在个人信息窗口**下面**，得先手动关掉查看面才能看到」。
// 根因：本项目所有弹窗都是 `.modal-overlay`、**z-index 全是 10000** —— 谁在 DOM 里靠后谁赢，
// 而 `#opponent-stats-modal`（查看面）在 index.html 里排在 `#profile-modal`（编辑面）之后
// → 编辑面必然被盖住。所以「先关掉别的」是唯一可靠的顺序保证；CSS 里给编辑面留了 z-index 兜底。
// ⚠️ 本函数必须是**顶层**函数：查看面/编辑面那套渲染在嵌套作用域里，设置面在顶层，
//    只有顶层定义才能让两边都调到（否则点设置会 ReferenceError）。
// 新增浮层时无需改本函数：只要带 `.modal-overlay` 就自动参与互斥。
// 反作弊管理后台入口（2026-09-20）：管理员看个人信息卡时，加一个「查后台」按钮。
//
// ⚠️ 必须是**顶层**函数（与 `closeOverlaysExcept` 同一理由）：`showUserProfile` 在
//    嵌套作用域里，而它引用的东西不能是那个作用域的局部变量（否则 ReferenceError
//    被 `.then()` 吞掉、页面零提示 —— 本项目的第 6 条硬教训）。
//
// ⚠️ 普通玩家**一个请求都不发**：`admin.js` 只有在 `/api/admin/me` 说 is_admin 时
//    才把 `window.battleshipAdmin.isAdmin()` 变成 true。这里先问它，
//    false 就直接返回 —— 普通玩家路径零开销，也不会因为 403 在控制台刷红。
function scheduleAdminEntry(username) {
    if (typeof window === 'undefined') return;
    const adm = window.battleshipAdmin;
    if (!adm || typeof adm.isAdmin !== 'function' || !adm.isAdmin()) return;
    if (!username) return;                      // 看自己时不挂（自己那张卡另有入口）

    // 按钮插进信息卡。卡是异步渲染的，所以用轮询等它出现（最多约 3 秒）。
    let tries = 0;
    const timer = setInterval(() => {
        tries += 1;
        const content = document.getElementById('opponent-stats-content');
        if (!content) { if (tries > 30) clearInterval(timer); return; }
        // 只在"正在看的那个人"没变时才挂，避免快速切换时挂错人
        if (window.__viewedProfileName !== username) { clearInterval(timer); return; }
        if (content.querySelector('.admin-open-player-btn')) { clearInterval(timer); return; }

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn secondary admin-open-player-btn';
        btn.textContent = '查后台';
        btn.onclick = () => {
            // 服务端按 uid 查；先按用户名换 uid。
            // ⚠️ 用 `/user_stats`（既有的公开战绩接口），**不要**写 `/api/profile`
            //    —— 后者是"当前登录者自己的名片"，不接受 username 参数（实测 404/401）。
            fetch('/user_stats?username=' + encodeURIComponent(username),
                  { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
                .then((r) => r.json())
                .then((j) => {
                    const uid = j && j.stats && j.stats.id;
                    if (uid) { adm.openPlayer(uid); }
                    else { alert('拿不到该玩家的 ID'); }
                })
                .catch(() => alert('查询失败（网络）'));
        };
        content.insertBefore(btn, content.firstChild);
        clearInterval(timer);
    }, 100);
}

function closeOverlaysExcept(keepId) {
    //    这里曾经是硬编码 6 个 id，而 index.html 已有 9 个 `.modal-overlay` ——
    //    漏掉的 #login-modal / #register-modal / #discard-pile-modal 不参与互斥，
    //    会被后开的面板压住（见本文件上方那条注释描述的坑）。
    //    改成按类名取后，新增浮层只要带 `.modal-overlay` 就自动参与互斥。
    if (typeof document === 'undefined' || !document.querySelectorAll) return;
    document.querySelectorAll('.modal-overlay').forEach((el) => {
        if (keepId && el.id === keepId) return;
        if (!el.classList.contains('hidden')) el.classList.add('hidden');
    });
}
window.closeOverlaysExcept = closeOverlaysExcept;

// 打开设置弹窗（可指定落在哪个分类上），供 #profile-goto-account / 🎬 / 🎵 等入口复用
function openSettingsModal(pane) {
    if (!settingsModal) return false;
    closeOverlaysExcept('settings-modal');   // 同上的浮层互斥：别让查看面/编辑面压在设置面下面
    themePickerTouched = false;
    if (primaryColorPicker) primaryColorPicker.value = currentPrimaryHex();
    showSettingsPane(pane || 'look');
    settingsModal.classList.remove('hidden');
    return true;
}

function applyPrimaryColor(color) {
    const dark = darkenHex(color, 0.25);
    const light = lightenHex(color, 0.15);
    document.documentElement.style.setProperty('--primary', color);
    document.documentElement.style.setProperty('--primary-600', dark);
    document.documentElement.style.setProperty('--primary-rgb', hexToRgb(color));
    document.documentElement.style.setProperty('--primary-gradient', `linear-gradient(135deg, ${dark}, ${light})`);
    document.documentElement.style.setProperty('--primary-50', `rgba(${hexToRgb(color)}, 0.12)`);
    document.documentElement.style.setProperty('--shadow-glow', `0 0 15px rgba(${hexToRgb(color)}, 0.5)`);
}

// 十六进制颜色转 "r, g, b" 字符串（供 rgba(var(--primary-rgb), ...) 使用）
function hexToRgb(hex) {
    const h = String(hex).trim().replace('#', '');
    const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
    const n = parseInt(full, 16);
    if (isNaN(n)) return '21, 101, 192';
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

// 按百分比加深十六进制颜色，非法输入时回退默认色
function darkenHex(hex, amount) {
    return shadeHex(hex, -amount);
}

// 按百分比提亮十六进制颜色，非法输入时回退默认色
function lightenHex(hex, amount) {
    return shadeHex(hex, amount);
}

function shadeHex(hex, amount) {
    const rgb = hexToRgb(hex).split(',').map(Number);
    if (rgb.length !== 3 || rgb.some(isNaN)) return '#1565c0';
    const adjust = v => Math.max(0, Math.min(255, Math.round(v * (1 + amount))));
    return `#${rgb.map(adjust).map(v => v.toString(16).padStart(2, '0')).join('')}`;
}

// ---------------------------------------------------------------------------
// 主题预设（2026-09-17 个人信息名片批）
//
// 具名预设只做一件事：把 html[data-theme-preset="…"] 设上，颜色变量由 CSS 覆盖
// （style.css 那一节，T2 写）。主色仍然可以被玩家手动改（#primary-color-picker），
// 两种状态互斥：
//   选具名预设 → 清掉 battleship_primary_color（否则旧的自定义色会一直压着预设）
//   手动改主色 → 预设记为 custom，并显示 #theme-preset-hint
// applyPrimaryColor() 往 documentElement 写的是**内联**变量，它优先级高于任何
// CSS 规则，所以切回预设时必须逐个 removeProperty，只清 localStorage 是不够的。
// ---------------------------------------------------------------------------
const THEME_PRESETS = ['deep', 'lava', 'cyber', 'dusk', 'aurora', 'classic'];
// 这些是 applyPrimaryColor() 会写进 documentElement.style 的变量名
const PRIMARY_INLINE_VARS = ['--primary', '--primary-600', '--primary-rgb',
    '--primary-gradient', '--primary-50', '--shadow-glow'];
let themePickerTouched = false;

function clearInlinePrimaryColor() {
    PRIMARY_INLINE_VARS.forEach(name => document.documentElement.style.removeProperty(name));
}

// `<input type=color>` 只认 #rrggbb；本地存过的可能是 rgb(r, g, b) 或 #abc
function normalizeHexColor(value, fallback) {
    const raw = String(value == null ? '' : value).trim();
    const m = raw.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i);
    if (m) {
        return '#' + [m[1], m[2], m[3]]
            .map(n => Math.max(0, Math.min(255, parseInt(n, 10))).toString(16).padStart(2, '0'))
            .join('');
    }
    const short = raw.match(/^#([0-9a-f]{3})$/i);
    if (short) return '#' + short[1].split('').map(c => c + c).join('').toLowerCase();
    if (/^#[0-9a-f]{6}$/i.test(raw)) return raw.toLowerCase();
    return fallback || '#1976d2';
}

function currentPrimaryHex() {
    const stored = localStorage.getItem('battleship_primary_color');
    if (stored) return normalizeHexColor(stored);
    const computed = (getComputedStyle(document.documentElement).getPropertyValue('--primary') || '').trim();
    return normalizeHexColor(computed, '#1976d2');
}

// 把「当前主题」同步到设置页那排预设卡上（.selected 由 CSS 画勾）
function syncThemePresetUI(preset) {
    const current = preset || localStorage.getItem('battleship_theme_preset') || 'deep';
    document.querySelectorAll('#theme-preset-grid .theme-card[data-preset]').forEach(card => {
        card.classList.toggle('selected', card.dataset.preset === current);
    });
    const hint = document.getElementById('theme-preset-hint');
    if (hint) hint.classList.toggle('hidden', current !== 'custom');
}

function applyThemePreset(name) {
    const preset = THEME_PRESETS.indexOf(name) >= 0 ? name : 'deep';
    document.documentElement.dataset.themePreset = preset;
    localStorage.setItem('battleship_theme_preset', preset);
    // 具名预设 = 不再使用自定义主色：清掉存量 + 清掉内联变量（后者会压过 CSS 预设）
    localStorage.removeItem('battleship_primary_color');
    clearInlinePrimaryColor();
    syncThemePresetUI(preset);
    if (primaryColorPicker) primaryColorPicker.value = currentPrimaryHex();
    return preset;
}

function applyCustomPrimaryColor(color) {
    const hex = normalizeHexColor(color, '#1976d2');
    localStorage.setItem('battleship_primary_color', hex);
    localStorage.setItem('battleship_theme_preset', 'custom');
    document.documentElement.dataset.themePreset = 'custom';
    applyPrimaryColor(hex);
    syncThemePresetUI('custom');
    if (primaryColorPicker) primaryColorPicker.value = hex;
    return hex;
}

// 页面加载时恢复主题：具名预设优先于残留的旧主色（老用户只存了主色的，
// 仍然按自定义色恢复 —— 那批颜色不能丢）
function restoreThemeFromStorage() {
    const preset = localStorage.getItem('battleship_theme_preset');
    if (preset && THEME_PRESETS.indexOf(preset) >= 0) return applyThemePreset(preset);
    const color = localStorage.getItem('battleship_primary_color');
    if (color) return applyCustomPrimaryColor(color);
    return applyThemePreset(preset || 'deep');
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restoreThemeFromStorage);
} else {
    restoreThemeFromStorage();
}

// 音乐控制相关元素
const musicBtn = document.getElementById('music-btn');
const musicVolume = document.getElementById('music-volume');
const volumeDisplay = document.getElementById('volume-display');
const musicLoopMode = document.getElementById('music-loop-mode');
const musicTogglePlay = document.getElementById('music-toggle-play');
const musicNext = document.getElementById('music-next');
const musicPrevious = document.getElementById('music-previous');
const musicMuted = document.getElementById('music-muted');
const currentTrack = document.getElementById('current-track');

// 音乐按钮逻辑
// ⚠️ 2026-09-17：设置页改「左导航 + 分区」后，音乐控件在 `sound` 分区里、默认是隐藏的。
// 只 remove('hidden') 的话点 🎵 会落在「外观与主题」上，玩家以为音乐设置没了。
// 所以走 openSettingsModal('sound') —— 切分区只有那一份实现。
if (musicBtn) {
    musicBtn.onclick = () => {
        openSettingsModal('sound');
    };
}

// 音量控制
if (musicVolume && volumeDisplay) {
    musicVolume.addEventListener('input', (e) => {
        const volume = e.target.value / 100;
        if (window.bgMusicPlayer) {
            window.bgMusicPlayer.setVolume(volume);
            volumeDisplay.textContent = e.target.value + '%';
            localStorage.setItem('bgm_volume', volume);
        }
    });
}

// 循环模式控制
if (musicLoopMode) {
    musicLoopMode.addEventListener('change', (e) => {
        if (window.bgMusicPlayer) {
            window.bgMusicPlayer.setLoopMode(e.target.value);
            localStorage.setItem('bgm_loop_mode', e.target.value);
        }
    });
}

// 播放/暂停控制
if (musicTogglePlay) {
    musicTogglePlay.onclick = () => {
        if (window.bgMusicPlayer) {
            window.bgMusicPlayer.togglePlay();
            updateMusicStatus();
        }
    };
}

// 下一首控制
if (musicNext) {
    musicNext.onclick = () => {
        if (window.bgMusicPlayer) {
            window.bgMusicPlayer.playNext();
            updateMusicStatus();
        }
    };
}

// 上一首控制
if (musicPrevious) {
    musicPrevious.onclick = () => {
        if (window.bgMusicPlayer) {
            window.bgMusicPlayer.playPrevious();
            updateMusicStatus();
        }
    };
}

// 静音控制
if (musicMuted) {
    musicMuted.addEventListener('change', (e) => {
        if (window.bgMusicPlayer) {
            window.bgMusicPlayer.isMuted = e.target.checked;
            if (window.bgMusicPlayer.audio) {
                window.bgMusicPlayer.audio.muted = e.target.checked;
            }
            localStorage.setItem('bgm_muted', e.target.checked);
        }
    });
}

// 更新音乐状态显示
function updateMusicStatus() {
    if (!window.bgMusicPlayer) return;
    
    const status = window.bgMusicPlayer.getStatus();
    
    // 更新当前播放曲目
    if (currentTrack) {
        if (status.currentTrack) {
            const trackName = status.currentTrack.split('/').pop();
            currentTrack.textContent = trackName;
        } else {
            currentTrack.textContent = '未播放';
        }
    }
    
    // 更新音量显示
    if (musicVolume && volumeDisplay) {
        musicVolume.value = status.volume * 100;
        volumeDisplay.textContent = Math.round(status.volume * 100) + '%';
    }
    
    // 更新循环模式
    if (musicLoopMode) {
        musicLoopMode.value = status.loopMode;
    }
    
    // 更新静音状态
    if (musicMuted) {
        musicMuted.checked = status.isMuted;
    }
}

// 设置弹窗打开时更新音乐状态
if (settingsBtn && settingsModal) {
    const originalOnClick = settingsBtn.onclick;
    settingsBtn.onclick = () => {
        if (originalOnClick) originalOnClick();
        updateMusicStatus();
    };
}

// 帮助相关元素
const helpBtn = document.getElementById('help-btn');
const helpModal = document.getElementById('help-modal');
const helpModalClose = document.getElementById('help-modal-close');
const helpContent = document.getElementById('help-content');
const helpMagicCards = document.getElementById('help-magic-cards');
// 对手信息相关元素
const opponentUsernameInfo = document.getElementById('opponent-username-info');
const myUsernameInfo = document.getElementById('my-username-info');
const showOpponentStatsBtn = document.getElementById('show-opponent-stats');
const opponentStatsModal = document.getElementById('opponent-stats-modal');
const opponentStatsModalClose = document.getElementById('opponent-stats-modal-close');
const opponentStatsContent = document.getElementById('opponent-stats-content');
// 对手战绩按钮事件
const showUserStatsBtn = document.getElementById('show-user-stats');
const userStatsModal = document.getElementById('user-stats-modal');
const userStatsModalClose = document.getElementById('user-stats-modal-close');
const userStatsContent = document.getElementById('user-stats-content');

// 对局详情模态窗口元素
const matchDetailModal = document.getElementById('match-detail-modal');
const matchDetailModalClose = document.getElementById('match-detail-modal-close');
const matchDetailContent = document.getElementById('match-detail-content');
// DOM元素
const startScreen = document.getElementById('start-screen');
const customRoomScreen = document.getElementById('custom-room-screen');
const matchSuccessScreen = document.getElementById('match-success-screen');
const shipPlacementScreen = document.getElementById('ship-placement-screen');
const rpsScreen = document.getElementById('rps-screen');
const gameScreen = document.getElementById('game-screen');
const gameOverScreen = document.getElementById('game-over-screen');

// 匹配成功界面元素
const opponentInfo = document.getElementById('opponent-info');
const countdownTimer = document.getElementById('countdown-timer');
const countdownBar = document.getElementById('countdown-bar');
const countdownFill = countdownBar.querySelector('.countdown-fill');

// 导航栏元素
const gameNav = document.getElementById('game-nav');

// 开始界面元素
const findMatchBtn = document.getElementById('find-match');
const aiMatchBtn = document.getElementById('ai-match');
const customRoomBtn = document.getElementById('custom-room');
const matchStatus = document.getElementById('match-status');
const cancelMatchBtn = document.getElementById('cancel-match');
// 排位排队那一套（段位批）。**不与休闲那套共用 id / 状态**，但两者是同一个队列，
// 所以互相之间要"进一个先清另一个"（见 rankedMatch / findMatch）。
const rankedMatchBtn = document.getElementById('ranked-match');
const rankedStatus = document.getElementById('ranked-status');
const cancelRankedBtn = document.getElementById('cancel-ranked');
const playerNameInput = document.getElementById('player-name');

// 自定义房间游戏界面元素
const customCreateRoomBtn = document.getElementById('custom-create-room');
const customJoinRoomBtn = document.getElementById('custom-join-room');
const customRoomIdInput = document.getElementById('custom-room-id-input');
const customConfirmJoinBtn = document.getElementById('custom-confirm-join');
const customRoomInfo = document.getElementById('custom-room-info');
const customCurrentRoomId = document.getElementById('custom-current-room-id');
const copyInviteLinkBtn = document.getElementById('copy-invite-link');
const inviteLinkMsg = document.getElementById('invite-link-msg');
// 解散房间（大厅批补）：等待房不自动回收，玩家需要一个主动出口
const customCloseRoomBtn = document.getElementById('custom-close-room');
const customCloseRoomMsg = document.getElementById('custom-close-room-msg');
const customPlayerNameInput = document.getElementById('custom-player-name');
const customRoomCodeInput = document.getElementById('custom-room-code');
const backToMainBtn = document.getElementById('back-to-main');

// 战舰放置界面元素
const playerBoard = document.getElementById('player-board');
const shipsPlaced = document.getElementById('placed-count');
const confirmShipsBtn = document.getElementById('confirm-ships');
const randomShipsBtn = document.getElementById('random-ships');

// 猜拳界面元素
const rpsChoices = document.querySelectorAll('.rps-choice');
const rpsResult = document.getElementById('rps-result');
const rpsRound = document.getElementById('rps-round');

// 游戏界面元素
const gamePlayerBoard = document.getElementById('game-player-board');
const opponentBoard = document.getElementById('opponent-board');
const yourShips = document.getElementById('your-ships');
const opponentShips = document.getElementById('opponent-ships');
const currentPlayer = document.getElementById('current-player');
const attacksRemaining = document.getElementById('attacks-remaining');
const gameRound = document.getElementById('game-round');

// 局内聊天相关元素
const chatContainer = document.getElementById('in-game-chat-container');
const chatMessages = document.getElementById('in-game-chat-messages');
const chatInput = document.getElementById('in-game-chat-input');
const chatSendBtn = document.getElementById('in-game-chat-send');
const chatHeader = document.getElementById('in-game-chat-header');

// 聊天Socket初始化
let chatSocketInitialized = false;

function initInGameChatSocket() {
    if (chatSocketInitialized) return;
    if (!window.gameState || !window.gameState.socket) return;
    const socket = window.gameState.socket;
    socket.on('chat_message', function (data) {
        console.log("Received chat message:", data);
        appendChatMessage(data.username, data.message, data.isMe);
    });
    chatSocketInitialized = true;
}

// 发送消息
function sendChatMessage() {
    if (!chatInput || !chatInput.value.trim() || !window.gameState || !window.gameState.socket) return;
    const msg = chatInput.value.trim().slice(0, 100);
    window.gameState.socket.emit('chat_message', { room_id: gameState.roomId, message: msg });
    chatInput.value = '';
}

if (chatSendBtn && chatInput) {
    chatSendBtn.addEventListener('click', sendChatMessage);
    chatInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') sendChatMessage();
    });
}

// 显示消息
function appendChatMessage(username, message, isMe) {
    if (!chatMessages) return;
    const div = document.createElement('div');
    div.className = 'in-game-chat-message ' + (isMe ? 'me' : 'opponent');
    div.innerHTML = `<span>${escapeHtml(username)}：</span>${escapeHtml(message)}`;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

// 只在游戏主界面显示聊天框
function setChatVisible(visible) {
    if (chatContainer) chatContainer.style.display = visible ? '' : 'none';
}

setChatVisible(false);

// 使聊天框可拖动（浮动窗，位置记在本地）
(function enableDraggableChat() {
    if (!chatContainer || !chatHeader) return;
    makeFloatingDraggable(chatContainer, chatHeader, 'in_game_chat_pos');
})();


// 日志功能元素
const logContainer = document.querySelector('.log-container');
const toggleLogBtn = document.getElementById('toggle-log');
const gameLogs = document.getElementById('game-logs');

// 游戏结束界面元素
const gameResult = document.getElementById('game-result');
const playAgainBtn = document.getElementById('play-again');
const returnToMenuBtn = document.getElementById('return-to-menu'); // 返回主菜单按钮

// 排行榜界面元素
const leaderboardScreen = document.getElementById('leaderboard-screen');
const backFromLeaderboardBtn = document.getElementById('back-to-main-from-leaderboard');
const leaderboardTableBody = document.querySelector('#leaderboard-table tbody');
const leaderboardError = document.getElementById('leaderboard-error');
// 段位榜（段位批）：页签条 + 独立的一张表 + 自己的错误条。
// ⚠️ 段位榜**不打进 #leaderboard-table**：那张表的表头是「胜/负/胜率/最长连胜」，
//    段位榜的列完全不同（名次/玩家/段位/排位分/战绩），塞进去只能改表头，
//    而 #leaderboard-table 的表头是既有回归工具盯着的（profile_leaderboard_check）。
const leaderboardTabs = document.getElementById('leaderboard-tabs');
const leaderboardRecordBox = document.getElementById('leaderboard-container');
const leaderboardRankedBox = document.getElementById('leaderboard-ranked-container');
const rankedTableBody = document.querySelector('#ranked-table tbody');
const rankedError = document.getElementById('ranked-error');

// 大厅界面元素
const lobbyScreen = document.getElementById('lobby-screen');
const joinLobbyBtn = document.getElementById('join-lobby-match');
const leaveLobbyBtn = document.getElementById('leave-lobby-match');
const backFromLobbyBtn = document.getElementById('back-to-main-from-lobby');
const lobbyPlayerCount = document.getElementById('lobby-player-count');
const lobbyPlayersList = document.getElementById('lobby-players-list');
// 大厅批（2026-09-18）新增元素。契约见 docs/LOBBY_2026_09_18.md §3.2。
// ⚠️ 这些 id 必须真的存在于 templates/index.html —— 引用了但页面里没有的 id
//    表现是 getElementById 拿到 null、被 if (el) 兜掉，**不报错、只是点了没反应**
//    （tools/dom_contract_check.mjs 就是查这个的）。
const lobbyBtn = document.getElementById('lobby-btn');
const lobbyRefreshBtn = document.getElementById('lobby-refresh');
const lobbyRankedBtn = document.getElementById('lobby-ranked-match');
const lobbyInLobbyCount = document.getElementById('lobby-in-lobby-count');
const lobbyQueueCasual = document.getElementById('lobby-queue-casual');
const lobbyQueueRanked = document.getElementById('lobby-queue-ranked');
const lobbyRoomsList = document.getElementById('lobby-rooms-list');
const lobbyRoomNameInput = document.getElementById('lobby-room-name');
const lobbyRoomPublic = document.getElementById('lobby-room-public');
const lobbyCreateRoomBtn = document.getElementById('lobby-create-room');
const lobbyChatMessages = document.getElementById('lobby-chat-messages');
const lobbyChatInput = document.getElementById('lobby-chat-input');
const lobbyChatSendBtn = document.getElementById('lobby-chat-send');


// 登录/注册模态弹窗及控件
const loginModal = document.getElementById('login-modal');
const registerModal = document.getElementById('register-modal');
const loginUsernameInput = document.getElementById('login-username');
const loginPasswordInput = document.getElementById('login-password');
const loginSubmitBtn = document.getElementById('login-submit');
const loginModalClose = document.getElementById('login-modal-close');
const registerUsernameInput = document.getElementById('register-username');
const registerPasswordInput = document.getElementById('register-password');
const registerSubmitBtn = document.getElementById('register-submit');
const registerModalClose = document.getElementById('register-modal-close');

// 游戏状态
window.gameState = {
    socket: null,
    playerId: null,
    roomId: null,
    playerName: '玩家',
    opponentName: '对手',
    ships: [],
    placedShips: 0,
    maxShips: 6,            // 默认可摆放的船数为6
    isMyTurn: false,
    attackOrder: [],        // 攻击顺序 [先手, 后手]；用于判断「自己是否先手」
    myAttacks: [],
    opponentAttacks: [],
    lastAttack: null,
    // 大厅（2026-09-18 大厅批）：最近一份 lobby_state、自己的身份键、
    // 是否已订阅（离开大厅页面时要退订，否则对局中还在收大厅广播）。
    lobbyState: null,
    lobbyKey: null,
    lobbySubscribed: false,
    deck: [],               // 牌堆
    hand: [],               // 手牌
    discardPile: [],        // 弃牌堆
    chain: [],              // 连锁栈
    shenweiHoles: [],       // 神威！扣掉的区域 [{player,x1,y1,x2,y2,return_turn}]
    currentPhase: null,     // 当前游戏阶段
    fieldMagic: null,       // 场地魔法
    revealedCells: [],      // 已被卡牌显形的对方格子（服务端是持久记录，本地也要留住）
    pendingChainCard: null, // 连锁响应窗口里已选好、正在点目标的速阶3卡
    pendingEffectChoice: null, // 神之宣告：出牌前选好的效果
    selectedCardIndex: -1,  // 当前选中的卡牌索引，-1表示未选中
    selectedCardKey: null,  // 选中的是哪张卡（name+speed）——手牌一变下标就不可信了
    inRoom: false,          // 是否在对局房间中（用于掉线重连）
    reconnectToken: null,   // 对局重连 token
    frozen: false,          // 对手掉线宽限期内冻结操作
    opponentGone: null,     // 对手掉线信息 {deadline}
    sacrificedSelf: [],     // 自己因效果（恶魔契约等）牺牲的格子 → 画在自己棋盘上
    sacrificedOpponent: [], // 对方牺牲的格子（公开信息）→ 画在对方棋盘上
    // 「仁王之盾」被打破的格子：打了一炮被盾挡下，船毫发无伤。
    // ⚠️ 它【不算已攻击】：同一回合还能再打这一格（服务端也不记进 attacks）。
    // 画成"破盾"标记而不是普通命中叉，玩家才看得懂发生了什么。
    shieldBrokenMine: [],       // 我打出来的破盾格 → 画在对方棋盘
    shieldBrokenOpponent: [],   // 对方打出来的破盾格 → 画在我自己棋盘
    // 「绝处逢生」的候选格：牺牲前原本有战舰的那几格，唯一一艘新船必在其中。
    // 公开信息，双方棋盘都高亮；这些格子【不是红叉】，对方照样能打。
    lastStandCells: [],
    // 上面那批候选格属于【谁的棋盘】（服务端 last_stand_cells.owner 下发）。
    // 两块棋盘各有自己的 0-5 坐标，画错棋盘会让玩家以为"敌方可能在这几格"。
    lastStandOwner: null,
    // 冻结的 3×3 区域（服务端 frozen_area 下发）：{x1,y1,x2,y2,owner,caster,frozen,until_round}。
    // owner = 这片区域在哪块棋盘上（受害者）。船上的雪花仍只给被冻的人看，这里是"区域"。
    frozenArea: null,
    // 正等待自己点选一艘船牺牲（恶魔契约等）。棋盘每次重绘后靠它把高亮补回来，
    // 否则伤害结算的重绘会把选区冲掉、让人以为「点了没反应」。
    pendingSacrifice: null,
    // ★ 棋盘选区的**归属**（2026-09-20 优先级仲裁批）。
    // `selectingOnBoard` 只说"有人在选"，不说"是谁在选"；两张效果同时想抢棋盘时，
    // 后来的那个会因为 `selectingOnBoard` 为真而静默失败（玩家报的"点了没反应"）。
    // 记下归属后就能给出明确提示：{kind:'sacrifice', reason, label}。
    boardSelection: null,
    // 正等待自己点选至多 3 艘船加护盾（仁王之盾）：{max, picked, cells}。
    // 同样靠它让 paintRenwangCells() 在棋盘重绘后补回高亮 + 保住已选。
    renwangPick: null,
    // 当前生效的效果角标（服务端 active_effects / room_sync 下发）。
    // 出牌门禁要读它判断「绝处逢生」，所以必须有初值 —— 此前只在 room_sync
    // 里被赋值，未重连过的玩家这里是 undefined，读取方得各自容错。
    activeEffects: [],
    // 绝处逢生的两个标记，服务端 room_sync 显式下发（别再靠卡名猜，理由见
    // isLastStandActive 的注释）。lastStandWin 只用于提示文案，不参与门禁。
    lastStandLock: false,
    lastStandWin: false,
    // 生效中效果角标的数据（服务端按收件人视角分别下发 self / opponent）。
    // 浮层靠这两份数据按卡名回查说明，所以角标重绘后也能正确展开。
    activeEffectsSelf: [],
    activeEffectsOpponent: [],
    // 「拒绝所有阶段转换时点」开关（服务端 decline_priority 的本地镜像）。
    // 勾上后服务端不再向我发优先权询问；开关本身可随时取消勾选。
    declinePriority: false,
    // 已经把这个偏好推给哪个房间了（每个房间推一次就够）
    declinePrioritySyncedRoom: null,
    // 优先权询问里已选好、正在点目标的速阶3卡（与 pendingChainCard 同构）
    pendingPriorityCard: null,
    // 我发起的阶段转换正被拦下、在等对方响应（服务端 priority_waiting 下发）。
    // 非空时阶段按钮全部禁用 —— 与后端的 _priority_wait_reason 同一口径。
    priorityWaiting: null,
    // 对方正在宣言神机妙算（服务端 shenji_waiting 下发）。
    // 非空时我也不能行动 —— 与后端的 _shenji_wait_reason 同一口径。
    shenjiWaiting: null
}

let opponentGoneTimer = null;
let opponentGoneEl = null;
let priorityWaitEl = null;
let priorityWaitTimer = null;
let shenjiWaitEl = null;
const ACTIVE_GAME_KEY = 'battle_active_game';

// 统一的 socket 获取入口：已有连接则复用，绝不重复建连。
// 之前多处直接 io.connect 覆盖 gameState.socket，旧连接未关闭会变成孤儿，
// 且 setupSocketListeners 会被重复调用导致同一事件被处理多次。
function ensureSocket() {
    if (gameState.socket) {
        return gameState.socket;
    }
    gameState.socket = io.connect('http://' + window.location.host);
    setupSocketListeners();
    return gameState.socket;
}

// 连接就绪后执行回调；已连接则立即执行。
// 使用 once 而非 on，避免反复调用时叠加重复监听。
function onSocketReady(callback) {
    const socket = ensureSocket();
    if (socket.connected) {
        callback(socket);
    } else {
        socket.once('connect', () => callback(socket));
    }
}

function freezeAlert() {
    if (gameState.frozen) { showAlert('对手已掉线，等待重连中'); return true; }
    return false;
}
function ensureOpponentGoneEl() {
    if (opponentGoneEl) return opponentGoneEl;
    opponentGoneEl = document.createElement('div');
    opponentGoneEl.id = 'opponent-gone-banner';
    opponentGoneEl.style.cssText = 'position:fixed;top:12px;right:12px;z-index:9999;background:#c0392b;color:#fff;padding:10px 16px;border-radius:8px;font-weight:bold;box-shadow:0 2px 10px rgba(0,0,0,.3);display:none';
    document.body.appendChild(opponentGoneEl);
    return opponentGoneEl;
}
function showOpponentGoneBanner(deadline) {
    gameState.opponentGone = { deadline: deadline };
    gameState.frozen = true;
    const el = ensureOpponentGoneEl();
    const tick = () => {
        const left = Math.max(0, Math.ceil(gameState.opponentGone.deadline - Date.now() / 1000));
        el.textContent = '对手已掉线 · 等待重连 ' + left + 's';
        if (left <= 0 && opponentGoneTimer) { clearInterval(opponentGoneTimer); opponentGoneTimer = null; }
    };
    if (opponentGoneTimer) clearInterval(opponentGoneTimer);
    tick();
    opponentGoneTimer = setInterval(tick, 1000);
    el.style.display = 'block';
}
function hideOpponentGoneBanner() {
    gameState.opponentGone = null;
    gameState.frozen = false;
    if (opponentGoneTimer) { clearInterval(opponentGoneTimer); opponentGoneTimer = null; }
    if (opponentGoneEl) opponentGoneEl.style.display = 'none';
}

// ── 「我的阶段转换正被拦下、等对方响应」横幅 ──────────────────────
// 用固定定位的横幅而不是往阶段卡片里加东西：
// 阶段卡片有严格的移动端布局不变量（横屏零纵向滚动的余量只有 1px），
// 而固定定位完全不参与布局，零风险。样式与「对手已掉线」横幅同一套。
function ensurePriorityWaitEl() {
    if (priorityWaitEl) return priorityWaitEl;
    priorityWaitEl = document.createElement('div');
    priorityWaitEl.id = 'priority-waiting-banner';
    priorityWaitEl.style.cssText = 'position:fixed;top:12px;right:12px;z-index:9998;background:#e8a33d;color:#3a2500;padding:10px 16px;border-radius:8px;font-weight:bold;box-shadow:0 2px 10px rgba(0,0,0,.3);display:none';
    document.body.appendChild(priorityWaitEl);
    return priorityWaitEl;
}

// deadline 为秒级时间戳；不传则只显示文案不显示倒计时
function showPriorityWaitingBanner(actionText, deadline) {
    gameState.priorityWaiting = { action_text: actionText, deadline: deadline || null };
    const el = ensurePriorityWaitEl();
    const tick = () => {
        let text = `已发起「${actionText}」 · 等待对方响应`;
        if (gameState.priorityWaiting && gameState.priorityWaiting.deadline) {
            const left = Math.max(0, Math.ceil(gameState.priorityWaiting.deadline - Date.now() / 1000));
            text += ' ' + left + 's';
        }
        el.textContent = text;
    };
    if (priorityWaitTimer) clearInterval(priorityWaitTimer);
    tick();
    priorityWaitTimer = setInterval(tick, 1000);
    el.style.display = 'block';
    updatePhaseUI();
}

function hidePriorityWaitingBanner() {
    if (!gameState.priorityWaiting) return;
    gameState.priorityWaiting = null;
    if (priorityWaitTimer) { clearInterval(priorityWaitTimer); priorityWaitTimer = null; }
    if (priorityWaitEl) priorityWaitEl.style.display = 'none';
    updatePhaseUI();
}

// ── 「对方正在宣言神机妙算」横幅 ────────────────────────────────
// 与上面那条同一套做法（固定定位、不加进阶段卡片）。
// 位置错开 64px：两条横幅可能同时出现（我在等对方响应阶段转换，
// 同时对方在宣言神机妙算），叠在一起会互相盖住。
function ensureShenjiWaitEl() {
    if (shenjiWaitEl) return shenjiWaitEl;
    shenjiWaitEl = document.createElement('div');
    shenjiWaitEl.id = 'shenji-waiting-banner';
    shenjiWaitEl.style.cssText = 'position:fixed;top:64px;right:12px;z-index:9998;background:#3d7de8;color:#fff;padding:10px 16px;border-radius:8px;font-weight:bold;box-shadow:0 2px 10px rgba(0,0,0,.3);display:none';
    document.body.appendChild(shenjiWaitEl);
    return shenjiWaitEl;
}

function showShenjiWaitingBanner(text) {
    gameState.shenjiWaiting = { text: text || '等待对方神机妙算宣言中' };
    const el = ensureShenjiWaitEl();
    el.textContent = gameState.shenjiWaiting.text;
    el.style.display = 'block';
    updatePhaseUI();
}

function hideShenjiWaitingBanner() {
    if (!gameState.shenjiWaiting) return;
    gameState.shenjiWaiting = null;
    if (shenjiWaitEl) shenjiWaitEl.style.display = 'none';
    updatePhaseUI();
}

// 桃园结义的「等对方选牌」是全屏浮层（挡住一切点击），只有 taoyuan_complete 会撤掉它。
// 因此凡是"这一局不用再等了"的时刻都必须主动收掉，否则玩家会被它永久挡住：
//   · 对方取消选择（服务端现在会补发 taoyuan_complete，见 handle_cancel_magic_selection）
//   · 对局结束（例如对方在选择中掉线后被判负）
//   · 棋盘重开
function dismissTaoyuanWaitingOverlay() {
    document.querySelectorAll('.taoyuan-waiting-overlay').forEach(el => el.remove());
}
function saveActiveGame(roomId, playerId) {
    try {
        const prev = loadActiveGame() || {};
        localStorage.setItem(ACTIVE_GAME_KEY, JSON.stringify({ room_id: roomId, player_id: playerId, token: gameState.reconnectToken || prev.token || '' }));
    } catch (e) {}
}
function clearActiveGame() {
    try { localStorage.removeItem(ACTIVE_GAME_KEY); } catch (e) {}
    gameState.inRoom = false;
    gameState.reconnectToken = null;
}
function loadActiveGame() {
    try { return JSON.parse(localStorage.getItem(ACTIVE_GAME_KEY) || 'null'); } catch (e) { return null; }
}
function requestReconnectToken(roomId, playerId) {
    if (!gameState.socket) return;
    gameState.socket.emit('get_reconnect_token', { room_id: roomId, player_id: playerId }, (resp) => {
        if (resp && resp.status === 'success' && resp.token) {
            gameState.reconnectToken = resp.token;
            saveActiveGame(roomId, playerId);
        }
    });
}
function applyRoomSync(data) {
    gameState.roomId = data.room_id;
    gameState.playerId = data.player_id;
    gameState.inRoom = true;
    gameState.currentPhase = data.current_phase;
    gameState.currentAttacker = data.current_attacker;
    gameState.round = data.round;
    // ⚠️ 以前是 `data.hand || []`：快照万一没带 hand（结构变更/字段漏传），
    // 手牌会被直接清空，而且此后只有刷新页面才能恢复。
    // 只有确实拿到数组才覆盖，否则保持现状并要一份权威手牌。
    if (Array.isArray(data.hand)) {
        gameState.hand = data.hand.filter((c) => c && typeof c === 'object' && c.name);
    } else {
        console.warn('[hand] room_sync 没带 hand 数组，保留当前手牌并请求重同步');
        requestHandSync('room_sync:no-hand-array');
    }
    gameState.ships = data.ships || [];
    gameState.myAttacks = data.attacks || [];
    // 对手打在我棋盘上的格：不恢复的话，重连后自己的伤损/沉船会全部显示成完好
    gameState.opponentAttacks = data.opponent_attacks || [];
    gameState.shenweiHoles = data.shenwei_holes || [];
    // 绝处逢生的候选格（公开信息）：重连后高亮不能丢，否则玩家又以为那几格不能打
    if (Array.isArray(data.last_stand_cells)) {
        gameState.lastStandCells = data.last_stand_cells;
        // 候选格属于谁的棋盘也要一起恢复 —— 只恢复格子会让高亮又画错棋盘
        gameState.lastStandOwner = data.last_stand_owner || null;
    }
    // 冻结区域：重连后也要恢复，否则玩家又会忘记冻的是哪片
    gameState.frozenArea = data.frozen_area || null;
    // 连锁/效果上下文：重连后恢复连锁显示与响应窗口
    if (Array.isArray(data.chain)) {
        gameState.chain = data.chain;
        if (typeof updateChainUI === 'function') updateChainUI();
    }
    if (typeof data.chain_waiting !== 'undefined') gameState.chainWaiting = data.chain_waiting;
    if (typeof data.chain_window !== 'undefined') gameState.chainWindow = data.chain_window;
    // 重连正好落在连锁响应窗口内：把响应弹窗补回来（否则窗口一过就再也没有机会响应）
    if (data.chain_waiting && data.chain_window && data.chain_window === gameState.playerId) {
        // 速阶同样先转数字再比（与服务端 _speed3_cards 的 int(c.speed) == 3 一致）。
        // 用 === 比的话，speed 是字符串时会漏掉真正能响应的速阶3卡。
        const speed3 = (gameState.hand || []).filter(c => c && Number(c.speed) === 3);
        const chainItems = data.chain || [];
        const lastItem = chainItems[chainItems.length - 1] || {};
        if (speed3.length > 0 && typeof showChainRequestPrompt === 'function') {
            showChainRequestPrompt({
                speed3_cards: speed3,
                caster: lastItem.caster || null,
                countdown: 10,
            });
        }
    }
    if (Array.isArray(data.active_effects)) gameState.activeEffects = data.active_effects;
    // 绝处逢生的两个标记（服务端显式下发，两个生命周期不同，别合并成一条）
    if (typeof data.last_stand_lock === 'boolean') gameState.lastStandLock = data.last_stand_lock;
    if (typeof data.last_stand_win === 'boolean') gameState.lastStandWin = data.last_stand_win;
    // 重连快照里带的效果角标：此前没带，重连后要等下一次 active_effects 广播才恢复，
    // 玩家会以为效果没了。这里直接渲染回来。
    if (data.effect_badges) {
        renderActiveEffects(data.effect_badges);
    }
    if (data.pending_placement && typeof showPlacementPrompt === 'function') {
        showPlacementPrompt({
            kind: data.pending_placement.kind,
            remaining: data.pending_placement.remaining,
            total: data.pending_placement.total,
            placed: data.pending_placement.placed,
            blocked: data.pending_placement_blocked || [],
            // 神机妙算 / 绝处逢生的合法格：重连后面板要能把这些格子重新点亮，
            // 否则玩家回来发现"原位置点不动了"
            allowed: data.pending_placement_allowed || [],
        });
    }
    if (data.field_magic) gameState.fieldMagic = data.field_magic;
    if (data.opponent_name) {
        gameState.opponentName = data.opponent_name;
        if (typeof opponentUsernameInfo !== 'undefined' && opponentUsernameInfo) opponentUsernameInfo.textContent = data.opponent_name;
    }
    saveActiveGame(data.room_id, data.player_id);

    // 重连正好落在"等待对方响应阶段转换"的窗口里：横幅与按钮禁用要恢复，
    // 否则玩家重连回来看到按钮能点，一点却被服务端拒绝（口径不一致）。
    if (data.priority_waiting && data.priority_waiting.action_text) {
        showPriorityWaitingBanner(data.priority_waiting.action_text, null);
    } else {
        hidePriorityWaitingBanner();
    }

    // 同一件事，神机妙算宣言窗口：重连回来要能恢复「等待对方宣言中」的横幅与冻结。
    if (data.shenji_waiting && data.shenji_waiting.text) {
        showShenjiWaitingBanner(data.shenji_waiting.text);
    } else {
        hideShenjiWaitingBanner();
    }

    // 像正常进入对局一样，先隐藏所有其它界面，避免与主菜单/大厅/等待界面叠层错乱。
    // 注意：这些元素是模块级 const（不在 window 上），必须直接引用。
    function rmActive(el) { try { if (el && el.classList) el.classList.remove('active'); } catch (e) {} }
    function addHidden(el) { try { if (el && el.classList) el.classList.add('hidden'); } catch (e) {} }
    if (typeof startScreen !== 'undefined') rmActive(startScreen);
    if (typeof customRoomScreen !== 'undefined') rmActive(customRoomScreen);
    if (typeof matchSuccessScreen !== 'undefined') rmActive(matchSuccessScreen);
    if (typeof shipPlacementScreen !== 'undefined') rmActive(shipPlacementScreen);
    if (typeof rpsScreen !== 'undefined') rmActive(rpsScreen);
    if (typeof gameOverScreen !== 'undefined') rmActive(gameOverScreen);
    // ⚠️ 屏的显隐只有 `active` 一套机制。这里曾经给 `#lobby-screen` 加 `hidden`，
    //    而 `.hidden{display:none !important}` 会压过 `.screen.active`，且全仓没有任何地方
    //    把屏上的 `hidden` 摘掉 —— 走过这条路径后，点「游戏大厅」能加上 active 却依然
    //    display:none，页面一片空白。屏上只能用 rmActive/switchScreen。
    if (typeof customRoomInfo !== 'undefined') addHidden(customRoomInfo);
    if (typeof customRoomIdInput !== 'undefined') addHidden(customRoomIdInput);
    if (typeof lobbyScreen !== 'undefined') rmActive(lobbyScreen);
    if (typeof leaderboardScreen !== 'undefined') rmActive(leaderboardScreen);
    if (typeof gameNav !== 'undefined' && gameNav) gameNav.style.display = 'none';
    if (typeof gameScreen !== 'undefined' && gameScreen) gameScreen.classList.add('active');

    if (typeof gameRound !== 'undefined' && gameRound) gameRound.textContent = data.round || 1;
    if (typeof yourShips !== 'undefined' && yourShips) yourShips.textContent = data.remaining_ships;
    if (typeof opponentShips !== 'undefined' && opponentShips) opponentShips.textContent = data.opponent_remaining_ships;
    if (typeof updateTurnIndicator === 'function') updateTurnIndicator(data.current_attacker, data.attacks_remaining);
    if (typeof updatePhaseUI === 'function') updatePhaseUI();
    if (typeof updateHandUI === 'function') updateHandUI();

    // 按服务端状态路由到正确界面（原先一律进 gameScreen：
    // 在布船 / 猜拳 / 已结束阶段重连会落到错误的界面）
    if (data.state === 'placing_ships') {
        if (typeof switchScreen === 'function') switchScreen(shipPlacementScreen);
        if (typeof initBoard === 'function') initBoard(playerBoard, true);
    } else if (data.state === 'rock_paper_scissors') {
        if (typeof switchScreen === 'function') switchScreen(rpsScreen);
        if (typeof rpsResult !== 'undefined' && rpsResult) rpsResult.textContent = '等待双方出拳…';
    } else if (data.state === 'game_over') {
        if (typeof switchScreen === 'function') switchScreen(gameOverScreen);
    } else {
        if (typeof switchScreen === 'function') switchScreen(gameScreen);
        if (typeof initGameBoards === 'function') initGameBoards();
    }

    // 服务端仍在等待我做的选择：重连后把对应面板重新弹出来
    if (data.pending_sacrifice && typeof showSacrificePrompt === 'function') {
        showSacrificePrompt({
            reason: data.pending_sacrifice.reason,
            message: data.pending_sacrifice.reason === 'kraken_eye'
                ? '克苏鲁之眼：请点选一艘自己的战舰暴露位置'
                : (data.pending_sacrifice.reason === 'divine_decree'
                    ? '神之宣告：请点选一艘自己的战舰使其阵亡'
                    : '恶魔契约：请点选一艘自己的战舰牺牲'),
            ships: data.pending_sacrifice_ships || [],
        });
    }
    if (data.pending_placement && typeof showPlacementPrompt === 'function') {
        showPlacementPrompt({
            kind: data.pending_placement.kind,
            remaining: data.pending_placement.remaining,
            total: data.pending_placement.total,
            placed: data.pending_placement.placed,
            blocked: data.pending_placement_blocked || [],
            allowed: data.pending_placement_allowed || [],
        });
    } else if (data.pending_placement && data.pending_placement.kind) {
        showMessage('有一艘待放置的战舰，请查看放置面板', { type: 'warning' });
    }
    if (data.magic_blocked) {
        showMessage('你本回合的魔法卡已被「看破！」封锁', { type: 'warning' });
    }
}

// 页面加载时初始化WebSocket连接，用于在线人数统计
document.addEventListener('DOMContentLoaded', function () {
    ensureSocket();
});

// 全局消息提示辅助函数
function showMessage(text, options = {}) {
    const duration = options.duration || 3500;
    const type = options.type || 'info'; // info, success, warning, error

    // 创建容器（如果还没创建）
    let container = document.getElementById('game-message-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'game-message-container';
        container.style.position = 'fixed';
        container.style.top = '20px';
        container.style.left = '50%';
        container.style.transform = 'translateX(-50%)';
        container.style.zIndex = 99999;
        container.style.pointerEvents = 'none';
        document.body.appendChild(container);
    }

    const msg = document.createElement('div');
    msg.className = `game-message ${type}`;
    msg.textContent = text;
    msg.style.pointerEvents = 'auto';
    container.appendChild(msg);

    // 动画入场
    requestAnimationFrame(() => {
        msg.style.opacity = '1';
        msg.style.transform = 'translateY(0)';
    });

    // 点击可立刻关闭
    msg.addEventListener('click', () => {
        msg.style.opacity = '0';
        msg.style.transform = 'translateY(-10px)';
        setTimeout(() => container.removeChild(msg), 300);
    });

    // 自动隐藏
    setTimeout(() => {
        msg.style.opacity = '0';
        msg.style.transform = 'translateY(-10px)';
        setTimeout(() => {
            if (msg.parentNode === container) container.removeChild(msg);
        }, 300);
    }, duration);
}

// 统一提示封装：用页内 toast 替代原生 alert，避免阻隔式系统对话框
function showAlert(text) {
    showMessage(String(text), { type: 'warning' });
}

// 添加加载完成验证
console.log("game.js 加载完成，playMagicCard 状态:", typeof window.playMagicCard);

// ============ 游戏日志窗口（2026-09-10 重写） ============
const GAME_LOG_MAX_ENTRIES = 200;   // 仅保留最近 N 条，防止长时间对局卡顿

// 日志空状态（开局还没有任何记录时占位，避免日志框整个是一片空白）
const GAME_LOG_EMPTY_HTML =
    '<div class="log-empty">暂无日志<br>攻击、使用魔法卡等操作会记录在这里</div>';

// 没有任何日志条目时才显示空状态
function ensureGameLogEmptyState() {
    if (!gameLogs) return;
    if (gameLogs.querySelector('.log-entry')) return;
    gameLogs.innerHTML = GAME_LOG_EMPTY_HTML;
}

// 清空日志（新开一局时调用）
function clearGameLogs() {
    if (gameLogs) gameLogs.innerHTML = GAME_LOG_EMPTY_HTML;
    ensureGameLogEmptyState();
}

// 追加一条日志（最新在最上面，超量自动裁剪）
// ==================== 结算：本局刚解锁的徽章（第 4 批追加） ====================
//
// 服务端在结算时做两件事：
//   ① 给**整个房间**一条 message：「XX 解锁了新徽章：五连胜」（对手也看得到）；
//   ② 给**本人**一条 `achievements_unlocked`（结构化：id/name/desc/group/requirement）。
// 这里只负责把 ② 渲染成结算界面上的一块「本局刚解锁 ⚓首胜」。
//
// 事件顺序：`_finalize_match` 在 `emit('game_over')` 之前跑，所以 ② 通常比 game_over 先到；
// 为了不依赖顺序，两条路都调 renderAchievementUnlockPanel()（一次缓冲、一次兜底刷新）。
//
// 图标不在这里写死：复用徽章墙那份 PROFILE_BADGE_GLYPH（按 group 取），
// 免得同一个徽章在徽章墙和结算提示里长得不一样。
// 分组 → 徽章上的小图标（纯装饰）。
// ⚠️ **模块级**（2026-09-17 从名片渲染函数里提上来的）：结算提示也要画徽章图标，
//    而两处各写一份映射必然漂移（"同一个徽章在徽章墙和结算提示里长得不一样"）。
//    第一版结算函数引用了函数内的同名 const → 运行时 `ReferenceError`，
//    表现是"结算面板不出现 + 控制台一条未捕获异常"（工具 Z1 抓到的就是它）。
//    分组中文名由服务端给（achievements.groups()），认不出来就用默认图标。
const PROFILE_BADGE_GLYPH = {
    '里程碑': '⚓', '连胜': '🔥', '击沉': '💥', '完美': '🛡️', '卡牌': '🎴', '榜单': '👑'
};

let pendingUnlockBadges = [];

// ==================== 等级 / 经验（2026-09-17 追加） ====================
//
// ⚠️ 前端**不算等级、不算"下一级要多少经验"** —— 那些都由服务端的 `leveling` 算，
//    随 `/api/profile` 的 `level_info` 与结算事件 `xp_gained` 的 `segments` 下发。
//    前端这里只做两件事：把数字画出来 + 按段播滚动动画。
//    （两份曲线实现必然漂移，第 2 批已经吃过一次"判据两份实现"的亏。）

/** 把等级视图画到一块 bar 上（首页条 / 名片条 / 结算条共用）。 */
function paintLevelBar(fillEl, textEl, levelEl, info) {
    const v = info || {};
    const ratio = Number(v.ratio);
    if (fillEl) fillEl.style.width = Math.round((isFinite(ratio) ? Math.min(1, Math.max(0, ratio)) : 0) * 100) + '%';
    if (textEl) {
        textEl.textContent = v.capped
            ? ('满级 ' + (v.max_level || 100))
            : (Number(v.into || 0) + ' / ' + Number(v.need || 0));
    }
    if (levelEl) levelEl.textContent = String(v.level || 1);
}

/** 首页的「Lv.N + 经验条」。登录后才显示；拿不到就整块隐藏。 */
function refreshMyLevelStrip(info) {
    const strip = document.getElementById('my-level-strip');
    if (!strip) return;
    const paint = (v) => {
        if (!v) { strip.classList.add('hidden'); return; }
        paintLevelBar(document.getElementById('mls-fill'), document.getElementById('mls-text'),
            document.getElementById('mls-level'), v);
        strip.classList.remove('hidden');
    };
    if (info) { paint(info); return; }
    if (!window.__USERNAME) { paint(null); return; }     // 游客没有等级
    fetch('/api/profile', { headers: { 'Accept': 'application/json' } })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => paint(d && d.profile && d.profile.level_info))
        .catch(() => paint(null));
}

// ---- 结算：本局经验的滚动动画 ----
let xpAnimToken = 0;          // 世代令牌：新的一局开始时把上一次动画作废
let lastXpView = null;        // 最近一次结算后的等级视图（用于顺手刷新首页条）

// ==================== 段位（2026-09-18 段位批） ====================
//
// ⚠️ 前端**不算段位**：`label` / `progress` / `to_next` / `tier_id` / `tier_index`
//    一律吃服务端下发的那份 `rank_info`（= `ranks.rank_view()` 的原样返回）。
//    与等级系统同一条规矩 —— 曲线只要有两份实现就一定会漂移；段位这里更进一步：
//    `label` 是**给玩家看的完整文案**（`水手长Ⅱ 90分` / `船长Ⅲ 2300分 #60` /
//    `大舰长 #20`），前端直接显示它，**绝不自己拼**（拼法一改就两边不一致）。
//
// ⚠️ 本段全部是**模块级**函数：结算面板的入口是模块级的 socket 处理器，
//    够不到 `bindEventListeners()` 里那些渲染函数。本项目为此踩过两次
//    「模块级代码引用函数作用域里的东西 → ReferenceError 被 .then() 吞掉、
//    页面上一点提示都没有」（`PROFILE_BADGE_GLYPH`、`profileTitleName`）。
//    所以这里只依赖 window 上的全局（`window.rankIconHtml`）与 DOM 本身。

let myRankInfo = null;            // 自己的段位视图（页面加载时取一次并缓存）
let myRankInfoPromise = null;     // 上面那次请求的 promise（复用，绝不重复拉）
let myRankInfoLoaded = false;     // 已经拉过（哪怕是失败）——防止回调里递归重试
let rankAnimToken = 0;            // 段位动画世代令牌：新一局作废上一局的滚动
let rankedQueuePending = false;   // 自己是否正在排位排队（收到 error 时要复位按钮）

// 只为"要不要显示船长段那行小字" / "这一行算不算顶端段位"的守卫用
// （段位下标 `tier_index` 由服务端下发，这里只是常数比较，不参与任何算分）
const RANK_CAPTAIN_TIER_INDEX = 7;

/** 段位图标。`window.rankIconHtml` 来自 static/rank_icons.js（在 game.js **之前**加载）。 */
function rankIconMarkup(tierId, size) {
    if (!tierId || typeof window.rankIconHtml !== 'function') return '';
    try { return String(window.rankIconHtml(String(tierId), size)); } catch (e) { return ''; }
}

/** 玩家看的段位文案 —— **服务端下发什么就显示什么**（`rank_view()['label']`）。 */
function rankLabelOf(info) {
    if (!info || typeof info !== 'object') return '';
    return String(info.label || '');
}

/** 「船长Ⅲ」这种段位名：两个字段都来自服务端（大舰长的 `sub` 是空串）。 */
function rankTierText(info) {
    if (!info || typeof info !== 'object') return '';
    return String(info.tier_name || '') + String(info.sub || '');
}

/**
 * 页面加载时取一次自己的段位（匹配等待界面要显示它 —— 那 5 秒里不许现拉）。
 * 游客 / 接口失败 → 保持 null，等待界面就只显示对手那部分（不显示假段位）。
 */
// ---- 帮助页的「段位与排位」块（段位帮助批）----
// ⚠️ 全部数字/文案**都从服务端拿**，这里一个字都不许硬编码：
//    · 段位名 / 起始分 / 小段位 / 计分表  → `GET /api/rank_constants`（= `ranks.constants()`）
//    · 每个段位解锁的称号 / 头像框 / 名片底色 → `GET /api/profile` 的 `catalog`，按
//      `requirement === '段位达到 <段位名>'` 归组（**不在这里抄一份解锁表**）
//    帮助页写「胜利 +20」而代码里改成 +25 之后，帮助就变成了谎话，而且没有任何报错 ——
//    这条铁律已经在 `ranks.py` / `leveling.py` 里各立过一次了。
//
// ⚠️ 下面这些常量与函数全是**模块级**：帮助入口可能在任何时候被点，
//    而 `bindEventListeners()` 里的东西模块级代码够不到（本项目为此踩过两次
//    `ReferenceError` 被 `.then()` 吞掉、页面上一点提示都没有）。
const HELP_RANK_IDS = {
    section: 'help-rank-section',
    tiers: 'help-rank-tiers',
    scoring: 'help-rank-scoring',
    win: 'help-rank-scoring-win',
    lose: 'help-rank-scoring-lose',
    error: 'help-rank-error'
};
const HELP_RANK_CATEGORY_LABELS = [
    ['titles', '称号'],
    ['frames', '头像框'],
    ['card_bgs', '名片底色']
];
let rankHelpConstants = null;      // /api/rank_constants 的结果（拉一次缓存）
let rankHelpConstantsPromise = null;
let rankHelpCatalogPromise = null; // 卡片目录补充拉取（未登录 / 没打开过名片时）

/** 取一个帮助页容器。页面里没有就返回 null（而不是抛）。 */
function helpRankEl(key) {
    const id = HELP_RANK_IDS[key];
    return id ? document.getElementById(id) : null;
}

/**
 * 解锁外观按「段位达到 X」归组。
 *
 * 判据只有一条：`requirement` 与 `段位达到 <段位名>` **逐字相等**（段位名来自服务端
 * 下发的 `tiers`）。这条文案的唯一来源是 `profile_spec._fill_rank_requirements`
 * （它按 `rank_tier` 现算），所以前端不重算、也不硬编码「哪一档解锁什么」。
 */
function rankUnlockIndexFromCatalog(catalog) {
    const out = {};
    if (!catalog || typeof catalog !== 'object') return out;
    for (const [key, label] of HELP_RANK_CATEGORY_LABELS) {
        const list = Array.isArray(catalog[key]) ? catalog[key] : [];
        for (const item of list) {
            if (!item || typeof item !== 'object') continue;
            const req = String(item.requirement || '').trim();
            if (req.indexOf('段位达到 ') !== 0) continue;
            const tierName = req.slice('段位达到 '.length).trim();
            if (!tierName) continue;
            if (!out[tierName]) out[tierName] = [];
            out[tierName].push({
                label: label,
                // 未解锁的加个标记：帮助页是"图鉴"，要一眼看出哪一档给什么
                name: String(item.name || ''),
                unlocked: item.unlocked !== false
            });
        }
    }
    return out;
}

/** 一个段位行的"解锁外观"那一栏（池子里没有 → 空串，由调用方兜"暂无"）。 */
function rankUnlockText(unlocks) {
    if (!Array.isArray(unlocks) || unlocks.length === 0) return '';
    return unlocks.map(u => u.label + ' ' + u.name).join('、');
}

/** 数值带符号（`+20` / `−15`；0 显示 `0`）。U+2212 是真正的减号，与设计稿一致。 */
function rankSignedValue(value) {
    const n = Number(value);
    if (!isFinite(n) || n === 0) return '0';
    return (n > 0 ? '+' : '−') + Math.abs(n);
}

/**
 * 计分项的分值显示。
 *
 * ⚠️ `value` **两种形态都要吃**（服务端现状如此，别按一种写死）：
 *   · 数字（`20` / `-15`）→ 这里补符号，显示成 `+20` / `−15`；
 *   · 字符串（`+2 × N（封顶 +10）` / `+8 / +12` / `负值补平`）→ **已经是给人看的文案**，
 *     原样显示，绝不二次加工（拼符号会把 `+8 / +12` 变成 `++8 / +12`）。
 */
function rankScoringValueText(value) {
    if (typeof value === 'number' && isFinite(value)) return rankSignedValue(value);
    if (value === null || value === undefined) return '';
    const text = String(value).trim();
    if (text === '') return '';
    // 纯数字串也走补符号那条（服务端若把 20 发成 "20" 也不会漏掉符号）
    if (/^[+-]?\d+(\.\d+)?$/.test(text)) return rankSignedValue(Number(text));
    return text;
}

/** 一个计分因子行（`标签 | 分值 | 条件`）。condition 缺省时不显示第三格。 */
function rankScoringRowHtml(row) {
    const item = (row && typeof row === 'object') ? row : {};
    const condition = String(item.condition || '');
    const text = rankScoringValueText(item.value);
    const isMinus = (typeof item.value === 'number' && item.value < 0)
        || (!text || text.charAt(0) === '−' || text.charAt(0) === '-');
    return '<div class="help-rank-score-row">' +
        '<span class="help-rank-score-label">' + String(item.label || item.key || '') + '</span>' +
        '<span class="help-rank-score-value' + (isMinus ? ' is-minus' : '') + '">' + text + '</span>' +
        (condition ? '<span class="help-rank-score-cond">' + condition + '</span>' : '') +
        '</div>';
}

/** 一张计分小表；没有行就给一句「暂不可用」（**绝不编数字顶上**）。 */
function rankScoringTableHtml(rows, emptyText) {
    const list = Array.isArray(rows) ? rows.filter(r => r && typeof r === 'object') : [];
    if (list.length === 0) return '<p class="muted-hint">' + emptyText + '</p>';
    return list.map(rankScoringRowHtml).join('');
}

/**
 * 段位图鉴那一栏：每行 = 图标 + 段位名 + 起始分 + 该段位解锁的外观。
 *
 * ⚠️ 名字与 id 全部来自服务端的 `tiers`（`tier_id` / `tier_name`）——
 *    前端**不建 id → 中文名的映射**（那又是一份会漂移的实现）。
 * ⚠️ 前 8 个段位才有「起始 N 分」；大舰长是晋升制，写的是晋升条件。
 */
function renderRankHelpTiers(constants, catalog) {
    const box = helpRankEl('tiers');
    if (!box) return;
    const tiers = Array.isArray(constants && constants.tiers) ? constants.tiers : [];
    const starts = (constants && constants.start_points_of_tier) || {};
    const subs = Array.isArray(constants && constants.subs) ? constants.subs : [];
    const perTier = (Number(constants && constants.sub_points) || 0) * subs.length;
    const unlocks = rankUnlockIndexFromCatalog(catalog);
    const limit = Number(constants && constants.admiral_rank_limit);
    const minCaptains = Number(constants && constants.admiral_min_captains);

    if (tiers.length === 0) {
        // 帮不到就**保留上一帧**：只有第一次打开才没有上一帧，那时给一句提示
        if (!box.querySelector('.help-rank-tier')) {
            box.innerHTML = '<p class="muted-hint">段位资料暂不可用</p>';
        }
        return;
    }

    const html = tiers.map((tier, i) => {
        const t = (tier && typeof tier === 'object') ? tier : {};
        const tid = String(t.id || '');
        const name = String(t.name || '');
        const last = (i === tiers.length - 1);
        const start = Number(starts[tid]);
        // 只有「靠分数晋级」的段位有起始分；大舰长没有（`start_points_of_tier` 里也没有它）
        const startHtml = isFinite(start)
            ? '<span class="help-rank-start">' + start + ' 分</span>' +
              (subs.length && perTier
                  ? '<span class="help-rank-subs">小段位 ' + subs.join(' / ') + ' · 每段 ' + perTier + ' 分</span>'
                  : '')
            : '';
        const text = rankUnlockText(unlocks[name]);
        const note = last
            ? ('晋升条件：先达到「' + (tiers[tiers.length - 2] ? String(tiers[tiers.length - 2].name || '') : '') + '」，' +
               '且在该段位内排名前 ' + (isFinite(limit) ? limit : '?') + '、' +
               '该段位人数不少于 ' + (isFinite(minCaptains) ? minCaptains : '?') + ' 人')
            : '';
        return '<div class="help-rank-tier' + (last ? ' is-top' : '') + '" data-tier="' + tid + '">' +
            '<span class="help-rank-icon">' + rankIconMarkup(tid, 26) + '</span>' +
            '<span class="help-rank-name">' + name + '</span>' +
            '<span class="help-rank-meta">' + startHtml + '</span>' +
            '<span class="help-rank-unlock">' + (text ? ('解锁：' + text) : '暂无额外解锁项') + '</span>' +
            (note ? '<span class="help-rank-note">' + note + '</span>' : '') +
            '</div>';
    }).join('');

    box.innerHTML = html;
}

/** 计分规则那两张小表（胜局 / 败局）。结构不对时**保留上一帧** + 报错提示。 */
function renderRankHelpScoring(constants) {
    const scoring = constants && constants.scoring;
    const winBox = helpRankEl('win');
    const loseBox = helpRankEl('lose');
    const errBox = helpRankEl('error');
    const scoringBox = helpRankEl('scoring');
    const placeholder = document.getElementById('help-rank-scoring-placeholder');
    const usable = (rows) => Array.isArray(rows) && rows.some(r => r && typeof r === 'object');
    const winOk = !!(scoring && typeof scoring === 'object' && usable(scoring.win));
    const loseOk = !!(scoring && typeof scoring === 'object' && usable(scoring.lose));

    if (!winOk && !loseOk) {
        // ⚠️ 「先清空再填充」的渲染：**先校验数据**，失败时保留上一帧
        //    （`updateHandUI` 那条教训：清空了却没填回来 = 页面留白且没有任何提示）。
        //    这里**不编一份数字顶上**：宁可显示"暂不可用"，也不显示一份可能与代码不符的计分表。
        if (scoringBox) scoringBox.classList.add('is-empty');
        if (errBox) {
            errBox.textContent = '计分规则暂不可用（没能从服务端取到 scoring 规则快照）——'
                + '这里的数字一律以服务端为准，不显示推算值。';
            errBox.hidden = false;
        }
        if (placeholder && !winBox.querySelector('.help-rank-score-row')
            && !loseBox.querySelector('.help-rank-score-row')) {
            placeholder.hidden = true;          // 别再挂着"加载中…"误导玩家
        }
        return;
    }

    // 两张表**各自校验**：一半坏了不该把另一半好的一起丢掉（"先校验再渲染"的粒度要够细）
    if (scoringBox) scoringBox.classList.remove('is-empty');
    if (errBox) { errBox.hidden = true; errBox.textContent = ''; }
    if (placeholder) placeholder.hidden = true;
    if (winOk && winBox) {
        winBox.innerHTML = '<div class="help-rank-score-head"><span>加分项</span><span>分值</span>'
            + '<span>条件</span></div>' + rankScoringTableHtml(scoring.win, '暂无胜局计分项');
    } else if (winBox) {
        winBox.innerHTML = '<p class="muted-hint">胜局计分项暂不可用</p>';
    }
    if (loseOk && loseBox) {
        loseBox.innerHTML = '<div class="help-rank-score-head"><span>扣分项</span><span>分值</span>'
            + '<span>条件</span></div>' + rankScoringTableHtml(scoring.lose, '暂无败局计分项');
    } else if (loseBox) {
        loseBox.innerHTML = '<p class="muted-hint">败局计分项暂不可用</p>';
    }
    // 封底 / 闪电战阈值这类"表外的数"也**照服务端下发的值**补一句（缺就不写）
    const caps = [];
    if (isFinite(Number(scoring.loss_floor))) {
        caps.push('败局单局扣分不低于 ' + rankSignedValue(scoring.loss_floor) + ' 分');
    }
    if (isFinite(Number(scoring.blitz_seconds)) && isFinite(Number(scoring.blitz_rounds))) {
        caps.push('「闪电战」判定：' + scoring.blitz_seconds + ' 秒内或 '
            + scoring.blitz_rounds + ' 个大回合内结束');
    }
    if (isFinite(Number(constants.min_points))) {
        caps.push('总分最低 ' + constants.min_points + ' 分（0 分封底）');
    }
    if (scoringBox && caps.length) {
        const old = scoringBox.querySelector('.help-rank-score-caps');
        if (old) old.remove();          // 重绘前先清掉上一帧那句，避免越积越多
        const p = document.createElement('p');
        p.className = 'muted-hint help-rank-score-caps';
        p.textContent = caps.join('；') + '。';
        scoringBox.appendChild(p);
    }
}

/** 段位块的一句话提示：拉不到就说清楚，别留白。 */
function setRankHelpError(text) {
    const errBox = helpRankEl('error');
    if (errBox) {
        errBox.textContent = text;
        errBox.hidden = false;
    }
    // 计分表那一格的**占位文案**也换成"暂不可用"。
    // ⚠️ 这里只动"还没有真表"的那一格（有 `.help-rank-score-row` 就说明上一帧还在，一个字都不碰）：
    //    否则首次打开时那句「计分规则加载中…」会一直挂着 —— 看着像还在加载，其实早就失败了。
    const placeholder = document.getElementById('help-rank-scoring-placeholder');
    const winBox = helpRankEl('win');
    const loseBox = helpRankEl('lose');
    if (winBox && loseBox && !winBox.querySelector('.help-rank-score-row')
        && !loseBox.querySelector('.help-rank-score-row')) {
        winBox.innerHTML = '<p class="muted-hint">计分规则暂不可用</p>';
        loseBox.innerHTML = '';
        if (placeholder) placeholder.hidden = true;
    }
}

/** 拉 `/api/rank_constants`（缓存一次；失败**不缓存**，下次点帮助还能再试）。 */
function loadRankHelpConstants() {
    if (rankHelpConstants) return Promise.resolve(rankHelpConstants);
    if (rankHelpConstantsPromise) return rankHelpConstantsPromise;
    rankHelpConstantsPromise = fetch('/api/rank_constants', { headers: { 'Accept': 'application/json' } })
        .then(r => (r && r.ok) ? r.json() : null)
        .then(d => {
            if (d && typeof d === 'object') rankHelpConstants = d;
            return rankHelpConstants;
        })
        .catch(() => null)
        .then(v => { rankHelpConstantsPromise = null; return v; });
    return rankHelpConstantsPromise;
}

/**
 * 名片目录（`catalog`）：先吃已经缓存的那份，没有就补拉一次 `/api/profile`。
 * 未登录 / 拉不到 → 返回 null，此时图鉴照画（只是不显示解锁外观）。
 */
function ensureRankHelpCatalog() {
    if (profileCatalog) return Promise.resolve(profileCatalog);
    if (!rankHelpCatalogPromise) {
        rankHelpCatalogPromise = fetch('/api/profile', { headers: { 'Accept': 'application/json' } })
            .then(r => (r && r.ok) ? r.json() : null)
            .then(res => {
                takeSelfProfile(res && res.profile);
                return profileCatalog;
            })
            .catch(() => null)
            .then(v => { rankHelpCatalogPromise = null; return v; });
    }
    return rankHelpCatalogPromise;
}

/**
 * 帮助页的「段位与排位」块。**打开帮助时调它**（入口仍是原来的 `#help-btn`，不新增按钮）。
 *
 * 顺序：先把**已有的**数据画出来（第二次打开就是瞬时的），再去补那些没拿到的；
 * 拿不到就显示 `#help-rank-error` 并**保留上一帧**，绝不清空容器留白。
 */
function renderRankHelp() {
    const section = helpRankEl('section');
    if (!section) return;
    section.hidden = false;

    if (rankHelpConstants) {
        renderRankHelpTiers(rankHelpConstants, profileCatalog);
        renderRankHelpScoring(rankHelpConstants);
    }
    // 目录可能比规则后到（没打开过名片时），所以两次渲染都要能独立触发
    ensureRankHelpCatalog().then(cat => {
        if (cat && rankHelpConstants) renderRankHelpTiers(rankHelpConstants, cat);
    }).catch(() => { /* 目录拿不到：图鉴不显示解锁项，不算错误 */ });

    loadRankHelpConstants().then(data => {
        if (!data) {
            setRankHelpError('段位规则加载失败：没能从服务端取到段位表与计分规则 ——'
                + '下面显示的是上一次成功加载的内容。');
            return;
        }
        renderRankHelpTiers(data, profileCatalog);
        renderRankHelpScoring(data);
    }).catch(() => {
        setRankHelpError('段位规则加载失败：没能从服务端取到段位表与计分规则 ——'
            + '下面显示的是上一次成功加载的内容。');
    });
}

function loadMyRankInfo() {
    if (myRankInfoPromise) return myRankInfoPromise;
    if (!window.__USERNAME) {
        myRankInfoLoaded = true;
        myRankInfoPromise = Promise.resolve(null);
        return myRankInfoPromise;
    }
    myRankInfoPromise = fetch('/api/profile', { headers: { 'Accept': 'application/json' } })
        .then(r => (r.ok ? r.json() : null))
        .then(d => {
            const info = d && d.profile && d.profile.rank_info;
            if (info && typeof info === 'object') myRankInfo = info;
            return myRankInfo;
        })
        .catch(() => null)
        .then(v => { myRankInfoLoaded = true; return v; });
    return myRankInfoPromise;
}

/**
 * 结算面板 `#rank-gain-panel`：段位积分的滚动动画。
 *
 * 做法与经验条（`showXpPanel`）**同一套**：数字滚动 + 进度条增长；
 * 涨到本小级满分就「走满 → 清空重来 → 继续涨」（升小段位），掉分则反向。
 * 事件 `rank_changed` 是**逐人单发**的，休闲局永远收不到 —— 所以这块面板
 * 在休闲对局里永远不会出现（不需要前端判 mode）。
 */
function showRankGainPanel(payload) {
    const panel = document.getElementById('rank-gain-panel');
    if (!panel || !payload) return;
    const before = (payload.before && typeof payload.before === 'object') ? payload.before : {};
    const after = (payload.after && typeof payload.after === 'object') ? payload.after : {};
    const delta = Number(payload.delta || 0);
    const sub = Number(after.sub_points || before.sub_points) || 100;

    // ---------- 静态文案（动画只动条子与数字） ----------
    // ⚠️ `delta` 是**实际**变化量（契约），所以 0 分封底时它会是 **0** 而不是 -15。
    //    直接渲染 delta 会让败者看到「±0」，看着像 bug —— 四种情况分开写，
    //    **全部能从现有字段判出来**（不需要新字段）：
    //      delta > 0            → 「+20 分」
    //      delta < 0            → 「-15 分」
    //      clamped && delta == 0 → 「已到 0 分下限，本局未扣分」（不写 ±0，也不播掉分动画）
    //      clamped && delta < 0  → 显示实际扣的分数 + 一句「已触及 0 分下限」
    const deltaEl = document.getElementById('rank-delta');
    const deltaPrefixEl = document.getElementById('rank-delta-prefix');
    const clampNoteEl = document.getElementById('rank-clamp-note');
    const clamped = payload.clamped === true;
    const noChange = (delta === 0);
    if (deltaEl) {
        if (clamped && noChange) deltaEl.textContent = '已到 0 分下限，本局未扣分';
        else deltaEl.textContent = (delta > 0 ? '+' : '') + String(delta) + ' 分';
    }
    if (deltaPrefixEl) deltaPrefixEl.textContent = (clamped && noChange) ? '' : '本局段位分 ';
    if (clampNoteEl) {
        const showClampNote = clamped && !noChange;
        clampNoteEl.textContent = showClampNote ? '已触及 0 分下限（实际扣 ' + Math.abs(delta) + ' 分）' : '';
        clampNoteEl.classList.toggle('hidden', !showClampNote);
    }
    const roleEl = document.getElementById('rank-role');
    if (roleEl) roleEl.textContent = (payload.role === 'loser') ? '排位失利' : '排位获胜';
    const beforeIcon = document.getElementById('rank-icon-before');
    if (beforeIcon) beforeIcon.innerHTML = rankIconMarkup(before.tier_id, 30);
    const afterIcon = document.getElementById('rank-icon-after');
    if (afterIcon) afterIcon.innerHTML = rankIconMarkup(after.tier_id, 30);
    const beforeLabelEl = document.getElementById('rank-label-before');
    if (beforeLabelEl) beforeLabelEl.textContent = rankLabelOf(before) || '—';
    const afterLabelEl = document.getElementById('rank-label-after');
    if (afterLabelEl) afterLabelEl.textContent = rankLabelOf(after) || '—';
    const pointsEl = document.getElementById('rank-points-text');
    if (pointsEl) pointsEl.textContent = '累计排位分 ' + String(Number(after.points || 0));

    // ---------- 升段 / 掉段那一行 ----------
    // ⚠️ 判据只用服务端给的 `tier_up` / `promoted` / `demoted` / `admiral_*`，
    //    **不许**自己比较 `label` 字符串（文案一改判据就废）。
    const promoteEl = document.getElementById('rank-promote');
    let promoteText = '';
    if (payload.admiral_promoted) {
        promoteText = '晋升大舰长！' + rankLabelOf(after);
    } else if (payload.admiral_demoted) {
        promoteText = '掉出大舰长段位：' + rankLabelOf(after);
    } else if (payload.tier_up) {
        promoteText = '升段！' + rankTierText(before) + ' → ' + rankTierText(after);
    } else if (payload.tier_down) {
        promoteText = '掉段：' + rankTierText(before) + ' → ' + rankTierText(after);
    } else if (payload.promoted) {
        promoteText = '升段！' + rankTierText(before) + ' → ' + rankTierText(after);
    } else if (payload.demoted) {
        promoteText = '掉级：' + rankTierText(before) + ' → ' + rankTierText(after);
    }
    if (promoteEl) {
        promoteEl.textContent = promoteText;
        promoteEl.classList.toggle('hidden', !promoteText);
        promoteEl.classList.remove('flash');
    }

    // ---------- 大舰长那行小字 ----------
    // ⚠️ 只在**船长段位**显示：低段位时服务端给的 `admiral_reason` 是
    //    「需要先达到船长段位」，对玩家没有信息量，不该占位置。
    const noteEl = document.getElementById('rank-admiral-note');
    if (noteEl) {
        const reason = String(payload.admiral_reason || '');
        const inCaptainTier = Number(after.tier_index) === RANK_CAPTAIN_TIER_INDEX
            || Number(before.tier_index) === RANK_CAPTAIN_TIER_INDEX;
        const showNote = !payload.admiral_promoted && !!reason && inCaptainTier
            && reason.indexOf('需要先达到船长段位') < 0;
        noteEl.textContent = showNote ? reason : '';
        noteEl.classList.toggle('hidden', !showNote);
    }

    panel.classList.toggle('is-admiral', !!payload.admiral_promoted);
    panel.classList.toggle('is-top-tier',
        Number(after.tier_index) >= RANK_CAPTAIN_TIER_INDEX || !!payload.admiral_promoted);
    // 封底且一分没扣：不算"掉分"，不套掉分配色（也就不会让进度条演成掉分）
    panel.classList.toggle('is-loss', delta < 0);
    panel.classList.remove('hidden');

    // ---------- 进度条 ----------
    const fill = document.getElementById('rank-bar-fill');
    const bar = document.getElementById('rank-bar');
    const text = document.getElementById('rank-progress-text');
    const from = Math.max(0, Math.min(1, (Number(before.progress) || 0) / sub));
    const to = Math.max(0, Math.min(1, (Number(after.progress) || 0) / sub));
    // `to_next === null` = 后面没有小级了（船长Ⅲ / 大舰长）：进度条不代表"离下一级多远"，
    // 只表示"已经攒到这里"，所以画满并收起「N / 100」的文案，改显示累计分。
    const saturated = (after.to_next === null || after.to_next === undefined);
    if (bar) bar.classList.toggle('capped', saturated || !!payload.admiral_promoted);
    if (text) text.classList.toggle('hidden', saturated);

    const token = ++rankAnimToken;
    const SEG_MS = 650;      // 一段滚动时长
    const RESET_MS = 380;    // 走满后"清空重来"的停顿

    function paint(p) {
        if (!text || text.classList.contains('hidden')) return;
        text.textContent = Math.round(p * sub) + ' / ' + sub;
    }
    function setWidth(r) {
        if (fill) fill.style.width = Math.round(Math.max(0, Math.min(1, r)) * 100) + '%';
    }

    // 分段：跨小段位的那一次要"走满 → 清空 → 继续加"（掉分反向）。
    // 起点/终点都是服务端给的 progress，前端只是把它们插值成动画。
    const segs = [];
    if (delta === 0) {
        segs.push({ a: from, b: to });
    } else if (payload.admiral_promoted) {
        segs.push({ a: from, b: 1 });
    } else if (delta > 0 && payload.promoted) {
        segs.push({ a: from, b: 1, resetAfter: true });
        segs.push({ a: 0, b: to });
    } else if (delta < 0 && payload.demoted) {
        segs.push({ a: from, b: 0, resetAfter: true });
        segs.push({ a: 1, b: to });
    } else {
        segs.push({ a: from, b: (isFinite(to) ? to : from) });
    }

    setWidth(segs[0].a);
    paint(segs[0].a);

    let segIndex = 0;
    function playNext() {
        if (token !== rankAnimToken) return;      // 被新一局作废
        const seg = segs[segIndex];
        if (!seg) { paint(to); return; }
        segIndex++;
        const t0 = performance.now();
        function tick(now) {
            if (token !== rankAnimToken) return;
            const p = Math.min(1, (now - t0) / SEG_MS);
            const r = seg.a + (seg.b - seg.a) * p;
            setWidth(r);
            paint(r);
            if (p < 1) { requestAnimationFrame(tick); return; }
            if (seg.resetAfter) {
                // 正好在此刻跨过了小段位：闪一下那行提示、把条子清空/填满，再继续
                if (promoteEl && !promoteEl.classList.contains('hidden')) {
                    promoteEl.classList.add('flash');
                    setTimeout(() => promoteEl.classList.remove('flash'), RESET_MS + 220);
                }
                setTimeout(() => {
                    if (token !== rankAnimToken) return;
                    setWidth(delta > 0 ? 0 : 1);
                    playNext();
                }, RESET_MS);
                return;
            }
            playNext();
        }
        requestAnimationFrame(tick);
    }
    playNext();
}

/** 新一局开始时收起段位面板并作废上一局的动画（与 xpAnimToken 同一条规矩）。 */
function hideRankGainPanel() {
    rankAnimToken++;
    const panel = document.getElementById('rank-gain-panel');
    if (panel) panel.classList.add('hidden');
}

function renderXpBreakdown(rows) {
    const box = document.getElementById('xp-breakdown');
    if (!box) return;
    const list = Array.isArray(rows) ? rows : [];
    box.textContent = list.length ? ('（' + list.map(r => r.label + ' +' + r.xp).join('，') + '）') : '';
}

function showXpPanel(payload) {
    const panel = document.getElementById('xp-gain-panel');
    if (!panel || !payload) return;
    const delta = Number(payload.delta || 0);
    const before = payload.before || {};
    const after = payload.after || {};
    const segs = Array.isArray(payload.segments) ? payload.segments.slice() : [];
    renderXpBreakdown(payload.breakdown);

    const deltaEl = document.getElementById('xp-delta');
    if (deltaEl) deltaEl.textContent = '+' + delta;
    const lvNow = document.getElementById('xp-level-now');
    if (lvNow) lvNow.textContent = String(before.level || 1);
    const fill = document.getElementById('xp-bar-fill');
    const text = document.getElementById('xp-progress-text');
    const up = document.getElementById('xp-levelup');
    if (up) up.classList.add('hidden');
    panel.classList.remove('hidden');

    // 起点：本级进度
    const seg0 = segs[0] || { ratio_from: before.ratio || 0, from: before.into || 0, need: before.need || 0 };
    if (fill) fill.style.width = Math.round((Number(seg0.ratio_from) || 0) * 100) + '%';
    if (text) text.textContent = Number(seg0.from || 0) + ' / ' + Number(seg0.need || 0);

    if (!segs.length || delta <= 0) {
        lastXpView = after;
        return;
    }

    const token = ++xpAnimToken;
    let segIndex = 0;
    const SEG_MS = 700;                 // 一段（一级内）滚动时长
    const RESET_MS = 420;               // 升级后"条子清空重来"的停顿

    function playSegment() {
        if (token !== xpAnimToken) return;           // 被新一局作废
        const seg = segs[segIndex];
        if (!seg) {
            if (text) text.textContent = after.capped
                ? ('满级 ' + (after.max_level || 100))
                : (Number(after.into || 0) + ' / ' + Number(after.need || 0));
            if (lvNow) lvNow.textContent = String(after.level || 1);
            lastXpView = after;
            return;
        }
        const from = Number(seg.ratio_from) || 0;
        const to = Number(seg.ratio_to) || 0;
        const need = Number(seg.need || 0);
        const xpFrom = Number(seg.from || 0);
        const xpTo = Number(seg.to || 0);
        const t0 = performance.now();
        function tick(now) {
            if (token !== xpAnimToken) return;
            const p = Math.min(1, (now - t0) / SEG_MS);
            const ratio = from + (to - from) * p;
            if (fill) fill.style.width = Math.round(ratio * 100) + '%';
            if (text) text.textContent = Math.round(xpFrom + (xpTo - xpFrom) * p) + ' / ' + need;
            if (p < 1) { requestAnimationFrame(tick); return; }
            // 这一段填完了
            if (seg.level_up) {
                // 升级：先把"升级了"闪一下，再把条子清空，然后继续加
                const fromLv = Number(seg.level || 1);
                const toLv = fromLv + 1;
                if (up) {
                    const f = document.getElementById('xp-from');
                    const t = document.getElementById('xp-to');
                    if (f) f.textContent = String(fromLv);
                    if (t) t.textContent = String(toLv);
                    up.classList.remove('hidden');
                    up.classList.add('flash');
                    setTimeout(() => up.classList.remove('flash'), RESET_MS + 200);
                }
                if (lvNow) lvNow.textContent = String(toLv);
                setTimeout(() => {
                    if (token !== xpAnimToken) return;
                    if (up) up.classList.add('hidden');
                    if (fill) fill.style.width = '0%';
                    if (text) text.textContent = '0 / ' + need;
                    segIndex++;
                    playSegment();
                }, RESET_MS);
            } else {
                segIndex++;
                playSegment();
            }
        }
        requestAnimationFrame(tick);
    }
    playSegment();
}

function renderAchievementUnlockPanel() {
    const panel = document.getElementById('achievement-unlock-panel');
    if (!panel) return;
    const items = pendingUnlockBadges.filter(b => b && b.id);
    if (!items.length) {
        panel.classList.add('hidden');
        panel.innerHTML = '';
        return;
    }
    const cards = items.map(b => {
        const glyph = PROFILE_BADGE_GLYPH[b.group] || '🏅';
        return '<li class="au-item">'
            + '<em class="au-glyph">' + escapeHtml(glyph) + '</em>'
            + '<span class="au-text"><strong class="au-name">' + escapeHtml(b.name || b.id) + '</strong>'
            + (b.desc ? '<span class="au-desc">' + escapeHtml(b.desc) + '</span>' : '')
            + '</span></li>';
    }).join('');
    panel.innerHTML = '<h3 class="au-title">本局刚解锁 <span class="au-count">' + items.length + '</span> 枚徽章</h3>'
        + '<ul class="au-list">' + cards + '</ul>';
    panel.classList.remove('hidden');
}

function addGameLog(logText, logType) {
    if (!gameLogs) return;
    const emptyHint = gameLogs.querySelector('.log-empty');
    if (emptyHint) emptyHint.remove();
    const logEntry = document.createElement('div');
    logEntry.className = 'log-entry' + (logType ? ' log-' + logType : '');
    logEntry.innerHTML = logText;
    gameLogs.insertBefore(logEntry, gameLogs.firstChild);
    while (gameLogs.childElementCount > GAME_LOG_MAX_ENTRIES) {
        gameLogs.removeChild(gameLogs.lastChild);
    }
    // 新条目在顶部，滚回顶部让玩家看到最新一条
    gameLogs.scrollTop = 0;
}

// 折叠 / 展开日志窗
function toggleGameLog() {
    const el = document.querySelector('.log-container');
    if (!el) return;
    const collapsed = el.classList.toggle('collapsed');
    const btn = document.getElementById('toggle-log');
    if (btn) {
        btn.textContent = collapsed ? '▲' : '▼';
        btn.setAttribute('aria-label', collapsed ? '展开日志' : '折叠日志');
        btn.setAttribute('title', collapsed ? '展开日志' : '折叠日志');
    }
}

// 把服务端日志条目渲染成统一格式
function renderServerLog(entry) {
    if (!entry || !entry.text) return;
    const time = entry.ts ? new Date(entry.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : '';
    // quick_chat：第 4 批快捷语走的是服务端 game_log 通道（那才是写进 room.game_logs /
    // 对局历史的同一份来源），缺这条映射就会被渲染成通用的「信息」徽标。
    const typeLabel = { attack: '攻击', magic: '魔法', result: '结果', info: '信息', quick_chat: '快捷语' }[entry.type] || '信息';
    addGameLog(
        `<span class="log-time">${escapeHtml(time)}</span>` +
        `<span class="log-badge log-badge-${escapeHtml(entry.type || 'info')}">${typeLabel}</span>` +
        renderLogTextHtml(entry),
        entry.type
    );
}

// ============ 局内快捷语（第 4 批） ============
// 三条硬规矩（冻结契约，别改）：
//   ① 文案一个字都不写在本文件里 —— 全部来自 GET /api/quick_chat 的
//      {groups, items:[{id, group, text}]}。前后端各写一份必然漂移，本项目已吃过多次。
//      这里只允许出现按钮自身的中文标签（如「快捷语」）与加载失败时的提示。
//   ② 面板是非模态浮层，绝不用 .modal-overlay：那是全屏遮罩，会挡住棋盘、格子点不动。
//   ③ 收到快捷语只做两件事：写进对局日志（复用 addGameLog）+ 轻提示。
//      不碰棋盘 / 手牌 / 阶段 / 连锁 —— 收到之后对局界面其他部分必须一模一样。
const QUICK_CHAT_API = '/api/quick_chat';
const QUICK_CHAT_TOAST_MS = 4000;   // 轻提示停留时长
let quickChatPanelData = null;      // 第一次成功拉到后缓存（文案是静态表，不必每开一次拉一次）
let quickChatPanelLoading = null;   // 进行中的请求；失败会置回 null 以便下次重试
let quickChatToastTimer = null;

function getQuickChatEls() {
    return {
        btn: document.getElementById('quick-chat-btn'),
        panel: document.getElementById('quick-chat-panel'),
        toast: document.getElementById('quick-chat-toast'),
    };
}

// 拉取快捷语表。失败（404 / 网络断 / 结构不对）一律返回 null，由调用方显示提示文案，
// 绝不上抛 —— 接口暂时没就绪时不允许把对局界面打崩。
function fetchQuickChatData() {
    if (quickChatPanelData) return Promise.resolve(quickChatPanelData);
    if (quickChatPanelLoading) return quickChatPanelLoading;
    quickChatPanelLoading = fetch(QUICK_CHAT_API, { headers: { 'Accept': 'application/json' } })
        .then((resp) => {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then((data) => {
            if (!data || data.success !== true || !Array.isArray(data.items)) {
                throw new Error('bad payload');
            }
            // group 名按【接口给的顺序】首次出现顺序去重；没有 group 的归到末尾
            const groups = [];
            const buckets = {};
            data.items.forEach((item) => {
                if (!item || typeof item.id !== 'string' || typeof item.text !== 'string') return;
                const g = (typeof item.group === 'string' && item.group) ? item.group : '';
                if (!buckets[g]) { buckets[g] = []; groups.push(g); }
                buckets[g].push({ id: item.id, text: item.text });
            });
            quickChatPanelData = { groups: groups, buckets: buckets };
            return quickChatPanelData;
        })
        .catch(() => {
            quickChatPanelLoading = null;   // 允许下次重试
            return null;
        });
    return quickChatPanelLoading;
}

function setQuickChatPanelOpen(open) {
    const { btn, panel } = getQuickChatEls();
    if (panel) {
        panel.hidden = !open;
        panel.setAttribute('aria-hidden', open ? 'false' : 'true');
    }
    if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function isQuickChatPanelOpen() {
    const { panel } = getQuickChatEls();
    return !!(panel && !panel.hidden);
}

// 按 group 渲染。每条都是 button.quick-chat-item[data-msg-id]（DOM 契约）。
function renderQuickChatPanel(data) {
    const { panel } = getQuickChatEls();
    if (!panel) return;
    panel.textContent = '';
    if (!data || !data.groups.length) {
        const hint = document.createElement('div');
        hint.className = 'quick-chat-hint';
        hint.textContent = '快捷语暂时加载不出来';
        panel.appendChild(hint);
        return;
    }
    data.groups.forEach((groupName) => {
        const items = data.buckets[groupName] || [];
        if (!items.length) return;
        const groupEl = document.createElement('div');
        groupEl.className = 'quick-chat-group';
        if (groupName) {
            const title = document.createElement('div');
            title.className = 'quick-chat-group-title';
            title.textContent = groupName;
            groupEl.appendChild(title);
        }
        const list = document.createElement('div');
        list.className = 'quick-chat-group-list';
        items.forEach((item) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'quick-chat-item';
            btn.dataset.msgId = item.id;
            btn.textContent = item.text;
            list.appendChild(btn);
        });
        groupEl.appendChild(list);
        panel.appendChild(groupEl);
    });
}

function showQuickChatPanel() {
    const { panel } = getQuickChatEls();
    if (!panel) return;
    // 先把"加载中"填进去再打开：否则异步取数期间面板是空白的，看着像坏了
    if (!quickChatPanelData) {
        panel.textContent = '';
        const hint = document.createElement('div');
        hint.className = 'quick-chat-hint';
        hint.textContent = '加载中…';
        panel.appendChild(hint);
    }
    setQuickChatPanelOpen(true);
    fetchQuickChatData().then((data) => {
        if (!isQuickChatPanelOpen()) return;   // 已经收起来了就别再动 DOM
        renderQuickChatPanel(data);
    });
}

function toggleQuickChatPanel() {
    if (isQuickChatPanelOpen()) setQuickChatPanelOpen(false);
    else showQuickChatPanel();
}

// 轻提示：形如「名字：文案」，几秒后自动消失。只动 #quick-chat-toast 自己。
function showQuickChatToast(name, text) {
    const { toast } = getQuickChatEls();
    if (!toast) return;
    toast.textContent = (name ? name + '：' : '') + text;
    toast.classList.add('is-show');
    if (quickChatToastTimer) clearTimeout(quickChatToastTimer);
    quickChatToastTimer = setTimeout(() => {
        toast.classList.remove('is-show');
        quickChatToastTimer = null;
    }, QUICK_CHAT_TOAST_MS);
}

function sendQuickChat(msgId) {
    const socket = gameState.socket;
    if (!socket || !msgId) return;
    if (!gameState.roomId || !gameState.playerId) {
        showAlert('还没进入对局，发不了快捷语');
        return;
    }
    // 与 end_turn / use_magic_card 同一套取值写法
    socket.emit('quick_chat', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        msg_id: msgId
    }, (response) => {
        // 服务端可能拒绝（频率限制 / 越界 id）。提示一句，但绝不动对局状态。
        if (response && response.status === 'error') showAlert(response.message || '快捷语发送失败');
    });
}

// 收到快捷语：只弹轻提示。
// ⚠️ 日志**不在这里写**：服务端广播 quick_chat 的同时还走既有日志助手把一条
// type='quick_chat' 的条目 push 给房间（客户端由 game_log → renderServerLog 渲染），
// 那才是写进 room.game_logs / 对局历史的同一份来源。这里再 addGameLog 一次，
// 真机上每条快捷语都会在日志里出现两遍（广播一次 + game_log 一次）。
// 同理：只碰 #quick-chat-toast 一个节点，不碰棋盘 / 手牌 / 阶段 / 连锁。
function handleQuickChatReceived(payload) {
    if (!payload || !payload.text) return;
    const name = payload.name || '对手';
    const isMine = !!(gameState.playerId && payload.player_id === gameState.playerId);
    // 自己发的那条不弹提示（自己刚点过，弹了是噪音）；回显只写日志
    if (!isMine) showQuickChatToast(name, String(payload.text));
}

// 绑定入口与面板（幂等：init 只跑一次；重绘不会碰这两个节点）
function initQuickChatUI() {
    const { btn, panel } = getQuickChatEls();
    if (!btn || !panel) return;
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleQuickChatPanel();
    });
    // 面板里只有一种可点目标：条目。用事件委托，重绘也不必重绑。
    panel.addEventListener('click', (e) => {
        const item = e.target && e.target.closest ? e.target.closest('.quick-chat-item') : null;
        if (!item) return;
        e.stopPropagation();
        sendQuickChat(item.dataset.msgId);
        setQuickChatPanelOpen(false);   // 点完就收起来
    });
    // 点面板/按钮以外的地方收起；按 Esc 也收起
    document.addEventListener('click', (e) => {
        if (!isQuickChatPanelOpen()) return;
        if (btn.contains(e.target) || panel.contains(e.target)) return;
        setQuickChatPanelOpen(false);
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isQuickChatPanelOpen()) setQuickChatPanelOpen(false);
    });
    // 断线重连后表可能变过（后端改动），让下次打开重新拉一次
    if (gameState.socket) {
        gameState.socket.on('reconnect', () => { quickChatPanelData = null; quickChatPanelLoading = null; });
    }
}

// 从 window.magicCards 里按卡名取卡；不存在返回 null
function lookupCard(name) {
    const list = window.magicCards;
    if (!Array.isArray(list) || !name) return null;
    return list.find(c => c && c.name === name) || null;
}

// 解析日志里提到的卡名：优先用服务端 payload，兜底扫【X】并用卡表校验
function findLogCardName(entry) {
    const detail = entry && entry.detail;
    if (detail && typeof detail === 'object') {
        // 服务端两处日志的字段名不一致：log_magic 用 card，硫磺火焰用 card_name
        const candidate = detail.card || detail.card_name;
        if (typeof candidate === 'string' && lookupCard(candidate)) return candidate;
    }
    const m = /【([^】]{1,24})】/.exec(String((entry && entry.text) || ''));
    if (m && lookupCard(m[1])) return m[1];
    return null;
}

// 渲染日志正文：卡名包成可交互 span（悬停/点击），其余照旧转义
function renderLogTextHtml(entry) {
    const raw = String(entry.text || '');
    const name = findLogCardName(entry);
    if (!name) return `<span class="log-text">${escapeHtml(raw)}</span>`;

    // 带【】的形态：连方括号一起做成可点区域，视觉上更醒目
    const wrapped = '【' + name + '】';
    let idx = raw.indexOf(wrapped);
    let before, after, inner;
    if (idx >= 0) {
        before = raw.slice(0, idx);
        after = raw.slice(idx + wrapped.length);
        inner = '【' + escapeHtml(name) + '】';
    } else {
        // 没写【】就直接匹配卡名本身
        idx = raw.indexOf(name);
        if (idx < 0) return `<span class="log-text">${escapeHtml(raw)}</span>`;
        before = raw.slice(0, idx);
        after = raw.slice(idx + name.length);
        inner = escapeHtml(name);
    }

    return `<span class="log-text">${escapeHtml(before)}` +
        `<span class="log-card-ref" data-card="${escapeHtml(name)}">${inner}</span>` +
        `${escapeHtml(after)}</span>`;
}

// ---------------------------------------------------------------------------
// 日志卡名：桌面悬停浮层 + 点击详情小窗（手机无悬停，点一下直接出窗）
// ---------------------------------------------------------------------------
let cardTooltipEl = null;

function showCardTooltip(anchorEl, card) {
    hideCardTooltip();
    if (!anchorEl || !card) return;

    const tip = document.createElement('div');
    tip.className = 'card-tooltip';
    tip.innerHTML =
        `<div class="card-tooltip-name">${escapeHtml(card.name)}</div>` +
        `<div class="card-tooltip-stats">${escapeHtml(card.type || '')} · 速阶 ${escapeHtml(String(card.speed))}</div>` +
        `<div class="card-tooltip-desc">${escapeHtml(card.description || '')}</div>`;
    document.body.appendChild(tip);
    cardTooltipEl = tip;

    // 先量尺寸再定位：默认卡名下方居中，出界就翻到上方 / 贴边
    const r = anchorEl.getBoundingClientRect();
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    let top = r.bottom + 8;
    if (top + th > window.innerHeight - 8) top = r.top - th - 8;
    if (top < 8) top = 8;
    let left = r.left + r.width / 2 - tw / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));

    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
}

function hideCardTooltip() {
    if (cardTooltipEl && cardTooltipEl.parentNode) {
        cardTooltipEl.parentNode.removeChild(cardTooltipEl);
    }
    cardTooltipEl = null;
}

function showCardDetail(card) {
    closeCardDetail();
    if (!card) return;

    const overlay = document.createElement('div');
    overlay.className = 'card-detail-overlay';
    overlay.id = 'card-detail-overlay';
    overlay.innerHTML =
        `<div class="card-detail-box">
            <button type="button" class="card-detail-close" aria-label="关闭">✕</button>
            <div class="card-detail-name">${escapeHtml(card.name)}</div>
            <div class="card-detail-stats">
                <span class="stat-item">速阶：${escapeHtml(String(card.speed))}</span>
                <span class="stat-item">类型：${escapeHtml(card.type || '-')}</span>
            </div>
            <div class="card-detail-desc-title">效果描述：</div>
            <div class="card-detail-desc">${escapeHtml(card.description || '（无描述）')}</div>
        </div>`;
    document.body.appendChild(overlay);

    // 关闭：点遮罩空白 / 点 ✕ / 按 ESC
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeCardDetail();
    });
    const closeBtn = overlay.querySelector('.card-detail-close');
    if (closeBtn) closeBtn.addEventListener('click', closeCardDetail);

    const onKey = (e) => { if (e.key === 'Escape') closeCardDetail(); };
    document.addEventListener('keydown', onKey);
    overlay._onKey = onKey;
}

function closeCardDetail() {
    const overlay = document.getElementById('card-detail-overlay');
    if (!overlay) return;
    if (overlay._onKey) document.removeEventListener('keydown', overlay._onKey);
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
}

// 事件委托：日志条目会不断新增又被裁剪，逐条绑监听会漏绑且泄漏，所以只绑一次
function initGameLogCardRefs() {
    const host = document.getElementById('game-logs');
    if (!host || host._cardRefsBound) return;
    host._cardRefsBound = true;

    host.addEventListener('click', (e) => {
        const ref = e.target && e.target.closest && e.target.closest('.log-card-ref');
        if (!ref) return;
        const card = lookupCard(ref.dataset.card);
        if (!card) return;
        hideCardTooltip();
        showCardDetail(card);
    });

    // 触摸设备没有 hover，不绑悬停事件
    const canHover = !window.matchMedia || window.matchMedia('(hover: hover)').matches;
    if (!canHover) return;

    host.addEventListener('mouseover', (e) => {
        const ref = e.target && e.target.closest && e.target.closest('.log-card-ref');
        if (!ref) return;
        const card = lookupCard(ref.dataset.card);
        if (card) showCardTooltip(ref, card);
    });
    host.addEventListener('mouseout', (e) => {
        const ref = e.target && e.target.closest && e.target.closest('.log-card-ref');
        if (ref) hideCardTooltip();
    });
    // 滚动/折叠日志时收起浮层，避免它停在原地
    host.addEventListener('scroll', hideCardTooltip, { passive: true });
}

// 卡牌图鉴：去重后的全部卡面 + 按速阶/类型筛选 + 关键词搜索 + 使用次数排序
// （卡面数据源是 window.magicCards，使用次数来自只读接口 /api/card_usage，拉一次就缓存）
let cardUsage = {};
let cardUsageLoaded = false;

function loadCardUsage() {
    if (cardUsageLoaded) return Promise.resolve(cardUsage);
    cardUsageLoaded = true;
    return fetch('/api/card_usage')
        .then(r => (r && r.ok) ? r.json() : {})
        .then(d => { cardUsage = (d && d.usage) || {}; return cardUsage; })
        .catch(() => ({}));   // 拉不到就不显示次数，不影响图鉴本身
}

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

function renderCardCompendium() {
    if (!helpMagicCards) return;
    const all = compendiumCards();
    const q = ((document.getElementById('compendium-search') || {}).value || '').trim().toLowerCase();
    const speed = (document.getElementById('compendium-speed') || {}).value || '';
    const type = (document.getElementById('compendium-type') || {}).value || '';
    const sort = (document.getElementById('compendium-sort') || {}).value || '';

    const list = all.filter(card => {
        if (speed && String(card.speed) !== speed) return false;
        if (type && card.type !== type) return false;
        if (q) {
            const hay = (card.name + ' ' + (card.description || '')).toLowerCase();
            if (hay.indexOf(q) < 0) return false;
        }
        return true;
    });

    if (sort === 'uses') {
        // 用得多不多是玩家最关心的信息之一；同次数按卡名稳定排序
        list.sort((a, b) => (cardUsage[b.name] || 0) - (cardUsage[a.name] || 0)
            || String(a.name).localeCompare(String(b.name), 'zh'));
    }

    helpMagicCards.innerHTML = list.map(card => {
        const uses = cardUsage[card.name] || 0;
        return `
        <div class="magic-card-help" data-card-name="${card.name}" data-card-speed="${card.speed}" data-card-type="${card.type}" data-card-uses="${uses}">
            <b>${card.name}</b> <span class="compendium-meta">${card.type}·速阶${card.speed}</span>
            ${uses > 0 ? '<span class="compendium-uses">使用 ' + uses + ' 次</span>' : ''}
            <div class="compendium-desc">${card.description}</div>
        </div>`;
    }).join('') || '<p class="muted-hint">没有符合条件的卡牌</p>';

    const counter = document.getElementById('compendium-count');
    if (counter) counter.textContent = '共 ' + list.length + ' / ' + all.length + ' 张';
}

// 绑定事件监听器
function bindEventListeners() {


    // 帮助按钮事件
    if (helpBtn) helpBtn.addEventListener('click', () => {
        // ⚠️ 浮层互斥：这里**曾经是全项目唯一漏调** `closeOverlaysExcept` 的入口
        //    （设置 / 名片 / 战绩 / 好友 / 公告那几处都有）。后果实测过：先开「更新公告」
        //    再点「帮助」→ 两个浮层同时开着，两者 z-index 都是 10000、帮助在 DOM 里靠后，
        //    于是**帮助压住公告**，公告读不了也点不动（只能点 × 关帮助）。
        //    `#help-modal` 本身就是 `.modal-overlay`，按类名取的全量互斥自动覆盖它 ——
        //    不需要往任何清单里加 id。
        if (typeof closeOverlaysExcept === 'function') closeOverlaysExcept('help-modal');
        if (helpModal) helpModal.classList.remove('hidden');
        renderCardCompendium();
        // 先按已有数据画出来，统计到了再重绘一次（拉不到也不会卡住图鉴）
        loadCardUsage().then(() => renderCardCompendium());
        // 段位介绍（段位帮助批）：数字/文案全部来自 `/api/rank_constants`，
        // 拉不到就显示 #help-rank-error 并保留上一帧（不清空留白）。
        // ⚠️ 单独包一层 try：这块出错绝不能把上面的卡牌图鉴一起带下水。
        try { renderRankHelp(); } catch (e) { /* 段位块偶发失败不影响图鉴 */ }
    });
    // 图鉴的搜索/筛选：输入即重绘（41 张卡的量级，不需要防抖）
    ['compendium-search', 'compendium-speed', 'compendium-type', 'compendium-sort'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('input', renderCardCompendium);
        el.addEventListener('change', renderCardCompendium);
    });
    if (helpModalClose) helpModalClose.addEventListener('click', () => helpModal.classList.add('hidden'));
    if (helpModal) helpModal.addEventListener('click', (e) => {
        if (e.target === helpModal) helpModal.classList.add('hidden');
    });
    // 对手战绩按钮事件
    if (showOpponentStatsBtn) showOpponentStatsBtn.addEventListener('click', (e) => {
        e.preventDefault();
        // 走与「点对手头像」一致的统一入口。⚠️ 不能直接写裸标识符
        // `showOpponentStats`：它只是游戏内 alias（要等 game_state 处理器跑过
        // 才有定义），早期点击会 ReferenceError，弹窗永远出不来。
        const oppName = (window.gameState && window.gameState.opponentName) || '';
        if (oppName && typeof window.showUserProfile === 'function') {
            window.showUserProfile(oppName);
        } else if (typeof window.showOpponentStats === 'function') {
            window.showOpponentStats();
        } else {
            showMessage('对手信息还没准备好，请稍后再试', { type: 'warning' });
        }
    });
    if (opponentStatsModalClose) opponentStatsModalClose.addEventListener('click', () => {
        opponentStatsModal.classList.add('hidden');
    });
    if (opponentStatsModal) opponentStatsModal.addEventListener('click', (e) => {
        if (e.target === opponentStatsModal) opponentStatsModal.classList.add('hidden');
    });
    // 个人战绩按钮事件
    if (showUserStatsBtn) showUserStatsBtn.addEventListener('click', (e) => {
        e.preventDefault();
        console.log('点击了个人战绩按钮');
        showUserStats();
    });
    if (userStatsModalClose) userStatsModalClose.addEventListener('click', () => {
        userStatsModal.classList.add('hidden');
    });
    // 点击遮罩关闭
    if (userStatsModal) userStatsModal.addEventListener('click', (e) => {
        if (e.target === userStatsModal) userStatsModal.classList.add('hidden');
    });
    
    // 对局详情模态窗口关闭事件
    if (matchDetailModalClose) matchDetailModalClose.addEventListener('click', () => {
        matchDetailModal.classList.add('hidden');
    });
    
    // 点击遮罩关闭对局详情
    if (matchDetailModal) matchDetailModal.addEventListener('click', (e) => {
        if (e.target === matchDetailModal) matchDetailModal.classList.add('hidden');
    });

    // ---------- 个人战绩 / 对局详情（全文件唯一实现） ----------
    // 注：历史上这里有两份逐字重复的定义，后一份静默覆盖前一份，已合并为一份。

    // 对手裸 ID：人机房在 users 表里没有记录（AI 的 user_id 为 None），
    // 前端回退到裸 ID 会显示成「vs ai-4530c8」，这里统一识别并映射为「电脑」。
    function opponentRawId(matchData, myId) {
        return matchData.winner_id === myId ? matchData.loser_id : matchData.winner_id;
    }
    function isAiOpponent(matchData, myId) {
        const rawId = opponentRawId(matchData, myId);
        return typeof rawId === 'string' && rawId.indexOf('ai-') === 0;
    }
    function opponentDisplayName(matchData, myId) {
        if (isAiOpponent(matchData, myId)) return '电脑';
        const isWin = matchData.winner_id === myId;
        const name = isWin ? matchData.loser_name : matchData.winner_name;
        return name || opponentRawId(matchData, myId) || '未知';
    }

    // ==================== 个人信息名片（2026-09-17 第 1 批） ====================
    //
    // 查看态 = 这张分层名片，渲染进 #opponent-stats-content（#profile-view 根节点）；
    // 编辑态 = #profile-modal 里的 #profile-edit（index.html 里由 T2 铺好，这里只填数据）。
    // 四个入口共用 window.showUserProfile(username)：排行榜点名字/头像、局内左上自己头像、
    // 局内右上对手头像、#show-opponent-stats。
    //
    // ⚠️ 上一轮的教训（CLAUDE.md §11 通用教训四）：个人信息曾经有两套渲染 —— 局内点头像
    // 弹的是另一张只有胜负/连胜的迷你表格。这次动手前后都 grep 过渲染文案
    // （当前连胜 / 胜场 / 胜率 / 最高连胜 / 第 N 名），确认只剩这一套。
    //
    // ⚠️ 为什么 id 是可选的（opts.ids）：#profile-view-* 这套 id 按契约属于"查看面"。
    // 首页「个人战绩」那个老容器（#user-stats-content）也会渲染同一张卡，两个容器同时
    // 存在就会出现重复 id —— 那时 document.getElementById 只会拿到文档里靠前的那个，
    // 症状是"点了另一个弹窗里的东西没反应"。所以除查看面外一律只出 class、不出 id。
    const PROFILE_DEFAULT_AVATAR = '/static/avatars/default.png';
    // 标签中文名以接口下发的 catalog 为准；这张表只是"没登录 / 拿不到 catalog"时的兜底
    // （id 与 docs/PROFILE_CARD_2026_09_17.md §5.2 一致，12 项）
    const PROFILE_TAG_FALLBACK = {
        aggressive: '激进', steady: '稳健', fast: '速攻', turtle: '蹲坑',
        cardflow: '卡牌流', chain: '连锁控', rookie: '萌新', pro: '大佬',
        nightowl: '夜猫子', needmate: '求带', serious: '不苟言笑', chatty: '爱聊'
    };

    function profileAvatarSrc(s) {
        return (s && s.avatar) ? String(s.avatar) : PROFILE_DEFAULT_AVATAR;
    }
    function profileRankValue(s) {
        const rank = parseInt(s && s.rank, 10);
        return (rank && rank > 0) ? String(rank) : '';
    }
    function profileCatalogList(key, fallbackIds) {
        const list = (profileCatalog && Array.isArray(profileCatalog[key])) ? profileCatalog[key] : null;
        return (list && list.length) ? list.map(t => t && t.id).filter(Boolean) : fallbackIds.slice();
    }
    function profileBgId(s) {
        const ids = profileCatalogList('card_bgs', ['deep', 'graphite', 'cyber', 'lava', 'dusk', 'aurora']);
        const id = String((s && s.card_bg_id) || 'deep');
        return ids.indexOf(id) >= 0 ? id : 'deep';
    }
    function profileFrameId(s) {
        const ids = profileCatalogList('frames', ['none', 'silver', 'gold', 'aurora', 'crimson']);
        const id = String((s && s.frame_id) || 'none');
        return ids.indexOf(id) >= 0 ? id : 'none';
    }
    function profileTitleName(s) {
        if (!s) return '';
        if (s.title_name) return String(s.title_name);
        const id = s.title_id ? String(s.title_id) : '';
        if (!id) return '';
        const titles = (profileCatalog && Array.isArray(profileCatalog.titles)) ? profileCatalog.titles : [];
        const hit = titles.filter(t => t && t.id === id)[0];
        return hit ? String(hit.name || id) : '';
    }
    // tags 可能是 id 数组、也可能是 [{id,name}]，中文名优先取接口给的
    function profileTagNames(tags) {
        const raw = Array.isArray(tags) ? tags : [];
        const pool = (profileCatalog && Array.isArray(profileCatalog.tags)) ? profileCatalog.tags : [];
        const byId = {};
        pool.forEach(t => { if (t && t.id) byId[t.id] = t.name || t.id; });
        const out = [];
        raw.forEach(item => {
            const id = (item && typeof item === 'object') ? item.id : item;
            if (!id) return;
            const name = (item && typeof item === 'object' && item.name)
                || byId[id] || PROFILE_TAG_FALLBACK[id];
            if (name && out.indexOf(name) < 0) out.push(name);
        });
        return out.slice(0, 3);
    }
    // 后端没有"等级"这个字段，这里按总场次换算（每 5 场 1 级，封顶 99），纯展示
    function profileLevel(total) {
        return Math.min(99, 1 + Math.floor((Number(total) || 0) / 5));
    }
    function profileToggleValue(value, defaultValue) {
        if (value === undefined || value === null || value === '') return defaultValue;
        return Number(value) === 0 ? 0 : 1;
    }
    function formatProfileDate(value) {
        const n = Number(value);
        if (!value || isNaN(n) || n <= 0) return '';
        const d = new Date(n * 1000);
        if (isNaN(d.getTime())) return '';
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
            + '-' + String(d.getDate()).padStart(2, '0');
    }

    // 徽章（第 2 批）：**展示兜底**只有名称 —— 判据与"解锁没解锁"一律以服务端下发的
    // `unlocked` 字段为准，前端绝不自己算「够不够格」（第 2 批硬规矩第 4 条：
    // 只在前端灰掉等于没校验；反过来，前端自己算解锁就会与服务端的 `evaluate()` 漂移）。
    // 这张表存在的唯一理由：接口万一只给了裸 id，徽章也不该显示成 `first_win` 这种英文 id。
    const PROFILE_BADGE_FALLBACK = {
        first_win: '首胜', veteran10: '十场老兵', streak5: '五连胜', streak10: '十连胜',
        sunk50: '五十沉', sunk200: '两百沉', flawless: '零伤获胜', flawless5: '完美指挥',
        speedrun: '闪电战', cardmaster: '卡牌大师', allrounder: '全能选手', rank1: '榜首'
    };
    // 把接口下发的任意一条徽章归一化成渲染用的形状。
    // defaultUnlocked：这条数据隐含的解锁状态（`/user_stats` 只发已解锁的 → true）
    function profileBadgeItem(raw, defaultUnlocked) {
        const item = (raw && typeof raw === 'object') ? raw : { id: raw };
        const id = String(item.id || '').trim();
        if (!id) return null;
        const name = String(item.name || PROFILE_BADGE_FALLBACK[id] || id);
        // 只有**明确**是 false 才算未解锁：`/user_stats` 那一路根本没有这个字段，
        // 缺字段时按调用方给的 defaultUnlocked（别人视角 = 已解锁）处理。
        const unlocked = (item.unlocked === undefined || item.unlocked === null)
            ? defaultUnlocked === true
            : item.unlocked !== false && item.unlocked !== 0;
        return {
            id: id,
            name: name,
            desc: String(item.desc || ''),
            requirement: String(item.requirement || ''),
            group: String(item.group || ''),
            unlocked: unlocked,
            unlocked_at: Number(item.unlocked_at) || 0
        };
    }

    // 徽章清单。selfCatalog = 自己视角的完整目录（含未解锁），由 /api/profile 提供；
    // 别人视角没有它，只有 `stats.achievements` 里那几枚已解锁的。
    //
    // ⚠️ 前端**不补**未解锁项：别人视角缺的未解锁徽章就该缺着（契约要求"看别人只显示已解锁"），
    // 拿自己那份目录去补会变成"看到别人的进度"。
    function profileBadgeList(s, selfCatalog) {
        const out = [];
        const seen = {};
        const push = (item) => { if (item && !seen[item.id]) { seen[item.id] = 1; out.push(item); } };
        if (Array.isArray(selfCatalog) && selfCatalog.length) {
            selfCatalog.forEach(it => push(profileBadgeItem(it, false)));
        } else {
            const raw = s && s.achievements;
            if (Array.isArray(raw)) {
                raw.forEach(it => push(profileBadgeItem(it, true)));
            } else if (raw && typeof raw === 'object') {
                // 容错形态：{badge_id: unlocked_at}
                Object.keys(raw).forEach(id => push(profileBadgeItem({ id: id, unlocked_at: raw[id] }, true)));
            }
        }
        // 已解锁的排前面（解锁时间新的更靠前），未解锁的按原顺序跟在后面
        const unlocked = out.filter(b => b.unlocked)
            .sort((a, b) => (b.unlocked_at || 0) - (a.unlocked_at || 0));
        const locked = out.filter(b => !b.unlocked);
        return unlocked.concat(locked);
    }

    // 徽章总数：接口的 badge_count 优先（**别人视角也给了它**）。
    // ⚠️ 不能用"下发了几枚"当总数 —— 别人视角只下发已解锁的，那样会把
    // 「已解锁 2 / 12」显示成「已解锁 2 / 2」。只有拿到**完整目录**（自己视角的
    // selfCatalog）时才允许用它的条数兜底；否则总数未知，标题只显示「已解锁 N」。
    function profileBadgeTotal(s, selfCatalog, items) {
        const fromApi = s && s.badge_count;
        const n = (fromApi && typeof fromApi === 'object') ? Number(fromApi.total) : Number(fromApi);
        if (n > 0) return n;
        if (Array.isArray(selfCatalog) && selfCatalog.length) return selfCatalog.length;
        return 0;
    }

    function profileBadgeHtml(b) {
        const locked = !b.unlocked;
        const title = locked
            ? ('未解锁' + (b.requirement ? '：' + b.requirement : ''))
            : (b.name + (b.desc ? ' · ' + b.desc : ''));
        const glyph = locked ? '?' : (PROFILE_BADGE_GLYPH[b.group] || '🏅');
        return '<span class="badge' + (locked ? ' locked' : '') + '"'
            + ' data-badge="' + escapeHtml(b.id) + '"'
            + ' data-group="' + escapeHtml(b.group) + '"'
            + ' title="' + escapeHtml(title) + '">'
            + '<em class="badge-glyph">' + escapeHtml(glyph) + '</em>'
            + '<em class="badge-name">' + escapeHtml(b.name) + '</em>'
            + '</span>';
    }

    // 名片要显示的**全部**内容都在这里算出来 —— 查看态/编辑态、两个容器都吃这一份，
    // 免得"同一份东西两份实现"再次漂移。
    // opts.badges → 自己视角的完整徽章目录（只有看自己时才传；见 profileBadgeList）
    function profileCardModel(s, opts) {
        s = s || {};
        opts = opts || {};
        const wins = Number(s.wins) || 0;
        const losses = Number(s.losses) || 0;
        const total = wins + losses;
        const rank = profileRankValue(s);
        const joinDate = formatProfileDate(s.created_at);
        const fav = (Array.isArray(s.fav_cards) ? s.fav_cards : [])
            .filter(c => c && c.name);
        const badges = profileBadgeList(s, opts.badges);
        const badgeUnlocked = badges.filter(b => b.unlocked).length;
        return {
            avatar: profileAvatarSrc(s),
            name: String(s.username || '未知玩家'),
            // 名字样式（特权外观）：'rainbow' = 彩虹渐变。**服务端下发的**，
            // 别人看你的名片也会带上（见 api.py 的 _name_style），
            // 前端只负责加个类，不做任何"判断谁有资格"的事 —— 资格在服务端的数据层。
            nameStyle: String(s.name_style || ''),
            signature: String(s.signature || ''),
            // 等级：**以服务端的 level_info 为准**（经验/等级/进度都由它算）。
            // 老接口没给 level_info 时退回原来的"按场次估算"，保证不会显示成 undefined。
            level: (s.level_info && Number(s.level_info.level)) || profileLevel(total),
            levelInfo: s.level_info || null,
            title: profileTitleName(s),
            status: String(s.status_text || ''),
            tags: profileTagNames(s.tags),
            streak: Number(s.longest_streak) || 0,
            rateText: total ? Math.round((wins / total) * 100) + '%' : '—',
            total: total,
            wins: wins,
            losses: losses,
            favCards: fav,
            badges: badges,
            badgeUnlocked: badgeUnlocked,
            badgeTotal: profileBadgeTotal(s, opts.badges, badges),
            // 有没有**徽章项**决定要不要显示这一块 —— 不是"已解锁几枚"。
            // 自己视角拿到的是完整目录（12 枚，新号可能 0 枚解锁）：这时候恰恰要显示
            // 一整墙灰位，否则新玩家根本不知道有徽章这回事（这一条按 B 票 2026-09-17
            // 的补充修正过：原 C 票规格写的是"已解锁为 0 也隐藏"，两者冲突，以"能看到
            // 收集目标"为准）。完全没有徽章项（接口没给 / 看的人没有数据）才整块收起。
            showBadges: badges.length > 0,
            frame: profileFrameId(s),
            bg: profileBgId(s),
            showStats: profileToggleValue(s.show_stats, 1) === 1,
            showFav: profileToggleValue(s.show_fav_cards, 1) === 1,
            rankText: rank ? '第 ' + rank + ' 名' : '',
            recordText: wins + ' 胜 ' + losses + ' 负',
            joinText: joinDate ? '加入于 ' + joinDate : '',
            // ---- 第 3 批：互动条 / 留言板 ----
            // 点赞与送花的计数**始终可见**（契约 §3.4：那是"人气"不是"内容"，
            // 不受任何展示开关与留言板隐私控制）。
            // `mine` 的初值只信接口：/api/profile/like 成功后由响应里的 mine 覆盖，
            // /user_stats 没给这个字段时一律按"没点过"（点一下就知道真实值，
            // 绝不能自己猜成 true —— 那会让按钮显示成已点亮却没在服务端生效）。
            likeCount: profileLikeCount(s, 'like'),
            flowerCount: profileLikeCount(s, 'flower'),
            likeMine: profileLikeMine(s, 'like'),
            flowerMine: profileLikeMine(s, 'flower'),
            guestbookPrivate: Number(s.show_guestbook) === 0,
            // ---- 段位批：段位块 ----
            // 服务端把 `label` / `progress` / `to_next` / `sub_points` 全算好了，这里只判"有没有"。
            // 别人 + 关掉「段位公开」时接口给的是 **null**（不是空 dict）→ 整块不渲染；
            // 绝不许退化成「二级水手Ⅰ 0分」这种假数据（那比不显示更糟）。
            rank: (s && s.rank_info && typeof s.rank_info === 'object') ? s.rank_info : null,
            self: opts.self === true,
            // ---- 好友批：查看面「加好友 / 邀战」按钮的关系态 ----
            // ⚠️ 关系**不是**从 /user_stats 或 /api/profile 来的 —— 这两个接口的响应里
            //    压根没有 relation 字段，而本批**没有改后端的授权**。
            //    所以由调用方（showUserProfile / fetchProfile）单独拉一次 GET /api/friends，
            //    用 username 在本地比对算出来，再通过 opts.friendRelation 传进来
            //    （算法见 resolveFriendRelation）。这里只负责"渲染"，一个判断都不做。
            //    没传时按 'none' 渲染，按钮照样存在（契约 id 必须落地）。
            friendRelation: FRIEND_RELATIONS.indexOf(opts.friendRelation) >= 0 ? opts.friendRelation : 'none'
        };
    }

    // 点赞 / 送花的计数：接口给了就用，没给按 0（后端 D 票在并行做，接口未落地时
    // 名片照样要能渲染，不能因为少一个字段就整张卡打不开）。
    function profileLikeCount(s, kind) {
        if (!s) return 0;
        const box = s.like_counts || s.counts;
        const raw = (box && typeof box === 'object') ? box[kind] : s['likes_' + kind];
        const n = Number(raw);
        return (isFinite(n) && n > 0) ? Math.floor(n) : 0;
    }
    function profileLikeMine(s, kind) {
        if (!s) return false;
        const box = s.like_mine || s.mine;
        const raw = (box && typeof box === 'object') ? box[kind] : s[kind + '_mine'];
        return raw === true || raw === 1 || raw === '1';
    }

    // 互动条（查看面自己的名片才有；本函数只在 withIds 时被调用）。
    // ⚠️ 「自己看自己」由服务端裁决（契约 §3.3：不能给自己点赞 → 400），
    // 这里 disabled + title 只是不让玩家白点一次 —— 第 1 批硬规矩第 4 条。
    //
    // 好友批追加：`#add-friend-btn`（加好友 / 已申请 / 接受申请 / 好友）也长在这一排。
    // 「邀战」按钮**不给 id** —— 它跟 `#add-friend-btn` 在同一个文档里，
    // 再要一个 id 只会多一处撞 id 的机会，用 `.fri-invite-btn` 走事件委托。
    function profileActionButtonsHtml(m) {
        const self = m.self === true;
        const selfTitle = '不能给自己点赞';
        const selfTitleFlower = '不能给自己送花';
        return friendActionButtonsHtml(m)
            + '<button type="button" class="pf-like' + (m.likeMine ? ' on' : '') + '"'
            + ' id="profile-like"' + (self ? ' disabled' : '')
            + ' title="' + escapeHtml(self ? selfTitle : (m.likeMine ? '取消点赞' : '点个赞')) + '">'
            + '<span class="pf-like-icon" aria-hidden="true">👍</span><span class="pf-like-label">点赞</span>'
            + '<span class="pf-like-count" id="profile-like-count">' + escapeHtml(String(m.likeCount)) + '</span>'
            + '</button>'
            + '<button type="button" class="pf-flower' + (m.flowerMine ? ' on' : '') + '"'
            + ' id="profile-flower"' + (self ? ' disabled' : '')
            + ' title="' + escapeHtml(self ? selfTitleFlower : (m.flowerMine ? '取消送花' : '送一朵花')) + '">'
            + '<span class="pf-like-icon" aria-hidden="true">🌸</span><span class="pf-like-label">送花</span>'
            + '<span class="pf-like-count" id="profile-flower-count">' + escapeHtml(String(m.flowerCount)) + '</span>'
            + '</button>';
    }

    // 留言板外壳（只在查看面渲染）。这里**只铺骨架不填数据** —— 留言列表由
    // openGuestbook() 异步取，这样"接口挂了"也不会把整张名片带崩（只多一行提示）。
    //   · guestbook_private === true → 显示「该玩家未开放留言板」的占位，
    //     但输入区 / 列表 / 计数这些 id 仍然渲染出来（契约 §3.5 要求 id 存在，
    //     只靠 hidden 收起 —— 少了 id 才是"点了没反应"的根源）。
    //   · self === true → 藏掉输入区（自己不能给自己留言），并写明这是你自己的名片。
    function guestbookBlockHtml(m) {
        const self = m.self === true;
        const privateG = m.guestbookPrivate === true;
        const inputHidden = self || privateG;
        let html = '<div id="profile-guestbook" class="pf-block pf-guestbook">';
        html += '<h4 class="pf-block-title">留言板'
            + '<span class="pf-guestbook-count" id="guestbook-count">0/' + String(GUESTBOOK_MAX) + '</span></h4>';
        html += '<div id="guestbook-private" class="guestbook-private' + (privateG ? '' : ' hidden') + '">'
            + '该玩家未开放留言板</div>';
        html += '<div class="guestbook-form' + (inputHidden ? ' hidden' : '') + '">'
            + '<textarea id="guestbook-input" class="guestbook-input" rows="2" maxlength="' + String(GUESTBOOK_MAX) + '"'
            + ' placeholder="说点什么吧（最多 ' + String(GUESTBOOK_MAX) + ' 字）"></textarea>'
            + '<button type="button" class="guestbook-send" id="guestbook-send">发表留言</button>'
            + '</div>';
        if (self) {
            html += '<p class="guestbook-hint" id="guestbook-self-hint">这是你自己的名片，别人给你留的话都在这儿。</p>';
        }
        html += '<p class="guestbook-msg" id="guestbook-msg" role="status"></p>';
        html += '<div id="guestbook-list" class="guestbook-list"></div>';
        html += '<p id="guestbook-empty" class="guestbook-empty hidden">还没有留言</p>';
        html += '<button type="button" id="guestbook-more" class="guestbook-more hidden">加载更多</button>';
        html += '</div>';
        return html;
    }

    function profileStatHtml(key, value, label) {
        return '<div class="stat" data-stat="' + key + '">'
            + '<b>' + escapeHtml(String(value)) + '</b>'
            + '<span>' + escapeHtml(label) + '</span>'
            + '</div>';
    }

    // 只读分层名片（查看态）。返回 HTML 字符串，由调用方决定塞进哪个容器。
    // opts.ids            → 是否输出 #profile-view-* 这套 id（只有查看面可以）
    // opts.canEdit        → 是否渲染「编辑资料」（只有看自己时）
    // opts.history        → 传了才渲染历史战绩区块
    // opts.hasMore        → 历史还有下一页时渲染「加载更多」
    // opts.historyPrivate → 对方没公开历史时的占位文案
    // opts.badges         → 自己视角的完整徽章目录（含未解锁）；别人视角不传
    //
    // 第 3 批（B3-E）在这张卡里追加了两块，**都只渲染进查看面**（withIds 为真时）：
    //   · .pf-actions 里的互动条（点赞 / 送花）—— 见 profileActionButtonsHtml
    //   · #profile-guestbook 留言板 —— 见 guestbookBlockHtml
    // 两者都只出「壳」：真实数据由 openGuestbook() 异步灌进 #guestbook-list，
    // 互动条点击就地改 DOM（applyProfileLikeState）。**任何一次互动都不整卡重渲染** ——
    // 重渲染会冲掉留言板输入到一半的内容与弹窗滚动位置。
    function buildProfileCard(s, opts) {
        opts = opts || {};
        const withIds = opts.ids === true;
        const m = profileCardModel(s, opts);
        // ⚠️ 这里刻意写成字面量属性（而不是 'id="' + name + '"'）：
        // tools/dom_contract_check.mjs 是靠源码里的 `id="…"` 字面量来判断
        // "这个契约 id 是由 JS 运行期渲染的"，拼接出来的它认不出来，会误报成悬空 id。
        const idsOn = (literal) => (withIds ? ' ' + literal : '');
        const history = Array.isArray(opts.history) ? opts.history : null;

        let html = '<div' + idsOn('id="profile-view"') + ' class="profile-card-view pf-card" data-bg="' + escapeHtml(m.bg) + '">';
        html += '<div class="pf-cover" data-bg="' + escapeHtml(m.bg) + '"></div>';
        html += '<div class="pf-hero">';
        html += '<div class="pf-avatar-wrap">'
            + '<img' + idsOn('id="profile-view-avatar"') + ' class="pf-avatar" data-frame="' + escapeHtml(m.frame) + '"'
            + ' src="' + escapeHtml(m.avatar) + '" alt="头像"'
            + ' onerror="this.onerror=null;this.src=\'/static/avatars/default.png\'">'
            + '<span' + idsOn('id="profile-view-level"') + ' class="lvl">Lv.' + m.level + '</span>'
            + '</div>';
        // 经验条（等级 / 本级进度都来自服务端的 level_info；接口没给就不画这一块）
        if (m.levelInfo) {
            const li = m.levelInfo;
            const pct = li.capped ? 100 : Math.round((Number(li.ratio) || 0) * 100);
            html += '<div' + idsOn('id="profile-view-xp"') + ' class="pf-xp">'
                + '<div class="pf-xp-bar"><i style="width:' + pct + '%"></i></div>'
                + '<span class="pf-xp-text">'
                + (li.capped ? ('满级 ' + (li.max_level || 100))
                             : (Number(li.into || 0) + ' / ' + Number(li.need || 0) + ' 经验'))
                + '</span></div>';
        }
        html += '<div class="pf-who">'
            // ⚠️ 彩虹类只能加在**包住名字文本**的 span 上，不能加在 <h3> 上：
            //    称号 chip 是 h3 的子元素，而 `-webkit-text-fill-color: transparent`
            //    **是可继承属性** → 称号文字会一起变透明（2026-09-17 实测：
            //    「不败神话」只剩一个金色药丸、字看不见了）。这条回归是加彩虹名字时引入的。
            + '<h3' + idsOn('id="profile-view-name"') + ' class="pf-name">'
            + '<span class="pf-name-text' + (m.nameStyle === 'rainbow' ? ' name-rainbow' : '') + '">'
            + escapeHtml(m.name) + '</span>'
            + '<span' + idsOn('id="profile-view-title"') + ' class="title-chip' + (m.title ? '' : ' hidden') + '">'
            + escapeHtml(m.title) + '</span></h3>'
            + '<p' + idsOn('id="profile-view-status"') + ' class="state">'            + escapeHtml(m.status || '这位玩家还没有写状态') + '</p>'
            + '<div' + idsOn('id="profile-view-tags"') + ' class="pf-tags">'
            + m.tags.map(t => '<span class="tag">' + escapeHtml(t) + '</span>').join('')
            + '</div>'
            + '</div>';
        // 个性签名（上一批作者明确要保留的一项资料）；签名与"一句话状态"并存
        html += '<p class="pf-signature profile-signature">'
            + escapeHtml(m.signature || '还没有填写个性签名') + '</p>';
        html += '<div class="pf-actions">'
            + (opts.canEdit
                ? '<button type="button"' + idsOn('id="profile-edit-btn"') + ' class="btn pf-edit-btn">编辑资料</button>'
                : '')
            + (withIds ? profileActionButtonsHtml(m) : '')
            + '</div>';
        html += '</div>';

        // 段位块（段位批）：图标 + 服务端下发的 `label` + 小段位进度条。
        // ⚠️ 一个数都不算：宽度用服务端的 `progress / sub_points`，
        //    「还差 N 分」用服务端的 `to_next`；`to_next` 为 null（船长Ⅲ / 大舰长，
        //    后面没有小级了）时**不画进度条、也不写"还差 N 分"**。
        //    `label` 直接显示（普通 `水手长Ⅱ 90分` / 船长 `船长Ⅲ 2300分 #60` / `大舰长 #20`）。
        if (m.rank) {
            const ri = m.rank;
            const sub = Number(ri.sub_points) || 0;
            const prog = Number(ri.progress) || 0;
            const hasNext = (ri.to_next !== null && ri.to_next !== undefined);
            const pct = (hasNext && sub > 0)
                ? Math.max(0, Math.min(100, Math.round((prog / sub) * 100))) : 100;
            html += '<div' + idsOn('id="profile-view-rank"') + ' class="pf-rank'
                + (ri.is_admiral ? ' is-admiral' : '') + '" data-tier="' + escapeHtml(String(ri.tier_id || '')) + '">'
                + '<span class="pf-rank-icon">' + rankIconMarkup(ri.tier_id, 30) + '</span>'
                + '<span class="pf-rank-label">' + escapeHtml(rankLabelOf(ri)) + '</span>'
                + (hasNext
                    ? '<span class="pf-rank-bar"><i style="width:' + pct + '%"></i></span>'
                        + '<span class="pf-rank-next">还差 ' + escapeHtml(String(Number(ri.to_next) || 0)) + ' 分</span>'
                    : '')
                + '</div>';
        }

        // 三个 show_* 是**同一套语义**：0 = 该区块对所有人隐藏（自己也不显示），
        // 1 = 对所有人可见。所以这里不看"是不是自己"，只看字段值。
        // 隐藏时元素仍然渲染出来（契约要求这两个 id 存在）但内容为空 ——
        // 只加 hidden 而留着数据的话，别人打开开发者工具还是能读到。
        const statBlockHtml = profileStatHtml('streak', m.streak, '最高连胜')
            + profileStatHtml('rate', m.rateText, '胜率')
            + profileStatHtml('matches', m.total, '总场次');
        html += '<div' + idsOn('id="profile-view-stats"') + ' class="pf-stats' + (m.showStats ? '' : ' hidden') + '">'
            + (m.showStats ? statBlockHtml : '')
            + '</div>';

        // 徽章墙（第 2 批）。已解锁的正常显示，未解锁的加 .locked 并在 title 里写解锁条件。
        //   自己看自己 → 全部徽章（含未解锁的灰位），目录来自 /api/profile；
        //   看别人     → 只有已解锁的那几枚（接口压根不下发未解锁的，前端也不去补，
        //                否则等于把别人的进度暴露出来）。
        // 判据是"有没有徽章**项**"：一枚都没解锁但有 12 个灰位时**照样显示**
        // （新玩家要看得到收集目标）；完全拿不到徽章项时才整块 hidden，
        // 而且**不留空标题**（第 1 批「空区块占位」的教训）。
        if (m.showBadges) {
            html += '<div' + idsOn('id="profile-view-badges"') + ' class="pf-block pf-badges">'
                + '<h4 class="pf-block-title">徽章墙'
                + '<span class="pf-badges-count">已解锁 ' + escapeHtml(String(m.badgeUnlocked))
                + (m.badgeTotal > 0 ? ' / ' + escapeHtml(String(m.badgeTotal)) : '') + '</span></h4>'
                + '<div class="badge-grid">' + m.badges.map(b => profileBadgeHtml(b)).join('') + '</div>'
                + '</div>';
        } else {
            // 完全拿不到徽章项时：契约要求这个 id 存在（查看面的 id 由 idsOn 统一管理），
            // 所以渲染成一个收起来的空块 —— 不渲染的话契约对账会报"id 没落地"。
            html += '<div' + idsOn('id="profile-view-badges"') + ' class="pf-block pf-badges hidden"></div>';
        }

        const showFav = m.showFav && m.favCards.length > 0;
        html += '<div' + idsOn('id="profile-view-favcards"') + ' class="pf-block pf-favcards' + (showFav ? '' : ' hidden') + '">'
            + '<h4 class="pf-block-title">最爱用的卡</h4>'
            + (showFav ? m.favCards.map(c => '<div class="fav">'
                + '<span class="fav-name">' + escapeHtml(String(c.name)) + '</span>'
                + '<span class="fav-meta">'
                + (Number(c.speed) > 0 ? '速阶 ' + Number(c.speed) + ' · ' : '')
                + (Number(c.uses) || 0) + ' 次</span>'
                + '</div>').join('') : '')
            + '</div>';

        if (history) {
            const hasAi = history.some(h => isAiOpponent(h, s.id));
            const emptyText = opts.historyPrivate ? '该玩家未公开对局历史' : '暂无历史战绩';
            html += '<div' + idsOn('id="profile-view-history"') + ' class="pf-block profile-history user-history">'
                + '<h4 class="pf-block-title">历史战绩</h4>'
                + (hasAi ? '<p class="user-stats-note">人机对局保留在历史中，不计入胜场 / 连胜，也不进排行榜。</p>' : '')
                + '<div' + idsOn('id="profile-history-list"') + ' class="history-list">'
                + buildHistoryList(history, s) + '</div>'
                + '<p' + idsOn('id="profile-history-empty"') + ' class="history-empty' + (history.length ? ' hidden' : '') + '">'
                + escapeHtml(emptyText) + '</p>'
                + (opts.hasMore ? '<button type="button"' + idsOn('id="profile-history-more"')
                    + ' class="history-more">加载更多</button>' : '')
                + '</div>';
        }

        html += '<div' + idsOn('id="profile-view-meta"') + ' class="pf-meta">'
            + '<span class="pf-meta-item">' + escapeHtml(m.joinText || '加入时间未知') + '</span>'
            + '<span class="pf-meta-item">' + escapeHtml(m.rankText || '暂未上榜') + '</span>'
            + '<span class="pf-meta-item pf-record">' + escapeHtml(m.recordText) + '</span>'
            + '</div>';
        // 留言板（第 3 批）。位置固定在名片末尾（#profile-view-meta 之后），
        // 交互条在 .pf-actions 里 —— 两块的详细说明见 prepareGuestbook/applyProfileLikeState。
        if (withIds) html += guestbookBlockHtml(m);
        html += '</div>';
        return html;
    }

    // 历史战绩列表：必须用 div 列表承载。
    // 旧写法把 <button> 塞进 table 的 tbody —— 那并非合法的表格子元素，HTML 解析器会
    // 启用 foster parenting 把它挪到 table 之前，表头于是孤立地留在整段列表下方
    // （2026-09-13 修复）。
    function buildHistoryList(history, s) {
        // 空占位由调用方渲染（#profile-history-empty 要区分"真没有"与"没公开"）
        if (!history.length) return '';
        let html = '<div class="history-head">'
            + '<span class="hist-time">时间</span>'
            + '<span class="hist-opp">对手</span>'
            + '<span class="hist-result">结果</span>'
            + '</div>';
        history.forEach((h, index) => {
            const isWin = h.winner_id === s.id;
            const timeText = h.timestamp ? new Date(h.timestamp * 1000).toLocaleString() : '';
            const aiTag = isAiOpponent(h, s.id) ? '<span class="hist-tag">人机</span>' : '';
            html += '<button type="button" class="match-history-btn ' + (isWin ? 'win' : 'lose') + '"'
                + ' data-match-index="' + index + '" title="点击查看本局详情">'
                + '<span class="hist-time">' + escapeHtml(timeText) + '</span>'
                + '<span class="hist-opp">vs ' + escapeHtml(opponentDisplayName(h, s.id)) + aiTag + '</span>'
                + '<span class="hist-result">' + (isWin ? '胜' : '负') + '</span>'
                + '</button>';
        });
        return html;
    }

    // 战绩正文 = 那张只读名片（+ 历史战绩）。
    // 名字与签名保持不变：无头 UI 回归检查（stats_modal_check / profile_leaderboard_check）
    // 直接调它往容器里塞 HTML，历史上也有别处引用过这个入口。
    // ids 默认关闭 —— 只有"查看面"（#opponent-stats-content）才允许带
    // #profile-view-* 这套 id，别的容器带上就会在同一个文档里撞 id。
    function renderUserStatsHTML(s, history, opts) {
        const options = opts || {};
        return buildProfileCard(s || {}, {
            ids: options.ids === true,
            canEdit: options.canEdit === true,
            history: Array.isArray(history) ? history : [],
            hasMore: options.hasMore === true,
            historyPrivate: options.historyPrivate === true,
            // 自己视角的完整徽章目录（含未解锁）。别人视角不传 —— /user_stats 本来就
            // 只发已解锁的，前端也不该拿自己那份去补（那是别人的进度）。
            badges: Array.isArray(options.badges) ? options.badges : null,
            // 第 3 批：看的是不是自己（决定留言输入区收不收、互动条灰不灰）。
            // 只影响这两块；接口层的权限（不能给自己留言/点赞）仍然由服务端裁决。
            self: options.self === true,
            // 好友批：查看面「加好友 / 邀战」按钮的关系态（'none' | 'pending_out' |
            // 'pending_in' | 'friends'）。由调用方拉 /api/friends 算好后传进来 ——
            // 详见 profileCardModel 里那段说明。
            // ⚠️ 必须**原样透传**（包括 undefined）：fetchProfile 重渲染那一趟就是靠
            //    把它带着关系传下来，才能把「邀战」画出来并结束重渲染循环。
            friendRelation: options.friendRelation
        });
    }
    window.renderUserStatsHTML = renderUserStatsHTML;
    window.buildProfileCard = buildProfileCard;
    window.profileCardModel = profileCardModel;

    // 单次 20 条，最多 100 条（与服务端 db.get_match_history 的上限一致）
    const STATS_PAGE_SIZE = 20;
    const STATS_MAX_ROWS = 100;
    // 留言单条长度上限（与契约 §3.3 的 100 字一致；服务端才是最终裁决，
    // 这里只做"当场拦住"，不让玩家白等一次往返）。
    const GUESTBOOK_MAX = 100;
    const GUESTBOOK_PAGE = 20;
    let statsHistoryLimit = STATS_PAGE_SIZE;
    // 当前正在看谁的名片 / 当前名片数据（"加载更多"与保存后重渲染都要用）
    let currentProfileUsername = '';
    let currentProfileStats = null;

    function bindHistoryButtons(container, history, myId) {
        container.querySelectorAll('.match-history-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const matchIndex = parseInt(btn.dataset.matchIndex, 10);
                if (history[matchIndex]) showMatchDetail(history[matchIndex], myId);
            });
        });
        const moreBtn = container.querySelector('.history-more');
        if (moreBtn) {
            moreBtn.addEventListener('click', () => {
                statsHistoryLimit = Math.min(statsHistoryLimit + STATS_PAGE_SIZE, STATS_MAX_ROWS);
                // 「加载更多」要接着看**当前这个人**的历史：以前这里写死成
                // showUserStats()，在对手面板里点"更多"会跳到自己的战绩。
                if (container === opponentStatsContent && currentProfileUsername) {
                    showUserProfile(currentProfileUsername);
                } else {
                    showUserStats();
                }
            });
        }
    }

    // 查看面里的互动按钮（编辑资料 / 点赞 / 送花 / 留言板）。
    // 用委托绑在容器上：整块 innerHTML 每次打开都会被换掉，逐次绑定必然失效。
    // 委托还有个额外好处：点赞/留言只就地改 DOM（不重渲染整卡），这条监听不会被打断。
    function bindProfileCardButtons(container) {
        if (!container || container.dataset.profileCardBound === '1') return;
        container.dataset.profileCardBound = '1';
        container.addEventListener('click', (e) => {
            const target = (e.target && e.target.closest) ? e.target.closest(
                '.pf-edit-btn, #profile-like, #profile-flower, #guestbook-send, .guestbook-del, #guestbook-more') : null;
            if (!target) return;
            if (target.classList.contains('pf-edit-btn')) {
                e.preventDefault();
                openMyProfileEditor();
                return;
            }
            if (target.id === 'profile-like' || target.id === 'profile-flower') {
                e.preventDefault();
                toggleProfileLike(target.id === 'profile-like' ? 'like' : 'flower');
                return;
            }
            if (target.id === 'guestbook-send') {
                e.preventDefault();
                sendGuestbookMessage();
                return;
            }
            if (target.classList.contains('guestbook-del')) {
                e.preventDefault();
                deleteGuestbookMessage(target.dataset.id, container);
                return;
            }
            if (target.id === 'guestbook-more') {
                e.preventDefault();
                loadGuestbookMore();
            }
        });
    }

    // ==================== 第 3 批 B3-E：点赞 / 送花 ====================
    //
    // 两条硬要求（票面）：
    //   ① **不许整卡重渲染** —— 成功后只改那几个 span/button 的文案与类，卡片其余部分
    //      （留言板输入框里没发出去的草稿、弹窗滚动位置、加载更多已经展开的留言）
    //      一个字都不动。所以这里没有一处调 fetchProfile / innerHTML 重建整卡。
    //   ② 接口挂了**不能把整张卡打崩** —— 只多一行红字提示，按钮恢复可点、状态回滚。
    //      （后端 D 票在并行做：契约未落地时这条路一定走得到，必须实测过。）
    //
    // 交互态放在模块变量里而不是 dataset 上：dataset 存的是字符串，'false' 是真值，
    // 这个项目已经因为"字符串当布尔用"栽过一次（classList/attr 那类）。
    const profileLikeState = { likeCount: 0, flowerCount: 0, likeMine: false, flowerMine: false };
    let profileLikeTarget = '';       // 当前这张名片是谁的（点赞/留言都要发给他）
    let profileCardIsSelf = false;
    const profileLikePending = { like: false, flower: false };

    function profileViewContainer() {
        return document.getElementById('opponent-stats-content');
    }

    function applyProfileLikeState() {
        const box = profileViewContainer();
        if (!box) return;
        const paint = (btnId, countId, mine, count) => {
            const btn = box.querySelector('#' + btnId);
            const cnt = box.querySelector('#' + countId);
            if (cnt) cnt.textContent = String(count);
            if (!btn) return;
            btn.classList.toggle('on', mine === true);
            // 自己看自己时按钮是 disabled 的，title 由渲染时写死，这里不要覆盖
            if (!btn.disabled) btn.title = mine ? '取消' : (btnId === 'profile-like' ? '点个赞' : '送一朵花');
        };
        paint('profile-like', 'profile-like-count', profileLikeState.likeMine, profileLikeState.likeCount);
        paint('profile-flower', 'profile-flower-count', profileLikeState.flowerMine, profileLikeState.flowerCount);
    }

    // 这行提示只属于互动条/留言板，不碰卡片别处
    function setProfileActionMsg(text, isError) {
        const box = profileViewContainer();
        if (!box) return;
        const el = box.querySelector('#guestbook-msg');
        if (!el) return;
        el.textContent = text || '';
        el.classList.toggle('error', text ? isError !== false : false);
    }

    // 统一读响应体：**不能用 res.json()** —— 失败时后端可能返回 HTML 错误页，
    // 解析抛错就成了"页面异常"（工具全程盯着 Runtime.exceptionThrown）。
    function profileReadJson(res) {
        return res.text().then(t => {
            let data = null;
            try { data = t ? JSON.parse(t) : null; } catch (err) { data = null; }
            if (!res.ok) {
                const msg = (data && (data.error || data.msg)) || ('请求失败（HTTP ' + res.status + '）');
                return { ok: false, data: data, error: msg };
            }
            if (data === null) return { ok: false, data: null, error: '服务端返回了无法解析的数据' };
            return { ok: true, data: data, error: '' };
        }, () => ({ ok: false, data: null, error: '网络错误' }));
    }

    // 点赞 / 送花：真发 POST，成功后按响应里的 counts / mine 就地更新。
    // 失败 → 状态回滚 + 一行提示 + 按钮保持可重试（不是把卡片打崩，也不是假装成功）。
    function toggleProfileLike(kind) {
        const box = profileViewContainer();
        const username = profileLikeTarget;
        if (!box || !username) return;
        if (profileCardIsSelf) {
            setProfileActionMsg('不能给自己点赞。', true);
            return;
        }
        if (profileLikePending[kind]) return;         // 连点只算一次
        const mineKey = kind === 'like' ? 'likeMine' : 'flowerMine';
        const countKey = kind === 'like' ? 'likeCount' : 'flowerCount';
        const btn = box.querySelector(kind === 'like' ? '#profile-like' : '#profile-flower');
        if (btn && btn.disabled) return;
        const wasMine = profileLikeState[mineKey] === true;
        const wasCount = profileLikeState[countKey];
        const on = !wasMine;
        profileLikePending[kind] = true;
        // 乐观预演：只改数字与点亮态，好让点击立刻有反应（失败会回滚）
        profileLikeState[mineKey] = on;
        profileLikeState[countKey] = Math.max(0, wasCount + (on ? 1 : -1));
        applyProfileLikeState();
        setProfileActionMsg('', false);
        fetch('/api/profile/like', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username, kind: kind, on: on })
        }).then(res => profileReadJson(res)).then(r => {
            profileLikePending[kind] = false;
            if (!r.ok) {
                profileLikeState[mineKey] = wasMine;
                profileLikeState[countKey] = wasCount;
                applyProfileLikeState();
                setProfileActionMsg(r.error, true);
                return;
            }
            // 服务端说了算：counts / mine 一律以响应为准（别拿本地的乐观值当结果）
            const counts = r.data && r.data.counts;
            if (counts && typeof counts === 'object') {
                const n = Number(counts[kind]);
                if (isFinite(n) && n >= 0) profileLikeState[countKey] = Math.floor(n);
            }
            const mine = r.data && r.data.mine;
            if (mine && typeof mine === 'object') {
                profileLikeState[mineKey] = mine[kind] === true || mine[kind] === 1;
            }
            applyProfileLikeState();
            setProfileActionMsg('', false);
        }).catch(() => {
            profileLikePending[kind] = false;
            profileLikeState[mineKey] = wasMine;
            profileLikeState[countKey] = wasCount;
            applyProfileLikeState();
            setProfileActionMsg('网络错误，点赞没成功，可以再点一次。', true);
        });
    }

    // ==================== 第 3 批 B3-E：留言板 ====================
    //
    // 数据只放内存：留言板按"每次打开名片"重新拉一页（20 条），
    // 「加载更多」用 before_id 往前翻。删除按钮**只在服务端下发的 can_delete === true
    // 时渲染** —— 权限由服务端算，前端不猜（硬规矩第 4 条）。
    const guestbookState = {
        username: '', self: false, privateG: false, loaded: false,
        messages: [], total: 0, hasMore: false, beforeId: 0
    };

    function guestbookReset(username, self) {
        guestbookState.username = username || '';
        guestbookState.self = self === true;
        guestbookState.privateG = false;
        guestbookState.loaded = false;
        guestbookState.messages = [];
        guestbookState.total = 0;
        guestbookState.hasMore = false;
        guestbookState.beforeId = 0;
    }

    function guestbookEl(id) {
        const box = profileViewContainer();
        return box ? box.querySelector('#' + id) : null;
    }

    function guestbookItemHtml(msg) {
        // 只有服务端算出来 can_delete 才给删除按钮
        const del = (msg.can_delete === true)
            ? '<button type="button" class="guestbook-del" data-id="' + escapeHtml(String(msg.id)) + '" title="删除这条留言">删除</button>'
            : '';
        return '<div class="guestbook-item" data-id="' + escapeHtml(String(msg.id)) + '">'
            + '<p class="guestbook-text">' + escapeHtml(String(msg.content || '')) + '</p>'
            + '<div class="guestbook-meta">'
            + '<span class="guestbook-who">' + escapeHtml(String(msg.from_name || '匿名玩家')) + '</span>'
            + '<span class="guestbook-time">' + escapeHtml(guestbookTimeText(msg.created_at)) + '</span>'
            + del
            + '</div>'
            + '</div>';
    }

    function guestbookTimeText(value) {
        const n = Number(value);
        if (value && isFinite(n) && n > 0) {
            const d = new Date(n * 1000);
            if (!isNaN(d.getTime())) return d.toLocaleString();
        }
        return value ? String(value) : '';
    }

    function guestbookRenderList() {
        const list = guestbookEl('guestbook-list');
        if (list) list.innerHTML = guestbookState.messages.map(guestbookItemHtml).join('');
        guestbookUpdateChrome();
    }

    // 空占位文案：真没有留言 / 自己看自己，两种都要说清楚，**不留白**。
    // （未开放留言板那一路由 #guestbook-private 自己的块显示，不靠这里兜。）
    function guestbookEmptyText() {
        if (guestbookState.self) return '这是你自己的名片，还没有人给你留言';
        return '还没有留言';
    }

    // ⚠️ #guestbook-count 是**输入框的字数计**（契约 §3.5：N/100），
    // 所有权只属于 guestbookUpdateCount()。这里绝不能拿它显示留言条数 ——
    // 第一版就是这么写的，结果打开名片后计数被改成 "0/0"，玩家看到的是 `0/0` 而不是 `0/100`。
    // 留言条数改由「加载更多」按钮与空占位承载。
    function guestbookUpdateChrome() {
        const empty = guestbookEl('guestbook-empty');
        if (empty) {
            // 只在**一条都没显示**时用这行；有留言时它必须是收起的
            // （否则会出现"上面一条留言、下面写还没有留言"的自相矛盾）
            empty.textContent = guestbookEmptyText();
            empty.classList.toggle('hidden', !guestbookState.loaded || guestbookState.messages.length > 0);
        }
        const more = guestbookEl('guestbook-more');
        if (more) {
            more.classList.toggle('hidden', !guestbookState.hasMore);
            const shown = guestbookState.messages.length;
            const rest = Math.max(0, guestbookState.total - shown);
            more.textContent = rest > 0 ? ('加载更多（还有 ' + rest + ' 条）') : '加载更多';
        }
    }

    function guestbookUpdateCount() {
        const input = guestbookEl('guestbook-input');
        const count = guestbookEl('guestbook-count');
        if (!count) return;
        const n = input ? String(input.value || '').length : 0;
        count.textContent = n + '/' + GUESTBOOK_MAX;
        count.classList.toggle('over', n > GUESTBOOK_MAX);
    }

    // 输入区实时计数（N/100）。maxlength 已经挡住了溢出，这里主要是给玩家看到进度，
    // 并且**超出上限时当场拦住并提示**（契约 §3.2 第 2 条：不是静默丢弃）。
    function bindGuestbookInput() {
        const input = guestbookEl('guestbook-input');
        if (!input || input.dataset.gbBound === '1') return;
        input.dataset.gbBound = '1';
        input.addEventListener('input', () => {
            const n = String(input.value || '').length;
            guestbookUpdateCount();
            if (n > GUESTBOOK_MAX) {
                setProfileActionMsg('留言最多 ' + GUESTBOOK_MAX + ' 字，现在是 ' + n + ' 字。', true);
            } else {
                const msg = guestbookEl('guestbook-msg');
                if (msg && msg.classList.contains('error')) setProfileActionMsg('', false);
            }
        });
    }

    // 打开一张名片后的留言板准备：重置状态 → 拉第一页。
    // 接口挂了只写一行提示（输入区照旧可用，按钮可重试），**不抛异常、不重建整卡**。
    function prepareGuestbook(username, stats, self) {
        guestbookReset(username, self);
        guestbookState.privateG = !!(stats && Number(stats.show_guestbook) === 0);
        const priv = guestbookEl('guestbook-private');
        if (priv) priv.classList.toggle('hidden', !guestbookState.privateG);
        // 输入区：自己看自己 / 对方没开放留言板 → 收起（契约 §3.5）
        const form = profileViewContainer() ? profileViewContainer().querySelector('.guestbook-form') : null;
        if (form) form.classList.toggle('hidden', guestbookState.self || guestbookState.privateG);
        bindGuestbookInput();
        guestbookUpdateCount();
        if (!username) return;
        if (guestbookState.privateG) {
            // 未开放留言板：显示占位（不是留白），不去打扰接口
            guestbookState.loaded = true;
            guestbookUpdateChrome();
            guestbookRenderList();
            return;
        }
        if (guestbookState.self) {
            // 自己看自己：留言板照常可看（那是别人留给你的），但输入区已收起
            setProfileActionMsg('这是你自己的名片，不能给自己留言。', false);
        }
        loadGuestbookMore(true);
    }

    function loadGuestbookMore(isFirst) {
        const username = guestbookState.username;
        if (!username) return;
        const more = guestbookEl('guestbook-more');
        if (!isFirst) {
            if (more) { more.disabled = true; more.textContent = '加载中…'; }
        }
        // ⚠️ 第一页**不能带 before_id**（含 before_id=0）。服务端把它解析成整数 0，
        // 而游标语义是"取 id < before_id 的消息" —— 传 0 就等于一条都不要，
        // 表现是"打开名片永远看不到留言，刷新后照样空"（实测踩过：接口
        // /api/profile/messages?before_id=0 返回 total=1 但 messages=[]）。
        // 翻页才带，且只带上一页最后一条的 id。
        const cursor = (isFirst || !guestbookState.beforeId) ? '' : ('&before_id=' + guestbookState.beforeId);
        fetch('/api/profile/messages?username=' + encodeURIComponent(username)
            + '&limit=' + GUESTBOOK_PAGE + cursor)
            .then(res => profileReadJson(res))
            .then(r => {
                if (more) { more.disabled = false; more.textContent = '加载更多'; }
                if (!r.ok) {
                    // 接口未落地 / 出错：给一行可重试的提示，卡片其余部分照常。
                    // ⚠️ 这里**不动 #guestbook-count** —— 那是输入框的字数计（N/100），
                    // 显示成 '—' 会让玩家以为字数上限没了。
                    setProfileActionMsg(r.error + '（留言板暂时打不开）', true);
                    const empty = guestbookEl('guestbook-empty');
                    if (empty) { empty.textContent = '留言板暂时打不开'; empty.classList.remove('hidden'); }
                    const moreEl = guestbookEl('guestbook-more');
                    if (moreEl) moreEl.classList.add('hidden');
                    return;
                }
                const data = r.data || {};
                const list = Array.isArray(data.messages) ? data.messages : [];
                // 第一页覆盖，后续页追加（接口按 id 倒序给，越往后越旧）
                guestbookState.messages = isFirst ? list.slice() : guestbookState.messages.concat(list);
                const total = Number(data.total);
                guestbookState.total = (isFinite(total) && total >= 0) ? Math.floor(total) : guestbookState.messages.length;
                // 契约 §3.4：未开放时后端返回空数组 + guestbook_private = true
                guestbookState.privateG = data.guestbook_private === true;
                // has_more 也兜一层：只要"已显示的条数 < 总数"就必须还能翻下一页，
                // 否则后端漏发这个字段时，第 21 条留言就永远看不到了（本项目吃过"兜底
                // 分支把能用的东西报成不能用"的亏，这里反过来取"能翻就翻"）。
                const moreByCount = guestbookState.messages.length < guestbookState.total;
                guestbookState.hasMore = (data.has_more === true || moreByCount) && list.length > 0;
                // 下一页游标 = 本页最后一条（最旧的那条）的 id
                const last = guestbookState.messages[guestbookState.messages.length - 1];
                const lastId = last ? parseInt(last.id, 10) : 0;
                if (lastId > 0) guestbookState.beforeId = lastId;
                guestbookState.loaded = true;
                const priv = guestbookEl('guestbook-private');
                if (priv) priv.classList.toggle('hidden', !guestbookState.privateG);
                const form = profileViewContainer() ? profileViewContainer().querySelector('.guestbook-form') : null;
                if (form) form.classList.toggle('hidden', guestbookState.self || guestbookState.privateG);
                guestbookUpdateChrome();
                guestbookRenderList();
            })
            .catch(() => {
                if (more) { more.disabled = false; more.textContent = '加载更多'; }
                setProfileActionMsg('网络错误（留言板暂时打不开）', true);
            });
    }

    function sendGuestbookMessage() {
        const input = guestbookEl('guestbook-input');
        const btn = guestbookEl('guestbook-send');
        if (!input) return;
        if (profileCardIsSelf) {
            setProfileActionMsg('不能给自己留言。', true);
            return;
        }
        const raw = String(input.value || '');
        const content = raw.trim();
        if (!content) {
            setProfileActionMsg('留言内容不能为空。', true);
            return;
        }
        if (content.length > GUESTBOOK_MAX) {
            setProfileActionMsg('留言最多 ' + GUESTBOOK_MAX + ' 字，现在是 ' + content.length + ' 字。', true);
            return;
        }
        if (btn) { btn.disabled = true; btn.textContent = '发送中…'; }
        fetch('/api/profile/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: guestbookState.username, content: content })
        }).then(res => profileReadJson(res)).then(r => {
            if (btn) { btn.disabled = false; btn.textContent = '发表留言'; }
            if (!r.ok) {
                // 内容原样留在输入框里，改一改就能重发
                setProfileActionMsg(r.error, true);
                return;
            }
            const msg = (r.data && r.data.message) ? r.data.message : null;
            if (msg && msg.id !== undefined && msg.id !== null) {
                guestbookState.messages.unshift(msg);
                guestbookState.total += 1;
                guestbookState.loaded = true;
                input.value = '';
                guestbookUpdateCount();
                guestbookUpdateChrome();
                guestbookRenderList();
            }
            setProfileActionMsg('留言成功。', false);
        }).catch(() => {
            if (btn) { btn.disabled = false; btn.textContent = '发表留言'; }
            setProfileActionMsg('网络错误，留言没发出去，可以再试一次。', true);
        });
    }

    function deleteGuestbookMessage(id, container) {
        const mid = parseInt(id, 10);
        if (!mid) return;
        const btn = container ? container.querySelector('.guestbook-del[data-id="' + id + '"]') : null;
        if (btn) { btn.disabled = true; btn.textContent = '删除中…'; }
        fetch('/api/profile/message/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: mid })
        }).then(res => profileReadJson(res)).then(r => {
            if (!r.ok) {
                if (btn) { btn.disabled = false; btn.textContent = '删除'; }
                setProfileActionMsg(r.error, true);
                return;
            }
            // 就地移除这一条 —— 不重拉整页，也不重渲染整卡
            guestbookState.messages = guestbookState.messages.filter(m => String(m.id) !== String(id));
            guestbookState.total = Math.max(0, guestbookState.total - 1);
            guestbookUpdateChrome();
            guestbookRenderList();
            setProfileActionMsg('已删除。', false);
        }).catch(() => {
            if (btn) { btn.disabled = false; btn.textContent = '删除'; }
            setProfileActionMsg('网络错误，删除没成功。', true);
        });
    }

    // 统一的个人信息取数：username 为空 = 查当前登录用户（带分页），
    // 否则查指定账号（排行榜 / 对局内对手）。四个入口共用，字段不会各写一份。
    // opts.ids：是否在渲染结果里输出 `#profile-view-*` / `#profile-view-badges` 这套 id。
    // opts.friendRelation（2026-09-19 补）：这次渲染要按哪个关系态画「加好友 / 邀战」。
    //
    // ⚠️⚠️ 这个参数的**存在本身**就是修一个循环的根：查看面重渲染（那一趟专门为了把
    //    「邀战」画出来）走的是 `showUserProfile`，而它最终落回这里；本行以前**写死**
    //    'none' —— 于是"重渲染出来的卡"永远不带关系、永远没有「邀战」按钮，调用方看到
    //    "没有邀战按钮"又再重渲染一次 → **无限重渲染**（实测：8 秒 830 次，
    //    页面永远停在「加载中…」、零 JS 异常）。调用方现在把已经算出来的关系传进来，
    //    重渲染一趟就把「邀战」画出来，循环自然收敛。详见 showUserProfile 里那段。
    //
    // ⚠️ 2026-09-17 实测纠正：这套 id **原先在两个容器里都会输出** —— 本函数写死了
    // `ids: true`，而它有两个调用点：查看面（`showUserProfile`）与首页老战绩容器
    // （`showUserStats` → `#user-stats-content`）。同一文档里两个容器带同一批 id 时，
    // `document.getElementById` 只会拿到靠前的那个 —— 表现是「点了没反应」，
    // 正是本项目最难查的一类故障（第 1 批的注释曾误以为老容器只出 class）。
    // 当时没炸只是因为所有读取方都用容器内 scoped 查询（`container.querySelector`）。
    // 现在按调用方显式声明：**只有查看面出 id**。
    function fetchProfile(username, limit, opts) {
        const withIds = !!(opts && opts.ids);
        // 这次渲染按哪个关系态画按钮：由调用方给（见上面 opts.friendRelation 那段）。
        // 没给 = 'none'（首次打开时的默认，与加好友之前完全一样）。
        const relForRender = (opts && FRIEND_RELATIONS.indexOf(opts.friendRelation) >= 0)
            ? opts.friendRelation : 'none';
        const url = username
            ? ('/user_stats?limit=' + limit + '&username=' + encodeURIComponent(username))
            : ('/user_stats?limit=' + limit);
        // 先按账号名判断"这是不是自己"，好在取 /user_stats 之前就把自己那份完整徽章目录
        // （含未解锁）准备好 —— 顺序反了的话，名片会先渲染出"只有已解锁"的一版。
        const preSelf = (username === undefined || username === null || username === '')
            ? true : profileIsSelf(null, username);
        const badgesReady = preSelf
            ? ensureSelfBadges().then(() => profileSelfAchievements)
            : Promise.resolve(null);
        // 好友批：查看面那个「加好友 / 邀战」按钮要按**关系**变文案，而 /user_stats
        // 与 /api/profile 的响应里都没有 relation（本批没改后端）→ 单独拉一次
        // GET /api/friends，用 username 在本地比对（算法见 resolveFriendRelation）。
        // 拉失败（游客 401 / 接口还没上线）**不影响**名片渲染：resolveFriendRelation
        // 内部把失败兜成 'none'，按钮显示成「加好友」，点下去服务端再裁决。
        //
        // ⚠️⚠️ 这次取数**绝不能挡在名片渲染前面**（这是本批最容易犯错的一处）。
        //    第一版把它串进 Promise.all 等它，结果名片整体慢了一个 RTT ——
        //    profile_leaderboard_check 里「点开头像 → 立刻读名片」那几条正好卡在这个
        //    窗口上（#opponent-stats-content 还是「加载中…」），G3/G3d/G4/G6 时红时绿。
        //    现在的做法：**先按调用方给的关系渲染名片**（首次打开就是 'none'，和加好友
        //    之前完全一样快），拿到关系之后再就地改那一个按钮（applyProfileFriendRelation；
        //    只有"不是好友 → 好友"这种按钮数量变了的跃迁才重渲染一次 —— 那一趟会把
        //    已经算好的关系带下来，见本函数开头 opts.friendRelation 那段）。
        const statsPromise = fetch(url);
        return badgesReady.then(selfBadges =>
            statsPromise.then(resp => {
                if (!resp.ok) throw new Error('未登录或获取失败');
                return resp.json();
            }).then(data => {
                if (!data.stats) {
                    return { html: '<p>未找到战绩数据</p>', stats: null, history: [] };
                }
                const history = data.history || [];
                // 不带 username = 查自己；带 username 时按缓存的账号名比对
                const isSelf = (username === undefined || username === null || username === '')
                    ? true : profileIsSelf(data.stats);
                const html = renderUserStatsHTML(data.stats, history, {
                    ids: withIds,
                    canEdit: isSelf,
                    // 对方关了"公开对局历史"时接口给的是空数组，要靠开关区分
                    // 「真没有历史」和「没公开」
                    historyPrivate: !isSelf && Number(data.stats.show_history) === 0,
                    hasMore: history.length >= limit && limit < STATS_MAX_ROWS,
                    // 只有看自己时才给完整目录；看别人时上面的 Promise 直接给 null
                    badges: isSelf ? selfBadges : null,
                    self: isSelf,
                    // ⚠️ 这里用的是**调用方传来的关系**（首次打开是 'none'，重渲染那趟
                    //    带的是缓存里已经算好的关系）。以前写死 'none' = 重渲染永远
                    //    画不出「邀战」→ 无限重渲染，见本函数开头那段。
                    friendRelation: relForRender
                });
                return { html, stats: data.stats, history, isSelf: isSelf };
            })
        ).catch(err => {
            // statsPromise 不再挂在同一条链上，漏出去会变成"谁都没接"的 rejection
            // （控制台一条红字 + 卡片空白）；这里一并收口。
            statsPromise.catch(() => {});
            throw err;
        });
    }

    // 打开某个账号的个人信息查看面（排行榜点名字/头像、局内两个头像、查看对手战绩都走它）
    function showUserProfile(username) {
        if (!opponentStatsModal || !opponentStatsContent) return;
        closeOverlaysExcept('opponent-stats-modal');   // 别让编辑面/设置面压在查看面下面
        const title = document.getElementById('opponent-stats-title');
        if (title) title.textContent = (username ? username + ' 的个人信息' : '个人信息');
        opponentStatsModal.classList.remove('hidden');
        opponentStatsContent.innerHTML = '<p>加载中…</p>';
        currentProfileUsername = username || '';
        window.__viewedProfileName = currentProfileUsername;
        // 反作弊管理后台（2026-09-20）：管理员在个人信息卡上加一个「查后台」按钮。
        // ⚠️ 普通玩家这里 `battleshipAdmin` 存在但 `isAdmin()` 恒为 false →
        //    一个按钮都不加，也不发任何请求（普通玩家路径零开销）。
        //    真正的门禁仍在服务端；这里只是别让管理员为了查人再去翻列表。
        scheduleAdminEntry(username);
        // 好友批：记下"正在看谁" —— 点 #add-friend-btn / .fri-invite-btn 时要发给他。
        // 看自己时置空（自己那张卡上压根不渲染这两个按钮，置空是多一层保险）。
        const willBeSelf = (username === undefined || username === null || username === '')
            || profileIsSelf(null, username);
        currentFriendTarget = willBeSelf ? '' : currentProfileUsername;
        currentFriendRelation = 'none';
        // 这一帧要按哪个关系态画按钮。**在这个函数里只算一次**，下面 opts 与渲染完成后的
        // 分支都用它 —— 少一处"两份实现"（本项目第 10 节第 1 条）。
        // 首次打开时 currentFriendRelation 刚被上面重置成 'none'（语义与加好友之前一致）；
        // 重渲染那趟它是缓存里算好的真实关系（见下面那段 ⚠️⚠️）。
        const friendRelationForCard = (FRIEND_RELATIONS.indexOf(currentFriendRelation) >= 0)
            ? currentFriendRelation : 'none';
        fetchProfile(username, STATS_PAGE_SIZE, {
            ids: true,
            // ⚠️⚠️ 重渲染那趟**必须**把已经知道的关系带上（2026-09-19 修）。
            //    以前这里只有 { ids: true }，而 fetchProfile 内部把 friendRelation 写死成
            //    'none' → 重渲染出来的卡永远没有「邀战」按钮 → 调用方看到"没有邀战按钮"
            //    又再重渲染（reRenderProfileCard → showUserProfile → 本节）→
            //    **无限重渲染**：实测 8 秒 830 次 showUserProfile、网络请求刷屏，
            //    而页面上**零 JS 异常**，只剩 `#opponent-stats-content` 被反复重设成
            //    「加载中…」（T2l 现场就是这个形状）。
            //    带上 currentFriendRelation（首次打开时它刚被重置成 'none'，语义不变；
            //    重渲染那趟它是缓存里算好的真实关系）循环就收敛了。
            friendRelation: friendRelationForCard
        }).then(r => {
            // ⚠️ 这一段是**同步渲染**：从写 innerHTML 到把关系补到按钮上，中间不能被
            //    第二趟重渲染插进来（见 reRenderProfileCard 里的重入保护）。所以用一个
            //    try/finally 把"正在渲染"这个标识保证复位 —— 中途任何一处抛异常都不会
            //    把它永久卡在 true（那会让「邀战」再也补不出来）。
            profileCardRendering = true;
            try {
                opponentStatsContent.innerHTML = r.html;
                currentProfileStats = r.stats;
                // ⚠️ 重置成**这一帧渲染用的那个关系**，不是无条件 'none'（2026-09-19 修）。
                //    重渲染那趟带着 `friendRelation='friends'` 进来（就是上面 opts 里传的
                //    那个值），卡上的按钮就已经是「好友」了；这里再把它按 'none' 记一遍，
                //    等于让下面"现值优先"那条判断拿不到真值，又绕回重渲染。
                //    注意变量的作用域：`relForRender` 是 fetchProfile 内部的局部量，
                //    这里看不见（第一版就写成了它 → ReferenceError 被 .catch 收口，
                //    页面显示"获取个人信息失败：relForRender is not defined"）。
                //    所以这里用的是本函数自己的 friendRelationForCard（上面算的那一个）。
                currentFriendRelation = friendRelationForCard;
                // 第 3 批：互动条与留言板的当前目标 + 初始状态。
                // ⚠️ 全程**不重渲染整卡**：点赞就地改 DOM，留言只重画 #guestbook-list。
                // 重渲染会冲掉输入到一半的留言草稿与弹窗滚动位置（票面明确禁止）。
                profileLikeTarget = String((r.stats && r.stats.username) || username || '');
                profileCardIsSelf = r.isSelf === true;
                profileLikePending.like = false;
                profileLikePending.flower = false;
                profileLikeState.likeCount = r.stats ? profileLikeCount(r.stats, 'like') : 0;
                profileLikeState.flowerCount = r.stats ? profileLikeCount(r.stats, 'flower') : 0;
                profileLikeState.likeMine = r.stats ? profileLikeMine(r.stats, 'like') : false;
                profileLikeState.flowerMine = r.stats ? profileLikeMine(r.stats, 'flower') : false;
                bindHistoryButtons(opponentStatsContent, r.history, r.stats && r.stats.id);
                bindProfileCardButtons(opponentStatsContent);
                prepareGuestbook(profileLikeTarget, r.stats, profileCardIsSelf);
                // 好友批：名片已经画好了，**现在**才把与这个人的关系补到按钮上。
                // 顺序不能反：先算关系再画卡会让名片多等一个 RTT（见 fetchProfile 里那段）。
                // 已经算过的人（同一次会话里第二次打开他的名片）直接用缓存，不再打接口 ——
                // 靠的就是这份缓存，而不是一个全局哨兵（见 friendRelationCache 的注释）。
                if (!profileCardIsSelf && currentFriendTarget) {
                    const target = currentFriendTarget;
                    // ⚠️ 卡片上那个按钮**可能已经带着关系**（重渲染那条路现在会把缓存里的
                    //    关系直接画进 data-relation）→ 直接用现值，**不要**再走一遍
                    //    "算关系 → 发现没有邀战按钮 → 再重渲染"。
                    //    这条曾经是无限重渲染的另一半成因：重渲染那时画出来的卡**不带**关系，
                    //    于是每一趟都重走一遍（实测 8 秒 830 次，页面永远停在「加载中…」）。
                    const btnNow = document.getElementById('add-friend-btn');
                    const relOnBtn = (btnNow && btnNow.dataset) ? String(btnNow.dataset.relation || '') : '';
                    const cached = friendRelationCache.get(target);
                    if (FRIEND_RELATIONS.indexOf(relOnBtn) >= 0 && relOnBtn !== 'none') {
                        currentFriendRelation = relOnBtn;
                    } else if (cached !== undefined) {
                        applyProfileFriendRelation(cached);
                    } else {
                        resolveFriendRelation(target, false).then(rel => {
                            friendRelationCache.set(target, rel);
                            if (window.__viewedProfileName !== target) return;
                            applyProfileFriendRelation(rel);
                        }).catch(e => {
                            // 兜底：这段是"锦上添花"，绝不能让它的异常变成一条没人接的
                            // Uncaught (in promise)（那种错在页面上同样零提示）
                            console.warn('好友关系按钮更新失败（不影响名片）:', e && e.message);
                        });
                    }
                }
            } finally {
                profileCardRendering = false;
            }
        }).catch(err => {
            opponentStatsContent.innerHTML =
                '<p style="color:var(--danger);">获取个人信息失败：' + escapeHtml(err.message) + '</p>';
        });
    }
    window.showUserProfile = showUserProfile;

    // 显示个人战绩弹窗并请求数据。
    // 首页「个人战绩」看的其实就是自己那张名片 —— 但这里仍然渲染进它自己的容器
    // （#user-stats-content，只出 class 不出 id），因为 index.html 里那个入口与弹窗
    // 是老链路，另有回归工具盯着；两个容器同时带 #profile-view-* 会撞 id。
    function showUserStats() {
        if (!userStatsModal || !userStatsContent) {
            // 老容器没了（新版布局）→ 退回查看面看自己
            const myName = window.__USERNAME || '';
            if (myName) { showUserProfile(myName); return; }
            console.error('DOM元素不存在：userStatsModal 或 userStatsContent');
            return;
        }
        userStatsModal.classList.remove('hidden');
        userStatsContent.innerHTML = '<p>加载中...</p>';

        // 首页老战绩容器：**不**输出 #profile-view-* 那套 id（同文档撞 id 会让 getElementById 拿错）
        fetchProfile(null, statsHistoryLimit, { ids: false }).then(r => {
            userStatsContent.innerHTML = r.html;
            // innerHTML 赋值后节点已同步就绪，直接绑定即可
            // （原先用 setTimeout(..., 100) 等 DOM，纯属多余且可能被重建打断）
            bindHistoryButtons(userStatsContent, r.history, r.stats && r.stats.id);
        }).catch(err => {
            console.error('获取个人战绩失败:', err);
            userStatsContent.innerHTML = '<p style="color:red;">获取个人战绩失败：' + err.message + '</p>';
        });
    }

    // ==================== 编辑态（#profile-modal 里的 #profile-edit） ====================
    //
    // 解锁与否**只在服务端做最终裁决**：前端把未解锁项 disabled + title 写清条件，
    // 只是不让玩家白点一次，服务端仍然会把越权请求整次拒掉（400 + error）。
    const PROFILE_TAG_LIMIT = 3;
    let profileEditData = null;   // 编辑态当前这份数据（保存/取消都要用）

    function profileIsSelf(stats, username) {
        const name = (username !== undefined && username !== null && username !== '')
            ? String(username)
            : String((stats && stats.username) || '');
        return !!(profileSelfName && name && profileSelfName === name);
    }

    function setProfileSaveMsg(text, isError) {
        const el = document.getElementById('profile-save-msg');
        if (!el) return;
        el.textContent = text || '';
        el.style.color = text ? (isError ? 'var(--danger)' : 'var(--success)') : '';
    }

    function setProfileToggle(id, value) {
        const el = document.getElementById(id);
        if (el) el.checked = Number(value) === 1;
    }

    // 一排"白名单选项"按钮（底色 / 头像框）：选中态 + 未解锁的灰掉并写明条件
    function fillProfileOptionRow(selector, dataKey, catalogList, currentId) {
        const list = Array.isArray(catalogList) ? catalogList : [];
        document.querySelectorAll(selector).forEach(btn => {
            const id = btn.dataset[dataKey];
            const item = list.filter(t => t && t.id === id)[0];
            const locked = !!(item && item.unlocked === false);
            btn.classList.toggle('selected', id === currentId);
            btn.classList.toggle('locked', locked);
            btn.disabled = locked;
            if (locked) {
                btn.title = '未解锁：' + String(item.requirement || item.desc || '达成条件后解锁');
            } else {
                btn.removeAttribute('title');
            }
        });
    }

    function updateProfileTagCount() {
        const el = document.getElementById('profile-tag-count');
        if (!el) return;
        const n = document.querySelectorAll('#profile-tag-list .pf-opt[data-tag].selected').length;
        el.textContent = '已选 ' + n + ' / ' + PROFILE_TAG_LIMIT;
    }

    // 编辑态内的分类导航（名片 / 头像 / 称号 / 账号）
    function setProfileEditorPane(pane) {
        const name = pane || 'card';
        document.querySelectorAll('#profile-edit .pf-pane[data-pane]').forEach(p => {
            p.classList.toggle('hidden', p.dataset.pane !== name);
        });
        document.querySelectorAll('#profile-edit .pf-editor-nav-item[data-pane]').forEach(item => {
            item.classList.toggle('active', item.dataset.pane === name);
        });
        return name;
    }

    function setProfileMode(mode) {
        const want = (mode === 'edit') ? 'edit' : 'view';
        const modal = document.getElementById('profile-modal');
        const editBox = document.getElementById('profile-edit');
        if (editBox) editBox.classList.toggle('hidden', want !== 'edit');
        if (modal) {
            // 查看态长在另一个弹窗里（#opponent-stats-modal），所以回查看态 = 收起编辑面
            if (want === 'edit') modal.classList.remove('hidden');
            else modal.classList.add('hidden');
        }
        if (want === 'edit') setProfileEditorPane('card');
        return want;
    }
    window.setProfileMode = setProfileMode;

    function renderProfileEditor(data) {
        const s = data || {};
        profileEditData = s;
        // ⚠️ 必须**在这里**（每张卡渲染出来的那一刻）就把第四个开关补进去。
        // 只在 collectProfileEditorPayload() 里补过的第一版是错的：那个函数要等"保存"
        // 才跑，于是玩家打开编辑面看到的只有 3 个开关、第 4 个在人点保存之后才冒出来
        // ——实测就是这么翻车的（探针在打开编辑面后查 `#profile-show-guestbook` 为 null）。
        ensureGuestbookToggle();
        const catalog = (s.catalog && typeof s.catalog === 'object') ? s.catalog : (profileCatalog || {});
        const statusInput = document.getElementById('profile-edit-status');
        if (statusInput) {
            // maxlength 由 index.html 的控件属性负责（契约里是 30）
            statusInput.value = String(s.status_text || '');
        }
        const usernameEl = document.getElementById('profile-username');
        if (usernameEl) usernameEl.textContent = String(s.username || '');
        const signatureInput = document.getElementById('profile-signature');
        if (signatureInput) signatureInput.value = String(s.signature || '');
        const avatarEl = document.getElementById('profile-avatar');
        if (avatarEl) avatarEl.src = profileAvatarSrc(s);

        fillProfileOptionRow('#profile-bg-row .pf-bg', 'bg', catalog.card_bgs, profileBgId(s));
        fillProfileOptionRow('#profile-frame-row .pf-frame', 'frame', catalog.frames, profileFrameId(s));

        const currentTitle = String(s.title_id || '');
        const titleList = document.getElementById('profile-title-list');
        if (titleList) {
            const titles = Array.isArray(catalog.titles) ? catalog.titles : [];
            let html = '<button type="button" class="pf-opt' + (currentTitle ? '' : ' selected')
                + '" data-title="">不展示</button>';
            titles.forEach(t => {
                if (!t || !t.id) return;
                const locked = t.unlocked === false;
                const tip = locked ? '未解锁：' + String(t.requirement || t.desc || '达成条件后解锁') : '';
                html += '<button type="button" class="pf-opt'
                    + (t.id === currentTitle ? ' selected' : '') + (locked ? ' locked' : '') + '"'
                    + ' data-title="' + escapeHtml(String(t.id)) + '"'
                    + (locked ? ' disabled title="' + escapeHtml(tip) + '"' : '')
                    + '>' + escapeHtml(String(t.name || t.id)) + '</button>';
            });
            titleList.innerHTML = html;
        }

        const currentTags = (Array.isArray(s.tags) ? s.tags : [])
            .map(t => ((t && typeof t === 'object') ? t.id : t)).filter(Boolean);
        const tagList = document.getElementById('profile-tag-list');
        if (tagList) {
            const tags = Array.isArray(catalog.tags) ? catalog.tags : [];
            tagList.innerHTML = tags.map(t => {
                if (!t || !t.id) return '';
                const locked = t.unlocked === false;
                const tip = locked ? '未解锁：' + String(t.requirement || '达成条件后解锁') : '';
                return '<button type="button" class="pf-opt'
                    + (currentTags.indexOf(t.id) >= 0 ? ' selected' : '') + (locked ? ' locked' : '') + '"'
                    + ' data-tag="' + escapeHtml(String(t.id)) + '"'
                    + (locked ? ' disabled title="' + escapeHtml(tip) + '"' : '')
                    + '>' + escapeHtml(String(t.name || t.id)) + '</button>';
            }).join('');
        }
        updateProfileTagCount();

        setProfileToggle('profile-show-stats', profileToggleValue(s.show_stats, 1));
        setProfileToggle('profile-show-favcards', profileToggleValue(s.show_fav_cards, 1));
        setProfileToggle('profile-show-history', profileToggleValue(s.show_history, 0));
        // 第 3 批：留言板开关（**并入既有的 POST /api/profile/card**，保存载荷 8 → 9 字段）
        setProfileToggle('profile-show-guestbook', profileToggleValue(s.show_guestbook, 1));
        // 段位批：段位开关（同样并入同一个接口，载荷 9 → **10** 字段）。
        // 缺省 1（公开）—— 与表定义 `show_rank INTEGER DEFAULT 1` 一致。
        setProfileToggle('profile-show-rank', profileToggleValue(s.show_rank, 1));
        // 好友批：是否允许他人加我好友（决策④的"设置里可关"）。
        // ⚠️ 它**不是展示开关**（管的是社交权限，服务端也只下发给本人），
        //    但故意走同一条保存通道（`POST /api/profile/card`，载荷 10 → **11** 字段）。
        //    缺省 1 = 开放申请 —— 与表定义 `friend_requests_open INTEGER DEFAULT 1` 一致。
        setProfileToggle('profile-friend-requests', profileToggleValue(s.friend_requests_open, 1));
        return s;
    }
    window.renderProfileEditor = renderProfileEditor;

    // 第四个展示开关（开放留言板）。
    // ⚠️ 由 JS 注入而不是写在 index.html 里：本票的文件独占清单只有
    // `static/game.js` + `static/style.css`，加不了 index.html 那一行。
    // 注入是幂等的（已存在就返回），并且放在 `.pf-toggles` 里与另外三个**同一份** ——
    // 第 1 批定过「展示开关只在编辑面一份」，不许在设置页再放一个。
    // 运行期创建这点 dom_contract_check 认：它靠源码里的 `id="…"` 字面量判断。
    function ensureGuestbookToggle() {
        if (document.getElementById('profile-show-guestbook')) return;
        const box = document.querySelector('#profile-edit .pf-pane[data-pane="card"] .pf-toggles');
        if (!box) return;      // index.html 还没铺好这一区时静默跳过（缺开关比抛异常好）
        const label = document.createElement('label');
        label.innerHTML = '<input type="checkbox" id="profile-show-guestbook" checked>'
            + '<span>开放留言板（关闭后别人看不到留言，只能看到提示）</span>';
        // 段位批的「段位公开」现在直接写在 index.html 里。它是第 **5** 个开关，
        // 所以留言板要插在它**前面**（池子顺序 = 界面上看到的顺序，插到后面顺序就反了）。
        // ⚠️ 要比的是那个 `<label>` 的父节点，不是 `<input>` 的 —— input 的父节点是 label 自己，
        //    第一版就是这么写错的（结果插到了末尾，顺序断言当场抓到）。
        const rankBox = document.getElementById('profile-show-rank');
        const rankLabel = rankBox && rankBox.closest ? rankBox.closest('label') : null;
        if (rankLabel && rankLabel.parentNode === box) box.insertBefore(label, rankLabel);
        else box.appendChild(label);
    }

    // 编辑态当前选了什么 —— **必须把服务端要求的字段全发**（现在是 11 个）：
    // 服务端的校验缺字段直接 400 点名，不是"只写改动过的字段"那种局部更新接口。
    // ⚠️ 段位批把 9 加到 10（多了 `show_rank`）；好友批加到 **11**（多了
    //    `friend_requests_open`）—— 只加界面不加这里的话，开关点得动、保存直接 400，
    //    而且报错文案是「缺少字段 friend_requests_open」。
    function collectProfileEditorPayload() {
        const el = (id) => document.getElementById(id);
        const selTitle = document.querySelector('#profile-title-list .pf-opt[data-title].selected');
        const selBg = document.querySelector('#profile-bg-row .pf-bg[data-bg].selected');
        const selFrame = document.querySelector('#profile-frame-row .pf-frame[data-frame].selected');
        const tags = [].slice.call(document.querySelectorAll('#profile-tag-list .pf-opt[data-tag].selected'))
            .map(b => b.dataset.tag).filter(Boolean);
        const checked = (id, fallback) => {
            const box = el(id);
            return box ? (box.checked ? 1 : 0) : fallback;
        };
        ensureGuestbookToggle();
        return {
            title_id: selTitle ? (selTitle.dataset.title || '') : '',
            tags: tags,
            status_text: el('profile-edit-status') ? el('profile-edit-status').value : '',
            frame_id: selFrame ? selFrame.dataset.frame : 'none',
            card_bg_id: selBg ? selBg.dataset.bg : 'deep',
            show_stats: checked('profile-show-stats', 1),
            show_fav_cards: checked('profile-show-favcards', 1),
            show_history: checked('profile-show-history', 0),
            // 缺失时按 1（公开）—— 与表定义 `show_guestbook INTEGER DEFAULT 1` 一致
            show_guestbook: checked('profile-show-guestbook', 1),
            // 第 5 个开关（段位批）。缺省 1 = 公开，与 `show_rank INTEGER DEFAULT 1` 一致。
            show_rank: checked('profile-show-rank', 1),
            // 第 6 个开关（好友批）：**社交权限**，不是展示开关。缺省 1 = 开放申请，
            // 与 `friend_requests_open INTEGER DEFAULT 1` 一致。
            friend_requests_open: checked('profile-friend-requests', 1)
        };
    }

    // 打开编辑面：只有看自己才会走到这里（按钮只在看自己时渲染）。
    // 数据现拉 —— 不复用查看面那份，免得把脏状态带进编辑态。
    function openMyProfileEditor() {
        const modal = document.getElementById('profile-modal');
        // ★ 先把查看面（以及设置面）关掉：三者的 z-index 相同，不关的话编辑面会**藏在查看面下面**
        //（作者 2026-09-17 实测：「还得自己手动关掉个人信息窗口才能看到编辑资料的窗口」）。
        closeOverlaysExcept('profile-modal');
        return fetch('/api/profile').then(r => {
            if (!r.ok) throw new Error('未登录');
            return r.json();
        }).then(res => {
            if (!res || !res.profile) throw new Error('未登录');
            profileCatalog = res.profile.catalog || profileCatalog;
            profileSelfName = res.profile.username || profileSelfName;
            renderProfileEditor(res.profile);
            if (modal) modal.classList.remove('hidden');
            setProfileMode('edit');
            setProfileSaveMsg('');
            return res.profile;
        }).catch(err => {
            setProfileSaveMsg('打开编辑失败：' + err.message, true);
            if (typeof showMessage === 'function') showMessage('未登录，无法编辑个人信息', { type: 'warning' });
            return null;
        });
    }
    window.openMyProfileEditor = openMyProfileEditor;

    function cancelProfileEdit() {
        // 丢弃未保存的改动：不复用编辑态那份脏数据，重新拉一次
        profileEditData = null;
        setProfileSaveMsg('');
        setProfileMode('view');
        const name = currentProfileUsername || profileSelfName || '';
        if (name) showUserProfile(name);
        return true;
    }

    function saveProfileCard() {
        const payload = collectProfileEditorPayload();
        setProfileSaveMsg('保存中…');
        return fetch('/api/profile/card', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(r => r.json().catch(() => ({})).then(body => ({ ok: r.ok, body: body })))
            .then(({ ok, body }) => {
                if (!ok || !body || body.success !== true || !body.profile) {
                    // 未解锁的称号/边框等一律整次拒绝，把原因原样显示出来（不静默）
                    setProfileSaveMsg((body && body.error) || '保存失败', true);
                    return null;
                }
                profileCatalog = body.profile.catalog || profileCatalog;
                renderProfileEditor(body.profile);
                setProfileMode('view');
                setProfileSaveMsg('已保存');
                const name = currentProfileUsername || body.profile.username || '';
                if (name) showUserProfile(name);
                return body.profile;
            })
            .catch(err => {
                setProfileSaveMsg('保存失败：' + err.message, true);
                return null;
            });
    }
    window.saveProfileCard = saveProfileCard;

    // 主题预设 / 设置左导航 / 编辑面的事件绑定。只绑一次（init 幂等）。
    function bindProfileCardUI() {
        if (bindProfileCardUI.done) return;
        bindProfileCardUI.done = true;

        const themeGrid = document.getElementById('theme-preset-grid');
        if (themeGrid) {
            themeGrid.addEventListener('click', (e) => {
                const card = e.target && e.target.closest ? e.target.closest('.theme-card[data-preset]') : null;
                if (!card) return;
                applyThemePreset(card.dataset.preset);
            });
        }
        syncThemePresetUI();

        const settingsNav = document.querySelector('#settings-modal .settings-nav');
        if (settingsNav) {
            settingsNav.addEventListener('click', (e) => {
                const item = e.target && e.target.closest ? e.target.closest('.settings-nav-item[data-pane]') : null;
                if (!item) return;
                showSettingsPane(item.dataset.pane);
            });
        }

        const gotoAccount = document.getElementById('profile-goto-account');
        if (gotoAccount) gotoAccount.addEventListener('click', (e) => {
            e.preventDefault();
            setProfileMode('view');          // 先收起编辑面
            closeOverlaysExcept('settings-modal');   // 查看面也别留在设置面下面（同一个坑）
            openSettingsModal('acct');       // 再开到「账号与隐私」（改密码在那）
        });
        const gotoSelf = document.getElementById('settings-goto-profile');
        if (gotoSelf) gotoSelf.addEventListener('click', (e) => {
            e.preventDefault();
            if (settingsModal) settingsModal.classList.add('hidden');
            openMyProfileEditor();
        });

        const saveBtn = document.getElementById('profile-card-save');
        if (saveBtn) saveBtn.addEventListener('click', (e) => { e.preventDefault(); saveProfileCard(); });
        const cancelBtn = document.getElementById('profile-edit-cancel');
        if (cancelBtn) cancelBtn.addEventListener('click', (e) => { e.preventDefault(); cancelProfileEdit(); });

        // 静态的「编辑资料」（如果 T2 写进了 index.html），查看面里那份走上面的委托
        const staticEditBtn = document.getElementById('profile-edit-btn');
        if (staticEditBtn) staticEditBtn.addEventListener('click', (e) => {
            e.preventDefault();
            openMyProfileEditor();
        });

        const editBox = document.getElementById('profile-edit');
        if (editBox) {
            editBox.addEventListener('click', (e) => {
                const target = e.target;
                if (!target || !target.closest) return;
                const navItem = target.closest('.pf-editor-nav-item[data-pane]');
                if (navItem) { setProfileEditorPane(navItem.dataset.pane); return; }
                const titleBtn = target.closest('#profile-title-list .pf-opt[data-title]');
                if (titleBtn && !titleBtn.disabled) {
                    document.querySelectorAll('#profile-title-list .pf-opt[data-title]')
                        .forEach(b => b.classList.toggle('selected', b === titleBtn));
                    setProfileSaveMsg('');
                    return;
                }
                const tagBtn = target.closest('#profile-tag-list .pf-opt[data-tag]');
                if (tagBtn && !tagBtn.disabled) {
                    const chosen = document.querySelectorAll('#profile-tag-list .pf-opt[data-tag].selected');
                    if (!tagBtn.classList.contains('selected') && chosen.length >= PROFILE_TAG_LIMIT) {
                        setProfileSaveMsg('最多只能选 ' + PROFILE_TAG_LIMIT + ' 个标签', true);
                        return;
                    }
                    tagBtn.classList.toggle('selected');
                    setProfileSaveMsg('');
                    updateProfileTagCount();
                    return;
                }
                const bgBtn = target.closest('#profile-bg-row .pf-bg[data-bg]');
                if (bgBtn && !bgBtn.disabled) {
                    document.querySelectorAll('#profile-bg-row .pf-bg[data-bg]')
                        .forEach(b => b.classList.toggle('selected', b === bgBtn));
                    setProfileSaveMsg('');
                    return;
                }
                const frameBtn = target.closest('#profile-frame-row .pf-frame[data-frame]');
                if (frameBtn && !frameBtn.disabled) {
                    document.querySelectorAll('#profile-frame-row .pf-frame[data-frame]')
                        .forEach(b => b.classList.toggle('selected', b === frameBtn));
                    setProfileSaveMsg('');
                }
            });
        }

        // 查看面里的「编辑资料」用委托（整块 innerHTML 每次都被换掉）
        bindProfileCardButtons(opponentStatsContent);
    }
    bindProfileCardUI();

    function renderMatchDetailHTML(matchData, playerId) {
        const isWin = matchData.winner_id === playerId;
        const resultText = isWin ? '胜' : '负';
        const resultColor = isWin ? 'var(--success)' : 'var(--danger)';
        const timeText = matchData.timestamp ? new Date(matchData.timestamp * 1000).toLocaleString() : '';
        const aiTag = isAiOpponent(matchData, playerId) ? ' <span class="hist-tag hist-tag-dark">人机</span>' : '';
        // 之前这里写的是 winner_name || loser_name：赢的局 winner_name 就是自己，
        // 「对手」栏会显示成自己；现在按胜负取真正的一方。
        const opponentName = opponentDisplayName(matchData, playerId);
        const logs = matchData.logs || [];
        const logsHtml = logs.length
            ? logs.map(l => {
                const ts = l.ts ? new Date(l.ts * 1000).toLocaleTimeString() : '';
                const text = escapeHtml(l.text || '');
                return ts ? '[' + ts + '] ' + text : text;
            }).join('<br>')
            : '无局内日志';
        return '<div style="margin-bottom:16px;">'
            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
            + '<h3 style="margin:0;font-size:1.2em;">对局信息</h3>'
            + '<span style="font-size:0.9em;color:var(--muted);">' + escapeHtml(timeText) + '</span>'
            + '</div>'
            + '<div class="match-detail-info-grid">'
            + '<div class="match-detail-info-box">'
            + '<div class="match-detail-label">对手</div>'
            + '<div class="match-detail-value">' + escapeHtml(opponentName) + aiTag + '</div>'
            + '</div>'
            + '<div class="match-detail-info-box">'
            + '<div class="match-detail-label">结果</div>'
            + '<div class="match-detail-result" style="color:' + resultColor + ';">' + resultText + '</div>'
            + '</div>'
            + '</div>'
            + '<div class="match-detail-info-box">'
            + '<div class="match-detail-label">局内日志</div>'
            + '<div class="match-detail-logs">' + logsHtml + '</div>'
            + '</div>'
            + '</div>';
    }
    window.renderMatchDetailHTML = renderMatchDetailHTML;

    // 显示对局详情
    function showMatchDetail(matchData, playerId) {
        if (!matchDetailModal || !matchDetailContent) {
            console.error('DOM元素不存在：matchDetailModal 或 matchDetailContent');
            return;
        }
        matchDetailModal.classList.remove('hidden');
        matchDetailContent.innerHTML = renderMatchDetailHTML(matchData, playerId);
    }

    // 开始界面
    findMatchBtn.addEventListener('click', findMatch);
    aiMatchBtn.addEventListener('click', aiMatch);
    customRoomBtn.addEventListener('click', () => {
        switchScreen(customRoomScreen);
    });
    cancelMatchBtn.addEventListener('click', cancelMatch);
    // 排位那一套（段位批）：按钮与取消各绑一次（init 幂等，这里不会被绑两遍）
    if (rankedMatchBtn) rankedMatchBtn.addEventListener('click', rankedMatch);
    if (cancelRankedBtn) cancelRankedBtn.addEventListener('click', cancelRankedMatch);
    playAgainBtn.addEventListener('click', resetGame);

    // 返回主菜单按钮事件处理
    returnToMenuBtn.addEventListener('click', resetGame);

    // 自定义房间游戏界面
    customCreateRoomBtn.addEventListener('click', customCreateRoom);
if (copyInviteLinkBtn) copyInviteLinkBtn.addEventListener('click', copyInviteLink);
    customJoinRoomBtn.addEventListener('click', () => customRoomIdInput.classList.remove('hidden'));
    customConfirmJoinBtn.addEventListener('click', customJoinRoom);
    if (customCloseRoomBtn) customCloseRoomBtn.addEventListener('click', closeCustomRoom);
    backToMainBtn.addEventListener('click', () => {
        history.pushState({}, '', '/');
        switchScreen(startScreen);
        // 隐藏所有可能显示的元素
        customRoomIdInput.classList.add('hidden');
        customRoomInfo.classList.add('hidden');
    });

    // 战舰放置
    confirmShipsBtn.addEventListener('click', confirmShipPlacement);
    if (randomShipsBtn) {
        randomShipsBtn.addEventListener('click', randomizeShips);
    }

    // 猜拳选择
    rpsChoices.forEach(choice => {
        choice.addEventListener('click', () => handleRPSChoice(choice.dataset.choice));
    });

    // 排行榜返回按钮
    if (backFromLeaderboardBtn) backFromLeaderboardBtn.addEventListener('click', () => {
        history.pushState({}, '', '/');
        switchScreen(startScreen);
    });

    // 排行榜页签（段位批）：事件委托绑一次（页签条本身不会被重建，逐个别绑也行，
    // 但委托更耐改）。段位榜的数据只在这里触发 —— 点页签才拉。
    if (leaderboardTabs) {
        leaderboardTabs.addEventListener('click', (e) => {
            const btn = e.target && e.target.closest ? e.target.closest('.lb-tab[data-tab]') : null;
            if (!btn) return;
            setLeaderboardTab(btn.dataset.tab);
        });
    }

    // 大厅按钮事件绑定（2026-09-18 大厅批）
    if (joinLobbyBtn) joinLobbyBtn.addEventListener('click', joinLobbyMatch);
    if (leaveLobbyBtn) leaveLobbyBtn.addEventListener('click', leaveLobbyMatch);
    if (lobbyRankedBtn) lobbyRankedBtn.addEventListener('click', lobbyRankedMatch);
    if (lobbyRefreshBtn) lobbyRefreshBtn.addEventListener('click', refreshLobby);
    if (lobbyCreateRoomBtn) lobbyCreateRoomBtn.addEventListener('click', createLobbyRoom);
    if (lobbyChatSendBtn) lobbyChatSendBtn.addEventListener('click', sendLobbyChat);
    // 公屏输入框回车即发（没绑的话玩家按回车什么都不会发生）
    if (lobbyChatInput) lobbyChatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); sendLobbyChat(); }
    });
    // 首页的「游戏大厅」入口
    if (lobbyBtn) lobbyBtn.addEventListener('click', () => {
        history.pushState({}, '', '/lobby');
        showLobby();
    });
    // 列表用**事件委托**绑一次：内容每次 lobby_state 都会被整段重建，
    // 逐行绑监听会漏绑/泄漏（排行榜那边踩过同一个坑，见 bindLeaderboardUserClick）。
    if (lobbyPlayersList) {
        lobbyPlayersList.addEventListener('click', (e) => {
            const row = e.target && e.target.closest ? e.target.closest('.lobby-player') : null;
            if (!row) return;
            const username = row.dataset.username;
            if (!username) return;                       // 游客没有名片，点不开
            if (typeof window.showUserProfile === 'function') window.showUserProfile(username);
        });
    }
    if (lobbyRoomsList) {
        lobbyRoomsList.addEventListener('click', (e) => {
            const btn = e.target && e.target.closest ? e.target.closest('.lobby-room-join') : null;
            if (!btn) return;
            joinLobbyRoom(btn.dataset.room);
        });
    }
    if (backFromLobbyBtn) backFromLobbyBtn.addEventListener('click', () => {
        history.pushState({}, '', '/');
        switchScreen(startScreen);
    });

    // 登录/注册弹窗按钮事件绑定
    if (loginSubmitBtn) loginSubmitBtn.addEventListener('click', handleLoginSubmit);
    if (registerSubmitBtn) registerSubmitBtn.addEventListener('click', handleRegisterSubmit);
    if (loginModalClose) loginModalClose.addEventListener('click', () => {
        hideLogin();
        history.pushState({}, '', '/');
    });
    if (registerModalClose) registerModalClose.addEventListener('click', () => {
        hideRegister();
        history.pushState({}, '', '/');
    });

    // ESC键关闭弹窗
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (loginModal && !loginModal.classList.contains('hidden')) {
                hideLogin();
                history.pushState({}, '', '/');
            }
            if (registerModal && !registerModal.classList.contains('hidden')) {
                hideRegister();
                history.pushState({}, '', '/');
            }
        }
    });

    // 「结束战斗阶段」按钮的绑定统一在 setupPhaseButtons() 里做。
    // 这里原本还有一份 addEventListener(endBattlePhase)，导致每次点击发两次
    // enter_end_phase：第二次必然失败并弹出「当前不是你的战斗阶段」，纯粹是噪音。

    // 日志切换按钮
    if (toggleLogBtn) {
        toggleLogBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleGameLog();
        });
    }

    // 全局监听 header 中的链接以便做 SPA 跳转（防止完整页面刷新），同时支持登录/注册
    document.addEventListener('click', (e) => {
        const a = e.target.closest && e.target.closest('a');
        if (!a) return;
        const href = a.getAttribute('href');
        if (href === '/leaderboard') {
            e.preventDefault();
            history.pushState({}, '', '/leaderboard');
            showLeaderboard();
        } else if (href === '/login') {
            e.preventDefault();
            history.pushState({}, '', '/login');
            showLogin();
        } else if (href === '/register') {
            e.preventDefault();
            history.pushState({}, '', '/register');
            showRegister();
        } else if (href === '/lobby') {
            e.preventDefault();
            history.pushState({}, '', '/lobby');
            showLobby();
        }
    });

    // 监听浏览器后退/前进
    window.addEventListener('popstate', () => {
        if (window.location.pathname.startsWith('/leaderboard')) {
            showLeaderboard();
        } else if (window.location.pathname.startsWith('/login')) {
            showLogin();
        } else if (window.location.pathname.startsWith('/register')) {
            showRegister();
        } else if (window.location.pathname.startsWith('/lobby')) {
            showLobby();
        } else {
            // 默认回到首页
            switchScreen(startScreen);
        }
    });
}

// 创建房间
// 切换自定义房间选项显示
// 寻找匹配
function findMatch() {
    gameState.playerName = playerNameInput.value || '玩家';

    // 休闲与排位是**同一个队列**（服务端 `has_player_in_match_queue` 会拒掉第二个），
    // 所以开休闲排队前先把排位那套状态收干净，反之见 rankedMatch()。
    rankedQueuePending = false;
    resetRankedQueueUI();

    // 复用/建立连接（ensureSocket 内部保证不重复建连）
    ensureSocket();

    // 发送匹配请求（mode 明确发 'casual'：服务端把缺省/非法值也当 casual，这里写清楚更不容易漂）
    gameState.socket.emit('find_match', {
        player_name: gameState.playerName,
        mode: 'casual'
    }, (response) => {
        if (response.status === 'error') {
            showAlert(response.message);
        }
    });
}

/**
 * 排位排队 UI 复位：收起「正在寻找排位对手…」、把「排位对战」按钮放回来。
 *
 * ⚠️ **三条路径都要走到它**：取消成功、服务端拒绝（未登录 → `emit('error')`）、
 *    匹配成功。只做其中两条就会卡在「正在寻找」——而玩家看到的是
 *    「按一次之后再点也没反应」，属于本项目最难查的那类故障。
 */
function resetRankedQueueUI() {
    rankedQueuePending = false;
    if (rankedStatus) rankedStatus.classList.add('hidden');
    if (cancelRankedBtn) cancelRankedBtn.classList.add('hidden');
    if (rankedMatchBtn) rankedMatchBtn.classList.remove('hidden');
}

/**
 * 排位对战入口 `#ranked-match`。
 *
 * 与休闲匹配的区别只有入队时的 `mode: 'ranked'`（同一个队列、同一套配对逻辑）；
 * 但**排位必须登录** —— 游客点它会收到 `error`（文案「排位模式需要先登录」），
 * 前端收到后必须把按钮恢复，不能停在「正在寻找」。
 */
function rankedMatch() {
    gameState.playerName = playerNameInput.value || '玩家';
    const socket = ensureSocket();

    // 先把自己这一套摆好、把休闲那套收干净（两套状态不许同时挂着）
    rankedQueuePending = true;
    if (matchStatus) matchStatus.classList.add('hidden');
    if (findMatchBtn) findMatchBtn.classList.remove('hidden');
    if (rankedMatchBtn) rankedMatchBtn.classList.add('hidden');
    if (rankedStatus) rankedStatus.classList.remove('hidden');
    if (cancelRankedBtn) cancelRankedBtn.classList.remove('hidden');

    socket.emit('find_match', { player_name: gameState.playerName, mode: 'ranked' }, (response) => {
        // 服务端两条路都会走：ack 里 status:'error' + `emit('error')`。两边都复位才稳。
        if (response && response.status === 'error') {
            resetRankedQueueUI();
            showAlert(response.message);
        }
    });
}

/** 取消排位排队：无论服务端怎么答，本地都把 UI 复位（不许卡在"正在寻找"）。 */
function cancelRankedMatch() {
    if (!gameState.socket) { resetRankedQueueUI(); return; }
    gameState.socket.emit('cancel_match', {}, () => resetRankedQueueUI());
}

// ==================== 排行榜：战绩榜 / 段位榜两个页签（段位批） ====================

let leaderboardTab = 'record';       // 当前页签（'record' | 'ranked'）
let rankedFetchToken = 0;            // 段位榜请求令牌：切页签/重拉时作废上一次

/**
 * 切页签。**段位榜的数据只在这里（点页签时）才拉** ——
 * 页面加载、读秒、切到排行榜页都不拉（`/api/ranked_leaderboard` 要现算名次与船长池）。
 */
function setLeaderboardTab(tab) {
    const want = (tab === 'ranked') ? 'ranked' : 'record';
    leaderboardTab = want;
    if (leaderboardRecordBox) leaderboardRecordBox.classList.toggle('hidden', want !== 'record');
    if (leaderboardRankedBox) leaderboardRankedBox.classList.toggle('hidden', want !== 'ranked');
    if (leaderboardTabs) {
        [].slice.call(leaderboardTabs.querySelectorAll('.lb-tab')).forEach(b => {
            const on = b.dataset.tab === want;
            b.classList.toggle('active', on);
            b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
    }
    if (want === 'ranked') fetchRankedLeaderboard();
    return want;
}

/** 段位榜一行。高段位的行靠 CSS 加权（左侧色条 + 发光 + 更大的图标），见 style.css 第 29 节。 */
function rankedRowHtml(row) {
    const r = (row && typeof row === 'object') ? row : {};
    // `tier_index` 是服务端给的段位下标（0 二级水手 … 7 船长 / 8 大舰长），前端只做阈值比较。
    const idx = Number(r.tier_index);
    const tierIndex = isFinite(idx) ? idx : 0;
    // ⚠️ 顶端那一档是**船长及以上（≥7）**，不是只有大舰长：本服 `ADMIRAL_MIN_CAPTAINS=50`
    //    意味着现在没人能到大舰长，只认 8 的话"高段位更重"在最常见的情况（船长）根本不生效。
    const top = (tierIndex >= RANK_CAPTAIN_TIER_INDEX) || r.is_admiral === true;
    const high = !top && tierIndex >= 6;                // 轮机长 = 中间那一档
    // 图标尺寸是"行有多重"的一部分（作者要求段位高低一眼可辨）。
    // ⚠️ 这里传像素给 SVG，不动任何既有元素的盒模型尺寸。
    const size = top ? 34 : (high ? 28 : 20);
    const cls = 'ranked-row' + (top ? ' top-tier' : (high ? ' high-tier' : ''));
    const username = String(r.username || '');
    const avatar = r.avatar ? String(r.avatar) : '/static/avatars/default.png';
    return '<tr class="' + cls + '" data-tier="' + escapeHtml(String(r.tier_id || '')) + '"'
        + ' data-tier-index="' + escapeHtml(String(tierIndex)) + '">'
        + '<td class="ranked-pos">' + escapeHtml(String(Number(r.position) || 0)) + '</td>'
        + '<td class="leaderboard-user-cell">'
        + '<button type="button" class="leaderboard-user" data-username="' + escapeHtml(username) + '"'
        + ' title="点击查看个人信息">'
        + '<img class="leaderboard-avatar" src="' + escapeHtml(avatar) + '" alt=""'
        + ' onerror="this.onerror=null;this.src=\'/static/avatars/default.png\'">'
        + '<span class="leaderboard-name">' + escapeHtml(username || '未知玩家') + '</span>'
        + '</button></td>'
        + '<td class="ranked-tier"><span class="ranked-tier-icon">' + rankIconMarkup(r.tier_id, size) + '</span>'
        + '<span class="ranked-label">' + escapeHtml(rankLabelOf(r)) + '</span></td>'
        + '<td class="ranked-points">' + escapeHtml(String(Number(r.points) || 0)) + '</td>'
        + '<td class="ranked-record">' + escapeHtml(String(Number(r.ranked_wins) || 0)) + ' 胜 '
        + escapeHtml(String(Number(r.ranked_losses) || 0)) + ' 负</td>'
        + '</tr>';
}

/**
 * 渲染段位榜。
 * ⚠️ 「先清空再填充」的渲染必须先校验数据、失败时**保留上一帧**
 *    （`updateHandUI` 那条教训）：所以这里清空之前先把新表拼成一个字符串，
 *    数据形状不对就原样返回，只在错误条上说明。
 */
function renderRankedTable(data) {
    if (!rankedTableBody) return;
    const rows = (data && Array.isArray(data.leaderboard)) ? data.leaderboard : null;
    const keepPrevious = () => {
        if (!rankedTableBody.querySelector('.ranked-row')) {
            rankedTableBody.innerHTML = '<tr class="ranked-empty"><td colspan="5">段位榜暂时取不到</td></tr>';
        }
    };
    if (!rows) {
        keepPrevious();
        if (rankedError) {
            rankedError.classList.remove('hidden');
            rankedError.textContent = '段位榜数据异常（接口没给 leaderboard 数组）';
        }
        return;
    }
    if (!rows.length) {
        rankedTableBody.innerHTML = '<tr class="ranked-empty"><td colspan="5">还没有人打过排位</td></tr>';
        return;
    }
    rankedTableBody.innerHTML = rows.map(rankedRowHtml).join('');
    bindRankedUserClick();
}

/** 段位榜取数。先渲染「加载中…」再异步取（弹窗可见 ≠ 内容就绪）。 */
function fetchRankedLeaderboard() {
    if (!rankedTableBody) return Promise.resolve();
    const token = ++rankedFetchToken;
    if (rankedError) { rankedError.classList.add('hidden'); rankedError.textContent = ''; }
    rankedTableBody.innerHTML = '<tr class="ranked-loading"><td colspan="5">加载中…</td></tr>';
    return fetch('/api/ranked_leaderboard?limit=100&offset=0', { headers: { 'Accept': 'application/json' } })
        .then(resp => {
            if (!resp.ok) throw new Error('网络错误 ' + resp.status);
            return resp.json();
        })
        .then(data => {
            if (token !== rankedFetchToken) return;      // 已经被后一次请求作废
            renderRankedTable(data);
        })
        .catch(err => {
            if (token !== rankedFetchToken) return;
            if (!rankedTableBody.querySelector('.ranked-row')) {
                rankedTableBody.innerHTML = '<tr class="ranked-empty"><td colspan="5">段位榜暂时取不到</td></tr>';
            }
            if (rankedError) {
                rankedError.classList.remove('hidden');
                rankedError.textContent = '无法加载段位榜：' + err.message;
            }
        });
}

/** 段位榜行点击：与战绩榜同一套（事件委托只绑一次，表会被整段重建）。 */
function bindRankedUserClick() {
    if (!rankedTableBody || rankedTableBody.dataset.userClickBound === '1') return;
    rankedTableBody.dataset.userClickBound = '1';
    rankedTableBody.addEventListener('click', (e) => {
        const btn = e.target && e.target.closest ? e.target.closest('.leaderboard-user') : null;
        if (!btn) return;
        const username = btn.dataset.username;
        if (!username) return;
        if (typeof window.showUserProfile === 'function') window.showUserProfile(username);
    });
}

// 人机对战
function aiMatch() {
    gameState.playerName = playerNameInput.value || '玩家';

    // 复用/建立连接（ensureSocket 内部保证不重复建连）
    ensureSocket();

    // 人机难度：easy = 电脑不出魔法卡（新手保底），normal / hard = 电脑会出牌
    const difficultyEl = document.getElementById('ai-difficulty');
    const difficulty = (difficultyEl && difficultyEl.value) || 'normal';

    // 发送人机对战请求
    gameState.socket.emit('create_ai_room', {
        player_name: gameState.playerName,
        difficulty: difficulty
    }, (response) => {
        if (response.status === 'success') {
            gameState.roomId = response.room_id;
            // 自动加入创建的人机对战房间
            gameState.socket.emit('join_room', {
                room_id: gameState.roomId,
                player_name: gameState.playerName
            }, (joinResponse) => {
                if (joinResponse.status === 'success') {
                    gameState.playerId = joinResponse.player_id;
                    // 不再直接跳战斗界面：由服务端 game_state(placing_ships)
                    // 驱动「匹配成功 -> 布船 -> 猜拳 -> 战斗」，与普通匹配一致
                } else {
                    showAlert(joinResponse.message);
                }
            });
        } else {
            showAlert(response.message);
        }
    });
}

// 取消匹配
function cancelMatch() {
    if (gameState.socket) {
        gameState.socket.emit('cancel_match', {}, (response) => {
            if (response.status === 'success') {
                matchStatus.classList.add('hidden');
            }
        });
    }
}

// 邀请链接：前端早就有 ?room=XXXX 的自动入房逻辑，但一直没有任何入口生成它。
// 复制失败（非 HTTPS / 老浏览器 / 无权限）时降级成 prompt 让玩家手动复制。
function copyInviteLink() {
    const roomId = gameState.roomId || (customCurrentRoomId && customCurrentRoomId.textContent) || '';
    if (!roomId) {
        if (inviteLinkMsg) inviteLinkMsg.textContent = '还没有房间号，请先创建房间';
        return;
    }
    const url = window.location.origin + window.location.pathname + '?room=' + encodeURIComponent(roomId);

    const done = (ok) => {
        if (!inviteLinkMsg) return;
        inviteLinkMsg.textContent = ok ? '已复制！发给好友即可直接入房' : '复制失败，请手动复制上面的链接';
        setTimeout(() => { if (inviteLinkMsg) inviteLinkMsg.textContent = ''; }, 4000);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => done(true)).catch(() => {
            window.prompt('复制下面的邀请链接发给好友：', url);
            done(false);
        });
    } else {
        window.prompt('复制下面的邀请链接发给好友：', url);
        done(false);
    }
}

// 自定义房间游戏 - 创建房间
function customCreateRoom() {
    // 名称由服务端取登录账号名（游客默认），不再让玩家手输
    // 等待Socket连接成功后再发送创建房间请求（复用已有连接）
    onSocketReady((socket) => {
        socket.emit('create_room', {}, (response) => {
            if (response.status === 'success') {
                gameState.roomId = response.room_id;
                customCurrentRoomId.textContent = gameState.roomId;
                customRoomInfo.classList.remove('hidden');

                // 自动加入创建的房间（名称用登录账号名）
                socket.emit('join_room', {
                    room_id: gameState.roomId
                }, (joinResponse) => {
                    if (joinResponse.status === 'success') {
                        gameState.playerId = joinResponse.player_id;
                    } else {
                        showAlert(joinResponse.message);
                    }
                });
            }
        });
    });
}

// 自定义房间游戏 - 加入房间
function customJoinRoom() {
    const roomId = customRoomCodeInput.value.trim();
    if (!roomId) return;

    const socket = ensureSocket();

    socket.emit('join_room', {
        room_id: roomId
    }, (response) => {
        if (response.status === 'success') {
            gameState.roomId = roomId;
            gameState.playerId = response.player_id;
            customCurrentRoomId.textContent = roomId;
            customRoomInfo.classList.remove('hidden');
        } else {
            showAlert(response.message);
        }
    });
}

// 解散自己主持的、还没开打的房（2026-09-18 大厅批补的出口）。
//
// 背景：等待房既不会自动回收（服务端 _WAITING_ROOM_TTL = 1 小时），玩家此前也没有
// 任何主动解散的入口 —— 建错了只能干等一小时，大厅列表里还会一直挂着。
// 服务端会校验「房内恰好 1 人且就是调用者自己」，所以这里不需要做权限判断。
function closeCustomRoom() {
    const roomId = gameState.roomId
        || (customCurrentRoomId ? customCurrentRoomId.textContent.trim() : '');
    if (!roomId) return;
    onSocketReady((socket) => {
        socket.emit('close_room', { room_id: roomId }, (response) => {
            if (!response || response.status !== 'success') {
                showAlert((response && response.message) || '解散房间失败');
                return;
            }
            gameState.roomId = null;
            gameState.playerId = null;
            if (customRoomInfo) customRoomInfo.classList.add('hidden');
            if (customRoomIdInput) customRoomIdInput.classList.add('hidden');
            if (customCloseRoomMsg) customCloseRoomMsg.textContent = '';
            if (customCurrentRoomId) customCurrentRoomId.textContent = '';
            showMessage('房间已解散');
        });
    });
}

// 加入房间
// 设置Socket监听器
function setupSocketListeners() {
    const socket = gameState.socket;

    socket.on('connect', () => {
        console.log('Connected to server');
    });

    // 匹配相关事件处理
    socket.on('match_queued', (response) => {
        console.log('已加入匹配队列:', response);
        // ⚠️ 排位与休闲**共用这一个事件**，靠 payload 里的 `mode` 区分：
        //    排位时不能再显示「正在寻找匹配...」（那会让玩家以为点的是休闲），
        //    两条状态互斥，进一个就清另一个。
        const isRanked = !!(response && response.mode === 'ranked');
        if (isRanked) {
            rankedQueuePending = true;
            if (matchStatus) matchStatus.classList.add('hidden');
            if (findMatchBtn) findMatchBtn.classList.remove('hidden');
            if (rankedStatus) rankedStatus.classList.remove('hidden');
            if (cancelRankedBtn) cancelRankedBtn.classList.remove('hidden');
            if (rankedMatchBtn) rankedMatchBtn.classList.add('hidden');
        } else {
            matchStatus.classList.remove('hidden');
            resetRankedQueueUI();
        }
        // 大厅按钮同步（服务端没有 lobby_joined/lobby_left 这类事件）
        if (joinLobbyBtn) joinLobbyBtn.classList.add('hidden');
        if (lobbyRankedBtn) lobbyRankedBtn.classList.add('hidden');
        if (leaveLobbyBtn) leaveLobbyBtn.classList.remove('hidden');
    });

    socket.on('match_canceled', (response) => {
        console.log('匹配已取消:', response);
        matchStatus.classList.add('hidden');
        resetRankedQueueUI();          // 排位那套也要复位（否则按钮永远回不来）
        if (joinLobbyBtn) joinLobbyBtn.classList.remove('hidden');
        if (leaveLobbyBtn) leaveLobbyBtn.classList.add('hidden');
        if (lobbyRankedBtn) lobbyRankedBtn.classList.remove('hidden');
    });

    // ---- 大厅（2026-09-18 大厅批，契约见 docs/LOBBY_2026_09_18.md §1.2）----
    // lobby_hello 只发给刚订阅的那个连接，带的是**我自己的身份键**。
    // lobby_state 是一条广播（服务端不可能逐人改 is_me），所以"我"由前端比对。
    socket.on('lobby_hello', (data) => {
        gameState.lobbyKey = (data && data.key) ? String(data.key) : null;
        gameState.lobbySubscribed = true;
        if (gameState.lobbyState) renderLobbyState(gameState.lobbyState);
    });
    socket.on('lobby_state', (state) => {
        renderLobbyState(state);
    });
    socket.on('lobby_chat_history', (data) => {
        // ⚠️ 用合并（只补缺的）而不是"清空重铺"：实时消息可能已经先到了
        applyLobbyChatHistory((data && data.messages) || []);
    });
    socket.on('lobby_chat', (item) => {
        appendLobbyChat(item);
    });

    socket.on('game_state', (data) => {
        console.log('Game state received:', data);
        // 这一局是不是排位（段位批）：服务端在 `game_state` 里带 `ranked` / `mode`，
        // 重连快照也带（否则重连之后不知道自己在打排位）。前端只用它做展示判断，
        // 加减分的门槛完全在服务端。
        gameState.ranked = !!data.ranked;
        gameState.mode = String(data.mode || (data.ranked ? 'ranked' : 'casual'));
        // 隐藏所有屏幕和信息面板
        customRoomInfo.classList.add('hidden');
        customRoomIdInput.classList.add('hidden');
        // 屏清单一律走 hideAllScreens()（唯一来源）。这里原先是手抄的，漏了
        // lobbyScreen / leaderboardScreen —— 在大厅点人机对战会两个屏同时 active。
        hideAllScreens();

        // 保存玩家名称和对手名称（支持多种字段名）
        const playerNameFromData = data.player_name || data.playerName || data.player || null;
        if (playerNameFromData) {
            gameState.playerName = playerNameFromData;
            if (myUsernameInfo) myUsernameInfo.textContent = playerNameFromData;
        }

        const oppNameFromData = data.opponent_name || data.opponentName || data.opponent || null;
        if (oppNameFromData) {
            gameState.opponentName = oppNameFromData;
            if (opponentUsernameInfo) {
                opponentUsernameInfo.textContent = oppNameFromData;
                showOpponentStatsBtn && (showOpponentStatsBtn.style.display = 'inline-block');
            }
            updateMyAvatarInGame();
            updateOpponentAvatarInGame(oppNameFromData);
        } else {
            // 如果没有从当前数据里获得对手名，尝试从 gameState 中恢复（有可能之前已设置）
            if (gameState.opponentName) {
                if (opponentUsernameInfo) opponentUsernameInfo.textContent = gameState.opponentName;
                showOpponentStatsBtn && (showOpponentStatsBtn.style.display = 'inline-block');
            } else {
                if (opponentUsernameInfo) opponentUsernameInfo.textContent = '';
                showOpponentStatsBtn && (showOpponentStatsBtn.style.display = 'none');
            }
        }

        // 设置玩家ID
        if (data.player_id) {
            gameState.playerId = data.player_id;
            console.log('设置playerId为:', gameState.playerId);
        }

        // 掉线重连准备：记录对局上下文并按需领取重连 token
        if (data.room_id && data.player_id) {
            gameState.inRoom = true;
            saveActiveGame(data.room_id, data.player_id);
            if (!gameState.reconnectToken) requestReconnectToken(data.room_id, data.player_id);
        }

        // 显示对手战绩弹窗并请求数据
        // 2026-09-17：改为走统一的个人信息面板（头像 / 个性签名 / 排行榜名次 /
        // 胜率 / 历史战绩 + 对局详情），而不是原来那 5 行裸表格。
        function showOpponentStats() {
            if (!gameState.opponentName) return;
            if (typeof window.showUserProfile === 'function') {
                window.showUserProfile(gameState.opponentName);
            }
        }

        // 将 showOpponentStats 暴露为全局，供 bindEventListeners 引用（修复作用域崩溃）
        window.showOpponentStats = showOpponentStats;

        switch (data.state) {
            case 'waiting':
                // 只有当游戏是从自定义房间创建或加入时，才显示自定义房间游戏界面
                // 匹配游戏不应该显示这个界面
                // 显示导航栏
                if (gameNav) gameNav.style.display = 'block';
                break;
            case 'placing_ships':
                console.log('Switching to ship placement screen');
                clearGameLogs();   // 新一局：日志从零开始

                // 设置playerId（使用socket.id）
                if (gameState.socket && !gameState.playerId) {
                    gameState.playerId = gameState.socket.id;
                    console.log('设置playerId为:', gameState.playerId);
                }

                // 隐藏导航栏
                if (gameNav) gameNav.style.display = 'none';

                // 显示匹配成功界面
                matchSuccessScreen.classList.add('active');

                // 显示对手信息
                opponentInfo.textContent = gameState.opponentName;
                // 顺手把对手的称号 / 标签 / 等级 / 段位显示出来（异步取公开的 /user_stats，
                // 与名片同一份数据源；取不到就留空，绝不影响开局倒计时）
                showOpponentChips(gameState.opponentName);
                // 自己的段位（页面加载时已经取过一次并缓存，这里不新拉接口）
                showMyRankChip();

                // 开始5秒倒计时
                let countdown = 5;
                countdownTimer.textContent = countdown;

                // 初始进度为100%
                const countdownFill = countdownBar.querySelector('.countdown-fill');
                countdownFill.style.width = '100%';

                // 每秒更新一次，确保数字和进度条完全同步
                const countdownInterval = setInterval(() => {
                    countdown--;
                    countdownTimer.textContent = countdown;

                    // 直接设置进度条宽度，与当前倒计时数字完全对应
                    const progress = (countdown / 5) * 100;
                    countdownFill.style.width = `${progress}%`;

                    // 倒计时结束，进入战舰放置界面
                    if (countdown <= 0) {
                        clearInterval(countdownInterval);

                        // 直接进入放置战舰界面
                        matchSuccessScreen.classList.remove('active');
                        shipPlacementScreen.classList.add('active');
                        initBoard(playerBoard, true);
                        // 确保界面正确切换。屏走 active，只有面板类容器用 hidden。
                        startScreen.classList.remove('active');
                        customRoomScreen.classList.remove('active');
                        matchStatus.classList.add('hidden');
                        // 保存房间ID
                        if (data.room_id) {
                            gameState.roomId = data.room_id;
                        }
                    }
                }, 1000);
                break;
            case 'rock_paper_scissors':
                // 隐藏导航栏
                if (gameNav) gameNav.style.display = 'none';
                rpsScreen.classList.add('active');
                rpsRound.textContent = data.round || 1;
                rpsResult.classList.add('hidden');
                break;
            // 在setupSocketListeners的game_state事件处理中添加
            case 'attacking':
                // 隐藏导航栏
                if (gameNav) gameNav.style.display = 'none';
                gameScreen.classList.add('active');
                gameRound.textContent = data.round || 1;
                gameState.currentPhase = data.current_phase || 'preparation';
                gameState.currentAttacker = data.current_attacker;
                // 记录攻击顺序（[先手, 后手]），供「是否先手」类判定使用
                if (Array.isArray(data.attack_order) && data.attack_order.length) {
                    gameState.attackOrder = data.attack_order;
                }
                initGameBoards();
                updateTurnIndicator(data.current_attacker, data.attacks_remaining);
                updatePhaseUI(); // 确保调用阶段UI更新
                break;
            case 'game_over':
                // 显示导航栏
                if (gameNav) gameNav.style.display = 'block';
                gameOverScreen.classList.add('active');
                // 根据胜利原因显示不同的提示
                if (data.winner === gameState.playerId) {
                    if (data.reason === 'surrender') {
                        gameResult.textContent = '对方已投降，你获胜了！';
                    } else if (data.reason === 'opponent_disconnected') {
                        gameResult.textContent = '对手掉线超时，你获胜了！';
                    } else {
                        gameResult.textContent = '恭喜你获胜了！';
                    }
                } else {
                    gameResult.textContent = '很遗憾，你输了。';
                }
                clearActiveGame();
                break;
            default:
                console.error('Unknown game state:', data.state);
                // 显示导航栏
                if (gameNav) gameNav.style.display = 'block';
                roomInfo.classList.remove('hidden');
                currentRoomId.textContent = gameState.roomId;
                roomInfo.querySelector('.waiting-message').textContent = '未知游戏状态，请刷新页面';
        }
    });

    // ===== 掉线/重连（2026-09-07 新增）=====
    socket.on('connect', () => {
        const active = loadActiveGame();
        if (active && active.room_id && active.player_id) {
            console.log('尝试自动重连对局:', active.room_id);
            socket.emit('rejoin_room', {
                room_id: active.room_id,
                player_id: active.player_id,
                token: gameState.reconnectToken || active.token || ''
            }, (resp) => {
                if (resp && resp.status === 'error') console.log('重连失败:', resp.message);
            });
        }
    });
    socket.on('resume_game', (data) => {
        console.log('服务端提示恢复对局:', data);
        if (data && data.room_id && data.player_id) {
            saveActiveGame(data.room_id, data.player_id);
            socket.emit('rejoin_room', {
                room_id: data.room_id,
                player_id: data.player_id,
                token: (gameState.reconnectToken || (loadActiveGame() && loadActiveGame().token) || '')
            }, (resp) => {
                if (resp && resp.status === 'error') console.log('恢复对局失败:', resp.message);
            });
        }
    });
    socket.on('reconnect_token', (data) => {
        if (data && data.token) {
            gameState.reconnectToken = data.token;
            const g = loadActiveGame();
            if (g && g.room_id) saveActiveGame(g.room_id, g.player_id);
        }
    });
    socket.on('opponent_disconnected', (data) => {
        console.log('对手掉线:', data);
        showOpponentGoneBanner(data.deadline || (Date.now() / 1000 + (data.seconds || 30)));
        showMessage('对手已掉线，等待重连…');
    });
    socket.on('opponent_reconnected', () => {
        console.log('对手重连');
        hideOpponentGoneBanner();
        showMessage('对手已重连，对局继续');
    });
    socket.on('game_canceled', (data) => {
        console.log('对局取消:', data);
        hideOpponentGoneBanner();
        clearActiveGame();
        if (data && data.message) showAlert(data.message);
        setTimeout(() => resetGame(), 1500);
    });
    socket.on('reconnect_warning', (data) => {
        console.log('掉线警告:', data);
        clearActiveGame();
        if (data && data.message) showAlert(data.message);
        setTimeout(() => resetGame(), 2000);
    });
    socket.on('room_sync', (data) => {
        console.log('对局快照恢复:', data);
        applyRoomSync(data);
    });

    socket.on('rps_result', (result) => {
        console.log('RPS result:', result);
        rpsResult.classList.remove('hidden');
        if (result.status === 'tie') {
            rpsResult.textContent = result.message;
        } else {
            const winnerName = result.winner === gameState.playerId ? '你' : '对手';
            rpsResult.textContent = `猜拳结果：你选择了${getRPSName(result.choices[gameState.playerId])}, 对手选择了${getRPSName(result.choices[Object.keys(result.choices).find(k => k !== gameState.playerId)])}。${winnerName}获胜，先攻击！`;
        }
    });

    socket.on('attack_result', (result) => {
        console.log('Attack result:', result);
        // 击沉 > 命中 > 落空，优先级从高到低
        if (result.ship_sunk) playSfx('sunk');
        else if (result.hit) playSfx('hit');
        else playSfx('miss');
        updateAttackDisplay(result);
        attacksRemaining.textContent = result.remaining_attacks;

        // 更新攻击次数后，重新检查阶段UI，确保按钮显示正确
        updatePhaseUI();

        // 攻击日志由服务端 game_log 事件统一推送，避免前后端重复
    });

    // 添加处理攻击次数更新事件
    socket.on('attacks_updated', (data) => {
        console.log('Attacks updated:', data);
        attacksRemaining.textContent = data.attacks_remaining;
        updatePhaseUI();
    });

    socket.on('turn_change', (data) => {
        console.log('Turn change:', data);
        if (data.current_attacker === gameState.playerId) playSfx('turn');
        gameState.currentPhase = data.phase;  // 添加阶段更新
        updateTurnIndicator(data.current_attacker, data.attacks_remaining);
        updatePhaseUI();  // 更新阶段UI
    });

    socket.on('game_over', (data) => {
        console.log('Game over:', data);
        playSfx(data.winner === gameState.playerId ? 'win' : 'lose');

        // 隐藏状态显示栏中的所有效果
        document.getElementById('reinforcement-status')?.classList.add('hidden');
        document.getElementById('holy-heart-status')?.classList.add('hidden');
        renderActiveEffects({ self: [], opponent: [] });   // 结算界面不该再挂着「生效中」的角标
        // 绝处逢生的两个门禁标记也要一起清：它们只用于"出牌门禁/提示"，对局结束
        // 就没有意义了，留着会让下一局的出牌门禁带着上一局的结论。
        gameState.lastStandLock = false;
        gameState.lastStandWin = false;
        hidePriorityWaitingBanner();                        // 对局结束：等待横幅一并撤掉
        hideShenjiWaitingBanner();
        // 对局结束也必须收掉桃园的全屏等待浮层：对方在选择中掉线被判负时，
        // 等着的这一方否则会被那层浮层一直挡住（同 handle_cancel_magic_selection 那个病灶）
        dismissTaoyuanWaitingOverlay();
        // 对局结束，手牌选中态一并清掉
        gameState.selectedCardIndex = -1;
        gameState.selectedCardKey = null;
        if (typeof updateHandUI === 'function') updateHandUI();

        switchScreen(gameOverScreen);
        // 本局新解锁的徽章：服务端在结算时**只发给本人**一条 achievements_unlocked，
        // 它比 game_over 先到（_finalize_match 在 emit game_over 之前），所以这里做一次
        // 兜底刷新 —— 无论事件先后，结算界面上都会出现「本局刚解锁 …」。
        renderAchievementUnlockPanel();
        // 根据胜利原因显示不同的提示
        if (data.winner === gameState.playerId) {
            if (data.reason === 'surrender') {
                gameResult.textContent = '对方已投降，你获胜了！';
            } else {
                gameResult.textContent = '恭喜你获胜了！';
            }
        } else {
            gameResult.textContent = '很遗憾，你输了。';
        }
        // 好友批：结算界面把对手那一行的「加好友」按钮补上。
        // ⚠️ 触发它的是 socket 事件 `recent_opponent`（服务端结算时**双方各收一条**），
        //    那条事件的到达顺序不保证 —— 可能在 game_over **之前**也可能在之后
        //    （本项目的经验：`_finalize_match` 系列事件常排在 game_over 之前，
        //    但 `rank_changed` 那种走 background task 的排在之后）。
        //    所以两处都兜一次，名字取"这局那个对手"：
        //    优先用 recent_opponent 给的名字（服务端权威），没有就用对局期间记下的对手名。
        renderRecentOpponentAdd(recentOpponentState.name || gameState.opponentName || '',
            recentOpponentState.relation);
    });

    socket.on('achievements_unlocked', (data) => {
        // 只发给本人的结算反馈。缓冲 + 立刻渲染（那块面板长在结算屏里，
        // 此刻可能还没切过去，但内容先填好，切屏后就能直接看到）。
        const items = (data && Array.isArray(data.items)) ? data.items : [];
        if (!items.length) return;
        pendingUnlockBadges = items.slice();
        renderAchievementUnlockPanel();
        // 对局日志里也留一行（玩家翻日志时能看到是哪局解锁的）
        const names = items.map(b => b.name || b.id).join('、');
        addGameLog('<span class="log-badge log-badge-info">成就</span>'
            + '<span class="log-text">本局解锁了新徽章：' + escapeHtml(names) + '</span>', 'info');
    });

    socket.on('xp_gained', (data) => {
        // 结算经验：只发给本人（服务端按 sid 单发）。面板长在结算屏里，
        // 事件比 game_over 先到，所以这里直接开播；game_over 那边再兜一次。
        try {
            showXpPanel(data);
            // 顺手把首页的等级条更新成"这一局之后"的状态（不用再打一次接口）
            if (data && data.after) refreshMyLevelStrip(data.after);
        } catch (e) {
            console.warn('经验动画失败（不影响结算）:', e && e.message);
        }
    });

    socket.on('rank_changed', (data) => {
        // 排位结算：**逐人单发**（服务端按 sid 发，对手看到的是他自己那份）。
        // 休闲局永远收不到这个事件 —— 所以 `#rank-gain-panel` 在休闲对局里不显示，
        // 前端**不需要**再用 mode 判一次。
        // 事件顺序：服务端把它排在 `game_over` 之后（它甚至走 background task 脱离请求上下文），
        // 所以到达时结算屏已经切好了。
        try {
            showRankGainPanel(data);
        } catch (e) {
            console.warn('段位动画失败（不影响结算）:', e && e.message);
        }
    });

    // ==================== 好友批：四个服务端 → 客户端的 socket 事件 ====================
    // 事件名与 payload 是**冻结契约**，一个字母都不能改（后端在并行实现）：
    //   friend_request  {from_user_id, from_username, from_avatar}
    //   friend_accepted {user_id, username, avatar}
    //   friend_invite   {room_id, from_user_id, from_username}
    //   recent_opponent {user_id, username, avatar, relation}
    // ⚠️ 每个 handler 都整块 try/catch：这四条都是"顺带提示"类事件，
    //    任何一条抛异常都不该把当前这局对局搅黄（同 xp_gained / rank_changed 的处理）。

    socket.on('friend_request', (data) => {
        try {
            handleFriendRequestEvent(data);
        } catch (e) {
            console.warn('好友申请提示失败（不影响对局）:', e && e.message);
        }
    });

    socket.on('friend_accepted', (data) => {
        try {
            handleFriendAcceptedEvent(data);
        } catch (e) {
            console.warn('好友通过提示失败（不影响对局）:', e && e.message);
        }
    });

    socket.on('friend_invite', (data) => {
        try {
            handleFriendInviteEvent(data);
        } catch (e) {
            console.warn('处理好友邀战失败（不影响对局）:', e && e.message);
        }
    });

    socket.on('recent_opponent', (data) => {
        try {
            handleRecentOpponentEvent(data);
        } catch (e) {
            console.warn('处理最近对手失败（不影响结算）:', e && e.message);
        }
    });

    // 好友私聊：收到一条私聊（私聊批，2026-09-19）。
    // payload 恰好 7 个字段（dm.PUSH_PAYLOAD_KEYS 是唯一一份清单）：
    //   {id, from_uid, from_username, from_avatar, body, created_at, stamp}
    // ⚠️ **没有 `mine`** —— 服务端有意不下发"发送方视角"的字段（§4 的坑 4），
    //    所以这条事件永远只可能是"别人发给我的"，渲染时一律 data-mine="0"。
    // ⚠️ 与本批三条好友事件一样整块 try/catch：它在对局中随时可能到，
    //    抛异常不该把当前这局搅黄。
    socket.on('friend_message', (data) => {
        try {
            handleFriendMessageEvent(data);
        } catch (e) {
            console.warn('处理好友私聊失败（不影响对局）:', e && e.message);
        }
    });

    // 添加阶段更新监听
    socket.on('phase_updated', (data) => {
        gameState.currentPhase = data.current_phase;
        gameState.currentAttacker = data.current_attacker;
        updatePhaseUI();
    });

    // 极限增援相关事件处理
    socket.on('reinforcement_activated', (data) => {
        console.log('极限增援激活:', data);
        // 显示极限增援倒计时
        const countdownElement = document.getElementById('reinforcement-countdown');
        const remainingElement = document.getElementById('reinforcement-remaining');

        // 更新状态显示栏
        const statusElement = document.getElementById('reinforcement-status');
        const statusRemainingElement = document.getElementById('reinforcement-status-remaining');

        // 更新传统倒计时
        if (countdownElement && remainingElement) {
            remainingElement.textContent = data.remaining_turns;
            countdownElement.classList.remove('hidden');
        }

        // 更新状态显示栏
        if (statusElement && statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
            statusElement.classList.remove('hidden');
        }
    });

    socket.on('reinforcement_turn_updated', (data) => {
        console.log('极限增援回合更新:', data);
        // 更新极限增援剩余回合
        const remainingElement = document.getElementById('reinforcement-remaining');
        // 更新状态显示栏
        const statusRemainingElement = document.getElementById('reinforcement-status-remaining');

        if (remainingElement) {
            remainingElement.textContent = data.remaining_turns;
        }
        if (statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
        }
    });

    // 无暇圣心激活监听
    socket.on('holy_heart_activated', (data) => {
        console.log('无暇圣心激活:', data);
        // 显示无暇圣心倒计时
        const countdownElement = document.getElementById('holy-heart-countdown');
        const remainingElement = document.getElementById('holy-heart-remaining');

        // 更新状态显示栏
        const statusElement = document.getElementById('holy-heart-status');
        const statusRemainingElement = document.getElementById('holy-heart-status-remaining');

        // 更新传统倒计时
        if (countdownElement && remainingElement) {
            remainingElement.textContent = data.remaining_turns;
            countdownElement.classList.remove('hidden');
        }

        // 更新状态显示栏
        if (statusElement && statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
            statusElement.classList.remove('hidden');
        }
    });

    // 无暇圣心回合更新监听
    socket.on('holy_heart_turn_updated', (data) => {
        console.log('无暇圣心回合更新:', data);
        // 更新无暇圣心剩余回合
        const remainingElement = document.getElementById('holy-heart-remaining');
        // 更新状态显示栏
        const statusRemainingElement = document.getElementById('holy-heart-status-remaining');

        if (remainingElement) {
            remainingElement.textContent = data.remaining_turns;
        }
        if (statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
        }
    });

    // 无暇圣心中断监听
    socket.on('holy_heart_interrupted', (data) => {
        console.log('无暇圣心中断:', data);
        // 隐藏无暇圣心倒计时
        const countdownElement = document.getElementById('holy-heart-countdown');
        // 隐藏状态显示栏中的无暇圣心
        const statusElement = document.getElementById('holy-heart-status');

        if (countdownElement) {
            countdownElement.classList.add('hidden');
        }
        if (statusElement) {
            statusElement.classList.add('hidden');
        }
        // 显示中断原因
        showMessage(data.reason);
    });

    // 极限增援结束监听

    // 添加场地魔法更新监听
    socket.on('field_magic_updated', function (data) {
        console.log('场地魔法更新:', data);
        updateFieldMagicUI(data.player_id, data.card);
    });

    // 添加魔法卡连锁相关事件监听
    socket.on('magic_chain_updated', (data) => {
        gameState.chain = data.chain;
        updateChainUI();
    });

    socket.on('chain_resolved', function (data) {
        console.log('连锁结算完成', data.results);
        // 服务端结算后只发 chain_resolved，不再发 magic_chain_updated，
        // 这里必须自己清空连锁栈 —— 否则「当前连锁 (N)」会一直挂着旧内容。
        gameState.chain = [];
        if (typeof updateChainUI === 'function') updateChainUI();
        // 应用连锁结算结果
        data.results.forEach(result => {
            // ⚠️ 结算失败的卡不能再说「效果生效」。
            // 例如平等条约现在无法无效化炮击造成的击沉，服务端会回 success=false；
            // 若照旧调用 applyCardEffect，双方都会看到「船数改变效果被无效化」的假消息，
            // 而实际上船根本没回来。
            //
            // 另外要分清两种 success=false，它们的含义完全不同：
            //   · negated_skip —— 这张牌【被别人康掉了】，不是它自己不行
            //   · 其它          —— 这张牌【发动条件不满足】，是它自己的问题
            // 混用同一句「X未能生效：…」会让玩家误以为康没成功（实测踩过）。
            if (result.success === false) {
                if (result.negated_skip) {
                    const by = result.negated_by || '对方的无效化效果';
                    showMessage(`【${result.card.name}】被${by}无效化了`,
                                { type: 'warning' });
                } else {
                    showMessage(`${result.card.name}未能生效：${result.message || '条件不满足'}`,
                                { type: 'warning' });
                }
            } else {
                applyCardEffect(result.card, result.caster);
            }
            // 将使用过的卡牌加入弃牌堆
            gameState.discardPile.push(result.card);

            // 魔法卡日志由服务端 game_log 事件统一推送，避免前后端重复

            // 处理需要选择的魔法卡效果
            if (result.temp_data_id) {
                if (result.temp_data_id === 'taoyuan_choice') {
                    // 只有当施法者是当前玩家时，才显示桃园结义选择UI
                    if (result.caster === gameState.playerId) {
                        // 桃园结义选择UI
                        showTaoyuanChoice(result);
                    }
                } else if (result.temp_data_id === 'divine_decree') {
                    // 神之宣告的「选两艘船 + 选效果」都在出牌链路里问完了
                    // （own_ships 选船 → promptDivineDecreeChoice 选效果）。
                    // 这里仅作兼容兜底：不再调用不存在的函数，避免中断整个连锁结算。
                    console.warn('收到 divine_decree 选择请求，选择已在出牌链路完成，忽略');
                } else if (result.temp_data_id === 'lingqi_choice') {
                    // 只有当施法者是当前玩家时，才显示灵气复苏选择UI
                    if (result.caster === gameState.playerId) {
                        // 灵气复苏选择UI
                        showLingqiChoice(result);
                    }
                } else if (result.temp_data_id === 'bury_choice') {
                    // 只有当施法者是当前玩家时，才显示明智埋葬选择UI
                    if (result.caster === gameState.playerId) {
                        // 明智埋葬选择UI
                        showBuryChoice(result);
                    }
                } else if (result.temp_data_id === 'wangyang_choice') {
                    // 只有当施法者是当前玩家时，才显示亡羊补牢选择UI
                    if (result.caster === gameState.playerId) {
                        showWangYangChoice(result);
                    }
                } else if (result.temp_data_id === 'shenji_declare') {
                    // 神机妙算宣言：仅施法者需要输入
                    if (result.caster === gameState.playerId) {
                        showShenjiDeclarePrompt(result);
                    }
                } else if (result.temp_data_id === 'shield_choice') {
                    // 仁王之盾：选择至多3艘自己的船
                    if (result.caster === gameState.playerId) {
                        showRenwangChoice();
                    }
                }
            }
        });
        // 更新游戏状态
        updateHandUI();
        // 如果是攻击阶段，恢复攻击状态
        if (gameState.currentPhase === 'battle') {
            if (typeof enableAttack === 'function') enableAttack();
        }
    });

    // 等待神之宣告选择的通知

    // 神之宣告结算完成通知

    // 弃牌堆更新通知


    socket.on('chain_request', function (data) { showChainRequestPrompt(data); });

    // 阶段转换的「优先权询问」：对方要推进阶段（进战斗 / 进结束）时，
    // 先问我要不要打出一张速阶3。参照游戏王 YGO 的优先权确认。
    socket.on('priority_request', function (data) { showPriorityPrompt(data); });
    // 我发起的阶段转换被拦下了：显示"等待对方响应"+倒计时，并把阶段按钮全部禁用。
    // 后端同一时刻也在冻结我的攻击/出牌/交回合（_priority_wait_reason），
    // 两边口径必须一致 —— 否则玩家会看到"按钮能点但服务端拒绝"的割裂。
    socket.on('priority_waiting', function (data) {
        data = data || {};
        const actionText = data.action_text || '阶段转换';
        const secs = Number(data.countdown) || 10;
        showPriorityWaitingBanner(actionText, Date.now() / 1000 + secs);
    });
    // 等待结束（对方响应了 / 超时了 / 被取消）：解冻
    socket.on('priority_waiting_end', function () { hidePriorityWaitingBanner(); });

    // 对方正在宣言神机妙算：显示等待横幅 + 冻结我的行动（服务端同时会拒绝）。
    socket.on('shenji_waiting', function (data) {
        showShenjiWaitingBanner(data && data.text);
    });
    socket.on('shenji_waiting_end', function () { hideShenjiWaitingBanner(); });
    // 拒绝开关的状态回执
    socket.on('priority_setting_updated', function (data) {
        gameState.declinePriority = !!(data && data.decline);
        syncDeclinePriorityUI();
    });

    // 连锁响应弹窗（10 秒倒计时 + 点选速阶 3 卡）。
    // 抽成具名函数是为了让「重连正好落在响应窗口内」也能把弹窗补回来。
    function showChainRequestPrompt(data) {
        // 绝处逢生生效中：自己的其余魔法卡全部无效，连锁响应同样打不出去。
        // 服务端（chain_response → can_play_magic_card）一定会拒绝，所以别弹这个
        // 窗口让玩家白点一次 —— 那会让窗口凭空消失、也没有任何解释。
        // 直接替玩家放弃，并把原因说清楚。
        if (isLastStandActive()) {
            showMessage('绝处逢生生效中，本回合你的其余魔法卡全部无效，已自动放弃连锁', { type: 'warning' });
            gameState.socket.emit('chain_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                chain: false
            });
            return;
        }
        playSfx('chain');

        const cards = Array.isArray(data.speed3_cards) ? data.speed3_cards : [];
        const total = data.countdown || 10;
        let left = total;
        // 桌面有 hover 就「移上去看效果」；触摸设备没有 hover，改成「点一次看、再点一次打出」。
        // 与日志卡名同一套判据（game.js 的 initGameLogCardRefs）。
        const canHover = !window.matchMedia || window.matchMedia('(hover: hover)').matches;
        // 效果描述来自前端卡面数据（window.magicCards），服务端 payload 里只有 name/speed
        const fullOf = (c) => lookupCard(c && c.name) || c || {};

        let cardsHTML = '';
        if (cards.length) {
            cardsHTML = cards.map((c, index) => {
                const desc = String(fullOf(c).description || '');
                const brief = desc.length > 46 ? desc.slice(0, 46) + '…' : desc;
                return `<button type="button" class="priority-card chain-request-card" data-card-index="${index}">
                    <span class="priority-card-name chain-request-card-name">${escapeHtml(String(c.name))}</span>
                    <span class="priority-card-speed chain-request-card-speed">速阶 ${escapeHtml(String(c.speed))}</span>
                    ${brief ? `<span class="chain-request-card-desc">${escapeHtml(brief)}</span>` : ''}
                </button>`;
            }).join('');
        } else {
            cardsHTML = '<p class="priority-empty chain-request-empty">你手上没有速阶3的魔法卡</p>';
        }

        // 对方（或自己）刚发动的那张卡：卡名做成可预览的锚点。
        // 作者要求：连锁窗口里必须能看"对方发动的是什么效果"，只给个卡名等于让人猜。
        // 与手牌同一套判据：桌面悬停出浮层，触摸设备点一下出详情小窗。
        const activatedName = String((data.card && data.card.name) || '未知卡');
        const activatedCard = fullOf(data.card);

        const cardsHint = canHover
            ? '把鼠标移到卡上可以看效果，点一下即打出；上面的卡名也能看对方那张卡。不响应请点「不响应」。'
            : '点一下先看效果，再点一下才打出；上面的卡名可以看对方那张卡。不响应请点「不响应」。';

        // 清掉可能残留的旧弹窗（重连 / 连续连锁时不叠加），并收掉可能还挂着的悬停浮层
        document.querySelectorAll('.chain-request-prompt').forEach(el => el.remove());
        hideCardTooltip();

        // 结构与 class 与阶段转换的优先权弹窗同源：
        // **外层**只用 `chain-request-prompt`（它是"这是哪个弹窗"的语义锚点 ——
        //   `.priority-prompt` 会被 showPriorityPrompt 的清理逻辑删掉，共用它会误删连锁弹窗）；
        // **内层**复用 `priority-*` 作视觉基类（面板/徽标/圆环/卡牌/按钮，深色主题与
        //   "剩余 3 秒变红"都自动继承），`chain-request-*` 只放连锁专属差异（蓝色 accent、描述行）。
        // 改整体质感只需改 .priority-* 一处，两个弹窗同时生效。
        const chainPrompt = document.createElement('div');
        chainPrompt.className = 'chain-request-prompt';
        chainPrompt.innerHTML = `
            <div class="priority-panel chain-request-panel">
                <div class="priority-head chain-request-head">
                    <span class="priority-badge chain-request-badge">连锁</span>
                    <h3>${data.caster && data.caster === gameState.playerId ? '你发动了' : '对方发动了'}魔法卡<button type="button" class="chain-request-card-ref" id="chain-request-activated">【${escapeHtml(activatedName)}】</button></h3>
                </div>
                <div class="priority-ring chain-request-ring" id="chain-request-ring">
                    <span id="chain-countdown-time">${total}</span>
                </div>
                <p class="priority-hint chain-request-hint">${cardsHint}</p>
                <div class="priority-cards chain-request-cards">${cardsHTML}</div>
                <div class="priority-actions chain-request-actions">
                    <button type="button" id="chain-cancel" class="priority-cancel-btn chain-request-cancel">不响应</button>
                </div>
            </div>
        `;
        document.body.appendChild(chainPrompt);

        // 倒计时圆环：与优先权弹窗同一个 --ring-deg 机制，≤3 秒变红
        const ring = chainPrompt.querySelector('#chain-request-ring');
        const tick = () => {
            const el = chainPrompt.querySelector('#chain-countdown-time');
            if (el) el.textContent = left;
            if (ring) {
                const deg = Math.max(0, Math.min(360, (left / total) * 360));
                ring.style.setProperty('--ring-deg', deg + 'deg');
                ring.classList.toggle('urgent', left <= 3);
            }
        };
        tick();

        const closePrompt = () => {
            clearInterval(countdownTimer);
            hideCardTooltip();
            if (chainPrompt.parentNode) chainPrompt.parentNode.removeChild(chainPrompt);
        };

        // 倒计时结束 → 自动「不响应」（与旧行为一致）
        const countdownTimer = setInterval(() => {
            left -= 1;
            tick();
            if (left <= 0) {
                gameState.socket.emit('chain_response', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    chain: false
                });
                closePrompt();
            }
        }, 1000);

        // 对方刚发动的那张卡：桌面悬停看效果，触摸设备点一下出详情。
        // 只做"看"，不改变响应行为（点它不等于打出、也不等于不响应）。
        const activatedRef = chainPrompt.querySelector('#chain-request-activated');
        if (activatedRef) {
            if (canHover) {
                activatedRef.addEventListener('mouseenter', () => showCardTooltip(activatedRef, activatedCard));
                activatedRef.addEventListener('mouseleave', hideCardTooltip);
            }
            activatedRef.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                hideCardTooltip();
                showCardDetail(activatedCard);
            });
        }

        // 不响应
        const cancelButton = chainPrompt.querySelector('#chain-cancel');
        if (cancelButton) {
            cancelButton.addEventListener('click', () => {
                gameState.socket.emit('chain_response', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    chain: false
                });
                closePrompt();
            });
        }

        const respondWith = (cardIndex, selectedCard) => {
            closePrompt();

            // 需要目标的速阶3卡（神威！/轰炸/冻结/硫磺火焰/探测雷达）此前
            // 一律发 targets: []，服务端缺目标直接失败 —— 等于这些卡在连锁
            // 响应窗口里根本打不出来。改为先走目标选择器，再回填 targets。
            if (needsTargetSelection(selectedCard.name)) {
                gameState.pendingChainCard = { card: selectedCard, index: cardIndex };
                gameState.currentMagicCard = selectedCard;
                gameState.currentCardIndex = cardIndex;
                // 神之宣告（速阶3）也走这个入口：先在自己棋盘上点选两艘要牺牲的船，
                // 确认后再问效果，最后一起回填给 chain_response。
                showMagicTargetSelection(selectedCard, cardIndex);
                return;
            }

            // 无需目标的卡：直接响应连锁
            gameState.socket.emit('chain_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                chain: true,
                card: selectedCard,
                targets: []
            });
        };

        // 触摸设备：第一次点只弹「卡牌详情」，第二次点同一张才真的打出去，
        // 免得"想看效果"被当成"确认出牌"。
        let detailShownIndex = -1;
        chainPrompt.querySelectorAll('.chain-request-card').forEach((cardElement) => {
            const cardIndex = parseInt(cardElement.dataset.cardIndex, 10);
            const selectedCard = cards[cardIndex];
            if (!selectedCard) return;

            if (canHover) {
                cardElement.addEventListener('mouseenter', () => showCardTooltip(cardElement, fullOf(selectedCard)));
                cardElement.addEventListener('mouseleave', hideCardTooltip);
            }

            cardElement.addEventListener('click', () => {
                if (!canHover && detailShownIndex !== cardIndex) {
                    detailShownIndex = cardIndex;
                    chainPrompt.querySelectorAll('.chain-request-card')
                        .forEach(el => el.classList.remove('detail-shown'));
                    cardElement.classList.add('detail-shown');
                    showCardDetail(fullOf(selectedCard));
                    return;
                }
                respondWith(cardIndex, selectedCard);
            });
        });
    }

    // ── 阶段转换的优先权询问（速阶3抢时点的仲裁）────────────────────────
    // 对方要「进入战斗阶段」或「进入结束阶段」时，先问我要不要打出一张速阶3。
    // 参照游戏王 YGO 的优先权确认：即使我手上没有速阶3也会问（只有「取消」），
    // 因为作者要求"玩家要有选择权"。
    // 弹窗底部有「拒绝所有阶段转换时点」开关 —— 勾上后本局不再弹（可随时取消勾选）。
    function showPriorityPrompt(data) {
        data = data || {};
        const actionText = data.action === 'enter_end' ? '进入结束阶段' : '进入战斗阶段';
        const cards = Array.isArray(data.speed3_cards) ? data.speed3_cards : [];
        const countdown = data.countdown || 10;

        // 清掉可能残留的旧弹窗（重连 / 连续询问时不叠加）
        document.querySelectorAll('.priority-prompt').forEach(el => el.remove());
        playSfx('chain');

        let cardsHTML = '';
        if (cards.length) {
            cardsHTML = cards.map((card, index) => `
                <button type="button" class="priority-card" data-card-index="${index}">
                    <span class="priority-card-name">${escapeHtml(card.name)}</span>
                    <span class="priority-card-speed">速阶 ${escapeHtml(String(card.speed))}</span>
                </button>`).join('');
        } else {
            cardsHTML = '<p class="priority-empty">你手上没有速阶3的魔法卡</p>';
        }

        const prompt = document.createElement('div');
        prompt.className = 'priority-prompt';
        prompt.innerHTML = `
            <div class="priority-panel">
                <div class="priority-head">
                    <span class="priority-badge">优先权</span>
                    <h3>对方即将${actionText}</h3>
                </div>
                <div class="priority-ring" id="priority-ring">
                    <span id="priority-countdown">${countdown}</span>
                </div>
                <p class="priority-hint">你可以打出一张速阶3卡牌后再让对方继续；不打就点「取消」。</p>
                <div class="priority-cards">${cardsHTML}</div>
                <label class="priority-toggle">
                    <input type="checkbox" id="decline-priority-toggle"${gameState.declinePriority ? ' checked' : ''}>
                    <span>拒绝所有阶段转换时点</span>
                    <em>勾上后本局不再询问（可随时取消）</em>
                </label>
                <div class="priority-actions">
                    <button type="button" id="priority-cancel" class="priority-cancel-btn">取消</button>
                </div>
            </div>
        `;
        document.body.appendChild(prompt);

        let left = countdown;
        const ring = prompt.querySelector('#priority-ring');
        const tick = () => {
            const el = prompt.querySelector('#priority-countdown');
            if (el) el.textContent = left;
            // 圆环按剩余比例收缩；少于 3 秒变红提醒
            if (ring) {
                const deg = Math.max(0, Math.min(360, (left / countdown) * 360));
                ring.style.setProperty('--ring-deg', deg + 'deg');
                ring.classList.toggle('urgent', left <= 3);
            }
        };
        tick();
        const timer = setInterval(() => {
            left -= 1;
            tick();
            if (left <= 0) {
                clearInterval(timer);
                answer(false);
            }
        }, 1000);

        function answer(respond, card) {
            clearInterval(timer);
            const toggle = prompt.querySelector('#decline-priority-toggle');
            const declineAll = !!(toggle && toggle.checked);
            // 顺手在这里改的也要记住：本局（服务端）+ 以后各局（本地偏好）
            gameState.declinePriority = declineAll;
            saveDeclinePriorityPref(declineAll);
            gameState.socket.emit('priority_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                respond: respond,
                card: card || null,
                targets: [],
                decline_all: declineAll,
            });
            prompt.remove();
        }

        prompt.querySelector('#priority-cancel')
            .addEventListener('click', () => answer(false));

        prompt.querySelectorAll('.priority-card').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.cardIndex, 10);
                const card = cards[idx];
                if (!card) return;
                // 需要目标的速阶3：先走目标选择器，确认后回填给 priority_response
                // （与连锁响应窗口同一套处理，见 pendingChainCard）
                if (needsTargetSelection(card.name)) {
                    clearInterval(timer);
                    prompt.remove();
                    gameState.pendingPriorityCard = { card: card, index: idx };
                    gameState.currentMagicCard = card;
                    gameState.currentCardIndex = -1;
                    showMagicTargetSelection(card, -1);
                    return;
                }
                answer(true, card);
            });
        });
    }

    // 灵气复苏相关事件
    socket.on('lingqi_waiting', function (data) {
        // 显示等待提示
        showMessage(data.message, { type: 'info' });
    });

    socket.on('lingqi_complete', function (data) {
        // 显示完成提示
        showMessage(data.message, { type: 'info' });
    });

    socket.on('reset_gameboard', function (data) {
        // 重置游戏棋盘，进入重新摆放阶段
        showMessage(data.message, { type: 'warning' });

        // 完全重置游戏状态，确保棋盘干净
        gameState.ships = [];
        gameState.attacks = [];
        gameState.myAttacks = [];
        gameState.opponentAttacks = [];
        gameState.revealedCells = [];   // 服务端在重开棋盘时也会清空已显形记录，本地同步
        gameState.lastStandOwner = null;   // 归属也要一起清，免得重开后又高亮错棋盘
        gameState.frozenArea = null;       // 冻结区域同理
        dismissTaoyuanWaitingOverlay();    // 重开棋盘：桃园全屏等待浮层一并收掉
        // 重开一局：手牌虽然保留，但选中态要清掉（下标含义随时可能变）
        gameState.selectedCardIndex = -1;
        gameState.selectedCardKey = null;
        gameState.remainingShips = 0;
        gameState.opponentRemainingShips = 0;
        gameState.maxShips = data.new_max_ships;
        // ⚠️ 防线：服务端若漏给 `new_max_ships`（或给了 null），这里必须有个数。
        //    `gameState.maxShips` 为 null/0 时，`handleCellClick` 的
        //    `if (gameState.placedShips >= gameState.maxShips) return;` **恒成立**
        //    → 点格子完全没反应，且 ships 一直为空 → 确认时报「布船数据无效」。
        //    （作者实测就是这两个症状。服务端那边也已补成显式 6，这里是第二道防线。）
        if (!Number.isFinite(Number(gameState.maxShips)) || Number(gameState.maxShips) <= 0) {
            console.warn('[placement] new_max_ships 缺失或非法，回退为 6：', data.new_max_ships);
            gameState.maxShips = 6;
        }
        gameState.placedShips = 0;

        // 隐藏所有其他屏幕（唯一来源，见 hideAllScreens）
        hideAllScreens();

        // 直接进入放置战舰界面
        shipPlacementScreen.classList.add('active');
        initBoard(playerBoard, true);

        // 确保界面正确切换（同上：屏不加 hidden）
        startScreen.classList.remove('active');
        customRoomScreen.classList.remove('active');
        matchStatus.classList.add('hidden');

        // 更新可摆放船数显示
        // 注意：shipsPlaced 是 <p> 容器，直接写 textContent 会抹掉内部的
        // <span id="placed-count">，导致之后"已放置 x/y"再也不更新。
        const placedCountEl = document.getElementById('placed-count');
        const totalShips = document.getElementById('total-ships');
        if (totalShips) {
            totalShips.textContent = data.new_max_ships;
        }
        if (placedCountEl) {
            placedCountEl.textContent = 0;
        }

        // 重置已放置船数
        gameState.placedShips = 0;
    });


    // 显示桃园结义选择界面
    function showTaoyuanChoice(result) {
        // 创建选择界面
        const taoyuanChoiceDiv = document.createElement('div');
        taoyuanChoiceDiv.className = 'taoyuan-choice-overlay';
        taoyuanChoiceDiv.style.zIndex = '10000'; // 设置最高优先级
        taoyuanChoiceDiv.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>桃园结义 - 卡牌选择</h3>
                    <p id="taoyuan-choice-message">${result.message}</p>
                    <div id="taoyuan-selection-result" style="margin-top: 8px; padding: 8px; background-color: rgba(25, 118, 210, 0.1); border-radius: 4px;"></div>
                </div>
                <div class="taoyuan-choice-step">
                    <h4 id="taoyuan-step-title">第一步：选择一张卡牌给自己</h4>
                </div>
                <div class="taoyuan-cards-container"></div>
                <div style="text-align:center;margin-top:10px;">
                    <button id="taoyuan-cancel-btn" class="secondary">取消（把牌放回牌堆）</button>
                </div>
            </div>
        `;
        document.body.appendChild(taoyuanChoiceDiv);

        // 获取卡片容器和选择结果区域
        const cardsContainer = taoyuanChoiceDiv.querySelector('.taoyuan-cards-container');
        const selectionResultDiv = document.getElementById('taoyuan-selection-result');

        // 存储选择状态
        let selectedCards = { caster: null, opponent: null };
        let step = 1; // 1: 选择自己的卡, 2: 选择对方的卡
        let cards = [];

        const renderTaoyuanCards = (response) => {
            if (response.status === 'success' && response.data && response.data.cards) {
                cards = response.data.cards;

                // 显示卡牌
                cards.forEach((card, index) => {
                    const cardElement = document.createElement('div');
                    cardElement.className = 'taoyuan-card-item';
                    cardElement.dataset.index = index;
                    cardElement.innerHTML = `
                        <div class="taoyuan-card-name">${card.name}</div>
                        <div class="taoyuan-card-type">${card.type}·速阶${card.speed}</div>
                        <div class="taoyuan-card-desc">${card.description}</div>
                    `;
                    cardsContainer.appendChild(cardElement);

                    // 添加点击事件
                    cardElement.addEventListener('click', () => {
                        if (step === 1) {
                            // 第一步：选择自己的卡
                            selectedCards.caster = index;

                            // 更新界面
                            cardElement.classList.add('selected');

                            // 更新选择结果提示
                            selectionResultDiv.innerHTML = `
                                <strong>选择结果：</strong><br>
                                已为自己选择卡牌：<span style="color: #1976d2; font-weight: bold;">${card.name}</span><br>
                                该卡牌已加入你的手牌库
                            `;

                            // 检查是否需要第二步
                            if (cards.length > 1) {
                                // 进入第二步
                                step = 2;
                                document.getElementById('taoyuan-step-title').textContent = '第二步：选择一张卡牌给对方';

                                // 禁用已选择的卡
                                cardElement.classList.add('disabled');
                            } else {
                                // 只有一张卡，直接确认
                                selectionResultDiv.innerHTML += '<br><strong style="color: #10b981;">选择完成！</strong>';
                                setTimeout(() => {
                                    confirmTaoyuanChoice(selectedCards, cards);
                                    document.body.removeChild(taoyuanChoiceDiv);
                                }, 1000);
                            }
                        } else if (step === 2) {
                            // 第二步：选择对方的卡
                            if (index !== selectedCards.caster) {
                                selectedCards.opponent = index;

                                // 更新选择结果提示
                                const opponentCard = cards[index];
                                selectionResultDiv.innerHTML = `
                                    <strong>选择结果：</strong><br>
                                    已为自己选择卡牌：<span style="color: #1976d2; font-weight: bold;">${cards[selectedCards.caster].name}</span><br>
                                    已为对方选择卡牌：<span style="color: #f57c00; font-weight: bold;">${opponentCard.name}</span><br>
                                    卡牌已分别加入双方手牌库
                                    <br><strong style="color: #10b981;">选择完成！</strong>
                                `;

                                // 确认选择
                                setTimeout(() => {
                                    confirmTaoyuanChoice(selectedCards, cards);
                                    document.body.removeChild(taoyuanChoiceDiv);
                                }, 1000);
                            }
                        }
                    });
                });
            }
        };
        if (result.cards && Array.isArray(result.cards) && result.cards.length) {
            renderTaoyuanCards({ status: 'success', data: { cards: result.cards } });
        } else {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, renderTaoyuanCards);
        }

        // 取消按钮事件（元素可能不存在时跳过，避免崩溃）
        const cancelBtn = document.getElementById('taoyuan-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                // 通知服务端放弃选择（把抽出的牌放回牌堆），再关闭浮窗
                if (gameState.socket) {
                    gameState.socket.emit('cancel_magic_selection', {
                        room_id: gameState.roomId, player_id: gameState.playerId,
                    });
                }
                try { document.body.removeChild(taoyuanChoiceDiv); } catch (e) {}
            });
        }
    }

    // 确认桃园结义选择
    function confirmTaoyuanChoice(selectedCards, cards) {
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'taoyuan_choice',
            target_data: {
                caster_choice: selectedCards.caster,
                opponent_choice: selectedCards.opponent || -1
            }
        }, (response) => {
            if (response.status === 'success') {
                showMessage('桃园结义选择完成');
                updateHandUI();
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    // 显示灵气复苏船数选择界面
    function showLingqiChoice(result) {
        // 创建选择界面，使用与桃园结义相同的UI样式
        const lingqiChoiceDiv = document.createElement('div');
        lingqiChoiceDiv.className = 'taoyuan-choice-overlay';
        lingqiChoiceDiv.style.zIndex = '10000'; // 设置最高优先级
        lingqiChoiceDiv.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>灵气复苏 - 船数选择</h3>
                    <p id="taoyuan-choice-message">灵气复苏船数选择 选择后双方的船数都会变为你选择的数目</p>
                </div>
                <div class="taoyuan-cards-container" style="display: flex; flex-wrap: wrap; gap: 12px; justify-content: center;"></div>
            </div>
        `;
        document.body.appendChild(lingqiChoiceDiv);

        // 获取卡片容器
        const cardsContainer = lingqiChoiceDiv.querySelector('.taoyuan-cards-container');

        // 获取最大船数
        let maxShips = result.max_ships;

        // 如果maxShips未在result中返回，请求服务器获取
        if (!maxShips) {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, (response) => {
                if (response.status === 'success' && response.data && response.data.max_ships) {
                    maxShips = response.data.max_ships;
                    renderShipButtons(maxShips);
                }
            });
        } else {
            renderShipButtons(maxShips);
        }

        // 渲染船数按钮
        function renderShipButtons(maxShips) {
            cardsContainer.innerHTML = '';

            // 创建1到maxShips的按钮，使用与桃园结义卡牌相同的样式
            for (let i = 1; i <= maxShips; i++) {
                const buttonElement = document.createElement('div');
                buttonElement.className = 'taoyuan-card-item';
                buttonElement.dataset.shipCount = i;
                buttonElement.innerHTML = `
                    <div class="taoyuan-card-name" style="text-align: center;">${i}艘</div>
                    <div class="taoyuan-card-type" style="text-align: center;">选择此船数</div>
                    <div class="taoyuan-card-desc" style="text-align: center;">双方船数将调整为${i}艘</div>
                `;

                // 添加点击事件
                buttonElement.addEventListener('click', () => {
                    const selectedShipCount = parseInt(buttonElement.dataset.shipCount);
                    confirmLingqiChoice(selectedShipCount);
                    document.body.removeChild(lingqiChoiceDiv);
                });

                cardsContainer.appendChild(buttonElement);
            }
        }
    }

    // 确认灵气复苏选择
    function confirmLingqiChoice(targetShips) {
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'lingqi_choice',
            target_data: {
                target_ships: targetShips
            }
        }, (response) => {
            if (response.status === 'success') {
                showMessage(response.message);
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    function showBuryChoice(result) {
        // 创建选择界面，使用与桃园结义相同的UI样式
        const buryChoiceDiv = document.createElement('div');
        buryChoiceDiv.className = 'taoyuan-choice-overlay';
        buryChoiceDiv.style.zIndex = '10000'; // 设置最高优先级
        buryChoiceDiv.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>明智埋葬 - 卡牌选择</h3>
                    <p id="taoyuan-choice-message">${result.message}</p>
                </div>
                <div class="taoyuan-cards-container"></div>
            </div>
        `;
        document.body.appendChild(buryChoiceDiv);

        // 获取卡片容器
        const cardsContainer = buryChoiceDiv.querySelector('.taoyuan-cards-container');

        // 存储选择状态
        let selectedCard = null;
        let cards = [];

        const renderBuryCards = (response) => {
            if (!response || response.status !== 'success' || !response.data) return;
            // 主链路（chain_resolved 结果）用 data.cards；
            // 兜底查询 get_magic_temp_data 时服务端返回的是 data.candidates（纯数据）
            const list = response.data.cards || response.data.candidates;
            if (Array.isArray(list) && list.length) {
                cards = list;

                // 显示卡牌（来源可能是牌堆或对方手牌）
                cards.forEach((card, index) => {
                    const cardElement = document.createElement('div');
                    cardElement.className = 'taoyuan-card-item';
                    cardElement.dataset.index = index;
                    cardElement.dataset.source = card.source || 'deck';

                    const sourceLabel = (card.source === 'opponent_hand') ? '对方手牌' : '牌堆';
                    cardElement.innerHTML = `
                        <div class="taoyuan-card-name">${card.name}</div>
                        <div class="taoyuan-card-type">${card.type}·速阶${card.speed} · ${sourceLabel}</div>
                        <div class="taoyuan-card-desc">${card.description}</div>
                    `;
                    cardsContainer.appendChild(cardElement);

                    // 添加点击事件
                    cardElement.addEventListener('click', () => {
                        // 移除其他卡牌的选中状态
                        cardsContainer.querySelectorAll('.taoyuan-card-item').forEach(item => {
                            item.classList.remove('selected');
                        });

                        // 选中当前卡牌
                        cardElement.classList.add('selected');

                        // 确认选择（带上来源 + 该卡在来源列表内的下标）
                        confirmBuryChoice(index, card.source || 'deck', card.index);
                        document.body.removeChild(buryChoiceDiv);
                    });
                });
            }
        };
        if (result.cards && Array.isArray(result.cards) && result.cards.length) {
            renderBuryCards({ status: 'success', data: { cards: result.cards } });
        } else {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, renderBuryCards);
        }
    }

    // 确认明智埋葬选择
    // cardIndex 是候选总表（牌堆在前、对方手牌在后）里的扁平下标，
    // sourceIndex 是该卡在自己来源列表内的下标 —— 服务端优先用后者精确定位。
    function confirmBuryChoice(cardIndex, source, sourceIndex) {
        const targetData = {
            card_index: cardIndex,
            source: source || 'deck'
        };
        if (typeof sourceIndex === 'number') {
            targetData.source_index = sourceIndex;
        }
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'bury_choice',
            target_data: targetData
        }, (response) => {
            if (response.status === 'success') {
                showMessage(response.message);
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    // 亡羊补牢：从弃牌区最新 n 张里挑 1 张加入手牌
    // 候选牌的顺序由服务端给出（最新那张在末尾），UI 顺序就是候选数组的顺序。
    function showWangYangChoice(result) {
        const overlay = document.createElement('div');
        overlay.className = 'taoyuan-choice-overlay';
        overlay.style.zIndex = '10000';
        overlay.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>亡羊补牢 - 从弃牌区选 1 张</h3>
                    <p id="taoyuan-choice-message">${result.message || ''}</p>
                    <div id="taoyuan-selection-result" style="margin-top: 8px; padding: 8px; background-color: rgba(25, 118, 210, 0.1); border-radius: 4px;"></div>
                </div>
                <div class="taoyuan-cards-container"></div>
                <div style="text-align:center;margin-top:10px;">
                    <button id="wangyang-cancel-btn" class="secondary">取消（弃牌区还原）</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const cardsContainer = overlay.querySelector('.taoyuan-cards-container');
        const selectionResultDiv = overlay.querySelector('#taoyuan-selection-result');
        let cards = [];

        const renderWangYangCards = (response) => {
            if (!response || response.status !== 'success' || !response.data) return;
            const list = response.data.cards;
            if (!Array.isArray(list) || !list.length) return;
            cards = list;

            cards.forEach((card, index) => {
                const cardElement = document.createElement('div');
                cardElement.className = 'taoyuan-card-item';
                cardElement.dataset.index = index;
                cardElement.innerHTML = `
                    <div class="taoyuan-card-name">${card.name}</div>
                    <div class="taoyuan-card-type">${card.type}·速阶${card.speed}</div>
                    <div class="taoyuan-card-desc">${card.description}</div>
                `;
                cardsContainer.appendChild(cardElement);

                cardElement.addEventListener('click', () => {
                    cardsContainer.querySelectorAll('.taoyuan-card-item').forEach(item => {
                        item.classList.remove('selected');
                    });
                    cardElement.classList.add('selected');
                    selectionResultDiv.innerHTML = `
                        <strong>已选择：</strong>
                        <span style="color: #1976d2; font-weight: bold;">${card.name}</span>
                        <br>该卡将加入你的手牌，其余回归弃牌堆
                    `;
                    setTimeout(() => {
                        confirmWangYangChoice(index);
                        try { document.body.removeChild(overlay); } catch (e) {}
                    }, 600);
                });
            });
        };

        if (result.cards && Array.isArray(result.cards) && result.cards.length) {
            renderWangYangCards({ status: 'success', data: { cards: result.cards } });
        } else {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, renderWangYangCards);
        }

        const cancelBtn = overlay.querySelector('#wangyang-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                if (gameState.socket) {
                    gameState.socket.emit('cancel_magic_selection', {
                        room_id: gameState.roomId, player_id: gameState.playerId,
                    });
                }
                try { document.body.removeChild(overlay); } catch (e) {}
            });
        }
    }

    function confirmWangYangChoice(chosenIndex) {
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'wangyang_choice',
            target_data: { chosen_index: chosenIndex }
        }, (response) => {
            if (response.status === 'success') {
                showMessage(response.message);
                updateHandUI();
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    // 说明：服务端从来没有 lobby_update / lobby_joined / lobby_left / match_found
    // 这些事件（历史遗留空壳，已删除）。大厅按钮状态改由上面真实的
    // match_queued / match_canceled 处理器同步。

    // 新增：监听手牌更新事件
    //
    // ⚠️ 这个 handler 以前直接 `gameState.hand = data.hand;`，没有任何校验。
    // 只要有一次 payload 不带 hand（结构不符 / 前端是旧缓存版本 / 某条新路径
    // 忘了带字段），gameState.hand 就变成 undefined —— 而 updateHandUI 是在
    // 清空容器之后才遍历 hand 的，于是整块手牌区域变成空白，并且**此后每一次
    // 刷新手牌都会抛异常，永远保持空白，只有刷新页面才能恢复**。
    // 这正是作者反馈的「打完一张，剩下的手牌莫名消失，刷新又回来」。
    // 服务端是手牌的唯一权威：结构不对就忽略它并要求重同步，绝不拿它覆盖。
    socket.on('hand_updated', (data) => {
        applyHandPayload(data, 'hand_updated');
    });

    // 神威！：扣掉 / 恢复 3x3 区域
    socket.on('shenwei_hole', (data) => {
        gameState.shenweiHoles = (gameState.shenweiHoles || []).filter(
            h => !(h.player === data.player && h.x1 === data.area.x1 && h.y1 === data.area.y1));
        gameState.shenweiHoles.push(Object.assign({ player: data.player }, data.area));
        applyShenweiHoles();
        showMessage(data.player === gameState.playerId
            ? '你的棋盘被神威！扣掉了一块 3x3 区域'
            : '对方棋盘被神威！扣掉了一块 3x3 区域');
    });
    socket.on('shenwei_hole_restored', (data) => {
        gameState.shenweiHoles = (gameState.shenweiHoles || []).filter(h => h.player !== data.player);
        applyShenweiHoles();
        showMessage('神威！区域已恢复，战舰回归原位');
    });

    // 恶魔契约：服务端要求选择一艘自己的战舰牺牲（在自己棋盘上点选，无额外弹窗）
    socket.on('sacrifice_request', (data) => {
        showSacrificePrompt(data);
    });

    // 某艘船因效果被牺牲 —— 公开事件，双方都能看到这艘船沉没
    socket.on('ship_sacrificed', (data) => {
        const positions = (data && data.positions) || [];
        if (!positions.length) return;
        const mine = data.player === gameState.playerId;

        // ⚠️ 绝处逢生的自牺牲【不画叉】。
        // 它的六个格子是"唯一一艘新船可能落点"，对方必须能打；画成红叉
        // （玩家眼里等于"已打过、别再点"）会让人以为这几格打不了（作者实测反馈）。
        // 改成由 last_stand_cells 事件下发候选格，前端画成高亮。
        if (data.reason === 'last_stand') {
            if (mine) {
                // 自己的船全没了：本地棋盘记录一并清掉
                const keys = new Set(positions.map(p => p.x + ',' + p.y));
                gameState.ships = (gameState.ships || [])
                    .map(ship => Object.assign({}, ship, {
                        positions: (ship.positions || []).filter(p => !keys.has(p.x + ',' + p.y))
                    }))
                    .filter(ship => (ship.positions || []).length > 0);
            }
            if (typeof initGameBoards === 'function') initGameBoards();
            return;   // 文案交给 last_stand_cells 那条统一播报
        }

        const sink = mine ? gameState.sacrificedSelf : gameState.sacrificedOpponent;

        positions.forEach(p => sink.push({ x: p.x, y: p.y }));

        if (mine) {
            // 自己的船死了：从本地棋盘记录里移除这艘船
            const keys = new Set(positions.map(p => p.x + ',' + p.y));
            gameState.ships = (gameState.ships || [])
                .map(ship => Object.assign({}, ship, {
                    positions: (ship.positions || []).filter(p => !keys.has(p.x + ',' + p.y))
                }))
                .filter(ship => (ship.positions || []).length > 0);
        }

        if (typeof initGameBoards === 'function') initGameBoards();
        // 卡片名按来源显示：恶魔契约 / 神之宣告 / 命运骰子 都走这条公开事件
        const reasonText = ({divine_decree: '神之宣告', dice_sacrifice: '命运骰子'})[data.reason] || '恶魔契约';
        showMessage(mine ? `${reasonText}：你牺牲了一艘战舰` : `${reasonText}：对方牺牲了一艘战舰`,
                    { type: 'warning' });
    });

    // 绝处逢生：牺牲前原本有战舰的格子（唯一一艘新船必在其中）。
    // 双方都要高亮 —— 对方据此知道该往哪儿打，而且这些格子照样能点。
    socket.on('last_stand_cells', (data) => {
        const cells = (data && Array.isArray(data.cells)) ? data.cells : [];
        gameState.lastStandCells = cells.filter(c => c && typeof c.x === 'number' && typeof c.y === 'number');
        // 归属：这批格子是【谁棋盘上的】。没有它就只能瞎猜棋盘，实测会画到对手棋盘上。
        gameState.lastStandOwner = (data && data.owner) || null;
        if (typeof initGameBoards === 'function') initGameBoards();
        if (gameState.lastStandCells.length) {
            const mine = gameState.playerId && gameState.lastStandOwner === gameState.playerId;
            showMessage(mine
                ? '绝处逢生：唯一一艘会放在高亮的格子之一（点一格放置）'
                : '绝处逢生：对方牺牲了全部战舰，唯一一艘会在高亮的格子之一（这些格子可以打）',
                { type: 'warning' });
        }
    });

    // 冻结的 3×3 区域：双方都要看到（施法方原先什么都收不到，过一会儿就忘了冻的是哪片）
    socket.on('frozen_area', (data) => {
        gameState.frozenArea = (data && !data.cleared) ? data : null;
        if (typeof initGameBoards === 'function') initGameBoards();
    });

    // 命运骰子：摇骰子动画 + 结果播报（双方都能看到）
    socket.on('dice_rolled', (data) => {
        showDiceRollAnimation(data && data.roll, data && data.effect_text, data && data.caster);
    });

    // 命运骰子摇到3：要求我弃一张手牌
    socket.on('dice_discard_request', (data) => {
        showDiceDiscardPrompt(data && data.message);
    });

    // 双方都弃完：关掉选牌浮层（如果还开着）
    socket.on('dice_discard_complete', () => {
        hideDiceDiscardPrompt();
    });

    // 服务端统一推送的局内日志
    socket.on('game_log', (entry) => {
        renderServerLog(entry);
    });

    // 局内快捷语（第 4 批）：只写日志 + 轻提示，不动棋盘 / 手牌 / 阶段 / 连锁
    socket.on('quick_chat', (payload) => {
        handleQuickChatReceived(payload);
    });

    // 日志里的卡名支持悬停查看 / 点击详情（幂等，只绑一次）
    initGameLogCardRefs();

    // 增援 / 复活：服务端请求选择部署位置
    socket.on('placement_request', (data) => {
        showPlacementPrompt(data);
    });
    socket.on('placement_done', (data) => {
        const p = document.getElementById('placement-prompt');
        if (p) p.remove();
        const doneMsg = (data && data.kind === 'lanyu') ? '滥竽充数·补充部署完成（大回合结束时收回）'
            : (data && data.kind === 'revive') ? '复活部署完成'
            : '增援部署完成';
        showMessage(doneMsg);
        if (typeof initGameBoards === 'function') initGameBoards();
    });
    // 自己棋盘上的战舰变化（复活/增援后同步显示）
    socket.on('player_ships_updated', (data) => {
        if (data && Array.isArray(data.ships)) {
            gameState.ships = data.ships;
            if (typeof initGameBoards === 'function') initGameBoards();
        }
    });

    // 盾牌挡下一击：必须明确提示，否则双方只看到一次普通"命中"，
    // 防守方会以为自己的船挨了一炮（其实毫发无伤）。
    socket.on('shield_absorbed', (data) => {
        const mine = data && data.player === gameState.playerId;
        showMessage(mine ? '你的战舰用护盾挡下了这次攻击'
                         : '对方的战舰用护盾挡下了这次攻击',
                    { type: 'info' });
    });

    // 新增：监听战舰数更新事件
    socket.on('ships_updated', (data) => {
        // 更新双方剩余战舰数
        yourShips.textContent = data.player_remaining_ships;
        opponentShips.textContent = data.opponent_remaining_ships;
    });

    // 「谁打过哪些格子」的全量重发：复活 / 增援 / 重新部署把格子从服务端
    // 攻击历史里清掉之后，必须用它刷新本地缓存，否则那个格子会一直画着 ✕
    // 并且【没有绑定点击监听】（initGameBoards 只在 !alreadyAttacked 时才绑），
    // 对手就永远点不动它。
    socket.on('board_attacks_updated', (data) => {
        const norm = (list) => (Array.isArray(list) ? list : []).map((a) => ({
            x: a.x, y: a.y, hit: !!a.hit, shipSunk: !!a.ship_sunk,
        }));
        if (data && Array.isArray(data.my_attacks)) {
            gameState.myAttacks = norm(data.my_attacks);
        }
        if (data && Array.isArray(data.opponent_attacks)) {
            gameState.opponentAttacks = norm(data.opponent_attacks);
        }
        initGameBoards();
    });

    // 当前生效效果角标：完全由服务端广播驱动（服务端是唯一真相）。
    // 服务端按收件人视角分别下发 self / opponent —— 双方都能看到对方挂着什么。
    socket.on('active_effects', (data) => {
        renderActiveEffects(data || { self: [], opponent: [] });
    });

    // 服务器推送的通用消息
    socket.on('message', (data) => {
        if (data && data.text) showMessage(data.text);
    });

    // 显示服务端通用消息 / 错误（此前未监听导致提示不可见）
    socket.on('game_message', (data) => {
        if (data && (data.message || data.text)) showMessage(data.message || data.text);
    });
    socket.on('error', (data) => {
        const msg = (data && (data.message || data.msg || data)) || '发生错误';
        // 排位排队被服务端拒绝（未登录 → 「排位模式需要先登录」）时必须**恢复按钮状态**，
        // 否则按一次就永远卡在「正在寻找排位对手…」。
        if (rankedQueuePending) resetRankedQueueUI();
        showMessage(typeof msg === 'string' ? msg : JSON.stringify(msg));
    });

    // 对手桃园结义结算等待提示
    socket.on('taoyuan_waiting', (data) => {
        // 创建等待提示界面
        const waitingDiv = document.createElement('div');
        waitingDiv.className = 'taoyuan-waiting-overlay';
        waitingDiv.style.zIndex = '10000';
        waitingDiv.style.position = 'fixed';
        waitingDiv.style.top = '0';
        waitingDiv.style.left = '0';
        waitingDiv.style.width = '100%';
        waitingDiv.style.height = '100%';
        waitingDiv.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
        waitingDiv.style.display = 'flex';
        waitingDiv.style.alignItems = 'center';
        waitingDiv.style.justifyContent = 'center';
        waitingDiv.style.color = 'white';
        waitingDiv.innerHTML = `
            <div style="background: rgba(25, 118, 210, 0.9); padding: 20px; border-radius: 10px; text-align: center;">
                <h3>${data.message}</h3>
            </div>
        `;
        document.body.appendChild(waitingDiv);
    });

    // 桃园结义结算完成提示
    socket.on('taoyuan_complete', (data) => {
        // 移除等待提示（取消时服务端也会发这个事件，见 handle_cancel_magic_selection）
        dismissTaoyuanWaitingOverlay();
        showMessage(data.message);
    });

    // 亡羊补牢结算完成提示（仅施法者选完/取消后通知对手）
    socket.on('wangyang_complete', (data) => {
        showMessage(data.message);
    });

    // 守株待兔：陷阱标记已打上（施法者自己 + 对方都能看到，所以 room 广播）
    socket.on('trap_set', (data) => {
        const isMine = data && data.player === gameState.playerId;
        const msg = isMine
            ? '已为一艘战舰设置陷阱（本回合该船被击沉时对方需牺牲两艘）'
            : '对方为一艘战舰设置了陷阱';
        showMessage(msg, { type: isMine ? 'success' : 'warning' });
    });

    // 守株待兔：陷阱被踩中
    socket.on('trap_triggered', (data) => {
        showMessage((data && data.message) || '陷阱触发', { type: 'warning' });
    });

    // 守株待兔：陷阱过期（新大回合开始）
    socket.on('trap_expired', (data) => {
        if (data && data.player === gameState.playerId) {
            showMessage('你的陷阱已过期', { type: 'info' });
        } else if (data && data.player) {
            showMessage('对方的陷阱已过期', { type: 'info' });
        }
    });

    // 卧薪尝胆：为所有活船加护盾（双方都可见，所以 room 广播）
    socket.on('shields_added', (data) => {
        const isMine = data && data.player === gameState.playerId;
        const cnt = (data && data.count) || 0;
        const msg = isMine
            ? `已为${cnt}艘战舰添加护盾`
            : `对方为${cnt}艘战舰添加了护盾`;
        showMessage(msg, { type: isMine ? 'success' : 'warning' });
    });

    // 滥竽充数：大回合结束时强制收回临时船（不显示沉没）
    socket.on('lanyu_recalled', (data) => {
        const isMine = data && data.player === gameState.playerId;
        const cnt = (data && data.count) || 0;
        const msg = isMine
            ? `滥竽充数：${cnt}艘临时战舰已收回`
            : `对方的滥竽充数临时战舰已收回${cnt}艘`;
        showMessage(msg, { type: 'info' });
        if (typeof initGameBoards === 'function') initGameBoards();
    });

    // 服务器返回的被揭示的位置（仅对触发方发送）
    socket.on('revealed_positions', (data) => {
        if (!data || !Array.isArray(data.positions)) return;
        // kind：'heal' = 疗愈原地复活（对方该知道船又回到这一格了）；
        // 缺省 = 旧的通用显形（探测雷达 / 克苏鲁之眼等），行为不变。
        const kind = data.kind || null;
        data.positions.forEach(pos => {
            let entry = gameState.revealedCells.find(c => c.x === pos.x && c.y === pos.y);
            if (!entry) {
                entry = { x: pos.x, y: pos.y, kind: kind };
                gameState.revealedCells.push(entry);
            } else if (kind && !entry.kind) {
                entry.kind = kind;          // 后到的更具体来源，覆盖"通用显形"
            }
            const cell = opponentBoard.querySelector(`.cell[data-x='${pos.x}'][data-y='${pos.y}']`);
            if (cell) {
                cell.classList.add('revealed');
                if (entry.kind === 'heal') {
                    cell.classList.add('revealed-heal');
                    cell.title = '疗愈：这艘战舰原地复活，仍在这一格';
                }
            }
        });
    });

}

// ── 屏注册表（UI 重构建议 §3.2）────────────────────
// 全仓只有这一份「有哪些屏」。以前 game_state 与 reset_gameboard 里各手抄一份，
// 两份都漏了 lobbyScreen / leaderboardScreen → 在大厅点人机对战会两个屏同时 active。
// 新增屏时：先加进 index.html，再在这里登记。
function allScreens() {
    return [startScreen, customRoomScreen, matchSuccessScreen, shipPlacementScreen, rpsScreen,
            gameScreen, gameOverScreen, leaderboardScreen, lobbyScreen,
            // 兜底：页面里任何带 .screen 的元素（防漏登记）
            ...Array.from(document.querySelectorAll('.screen'))];
}

// 隐藏所有屏。⚠️ 只动 `active`，绝不动 `hidden`（单向锁死，见 applyRoomSync 注释）。
function hideAllScreens() {
    const seen = new Set();
    allScreens().forEach(function (el) {
        if (!el || seen.has(el)) return;
        seen.add(el);
        el.classList.remove('active');
    });
}

// 切换屏幕
function switchScreen(screen) {
    hideAllScreens();
    if (screen) screen.classList.add('active');

    // 大厅批：切走就退订（否则打完一局还在收大厅广播）。函数声明会提升，
    // 这里调它不存在时序问题。
    leaveLobbySubscription(screen);

    // 进入对局界面时兜底显示日志空状态（避免出现一个空白日志框）
    if (screen && screen.id === 'game-screen') ensureGameLogEmptyState();

    // 隐藏或显示在局内不应显示的导航项（登录/注册/排行榜）
    const hideEls = document.querySelectorAll('.hide-in-game');
    const inRoomScreens = ['ship-placement-screen', 'rps-screen', 'game-screen', 'custom-room-screen'];
    const shouldHide = screen && inRoomScreens.includes(screen.id);
    hideEls.forEach(el => {
        el.style.display = shouldHide ? 'none' : '';
    });
}

// 展示并加载排行榜
function showLeaderboard() {
    switchScreen(leaderboardScreen);
    // 每次进这一页都从「战绩榜」开始（段位榜要现算名次，别在导航时就拉）
    setLeaderboardTab('record');
    fetchLeaderboard();
}

// 显示大厅 —— 实现见下方「大厅系统（2026-09-18）」分节（showLobby）。
// ⚠️ 不要再在这里补一份：同名函数声明后出现的会覆盖前面的，
//    两份实现并存正是本项目"改了没生效"的经典来源。

function fetchLeaderboard() {
    if (!leaderboardTableBody || !leaderboardError) return;
    leaderboardTableBody.innerHTML = '';
    leaderboardError.classList.add('hidden');
    const loadingRow = document.createElement('tr');
    loadingRow.innerHTML = '<td colspan="6" style="text-align:center; padding:12px">加载中...</td>';
    leaderboardTableBody.appendChild(loadingRow);

    fetch('/api/leaderboard').then(resp => {
        if (!resp.ok) throw new Error('网络错误');
        return resp.json();
    }).then(data => {
        leaderboardTableBody.innerHTML = '';
        data.forEach((row, idx) => {
            const tr = document.createElement('tr');
            const wins = row.wins || 0;
            const losses = row.losses || 0;
            const total = wins + losses;
            const winrate = total ? Math.round((wins / total) * 100) + '%' : '-';
            // 头像 + 名字都要能点：打开那个人的个人信息（个人信息面板见 showUserProfile）
            const username = String(row.username || '');
            const avatar = row.avatar ? String(row.avatar) : '/static/avatars/default.png';
            // 名字样式（特权外观，服务端逐行下发；见 api.py 的 /api/leaderboard）
            const nameCls = 'leaderboard-name' + (String(row.name_style || '') === 'rainbow' ? ' name-rainbow' : '');
            tr.innerHTML = `<td>${idx + 1}</td>`
                + `<td class="leaderboard-user-cell">`
                + `<button type="button" class="leaderboard-user" data-username="${escapeHtml(username)}"`
                + ` title="点击查看个人信息">`
                + `<img class="leaderboard-avatar" src="${escapeHtml(avatar)}" alt=""`
                + ` onerror="this.onerror=null;this.src='/static/avatars/default.png'">`
                + `<span class="${nameCls}">${escapeHtml(username || '未知玩家')}</span>`
                + `</button></td>`
                + `<td>${wins}</td><td>${losses}</td><td>${winrate}</td>`
                + `<td>${row.longest_streak || 0}</td>`;
            leaderboardTableBody.appendChild(tr);
        });
        bindLeaderboardUserClick();
    }).catch(err => {
        leaderboardTableBody.innerHTML = '';
        leaderboardError.classList.remove('hidden');
        leaderboardError.textContent = '无法加载排行榜：' + err.message;
    });
}

// 排行榜行点击：事件委托只绑一次（表格内容会被整段重建，逐行绑监听会泄漏/漏绑）
function bindLeaderboardUserClick() {
    if (!leaderboardTableBody || leaderboardTableBody.dataset.userClickBound === '1') return;
    leaderboardTableBody.dataset.userClickBound = '1';
    leaderboardTableBody.addEventListener('click', (e) => {
        const btn = e.target && e.target.closest ? e.target.closest('.leaderboard-user') : null;
        if (!btn) return;
        const username = btn.dataset.username;
        if (!username) return;
        if (typeof window.showUserProfile === 'function') window.showUserProfile(username);
    });
}

// ---------------------------------------------------------------------------
// 大厅系统（2026-09-18）。冻结契约见 docs/LOBBY_2026_09_18.md。
// ---------------------------------------------------------------------------
// 与改造前的区别：以前这一页只有一个"数字 + 一句提示"，数字还只在进入页面时
// 拉一次。现在服务端会持续推 lobby_state（订阅/匹配/建房/掉线 + 4 秒兜底），
// 这一页整个由 renderLobbyState() 按最后一份状态重画。
//
// ⚠️ 列表内容**全部**是玩家可控输入（名字、房间名、公屏），插值一律走 escapeHtml。
// 四态（契约 §1.3）：空闲 / 匹配中 / 在房间（建了房在等人，仍可被别人拉走）/ 对局中
const LOBBY_STATUS_TEXT = { idle: '空闲', matching: '匹配中', in_room: '在房间', in_game: '对局中' };

// 大厅里用的玩家名：优先首页输入框（游客），其次 gameState，最后兜底。
function lobbyPlayerName() {
    const typed = playerNameInput && playerNameInput.value ? playerNameInput.value.trim() : '';
    return typed || gameState.playerName || '玩家';
}

// 进入大厅：订阅 + 拉一份状态。幂等（重复进不会重复订阅）。
function showLobby() {
    switchScreen(lobbyScreen);
    const socket = ensureSocket();
    // 先复位按钮状态：真正的排队状态由 match_queued / match_canceled 同步
    if (joinLobbyBtn) joinLobbyBtn.classList.remove('hidden');
    if (leaveLobbyBtn) leaveLobbyBtn.classList.add('hidden');
    if (lobbyRankedBtn) lobbyRankedBtn.classList.remove('hidden');
    gameState.lobbySubscribed = true;
    onSocketReady((s) => {
        s.emit('lobby_subscribe', { player_name: lobbyPlayerName() }, () => {});
    });
    return socket;
}

// 离开大厅页面：退订（否则打对局时还在收大厅广播）。switchScreen 每次都会调它。
function leaveLobbySubscription(nextScreen) {
    if (nextScreen && nextScreen.id === 'lobby-screen') return;
    if (!gameState.lobbySubscribed) return;
    gameState.lobbySubscribed = false;
    gameState.lobbyKey = null;
    if (gameState.socket) gameState.socket.emit('lobby_unsubscribe', {});
}

// 按最后一份 lobby_state 重画整个大厅。
function renderLobbyState(state) {
    if (!state || typeof state !== 'object') return;
    gameState.lobbyState = state;
    if (lobbyPlayerCount) lobbyPlayerCount.textContent = String(state.online_count || 0);
    if (lobbyInLobbyCount) lobbyInLobbyCount.textContent = String(state.lobby_count || 0);
    const queue = state.queue || {};
    if (lobbyQueueCasual) lobbyQueueCasual.textContent = String(queue.casual || 0);
    if (lobbyQueueRanked) lobbyQueueRanked.textContent = String(queue.ranked || 0);
    renderLobbyPlayers(Array.isArray(state.players) ? state.players : []);
    renderLobbyRooms(Array.isArray(state.rooms) ? state.rooms : []);
}

// 在线玩家列表。自己的那一行靠 lobby_hello.key 比对（lobby_state 是广播，
// 服务端没法逐人改 is_me）。
function renderLobbyPlayers(players) {
    if (!lobbyPlayersList) return;
    lobbyPlayersList.innerHTML = '';
    if (!players.length) {
        lobbyPlayersList.innerHTML = '<li class="lobby-empty">当前没有其他在线玩家</li>';
        return;
    }
    players.forEach((p) => {
        const li = document.createElement('li');
        const mine = !!gameState.lobbyKey && p.key === gameState.lobbyKey;
        li.className = 'lobby-player' + (mine ? ' lobby-me' : '');
        li.dataset.username = p.guest ? '' : String(p.name || '');
        const avatar = p.avatar ? String(p.avatar) : '/static/avatars/default.png';
        const nameCls = 'lobby-player-name'
            + (String(p.name_style || '') === 'rainbow' ? ' name-rainbow' : '');
        const status = LOBBY_STATUS_TEXT[p.status] || '空闲';
        const rankIcon = (p.rank && p.rank.tier_id && typeof window.rankIconHtml === 'function')
            ? window.rankIconHtml(p.rank.tier_id, 18) : '';
        const rankLabel = (p.rank && p.rank.label) ? escapeHtml(p.rank.label) : '';
        const title = p.title ? '<span class="lobby-player-title">' + escapeHtml(p.title) + '</span>' : '';
        const guest = p.guest ? '<span class="lobby-player-guest">游客</span>' : '';
        const meTag = mine ? '<span class="lobby-player-me">我</span>' : '';
        li.innerHTML = '<img class="lobby-avatar" src="' + escapeHtml(avatar) + '" alt=""'
            + ' onerror="this.onerror=null;this.src=\'/static/avatars/default.png\'">'
            + '<span class="lobby-player-main">'
            + '<span class="' + nameCls + '">' + escapeHtml(p.name || '游客') + '</span>'
            + meTag + guest + title
            + '</span>'
            + '<span class="lobby-player-meta">'
            + '<span class="lobby-level">Lv.' + String(p.level || 1) + '</span>'
            + '<span class="lobby-rank">' + rankIcon + rankLabel + '</span>'
            + '<span class="lobby-status lobby-status-' + escapeHtml(String(p.status || 'idle')) + '">'
            + escapeHtml(status) + '</span>'
            + '</span>';
        lobbyPlayersList.appendChild(li);
    });
}

// 房间列表：只列等待中、公开、房主仍在线的房间（服务端已经过滤，这里只渲染）。
function renderLobbyRooms(rooms) {
    if (!lobbyRoomsList) return;
    lobbyRoomsList.innerHTML = '';
    if (!rooms.length) {
        lobbyRoomsList.innerHTML = '<li class="lobby-empty">暂无等待中的房间，点下面的「创建房间」开一桌</li>';
        return;
    }
    rooms.forEach((r) => {
        const li = document.createElement('li');
        li.className = 'lobby-room';
        li.innerHTML = '<span class="lobby-room-main">'
            + '<span class="lobby-room-name">' + escapeHtml(r.name || r.room_id) + '</span>'
            + '<span class="lobby-room-host">房主 ' + escapeHtml(r.host || '') + '</span>'
            + '</span>'
            + '<span class="lobby-room-seats">' + String(r.players || 1) + '/' + String(r.capacity || 2) + '</span>'
            + '<button type="button" class="btn secondary lobby-room-join" data-room="'
            + escapeHtml(String(r.room_id || '')) + '">加入</button>';
        lobbyRoomsList.appendChild(li);
    });
}

// 大厅建房：走服务端的 lobby_create_room（内部复用 create_room，不另写一份建房逻辑）
function createLobbyRoom() {
    const name = lobbyRoomNameInput ? lobbyRoomNameInput.value.trim() : '';
    const isPublic = lobbyRoomPublic ? !!lobbyRoomPublic.checked : true;
    onSocketReady((socket) => {
        socket.emit('lobby_create_room', {
            name: name, public: isPublic, player_name: lobbyPlayerName(),
        }, (response) => {
            if (!response || response.status !== 'success') {
                showAlert((response && response.message) || '创建房间失败');
                return;
            }
            gameState.roomId = response.room_id;
            if (customCurrentRoomId) customCurrentRoomId.textContent = response.room_id;
            if (customRoomInfo) customRoomInfo.classList.remove('hidden');
            if (lobbyRoomNameInput) lobbyRoomNameInput.value = '';
            switchScreen(customRoomScreen);
        });
    });
}

// 从大厅加入某个房间（复用既有的 join_room 事件与自定义房间页的展示）
function joinLobbyRoom(roomId) {
    if (!roomId) return;
    onSocketReady((socket) => {
        socket.emit('join_room', { room_id: roomId, player_name: lobbyPlayerName() }, (response) => {
            if (!response || response.status !== 'success') {
                showAlert((response && response.message) || '加入房间失败');
                return;
            }
            gameState.roomId = roomId;
            gameState.playerId = response.player_id;
            if (customCurrentRoomId) customCurrentRoomId.textContent = roomId;
            if (customRoomInfo) customRoomInfo.classList.remove('hidden');
            switchScreen(customRoomScreen);
        });
    });
}

// 公屏渲染。时间戳兜底成 '--:--:--'，别把 ts=0 渲染成 1970 年。
//
// ⚠️ **绝对不要"先清空再填充"**（CLAUDE.md 的硬规矩：凡是先清空再填充的渲染，
//    都要先校验数据、并保证失败时保留上一帧）。这里第一版就踩了：
//    lobby_chat_history 一到就 clearLobbyChat() 再铺历史，而"补发的历史"与
//    "实时推送"**是会重叠的**——自己刚发的那条已经上屏了，紧接着来的历史把它
//    整段冲掉（浏览器工具实测抓到过：A 自己的消息在自己的公屏里消失，
//    而 B 那边看得到）。改法是按服务端的单调序号 seq 合并：
//    历史只**补**缺的（插在最前面），已有的原样留着。
function buildLobbyChatItem(item) {
    if (!item) return null;
    const mine = !!gameState.lobbyKey && item.key === gameState.lobbyKey;
    const div = document.createElement('div');
    div.className = 'lobby-chat-item' + (mine ? ' me' : '');
    // data-key / data-seq 只是排查与去重用，不影响渲染
    div.dataset.key = String(item.key || '');
    div.dataset.seq = item.seq === undefined ? '' : String(item.seq);
    let time = '--:--:--';
    const ts = Number(item.ts || 0);
    if (ts > 0) {
        try {
            time = new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false });
        } catch (e) { /* 时间只是装饰，渲染失败不影响消息本身 */ }
    }
    div.innerHTML = '<span class="lobby-chat-time">' + escapeHtml(time) + '</span>'
        + '<span class="lobby-chat-name">' + escapeHtml(item.name || '游客') + '：</span>'
        + '<span class="lobby-chat-text">' + escapeHtml(item.message || '') + '</span>';
    return div;
}

// 该条是否已经在屏幕上（有 seq 就按 seq 比，没有就退化成"文案+作者"比）
function lobbyChatRendered(item) {
    if (!lobbyChatMessages || !item) return false;
    const seq = item.seq === undefined ? '' : String(item.seq);
    if (seq) return !!lobbyChatMessages.querySelector('.lobby-chat-item[data-seq="' + seq + '"]');
    const text = String(item.message || '');
    return Array.prototype.some.call(
        lobbyChatMessages.querySelectorAll('.lobby-chat-item'),
        (el) => {
            const t = el.querySelector('.lobby-chat-text');
            return el.dataset.key === String(item.key || '') && t && t.textContent === text;
        });
}

function appendLobbyChat(item) {
    if (!lobbyChatMessages || !item) return;
    if (lobbyChatRendered(item)) return;            // 重复投递（历史 ∩ 实时）直接忽略
    const div = buildLobbyChatItem(item);
    if (!div) return;
    lobbyChatMessages.appendChild(div);
    lobbyChatMessages.scrollTop = lobbyChatMessages.scrollHeight;
}

// 补发历史：**只补缺的**，插在现有内容之前（历史一定比实时消息旧）
function applyLobbyChatHistory(messages) {
    if (!lobbyChatMessages) return;
    const frag = document.createDocumentFragment();
    let added = 0;
    (messages || []).forEach((m) => {
        if (!m || lobbyChatRendered(m)) return;
        const div = buildLobbyChatItem(m);
        if (!div) return;
        frag.appendChild(div);
        added += 1;
    });
    if (added) lobbyChatMessages.insertBefore(frag, lobbyChatMessages.firstChild);
    lobbyChatMessages.scrollTop = lobbyChatMessages.scrollHeight;
}

function sendLobbyChat() {
    if (!lobbyChatInput) return;
    const text = lobbyChatInput.value.trim();
    if (!text) return;
    onSocketReady((socket) => {
        socket.emit('lobby_chat_send', { message: text }, (response) => {
            if (response && response.status === 'error') {
                showAlert(response.message || '发送失败');
                return;
            }
            lobbyChatInput.value = '';
        });
    });
}

// 手动刷新（服务端未订阅时会顺带订阅）
function refreshLobby() {
    onSocketReady((socket) => {
        socket.emit('lobby_refresh', {}, () => {});
    });
}

// 快速匹配：走真实的 find_match（后端没有 join_lobby handler）
function joinLobbyMatch() {
    gameState.playerName = lobbyPlayerName();
    onSocketReady((socket) => {
        socket.emit('find_match', { player_name: gameState.playerName, mode: 'casual' }, (response) => {
            if (response && response.status === 'error') showAlert(response.message);
        });
    });
}

// 大厅里的排位匹配：与首页的 #ranked-match 同一条链路，只是入队 mode=ranked
function lobbyRankedMatch() {
    gameState.playerName = lobbyPlayerName();
    onSocketReady((socket) => {
        socket.emit('find_match', { player_name: gameState.playerName, mode: 'ranked' }, (response) => {
            if (response && response.status === 'error') showAlert(response.message);
        });
    });
}

// 取消匹配：走真实的 cancel_match（后端没有 leave_lobby handler）
function leaveLobbyMatch() {
    if (!gameState.socket) return;
    gameState.socket.emit('cancel_match', {
        room_id: gameState.roomId, player_id: gameState.playerId,
    });
}

// 初始化棋盘
function initBoard(boardElement, isEditable = false) {
    boardElement.innerHTML = '';
    for (let y = 0; y < 6; y++) {
        for (let x = 0; x < 6; x++) {
            const cell = document.createElement('div');
            cell.classList.add('cell');
            cell.dataset.x = x;
            cell.dataset.y = y;
            if (isEditable) {
                cell.addEventListener('click', () => handleCellClick(x, y));
            }
            boardElement.appendChild(cell);
        }
    }
}

// 初始化游戏棋盘
function initGameBoards() {
    // 绝处逢生候选格属于【谁的棋盘】——两块棋盘各有自己的 0-5 坐标，画错棋盘会误导攻击。
    // owner 为空（旧载荷 / 已清空）时按"不是我"处理，与修复前的行为保持一致。
    const lastStandIsMine = () => !!(gameState.lastStandOwner && gameState.playerId
        && gameState.lastStandOwner === gameState.playerId);

    // 冻结的 3×3 区域同样按归属画：owner 是受害者，所以区域只画在**受害者的那块棋盘**上。
    // 船上的雪花不受影响（服务端只发给被冻的人，前端照旧画在自己的船上）。
    const frozenArea = gameState.frozenArea;
    const frozenAreaIsMine = !!(frozenArea && frozenArea.owner && gameState.playerId
        && frozenArea.owner === gameState.playerId);
    const inFrozenArea = (x, y) => !!(frozenArea
        && x >= frozenArea.x1 && x <= frozenArea.x2
        && y >= frozenArea.y1 && y <= frozenArea.y2);
    const frozenAreaTitle = () => {
        if (!frozenArea) return '';
        const n = Number(frozenArea.frozen || 0);
        return frozenAreaIsMine
            ? `冻结区域：对方冻结了这片 3×3 区域${n ? '（' + n + ' 艘被冻）' : ''}，被冻的船本回合不提供攻击次数`
            : `冻结区域：你冻结的这片 3×3 区域${n ? '（' + n + ' 艘被冻）' : ''}，区域内对方的船本回合不提供攻击次数`;
    };
    // 初始化玩家棋盘
    gamePlayerBoard.innerHTML = '';
    for (let y = 0; y < 6; y++) {
        for (let x = 0; x < 6; x++) {
            const cell = document.createElement('div');
            cell.classList.add('cell');
            cell.dataset.x = x;
            cell.dataset.y = y;

            // 显示自己的战舰（冻结中的要能一眼看出来：它本回合不提供攻击次数）
            const ownShip = gameState.ships.find(ship => ship.positions.some(pos => pos.x === x && pos.y === y));
            if (ownShip) {
                cell.classList.add('ship');
                // 已沉的船：沉船仍留在 ships 列表里，服务端用 alive 标记死活，
                // 前端据此灰掉（否则棋盘上看不出哪艘已经没了）
                if (ownShip.alive === false) {
                    cell.classList.add('sunk');
                    cell.title = '这艘船已被击沉';
                }
                if (ownShip.frozen) {
                    cell.classList.add('frozen');
                    cell.title = '这艘船被冻结了：本回合不提供攻击次数';
                }
                // 盾牌：仁王之盾一次性挡伤。不画出来的话，盾被打掉时玩家
                // 只会看到一次普通"命中"，还以为自己掉了一艘船。
                if (ownShip.shield) {
                    cell.classList.add('shielded');
                    cell.title = '这艘船带护盾，可抵挡一次伤害';
                }
                // 无敌：钢筋铁骨期间打不沉。不画出来的话，玩家会朝无敌船
                // 白白浪费炮弹，也不知道自己这回合的船其实打不沉。
                if (ownShip.invincible) {
                    cell.classList.add('invincible');
                    cell.title = '这艘船处于无敌状态，本回合打不沉';
                }
            }

            // 显示被攻击的位置
            if (gameState.opponentAttacks.some(attack => attack.x === x && attack.y === y)) {
                const attack = gameState.opponentAttacks.find(a => a.x === x && a.y === y);
                cell.classList.add(attack.hit ? 'hit' : 'miss');
                cell.textContent = attack.hit ? '✕' : '○';
            }

            // 自己因恶魔契约等效果牺牲的船：画叉
            if ((gameState.sacrificedSelf || []).some(p => p.x === x && p.y === y)) {
                cell.classList.add('hit', 'sacrificed');
                cell.textContent = '✕';
            }

            // 对方打过来、被我的护盾挡下的那一炮：画"破盾"标记，不画命中叉。
            // （这一格在他那边不算已攻击，他还能再打一次）
            if ((gameState.shieldBrokenOpponent || []).some(p => p.x === x && p.y === y)) {
                cell.classList.add('shield-broken');
                cell.title = '护盾挡住了这一炮，本回合还能被再打一次';
            }

            // 绝处逢生的候选格（**我的棋盘**上的）：我自己放的那次，唯一一艘必在这几格之一。
            // 修复前这里只写在对手棋盘的循环里 —— 于是自己放绝处逢生时，
            // 属于我棋盘的候选格被画到了对手棋盘上（作者实测反馈）。
            if (lastStandIsMine() && (gameState.lastStandCells || []).some(p => p.x === x && p.y === y)) {
                cell.classList.add('last-stand-candidate');
                if (!cell.textContent) cell.title = '绝处逢生的唯一一艘战舰可能在这一格（你的棋盘）';
            }

            // 冻结区域（**我的棋盘**上）：对方冻了这片 3×3。
            // 只加区域类，绝不加 hit/miss（否则玩家以为这几格打过了/打不了）。
            if (frozenAreaIsMine && inFrozenArea(x, y)) {
                cell.classList.add('frozen-area');
                if (!cell.title) cell.title = frozenAreaTitle();
            }

            gamePlayerBoard.appendChild(cell);
        }
    }

    // 初始化对手棋盘
    opponentBoard.innerHTML = '';
    for (let y = 0; y < 6; y++) {
        for (let x = 0; x < 6; x++) {
            const cell = document.createElement('div');
            cell.classList.add('cell');
            cell.dataset.x = x;
            cell.dataset.y = y;

            // 如果是自己的回合，可以点击攻击
            if (gameState.isMyTurn) {
                // 检查是否已经攻击过
                const alreadyAttacked = gameState.myAttacks.some(attack => attack.x === x && attack.y === y);
                if (!alreadyAttacked) {
                    cell.addEventListener('click', () => handleAttack(x, y));
                }
            }

            // 显示攻击结果
            if (gameState.myAttacks.some(attack => attack.x === x && attack.y === y)) {
                const attack = gameState.myAttacks.find(a => a.x === x && a.y === y);
                cell.classList.add(attack.hit ? 'hit' : 'miss');
                cell.textContent = attack.hit ? '✕' : '○';
            }

            // 对方因恶魔契约等效果牺牲的船：公开信息，同样画叉
            if ((gameState.sacrificedOpponent || []).some(p => p.x === x && p.y === y)) {
                cell.classList.add('hit', 'sacrificed');
                cell.textContent = '✕';
            }

            // 我打过去被对方护盾挡下的那一炮：画"破盾"标记（不是命中叉）。
            // 服务端没把这一格记进"已攻击"，所以它仍然有 click 监听、还能再打。
            if ((gameState.shieldBrokenMine || []).some(p => p.x === x && p.y === y)) {
                cell.classList.add('shield-broken');
                cell.title = '这一炮被护盾挡下，船毫发无伤 —— 本回合还能再打这一格';
            }

            // 绝处逢生的候选格（**对方棋盘**上的）：只有当这批候选格属于对方棋盘时才画这里。
            // ⚠️ 属于我自己棋盘的候选格绝不能画到这块棋盘上 —— 看起来就是"敌方可能在这几格"，
            // 会直接误导我自己的攻击（作者 2026-09-16 实测反馈）。
            // ⚠️ 仍然绝不能画成叉或加 hit/miss 类 —— 那会让玩家以为"已经打过、打不了"。
            if (!lastStandIsMine() && (gameState.lastStandCells || []).some(p => p.x === x && p.y === y)) {
                cell.classList.add('last-stand-candidate');
                if (!cell.textContent) cell.title = '绝处逢生的唯一一艘战舰可能在这一格（对方棋盘）';
            }

            // 冻结区域（**对手棋盘**上）：这片是我冻的 —— 施法方原先什么都看不到，
            // 过一会儿就忘了自己冻的是哪片（作者实测）
            if (!frozenAreaIsMine && inFrozenArea(x, y)) {
                cell.classList.add('frozen-area');
                if (!cell.title) cell.title = frozenAreaTitle();
            }

            // 已被卡牌显形的格子：重绘棋盘后也要保留（否则一次 initGameBoards 就把线索擦没了）
            if ((gameState.revealedCells || []).some(c => c.x === x && c.y === y)) {
                const rc = gameState.revealedCells.find(c => c.x === x && c.y === y);
                cell.classList.add('revealed');
                // 疗愈原地复活的格子用专属标记 + 悬停说明，与雷达显形等区分开
                if (rc && rc.kind === 'heal') {
                    cell.classList.add('revealed-heal');
                    if (!cell.title) cell.title = '疗愈：这艘战舰原地复活，仍在这一格';
                }
            }

            opponentBoard.appendChild(cell);
        }
    }

    applyShenweiHoles();

    // 棋盘刚被重建（innerHTML=''），所有格子上的高亮/监听都没了。
    // 如果此刻正等着玩家选一艘自己的船牺牲（恶魔契约等）或选船加护盾（仁王之盾），
    // 必须把高亮补回去 —— 否则弹窗还在、格子却点不动：
    //   · 伤害结算的 attack_result 会重绘棋盘，而 sacrifice_request 比它先到；
    //   · 仁王之盾是在 chain_resolved 处理器里开的选船面板，而服务端紧接着就推
    //     ships_updated / player_ships_updated（同样触发本函数），玩家的实测现象
    //     就是「点不了任何有船的格子、也没有绿色高亮」。
    if (typeof paintSacrificeCells === 'function') paintSacrificeCells();
    if (typeof paintRenwangCells === 'function') paintRenwangCells();
}

// 神威！：把被扣掉的 3x3 区域在棋盘上“挖空”显示
function applyShenweiHoles() {
    const holes = gameState.shenweiHoles || [];
    document.querySelectorAll('.cell.shenwei-hole').forEach(c => c.classList.remove('shenwei-hole'));
    holes.forEach(h => {
        const boardEl = (h.player === gameState.playerId) ? gamePlayerBoard : opponentBoard;
        if (!boardEl) return;
        for (let y = h.y1; y <= h.y2; y++) {
            for (let x = h.x1; x <= h.x2; x++) {
                const cell = boardEl.querySelector(`.cell[data-x="${x}"][data-y="${y}"]`);
                if (cell) cell.classList.add('shenwei-hole');
            }
        }
    });
}

// 随机摆放战舰
function randomizeShips() {
    // 清空当前所有战舰
    gameState.ships = [];
    gameState.placedShips = 0;

    // 清空棋盘显示
    playerBoard.querySelectorAll('.cell').forEach(cell => {
        cell.classList.remove('ship');
    });

    // 生成maxShips个不重复的随机位置
    const positions = new Set();
    while (positions.size < gameState.maxShips) {
        const x = Math.floor(Math.random() * 6);
        const y = Math.floor(Math.random() * 6);
        positions.add(`${x},${y}`);
    }

    // 放置战舰
    positions.forEach(pos => {
        const [x, y] = pos.split(',').map(Number);

        // 添加新战舰（1x1大小）
        gameState.ships.push({
            positions: [{ x, y }],
            hits: []
        });

        gameState.placedShips++;

        // 更新界面，显示战舰
        const cell = playerBoard.querySelector(`[data-x="${x}"][data-y="${y}"]`);
        cell.classList.add('ship');
    });

    // 更新放置计数
    shipsPlaced.textContent = gameState.placedShips;

    // 显示确认按钮
    confirmShipsBtn.classList.remove('hidden');
}

// 处理棋盘单元格点击（放置/移除战舰）
function handleCellClick(x, y) {
    // 检查该位置是否已经放置了战舰
    const shipIndex = gameState.ships.findIndex(ship =>
        ship.positions.some(pos => pos.x === x && pos.y === y)
    );

    if (shipIndex !== -1) {
        // 移除已放置的战舰
        gameState.ships.splice(shipIndex, 1);
        gameState.placedShips--;
        shipsPlaced.textContent = gameState.placedShips;

        // 更新界面，移除战舰显示
        const cell = playerBoard.querySelector(`[data-x="${x}"][data-y="${y}"]`);
        cell.classList.remove('ship');

        // 如果之前显示了确认按钮，检查是否需要隐藏
        if (gameState.placedShips < gameState.maxShips) {
            confirmShipsBtn.classList.add('hidden');
        }
    } else {
        // 检查是否已经放置了最大数量的战舰
        if (gameState.placedShips >= gameState.maxShips) return;

        // 添加新战舰（1x1大小）
        gameState.ships.push({
            id: Date.now(),
            positions: [{ x, y }],
            hits: []
        });

        gameState.placedShips++;
        shipsPlaced.textContent = gameState.placedShips;

        // 更新界面
        const cell = playerBoard.querySelector(`[data-x="${x}"][data-y="${y}"]`);
        cell.classList.add('ship');

        // 如果放置了最大数量的战舰，显示确认按钮
        if (gameState.placedShips === gameState.maxShips) {
            confirmShipsBtn.classList.remove('hidden');
        }
    }
}

// 确认战舰放置
function confirmShipPlacement() {
    console.log('确认放置按钮被点击');
    console.log('gameState.socket:', gameState.socket);
    console.log('gameState.roomId:', gameState.roomId);
    console.log('gameState.playerId:', gameState.playerId);
    console.log('gameState.ships:', gameState.ships);

    if (!gameState.socket) {
        console.error('socket连接为null');
        showAlert('socket连接为null，请重新创建或加入房间');
        return;
    }

    if (!gameState.roomId) {
        console.error('roomId为null');
        showAlert('roomId为null，请重新创建或加入房间');
        return;
    }

    if (!gameState.playerId) {
        console.error('playerId为null');
        showAlert('playerId为null，请重新创建或加入房间');
        return;
    }

    gameState.socket.emit('place_ships', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        ships: gameState.ships
    }, (response) => {
        console.log('place_ships响应:', response);
        if (response.status === 'success') {
            console.log('Ships placed successfully');
        } else {
            console.error('Ships placement failed:', response.message);
            showAlert('放置战舰失败：' + response.message);
        }
    });
}

// 处理猜拳选择
function handleRPSChoice(choice) {
    gameState.socket.emit('rps_choice', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        choice: choice
    }, (response) => {
        if (response.status === 'success') {
            console.log('RPS choice sent:', choice);
        }
    });
}

// 处理攻击
function handleAttack(x, y) {
    // 检查是否正在进行魔法卡目标选择，如果是则不执行攻击
    if (gameState.currentMagicCard) return;

    if (!gameState.isMyTurn) return;
    if (freezeAlert()) return;

    // 教皇旨意：攻击次数被压成 0，必须【弃一张魔法卡换 2 次攻击】。
    // ⚠️ 只有"次数为 0"时才拦下来引导去弃卡；已经换到次数之后就【走正常攻击】——
    // 作者裁定："弃置魔法卡之后应该是让自己攻击次数+2 然后可以和正常攻击逻辑一样"。
    // 旧实现是拿到次数也一律走 papal_attack（服务端对着同一个格子一次打两发），
    // 玩家既选不了目标，也走不到这里的正常路径。
    if (gameState.fieldMagic === '教皇旨意') {
        const left = parseInt(attacksRemaining.textContent, 10) || 0;
        if (left <= 0) {
            if (!gameState.hand || gameState.hand.length === 0) {
                showAlert('教皇旨意：攻击次数为 0，需要弃一张魔法卡换 2 次攻击，但你没有手牌');
                return;
            }
            showPapalDiscardChoice();
            return;
        }
        // 有次数了 → 落到下面走普通攻击
    }

    // 检查当前是否为战斗阶段
    if (gameState.currentPhase !== 'battle') {
        showAlert('当前不是战斗阶段');
        return;
    }
    if (attacksRemaining.textContent === "0") {
        showAlert('无剩余攻击次数');
        return;
    }

    gameState.socket.emit('attack', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        x: x,
        y: y
    }, (response) => {
        if (response.status === 'error') {
            showAlert(response.message);
        }
    });
}

// 更新攻击显示
function updateAttackDisplay(result) {
    const mine = result.attacker === gameState.playerId;

    // 这一炮被「仁王之盾」挡下：不算"已攻击"，改记成"破盾"标记。
    //
    // ⚠️ 关键差别：普通命中会把坐标推进 myAttacks/opponentAttacks，
    // 而那两个数组同时决定了【格子还能不能点】（initGameBoards 只给
    // "没打过的格子"绑 click）。盾挡下的这一炮船毫发无伤，把它算成"已打过"
    // 就等于白送对手一个永久免打区（作者实测反馈：格子变红叉、同一回合再也打不了）。
    if (result.shield_blocked) {
        const sink = mine ? gameState.shieldBrokenMine : gameState.shieldBrokenOpponent;
        if (!sink.some(p => p.x === result.x && p.y === result.y)) {
            sink.push({ x: result.x, y: result.y });
        }
        if (mine) {
            yourShips.textContent = result.attacker_remaining_ships;
            opponentShips.textContent = result.defender_remaining_ships;
        } else {
            yourShips.textContent = result.defender_remaining_ships;
            opponentShips.textContent = result.attacker_remaining_ships;
        }
        gameState.lastAttack = {
            x: result.x, y: result.y, attacker: result.attacker,
            hit: true, shipSunk: false, shieldBlocked: true
        };
        initGameBoards();
        return;
    }

    // 如果是自己的攻击
    if (mine) {
        // 这一格真挨了一炮：把之前的"破盾"标记清掉（现在是真实结果了）
        gameState.shieldBrokenMine = (gameState.shieldBrokenMine || [])
            .filter(p => !(p.x === result.x && p.y === result.y));
        gameState.myAttacks.push({
            x: result.x,
            y: result.y,
            hit: result.hit
        });
        // 更新自己和对手的剩余战舰数
        yourShips.textContent = result.attacker_remaining_ships;
        opponentShips.textContent = result.defender_remaining_ships;
    } else {
        gameState.shieldBrokenOpponent = (gameState.shieldBrokenOpponent || [])
            .filter(p => !(p.x === result.x && p.y === result.y));
        // 如果是对手的攻击
        gameState.opponentAttacks.push({
            x: result.x,
            y: result.y,
            hit: result.hit
        });
        // 更新自己和对手的剩余战舰数
        yourShips.textContent = result.defender_remaining_ships;
        opponentShips.textContent = result.attacker_remaining_ships;
    }

    // 记录最近一次攻击坐标与来源，供溅射动画使用。
    // shipSunk 也要存：饮血的发动前提是"击沉"而非"命中"，
    // 少了它前端没法在出牌前拦掉，只能等服务端拒绝 —— 而那时牌已经被扣掉了。
    gameState.lastAttack = {
        x: result.x,
        y: result.y,
        attacker: result.attacker,
        hit: result.hit,
        shipSunk: !!result.ship_sunk
    };

    // 更新棋盘显示
    initGameBoards();
}
// 更新回合指示器
function updateTurnIndicator(currentAttacker, remainingAttacks) {
    gameState.isMyTurn = currentAttacker === gameState.playerId;
    currentPlayer.textContent = gameState.isMyTurn ? '你' : '对手';
    attacksRemaining.textContent = remainingAttacks;
    initGameBoards(); // 重新初始化棋盘以更新可点击状态
}

// 音效调用壳：sfx.js 没加载 / 浏览器不支持 Web Audio 时静默降级，不影响对局
function playSfx(name) {
    try {
        if (window.sfx && typeof window.sfx.play === 'function') window.sfx.play(name);
    } catch (e) { /* ignore */ }
}

// 获取猜拳名称
function getRPSName(choice) {
    const names = {
        'rock': '石头',
        'paper': '布',
        'scissors': '剪刀'
    };
    return names[choice] || choice;
}

// 显示登录/注册屏幕

function showLogin() {
    if (!loginModal) return;
    loginModal.classList.remove('hidden');
}

function hideLogin() {
    if (!loginModal) return;
    loginModal.classList.add('hidden');
}

function showRegister() {
    if (!registerModal) return;
    registerModal.classList.remove('hidden');
}

function hideRegister() {
    if (!registerModal) return;
    registerModal.classList.add('hidden');
}

// 从 fetch 返回的页面文本中提取服务端 flash 提示（fetch 跟随重定向会消费掉 session 中的 flash，
// 因此必须在返回的 HTML 里就地取出并展示，否则刷新后提示会丢失）
function extractFlashMessages(htmlText) {
    try {
        const doc = new DOMParser().parseFromString(htmlText, 'text/html');
        const toast = doc.getElementById('flash-toast');
        if (!toast) return { messages: [], hasError: false };
        const items = Array.from(toast.querySelectorAll('.flash-item'));
        return {
            messages: items.map(el => el.textContent.trim()).filter(Boolean),
            hasError: items.some(el => el.classList.contains('flash-error') || el.classList.contains('flash-danger') || el.classList.contains('flash-warning'))
        };
    } catch (e) {
        return { messages: [], hasError: false };
    }
}

// 登录提交处理
async function handleLoginSubmit() {
    const username = loginUsernameInput.value.trim();
    const password = loginPasswordInput.value;
    if (!username || !password) {
        showMessage('用户名和密码不能为空', { type: 'warning' });
        return;
    }
    try {
        const resp = await fetch('/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ username, password }),
            credentials: 'same-origin'
        });
        const text = await resp.text();
        // 登录成功：服务端重定向到了非 /login 页面
        if (resp.redirected && new URL(resp.url).pathname !== '/login') {
            window.location.href = resp.url;
            return;
        }
        // 失败：就地展示服务端 flash 提示
        const flash = extractFlashMessages(text);
        showMessage(flash.messages.join('；') || '用户名或密码错误', { type: flash.hasError ? 'error' : 'error', duration: 4000 });
    } catch (err) {
        showMessage('登录失败，请稍后重试', { type: 'error' });
    }
}

// 注册提交处理
async function handleRegisterSubmit() {
    const username = registerUsernameInput.value.trim();
    const password = registerPasswordInput.value;
    if (!username || !password) {
        showMessage('用户名和密码不能为空', { type: 'warning' });
        return;
    }
    if (username.length < 3) {
        showMessage('用户名长度至少 3 位', { type: 'warning' });
        return;
    }
    if (password.length < 6) {
        showMessage('密码长度至少 6 位', { type: 'warning' });
        return;
    }
    try {
        const resp = await fetch('/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ username, password }),
            credentials: 'same-origin'
        });
        const text = await resp.text();
        // 注册成功：服务端重定向到了非 /register 页面
        if (resp.redirected && new URL(resp.url).pathname !== '/register') {
            window.location.href = resp.url;
            return;
        }
        // 失败：就地展示服务端 flash 提示
        const flash = extractFlashMessages(text);
        showMessage(flash.messages.join('；') || '注册失败，请稍后重试', { type: 'error', duration: 4000 });
    } catch (err) {
        showMessage('注册失败，请稍后重试', { type: 'error' });
    }
}

// 重置游戏
/**
 * 匹配成功的 5 秒等待界面里显示对手的**称号 / 标签 / 等级**。
 *
 * 数据来自公开的 `/user_stats`（与名片、排行榜同一份来源 —— 不新开接口）。
 * 5 秒内足够取回；失败/游客对手（查不到这个人）就清空，不打断倒计时。
 *
 * ⚠️ **只用接口给的名字，不去调前端的映射函数**：`profileTitleName` /
 *    `profileTagNames` 声明在名片渲染那个函数作用域里，模块级函数够不到 ——
 *    第一版就是这么写的，结果是"名字有了、标签一个不显示"，而且因为跑在
 *    `.then()` 里连异常都不显眼（同一天里第二次踩这个作用域的坑）。
 *    现在服务端把 `title_name` 与 `tag_names` 直接下发，这里只负责拼 DOM。
 */
function showOpponentChips(username) {
    const box = document.getElementById('opponent-chips');
    if (!box) return;
    box.innerHTML = '';
    box.classList.add('hidden');
    if (!username) return;
    fetch('/user_stats?username=' + encodeURIComponent(username), { headers: { 'Accept': 'application/json' } })
        .then(r => (r.ok ? r.json() : null))
        .then(d => {
            const s = (d && d.stats) || null;
            if (!s) return;
            const parts = [];
            const lv = s.level_info && Number(s.level_info.level);
            if (lv) parts.push('<span class="match-chip lv">Lv.' + escapeHtml(String(lv)) + '</span>');
            const title = String(s.title_name || '');
            if (title) parts.push('<span class="match-chip title">' + escapeHtml(title) + '</span>');
            // 段位 chip（段位批）：**对方关掉「段位公开」时接口给的是 null**，
            // 这时不显示这一条（也**不显示「隐藏」字样**去挤掉别的 chip）。
            // 文案直接用服务端的 `label`（`水手长Ⅱ 90分` / `船长Ⅲ 2300分 #60` / `大舰长 #20`）。
            const rank = (s.rank_info && typeof s.rank_info === 'object') ? s.rank_info : null;
            if (rank && Number(s.show_rank) !== 0) {
                const label = rankLabelOf(rank);
                if (label) {
                    parts.push('<span class="match-chip rank">' + rankIconMarkup(rank.tier_id, 24)
                        + '<span class="rank-chip-text">' + escapeHtml(label) + '</span></span>');
                }
            }
            // tag_names 是服务端给的中文名；老接口没给就退回裸 id（总比不显示强）
            const tagNames = Array.isArray(s.tag_names) && s.tag_names.length
                ? s.tag_names : (Array.isArray(s.tags) ? s.tags : []);
            tagNames.forEach(t => {
                if (t) parts.push('<span class="match-chip tag">' + escapeHtml(String(t)) + '</span>');
            });
            box.innerHTML = parts.join('');
            box.classList.toggle('hidden', parts.length === 0);
        })
        .catch(() => { /* 取不到就算了：等待界面照常倒计时 */ });
}

/**
 * 匹配等待界面里**自己的段位**（`#match-self-rank`）。
 *
 * 数据来自 `/api/profile`，**页面加载时取一次缓存**（`loadMyRankInfo()`）——
 * 那 5 秒倒计时里绝不现拉接口。游客 / 取不到 → 整块隐藏（不显示假段位）。
 *
 * ⚠️ 模块级函数：`#opponent-chips` 的同一个位置在 `game_state` 处理器里被调用，
 *    而那个处理器够不到 `bindEventListeners()` 内部（本项目的老坑）。
 */
function showMyRankChip() {
    const box = document.getElementById('match-self-rank');
    if (!box) return;
    const paint = (info) => {
        if (!info || typeof info !== 'object') {
            box.innerHTML = '';
            box.classList.add('hidden');
            return;
        }
        const label = rankLabelOf(info);
        if (!label) { box.innerHTML = ''; box.classList.add('hidden'); return; }
        box.innerHTML = '<span class="match-chip rank self">' + rankIconMarkup(info.tier_id, 24)
            + '<span class="rank-chip-text">你 ' + escapeHtml(label) + '</span></span>';
        box.classList.remove('hidden');
    };
    if (myRankInfo) { paint(myRankInfo); return; }
    if (myRankInfoLoaded) { paint(null); return; }   // 拉过了就是没有（游客 / 失败）
    loadMyRankInfo().then(() => {
        // 复用同一次请求（不会因为这里再拉一次接口）
        if (myRankInfo) paint(myRankInfo); else paint(null);
    });
}

function resetGame() {
    // 新一局开始：清掉上一局的「本局刚解锁」缓冲与经验 / 段位动画世代
    pendingUnlockBadges = [];
    renderAchievementUnlockPanel();
    xpAnimToken++;                     // 作废上一局的滚动动画（避免它接着改新一局的条）
    hideRankGainPanel();               // 段位面板同理（含作废它的动画）
    const xpPanel = document.getElementById('xp-gain-panel');
    if (xpPanel) xpPanel.classList.add('hidden');
    // 断开socket连接（如果存在）
    if (gameState.socket) {
        gameState.socket.disconnect();
        gameState.socket = null;
    }

    // 重置游戏状态
    gameState = {
        socket: null,
        playerId: null,
        roomId: null,
        playerName: playerNameInput.value || '玩家',
        ships: [],
        placedShips: 0,
        isMyTurn: false,
        myAttacks: [],
        opponentAttacks: [],
        lastAttack: null,
        currentPhase: 'preparation',
        currentAttacker: null,
        hand: [],
        opponentHand: [],
        chain: [],
        fieldMagic: null
    };

    // 直接重新加载页面，确保完全重置
    window.location.href = '/';
}

// 在初始化时调用按钮设置
window.addEventListener('load', () => {
    init();
    setupPhaseButtons(); // 添加这行
    initCardPreview(); // 初始化卡牌预览功能
    // 首页「Lv.N + 经验条」：登录了才显示（游客没有等级）。
    // 放在 load 之后异步取，取不到就把整块藏起来（绝不挡住首页）。
    refreshMyLevelStrip();
    // 自己的段位（段位批）：**也在这里取一次**并缓存 —— 匹配成功的 5 秒等待界面
    // 要显示自己的段位，而那时候现拉接口会跟倒计时抢时间。
    loadMyRankInfo();
});


// 结束阶段默认禁止使用魔法卡，但以下卡设计上就在结束阶段发动。
// （服务端 server.py 的 END_PHASE_PLAYABLE 有一份对应名单，改动需同步。）
const END_PHASE_PLAYABLE_CARDS = ['Freezing！'];

// 是否为「先手」（猜拳胜者）。判定条件与后端 freezing_block_reason 保持一致，
// 否则会出现「前端点得下去、后端拒绝」的割裂体验。
function isFirstPlayer() {
    const order = gameState.attackOrder || [];
    return order.length > 0 && order[0] === gameState.playerId;
}

// 绝处逢生是否正在生效：生效回合内自己的其余魔法卡全部无效
// （服务端 can_play_magic_card 第一条就拦这个，前端要给出同样的理由）。
//
// ⚠️ 绝处逢生在服务端是【两个】标记，生命周期不同：
//   · last_stand     → 锁卡，只持续发动回合
//   · last_stand_win → 击杀即胜，活到对局结束
// 两个标记的角标显示名都含"绝处逢生"，**所以绝不能靠卡名匹配**：
// 拿名字判断的话，"击杀即胜"会一直亮着，前端就以为魔法卡还被锁着 ——
// 玩家点卡被本地拒掉、弹"绝处逢生生效中"，而服务端其实放行了。
// 这里一律认标记名（服务端 room_sync 下发的布尔字段 / 角标对象的 key）。
//
// 认三种下发口径（老客户端 / 老快照升级瞬间也要能用）：
//   · room_sync（重连快照）        → last_stand_lock 布尔字段
//   · room_sync 的 effect_badges   → 角标对象的 key
//   · active_effects 事件          → 中文标签，退化为"绝处逢生·封锁魔法卡"
// 只读游戏状态、不改它，纯判定。
function _effectMarkerSet() {
    const out = new Set();
    const push = (v) => {
        if (v === null || v === undefined) return;
        if (typeof v === 'string') { if (v) out.add(v); return; }
        if (typeof v === 'object') {
            if (v.key) out.add(String(v.key));
            if (v.name) out.add(String(v.name));
        }
    };
    (Array.isArray(gameState.activeEffects) ? gameState.activeEffects : []).forEach(push);
    (Array.isArray(gameState.activeEffectsSelf) ? gameState.activeEffectsSelf : []).forEach(push);
    return out;
}

function isLastStandActive() {
    if (gameState.lastStandLock === true) return true;
    const markers = _effectMarkerSet();
    // 标记名精确匹配。老口径 'last_stand' 认；新的 'last_stand_win' **不认**。
    if (markers.has('last_stand') || markers.has('绝处逢生·封锁魔法卡')) return true;
    // 兜底：只有在"新口径标记一个都没出现"时才按旧卡名判断，
    // 免得升级瞬间（还没收到 room_sync 的新字段）把门禁整个放开。
    if (!markers.has('last_stand_win') && !markers.has('绝处逢生·击杀即胜')) {
        return markers.has('绝处逢生');
    }
    return false;
}

// 修改canPlayCard函数
function canPlayCard(card) {
    // 绝处逢生生效中：自己的其余魔法卡一律不能使用。
    // 这条必须排在速阶判定之前 —— 否则速阶1/2会被下面的阶段判断拒掉，
    // 玩家看到的是「当前阶段不允许使用速阶1」这种与真实原因无关的提示。
    if (isLastStandActive()) {
        return false;
    }
    // 特例：Freezing！ 只能在自己先手回合的结束阶段发动
    if (END_PHASE_PLAYABLE_CARDS.indexOf(card.name) >= 0) {
        return isFirstPlayer() &&
            gameState.currentPhase === 'end' &&
            gameState.currentAttacker === gameState.playerId;
    }
    // ⚠️ 速阶一律先转成数字再比较。
    // 此前写的是 card.speed === 1 / === 2 / === 3（严格相等）：
    // 只要 card.speed 是字符串 "2"（或 undefined），三个分支全部落空，
    // 函数直接掉到最后的 return false —— 于是【本来能用的卡被前端拦下】，
    // 并弹出「当前阶段preparation不允许使用速阶2」这种冤枉阶段的提示。
    // 服务端 can_play_magic_card 用的是 int(card.speed)，两边口径必须一致。
    // 实测复现：tools/diag_bomb_alert.mjs 里 speed 传 "2" 时
    // 准备阶段 + 自己回合的「轰炸」被判为不可用。
    const speed = Number(card.speed);
    // 速阶1: 只能在自己的准备阶段使用
    if (speed === 1) {
        return gameState.currentPhase === 'preparation' && gameState.currentAttacker === gameState.playerId;
    }
    // 速阶2: 可以在自己的准备阶段和战斗阶段使用
    else if (speed === 2) {
        return (gameState.currentPhase === 'preparation' || gameState.currentPhase === 'battle') &&
            gameState.currentAttacker === gameState.playerId;
    }
    // 速阶3: 任何时候都可以使用
    else if (speed === 3) {
        return true;
    }
    // 速阶读不出来（数据缺失）不能当作"不允许"：放行给服务端裁定，
    // 服务端有权威校验；这里静默拦下只会让玩家看到一条与事实不符的提示。
    return true;
}

// 依赖「自己上一发攻击」的卡是否能发动。返回 null 表示可以；否则返回原因文案。
// 与服务端 _last_attack_requirement_reason 保持同一口径：
//   · 饮血     —— 须【击沉】（卡面：可在击沉对方一艘战舰后选择使用）
//   · 溅射     —— 须【击中】
//   · 雷达子弹 —— 须【击中】
// ⚠️ 饮血此前漏在这里：它只在服务端结算时才判，而那时牌已经离手，失败也不退还。
function afterHitBlockReason(card) {
    if (!card) return null;
    const needsLastAttack = card.name === '饮血' || card.name === '溅射' || card.name === '雷达子弹';
    if (!needsLastAttack) return null;

    const last = gameState.lastAttack;
    if (!last || last.attacker !== gameState.playerId) {
        return '你这一局还没有攻击过';
    }
    if (card.name === '饮血') {
        if (!last.shipSunk) return '需要你先击沉对方一艘战舰';
        return null;
    }
    if (!last.hit) return '需要你上一发攻击命中对方';
    return null;
}

// 限制需命中后才能发动的卡（保留旧签名供既有调用点使用）
function canPlayAfterHit(card) {
    return afterHitBlockReason(card) === null;
}

// 添加魔法卡目标选择UI
function showMagicTargetSelection(card, index) {
    // 自愈：上次选区若没清理干净，先收尾（否则 selectingOnBoard 卡住，界面出不来又关不掉）
    if (typeof gameState.selectionCleanup === 'function') {
        try { gameState.selectionCleanup(); } catch (_) { }
        gameState.selectionCleanup = null;
    }
    gameState.selectingOnBoard = false;
    document.querySelectorAll('.magic-target-prompt').forEach(el => el.remove());
    document.querySelectorAll('.area-picker-bar').forEach(el => el.remove());
    document.querySelectorAll('.cell.selection-highlight').forEach(c => c.classList.remove('selection-highlight'));

    // 记录当前待选卡和索引，供确认时使用
    gameState.currentMagicCard = card;
    gameState.currentCardIndex = index;

    const targetPrompt = document.createElement('div');
    targetPrompt.className = 'magic-target-prompt';

    const descriptor = needsTargetSelection(card.name);

    if (!descriptor) {
        showAlert('此卡不需要选择目标');
        return;
    }

    // Helper to cleanup prompt and selection mode
    function cleanupPrompt() {
        if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
        if (typeof gameState.selectionCleanup === 'function') {
            gameState.selectionCleanup();
            gameState.selectionCleanup = null;
        }
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
        gameState.pendingChainCard = null;
        gameState.pendingPriorityCard = null;
        gameState.pendingEffectChoice = null;
    }

    // AREA selection (square) —— 点选定位 + 确认，触摸可用
    if (descriptor.type === 'area') {
        const size = descriptor.size;
        // 提示与确认合并在同一条浮动条上。
        // 此前这里会再挂一个 .magic-target-prompt 裸 div，而那个类名当时
        // 【没有任何 CSS】—— 等于玩家只看得到一条确认条，不知道要点棋盘。
        const picker = createBoardAreaPicker(opponentBoard, size, (areaObj) => {
            confirmMagicTarget(areaObj);
            cleanupPrompt();
        }, cleanupPrompt, {
            title: `在对手棋盘上选择 ${size}×${size} 区域`,
            hint: '点一下棋盘定位，可以随时改点；确认后生效',
        });
        gameState.selectionCleanup = picker ? picker.cleanup : null;
        return;
    }

    // 神威！—— 先选己方/对方棋盘，再点选 3x3 区域
    if (descriptor.type === 'shenwei') {
        targetPrompt.innerHTML = `
            <h3>神威！— 选择作用棋盘</h3>
            <p class="magic-hint">己方：仅除外与回归；对方：区域仅 1 艘船时直接击沉</p>
            <div class="shenwei-board-picker">
                <button id="shenwei-pick-self">己方棋盘</button>
                <button id="shenwei-pick-opp">对方棋盘</button>
            </div>
            <div style="text-align:center;margin-top:10px;">
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);
        document.getElementById('cancel-target').addEventListener('click', cleanupPrompt);
        document.getElementById('shenwei-pick-self').addEventListener('click', () => {
            targetPrompt.innerHTML = `
                <h3>神威！— 在己方棋盘点选 3x3 区域</h3>
                <p class="magic-hint">点一下定位区域，再点「确认」</p>
            `;
            const picker = createBoardAreaPicker(gamePlayerBoard, 3, (areaObj) => {
                confirmMagicTarget(Object.assign({ board: 'self' }, areaObj));
                cleanupPrompt();
            }, cleanupPrompt);
            gameState.selectionCleanup = picker ? picker.cleanup : null;
        });
        document.getElementById('shenwei-pick-opp').addEventListener('click', () => {
            targetPrompt.innerHTML = `
                <h3>神威！— 在对方棋盘点选 3x3 区域</h3>
                <p class="magic-hint">点一下定位区域，再点「确认」</p>
            `;
            const picker = createBoardAreaPicker(opponentBoard, 3, (areaObj) => {
                confirmMagicTarget(Object.assign({ board: 'opponent' }, areaObj));
                cleanupPrompt();
            }, cleanupPrompt);
            gameState.selectionCleanup = picker ? picker.cleanup : null;
        });
        return;
    }

    // LINE selection (row or column) e.g., 轰炸 — 支持拖拽与方向切换
    if (descriptor.type === 'line') {
        // ⚠️ 样式统一在 style.css 的「范围选择的选中态」一节里定义。
        // 这里原本会注入一段 <style id="magic-selection-styles">，而下面的
        // 「连选」分支用的是【同一个 id】—— 谁先打开谁生效，后打开的那种模式
        // 样式永远不生效（实测：先开轰炸再开硫磺火焰，绿色变成了橙红色）。
        targetPrompt.innerHTML = `
            <h3>拖拽或点击选择一整行/列（拖拽时松开确认）</h3>
            <p id="line-picker-info" class="selection-info pending">把鼠标移到棋盘上，或拖拽到目标行/列</p>
            <div class="magic-selection-controls">
                <button id="toggle-line-dir">方向：行</button>
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);

        const boardEl = opponentBoard;
        if (!boardEl) return;
        gameState.selectingOnBoard = true;

        let mode = 'row'; // 'row' or 'col'
        const toggleBtn = document.getElementById('toggle-line-dir');
        toggleBtn.addEventListener('click', () => {
            mode = mode === 'row' ? 'col' : 'row';
            toggleBtn.textContent = `方向：${mode === 'row' ? '行' : '列'}`;
            const info = document.getElementById('line-picker-info');
            if (info) {
                info.className = 'selection-info pending';
                info.textContent = `当前方向：${mode === 'row' ? '整行' : '整列'}`;
            }
        });

        const cells = Array.from(boardEl.querySelectorAll('.cell'));
        let isMouseDown = false;
        let lastIndex = null;

        function clearHighlights() {
            cells.forEach(c => c.classList.remove('magic-selection-overlay', 'col', 'sel-mode-line'));
        }

        function highlightIndex(idx) {
            clearHighlights();
            if (mode === 'row') {
                boardEl.querySelectorAll(`.cell[data-y="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay', 'sel-mode-line'));
            } else {
                boardEl.querySelectorAll(`.cell[data-x="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay', 'col', 'sel-mode-line'));
            }
            // 说清楚落在哪一行/列 —— 旧实现只有一片几乎看不见的淡色，玩家无法确认落点。
            const info = document.getElementById('line-picker-info');
            if (info) {
                info.className = 'selection-info';
                info.innerHTML = '<span class="sel-dot"></span>' +
                    (mode === 'row'
                        ? `已选中：第 ${idx + 1} 行（整行 6 格）`
                        : `已选中：第 ${idx + 1} 列（整列 6 格）`);
            }
        }

        function confirmIndex(idx) {
            if (mode === 'row') confirmMagicTarget({ target_line: { type: 'row', index: idx } });
            else confirmMagicTarget({ target_line: { type: 'col', index: idx } });
            cleanupAll();
        }

        cells.forEach(cell => {
            const mx = parseInt(cell.dataset.x, 10);
            const my = parseInt(cell.dataset.y, 10);

            const onMouseDown = (e) => {
                e.preventDefault();
                e.stopPropagation();
                isMouseDown = true;
                lastIndex = mode === 'row' ? my : mx;
                highlightIndex(lastIndex);
                // attach a global mouseup to capture end of drag
                const onUp = (ev) => {
                    if (isMouseDown) {
                        confirmIndex(lastIndex);
                    }
                    isMouseDown = false;
                    window.removeEventListener('mouseup', onUp);
                };
                window.addEventListener('mouseup', onUp);
            };

            const onEnter = () => {
                if (isMouseDown) {
                    lastIndex = mode === 'row' ? my : mx;
                    highlightIndex(lastIndex);
                } else {
                    // hover preview
                    const idx = mode === 'row' ? my : mx;
                    highlightIndex(idx);
                }
            };

            const onLeave = () => {
                if (!isMouseDown) clearHighlights();
            };

            // click fallback: open small confirm box
            const onClick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                const idx = mode === 'row' ? my : mx;
                const confirmBox = document.createElement('div');
                confirmBox.className = 'inline-confirm';
                confirmBox.style.position = 'absolute';
                confirmBox.style.left = (e.pageX + 8) + 'px';
                confirmBox.style.top = (e.pageY + 8) + 'px';
                confirmBox.innerHTML = `
                    <div>确认轰炸</div>
                    <button id="confirm-line">确认 (${mode === 'row' ? '轰炸整行' : '轰炸整列'})</button>
                    <button id="cancel-line">取消</button>
                `;
                document.body.appendChild(confirmBox);
                document.getElementById('confirm-line').addEventListener('click', () => {
                    confirmIndex(idx);
                    cleanupConfirm();
                });
                document.getElementById('cancel-line').addEventListener('click', () => {
                    cleanupConfirm();
                });

                function cleanupConfirm() {
                    if (document.body.contains(confirmBox)) document.body.removeChild(confirmBox);
                }
            };

            cell.addEventListener('mousedown', onMouseDown, true);
            cell.addEventListener('mouseenter', onEnter);
            cell.addEventListener('mouseleave', onLeave);
            cell.addEventListener('click', onClick, true);
            // store for cleanup
            (cell._magicHandlers = cell._magicHandlers || []).push({
                type: 'line',
                handlers: { onMouseDown, onEnter, onLeave, onClick }
            });
        });

        function cleanupAll() {
            cells.forEach(cell => {
                if (cell._magicHandlers) {
                    cell._magicHandlers.filter(h => h.type === 'line').forEach(h => {
                        const { onMouseDown, onEnter, onLeave, onClick } = h.handlers;
                        cell.removeEventListener('mousedown', onMouseDown, true);
                        cell.removeEventListener('mouseenter', onEnter);
                        cell.removeEventListener('mouseleave', onLeave);
                        cell.removeEventListener('click', onClick, true);
                    });
                }
                cell.classList.remove('magic-selection-overlay', 'col', 'sel-mode-line');
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            gameState.selectingOnBoard = false;
            gameState.selectionCleanup = null;
        }

        document.getElementById('cancel-target').addEventListener('click', cleanupAll);
        gameState.selectionCleanup = cleanupAll;
        return;
    }

    // CONTINUOUS selection (自由连续 n 格) e.g., 硫磺火焰 — 自由连选 6 格
    if (descriptor.type === 'continuous') {
        const L = descriptor.length;
        // 样式统一在 style.css（见「范围选择的选中态」一节的说明：
        // 这里原本注入的 <style> 与「整行整列」分支抢同一个 id，互相覆盖）。

        targetPrompt.innerHTML = `
            <h3>自由选择连续 ${L} 个格子（点击选中/取消，每个新增格需与已选格相邻）</h3>
            <p id="cont-picker-info" class="selection-info pending">已选 0 / ${L} 格</p>
            <div style="text-align:center;margin-top:8px;">
                <button id="confirm-continuous" disabled>确认</button>
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);

        const boardEl = opponentBoard;
        if (!boardEl) return;
        gameState.selectingOnBoard = true;

        const cells = Array.from(boardEl.querySelectorAll('.cell'));
        const selected = new Set();

        const key = (x, y) => `${x},${y}`;
        const parseKey = (k) => k.split(',').map(Number);

        function isAdjacentToSelected(x, y) {
            if (selected.size === 0) return true;
            for (const k of selected) {
                const [sx, sy] = parseKey(k);
                if (Math.abs(sx - x) + Math.abs(sy - y) === 1) return true;
            }
            return false;
        }

        function isConnected(setLike) {
            if (setLike.size <= 1) return true;
            const arr = Array.from(setLike);
            const [startX, startY] = parseKey(arr[0]);
            const visited = new Set();
            const stack = [[startX, startY]];
            const lookup = new Set(arr);
            while (stack.length) {
                const [cx, cy] = stack.pop();
                const ck = key(cx, cy);
                if (visited.has(ck)) continue;
                visited.add(ck);
                const neighbors = [
                    [cx + 1, cy],
                    [cx - 1, cy],
                    [cx, cy + 1],
                    [cx, cy - 1]
                ];
                neighbors.forEach(([nx, ny]) => {
                    const nk = key(nx, ny);
                    if (lookup.has(nk) && !visited.has(nk)) stack.push([nx, ny]);
                });
            }
            return visited.size === setLike.size;
        }

        function refreshHighlights() {
            cells.forEach(c => c.classList.remove('magic-selection-overlay', 'vert', 'sel-mode-cont'));
            cells.forEach(c => {
                const cx = parseInt(c.dataset.x, 10);
                const cy = parseInt(c.dataset.y, 10);
                if (selected.has(key(cx, cy))) c.classList.add('magic-selection-overlay', 'sel-mode-cont');
            });
            // 实时报数 + 未选满就禁用确认，玩家不用自己数格子。
            const info = document.getElementById('cont-picker-info');
            if (info) {
                if (selected.size === L) {
                    info.className = 'selection-info';
                    info.innerHTML = `<span class="sel-dot"></span>已选 ${selected.size} / ${L} 格 — 可以确认了`;
                } else {
                    info.className = 'selection-info pending';
                    info.textContent = `已选 ${selected.size} / ${L} 格（还需 ${L - selected.size} 格）`;
                }
            }
            const okBtn = document.getElementById('confirm-continuous');
            if (okBtn) okBtn.disabled = selected.size !== L;
        }

        cells.forEach(cell => {
            const mx = parseInt(cell.dataset.x, 10);
            const my = parseInt(cell.dataset.y, 10);
            cell.style.cursor = 'pointer';

            const onClick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                const k = key(mx, my);
                if (selected.has(k)) {
                    const temp = new Set(selected);
                    temp.delete(k);
                    if (temp.size > 0 && !isConnected(temp)) {
                        showAlert('移除该格会导致不连续，请选择其他格子');
                        return;
                    }
                    selected.delete(k);
                    refreshHighlights();
                    return;
                }

                if (selected.size >= L) {
                    showAlert(`最多只能选择 ${L} 个格子`);
                    return;
                }
                if (!isAdjacentToSelected(mx, my)) {
                    showAlert('新增格子需与已选格子相邻');
                    return;
                }
                selected.add(k);
                refreshHighlights();
            };

            cell.addEventListener('click', onClick, true);
            (cell._magicHandlers = cell._magicHandlers || []).push({
                type: 'continuous',
                handlers: { onClick }
            });
        });

        function cleanupAll() {
            cells.forEach(cell => {
                if (cell._magicHandlers) {
                    cell._magicHandlers.filter(h => h.type === 'continuous').forEach(h => {
                        const { onClick } = h.handlers;
                        cell.removeEventListener('click', onClick, true);
                    });
                }
                cell.classList.remove('magic-selection-overlay', 'vert', 'sel-mode-cont');
                cell.style.cursor = '';
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            gameState.selectingOnBoard = false;
            gameState.selectionCleanup = null;
        }

        document.getElementById('cancel-target').addEventListener('click', cleanupAll);
        document.getElementById('confirm-continuous').addEventListener('click', () => {
            if (selected.size !== L) {
                showAlert(`需要选择 ${L} 个格子`);
                return;
            }
            if (!isConnected(selected)) {
                showAlert('所选格子必须保持连续相邻');
                return;
            }
            const payload = Array.from(selected).map(k => {
                const [x, y] = parseKey(k);
                return { x, y };
            });
            confirmMagicTarget({ target_cells: payload });
            cleanupAll();
        });
        gameState.selectionCleanup = cleanupAll;
        return;
    }

    // SINGLE selection (单格) - 默认选择对手棋盘，如需选择我方则 descriptor.board === 'self'
    if (descriptor.type === 'single') {
        const which = descriptor.board || 'opponent';
        // board==='self'（克苏鲁之眼）：只能点自己战舰所在的格子，空格不可选
        const selfShipsOnly = (which === 'self');

        targetPrompt.innerHTML = selfShipsOnly
            ? `<h3>选择你要暴露的战舰</h3>
               <p class="magic-hint">只能点自己战舰所在的格子（绿色高亮）</p>
               <div style="text-align:center;margin-top:8px;">
                   <button id="cancel-target">取消</button>
               </div>`
            : `<h3>选择一个目标格子</h3>
               <div style="text-align:center;margin-top:8px;">
                   <button id="cancel-target">取消</button>
               </div>`;
        document.body.appendChild(targetPrompt);

        const boardEl = selfShipsOnly ? gamePlayerBoard : opponentBoard;
        if (!boardEl) return;
        gameState.selectingOnBoard = true;
        const listeners = [];

        // 自己船所在格集合
        const ownCells = new Set();
        if (selfShipsOnly) {
            // 只收【还活着】的船：沉船仍留在 gameState.ships 里（击沉只减船数、
            // 不把船移出列表），不过滤的话点自己沉船的格子也会被当成有效选择 ——
            // 克苏鲁之眼就能靠这个拿一艘早沉的船来「暴露」。
            (gameState.ships || []).forEach(ship => {
                if (ship.alive === false) return;
                (ship.positions || []).forEach(p => ownCells.add(p.x + ',' + p.y));
            });
        }

        const onClick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            const el = e.currentTarget;
            const x = parseInt(el.dataset.x, 10);
            const y = parseInt(el.dataset.y, 10);
            confirmMagicTarget({ x, y });
            cleanupAll();
        };

        boardEl.querySelectorAll('.cell').forEach(cell => {
            const x = parseInt(cell.dataset.x, 10);
            const y = parseInt(cell.dataset.y, 10);
            if (selfShipsOnly && !ownCells.has(x + ',' + y)) {
                cell.classList.add('pick-disabled');   // 空格：灰掉，点了没用
                return;
            }
            if (selfShipsOnly) cell.classList.add('pick-ship');
            cell.addEventListener('click', onClick, true);
            listeners.push({ el: cell, handler: onClick });
        });

        function cleanupAll() {
            listeners.forEach(({ el, handler }) => el.removeEventListener('click', handler, true));
            document.querySelectorAll('.cell.pick-ship, .cell.pick-disabled')
                .forEach(c => c.classList.remove('pick-ship', 'pick-disabled'));
            gameState.selectingOnBoard = false;
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
        }

        document.getElementById('cancel-target').addEventListener('click', cleanupAll);
        gameState.selectionCleanup = cleanupAll;
        return;
    }

    // OWN_SHIPS selection (选择若干我方舰船) e.g., 神之宣告 选择两艘自己船
    if (descriptor.type === 'own_ships') {
        const count = descriptor.count || 1;
        targetPrompt.innerHTML = `
            <h3>请选择 ${count} 艘你自己的战舰（点击格子切换选择）</h3>
            <div style="text-align:center;margin-top:8px;">
                <button id="confirm-magic-ships">确认</button>
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);

        const boardEl = gamePlayerBoard;
        if (!boardEl) return;
        const selected = new Set();
        boardEl.querySelectorAll('.cell').forEach(cell => {
            const x = parseInt(cell.dataset.x, 10);
            const y = parseInt(cell.dataset.y, 10);
            // 仅允许选有船的格子
            const hasShip = gameState.ships.some(s => s.positions.some(p => p.x === x && p.y === y));
            if (!hasShip) return;
            cell.style.cursor = 'pointer';
            const onClick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                const key = `${x},${y}`;
                if (selected.has(key)) {
                    selected.delete(key);
                    cell.classList.remove('selected');
                    cell.style.outline = '';
                } else {
                    if (selected.size >= count) {
                        showAlert(`只能选择 ${count} 艘战舰`);
                        return;
                    }
                    selected.add(key);
                    cell.classList.add('selected');
                    cell.style.outline = '3px solid rgba(0,191,255,0.9)';
                }
            };
            cell.addEventListener('click', onClick, true);
            // store to cleanup later
            (cell._magicHandlers = cell._magicHandlers || []).push(onClick);
        });

        document.getElementById('confirm-magic-ships').addEventListener('click', () => {
            if (selected.size !== count) {
                showAlert(`请选中 ${count} 艘战舰`);
                return;
            }
            const arr = Array.from(selected).map(k => {
                const [x, y] = k.split(',');
                return { x: parseInt(x, 10), y: parseInt(y, 10) };
            });
            confirmMagicTarget({ selected_cells: arr });
            // cleanup
            document.querySelectorAll('#player-board .cell').forEach(cell => {
                if (cell._magicHandlers && cell._magicHandlers.length) {
                    cell._magicHandlers.forEach(h => cell.removeEventListener('click', h, true));
                    cell._magicHandlers = [];
                }
                cell.style.outline = '';
                cell.classList.remove('selected');
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            gameState.currentMagicCard = null;
            gameState.currentCardIndex = null;
            gameState.pendingChainCard = null;
            gameState.pendingEffectChoice = null;
        });

        document.getElementById('cancel-target').addEventListener('click', () => {
            // cleanup
            document.querySelectorAll('#player-board .cell').forEach(cell => {
                if (cell._magicHandlers && cell._magicHandlers.length) {
                    cell._magicHandlers.forEach(h => cell.removeEventListener('click', h, true));
                    cell._magicHandlers = [];
                }
                cell.style.outline = '';
                cell.classList.remove('selected');
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            gameState.currentMagicCard = null;
            gameState.currentCardIndex = null;
            gameState.pendingChainCard = null;
            gameState.pendingEffectChoice = null;
            gameState.pendingEffectChoice = null;
        });

        return;
    }

    showAlert('尚未实现该卡的目标选择方式');
}

// 添加魔法卡目标选择判断函数（返回目标选择描述）
function needsTargetSelection(cardName) {
    const map = {
        '冻结': { type: 'area', size: 3, board: 'opponent' },          // 3x3区域
        '探测雷达': { type: 'area', size: 2, board: 'opponent' },      // 2x2区域
        '轰炸': { type: 'line', board: 'opponent' },                  // 行或列
        '硫磺火焰': { type: 'continuous', length: 6, board: 'opponent' }, // 6个连续格子
        '克苏鲁之眼': { type: 'single', board: 'self' },             // 选择自己的船暴露
        '神之宣告': { type: 'own_ships', count: 2 },                  // 选择两艘自己的船牺牲
        '神威！': { type: 'shenwei' }                                 // 己方/对方 3x3 扣区
    };
    return map[cardName] || null;
}

// 通用区域点选器：在真实棋盘上点选 size×size 区域（触摸/鼠标均可用）。
// 点一下定位并高亮，再点「确认」提交；桌面端保留悬停预览。
function createBoardAreaPicker(boardEl, size, onConfirm, onCancel, opts) {
    if (!boardEl) return null;
    // ★ 2026-09-20 修：占用中**不再静默返回 null**。
    //
    // 旧写法 `if (!boardEl || gameState.selectingOnBoard) return null;` —— 被占用时
    // 悄悄放弃，调用方 `picker ? picker.cleanup : null` 什么也不做，
    // 于是弹窗已经显示、棋盘却点不动，玩家看到的就是「点了没反应、卡住选不了」。
    //
    // 现在：明确告诉玩家**是谁**占着棋盘（通常是恶魔契约那类强制点选），
    // 并给出「先完成它」的指引 —— 与后端的优先级闸门是同一套语义。
    if (gameState.selectingOnBoard) {
        const cur = gameState.boardSelection;
        const who = (cur && cur.label) ? cur.label : '另一个需要点选的效果';
        showAlert(`请先完成「${who}」的点选，再使用这张卡`);
        return null;
    }
    gameState.selectingOnBoard = true;
    const options = opts || {};

    const listeners = [];
    let highlighted = [];
    let current = null;

    const clampStart = (mx, my) => ({
        sx: Math.max(0, Math.min(mx, 6 - size)),
        sy: Math.max(0, Math.min(my, 6 - size))
    });

    function clearHighlights() {
        highlighted.forEach(c => c.classList.remove('selection-highlight', 'sel-mode-area'));
        highlighted = [];
    }

    function highlight(sx, sy) {
        clearHighlights();
        for (let y = sy; y < sy + size; y++) {
            for (let x = sx; x < sx + size; x++) {
                if (x < 0 || x > 5 || y < 0 || y > 5) continue;
                const cell = boardEl.querySelector(`.cell[data-x="${x}"][data-y="${y}"]`);
                if (cell) {
                    cell.classList.add('selection-highlight', 'sel-mode-area');
                    highlighted.push(cell);
                }
            }
        }
        current = { x1: sx, y1: sy, x2: sx + size - 1, y2: sy + size - 1 };
        const btn = document.getElementById('area-confirm');
        if (btn) btn.disabled = false;
        // 明确写出「选中的是哪一块」：旧实现只有棋盘上一片淡色，玩家看不出落点。
        const info = document.getElementById('area-picker-info');
        if (info) {
            info.className = 'selection-info';
            info.innerHTML = '<span class="sel-dot"></span>' +
                `${size}×${size} 已选中：第 ${sx + 1}–${sx + size} 列，第 ${sy + 1}–${sy + size} 行`;
        }
    }

    // 浮动确认条（可选带标题/说明：区域类卡牌的「点哪里」提示就放在这里，
    // 免得再挂一个没有样式的裸 div 跟它重叠）
    const bar = document.createElement('div');
    bar.className = 'area-picker-bar';
    const titleHTML = options.title
        ? `<div class="selection-info pending" style="flex-basis:100%;margin:0 0 2px;">${escapeHtml(options.title)}</div>`
        : '';
    const hintHTML = options.hint
        ? `<div class="magic-hint" style="flex-basis:100%;margin:0 0 6px;">${escapeHtml(options.hint)}</div>`
        : '';
    bar.style.flexWrap = 'wrap';
    bar.innerHTML = titleHTML + hintHTML
        + `<span id="area-picker-info" class="selection-info pending">点击棋盘上的格子来选择区域</span>`
        + `<button id="area-confirm" disabled>确认</button><button id="area-cancel">取消</button>`;
    document.body.appendChild(bar);
    bar.querySelector('#area-confirm').addEventListener('click', () => {
        if (!current) { showAlert('请先点选一个区域'); return; }
        const area = current;
        cleanup();
        if (typeof onConfirm === 'function') onConfirm({ target_area: area });
    });
    bar.querySelector('#area-cancel').addEventListener('click', () => {
        cleanup();
        if (typeof onCancel === 'function') onCancel();
    });

    boardEl.querySelectorAll('.cell').forEach(cell => {
        const mx = parseInt(cell.dataset.x, 10);
        const my = parseInt(cell.dataset.y, 10);
        const onEnter = () => { if (!current) { const p = clampStart(mx, my); highlight(p.sx, p.sy); } };
        const onLeave = () => { if (!current) clearHighlights(); };
        const onPick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            const p = clampStart(mx, my);
            highlight(p.sx, p.sy);
        };
        cell.addEventListener('mouseenter', onEnter);
        cell.addEventListener('mouseleave', onLeave);
        cell.addEventListener('click', onPick, true);
        listeners.push({ cell, onEnter, onLeave, onPick });
    });

    function cleanup() {
        listeners.forEach(({ cell, onEnter, onLeave, onPick }) => {
            cell.removeEventListener('mouseenter', onEnter);
            cell.removeEventListener('mouseleave', onLeave);
            cell.removeEventListener('click', onPick, true);
        });
        clearHighlights();
        if (bar.parentNode) bar.parentNode.removeChild(bar);
        gameState.selectingOnBoard = false;
        current = null;
    }

    return { cleanup };
}

// 创建区域选择面板 - 用于区域选择类魔法卡
// 支持两种模式：
// - 小面板模式（默认）：创建 size x size 的选择面板
// - 对手棋盘模式（isOpponentBoard === true）：在对手真实棋盘上悬停预览、点击确认区域
// 获取选中的单元格坐标
// 发动魔法卡
function playMagicCard(index) {
    console.log('playMagicCard called with index:', index);
    const card = gameState.hand[index];
    if (!card) return;
    if (freezeAlert()) { clearCardSelection(); return; }

    // 检查卡牌是否可以在当前阶段使用
    if (!canPlayCard(card)) {
        // 出牌被拒：必须清掉选中态，否则下一次单击会被当成
        // 「同一张已选中的卡」立刻重试 —— 玩家看到提示弹两遍。
        clearCardSelection();
        if (isLastStandActive()) {
            // 绝处逢生生效中，跟「阶段 / 回合」毫无关系。
            // 旧实现会一路掉到最后一个 else，弹出「当前阶段battle不允许使用
            // 速阶1的魔法卡」—— 阶段明明是对的，玩家据此以为游戏坏了。
            showAlert(`无法使用${card.name}：绝处逢生生效中，本回合你的其余魔法卡全部无效`);
        } else if (END_PHASE_PLAYABLE_CARDS.indexOf(card.name) >= 0) {
            // 这类卡有专属的条件提示，别让玩家看到「速阶2」这种内部术语
            const reasons = [];
            if (!isFirstPlayer()) reasons.push('你这一局是后手');
            if (gameState.currentAttacker !== gameState.playerId) reasons.push('不是你的回合');
            if (gameState.currentPhase !== 'end') reasons.push('不是结束阶段');
            showAlert(`${card.name}只能在自己先手回合的结束阶段发动（${reasons.join('；') || '条件不满足'}）`);
        } else if (gameState.currentAttacker !== gameState.playerId) {
            // 另一种同样常见的原因：不是你的回合。旧文案一律甩锅给「阶段」，
            // 玩家在准备阶段拿着速阶2的卡会看到「当前阶段preparation不允许使用速阶2」，
            // 完全是误导（服务端本来就允许准备阶段用速阶2）。
            showAlert(`无法使用${card.name}：现在不是你的回合`);
        } else {
            const phaseName = gameState.currentPhase || '未开始';
            showAlert(`无法使用${card.name}：当前阶段${phaseName}不允许使用速阶${card.speed}的魔法卡`);
        }
        return;
    }

    // 特殊限制：饮血 / 溅射 / 雷达子弹 都需要「自己上一发攻击」满足各自条件。
    // 必须在这里拦下 —— 否则牌会被服务端扣掉，结算时才告诉你条件不满足，
    // 而那时牌已经进了弃牌堆、不会退还（玩家实测过）。
    const afterHitReason = afterHitBlockReason(card);
    if (afterHitReason) {
        clearCardSelection();
        showAlert(`无法使用${card.name}：${afterHitReason}`);
        return;
    }
    if (gameState.fieldMagic === "禁忌果实") {
        if (!(card.name === "失灵！" || card.type === "场地")) {
            clearCardSelection();
            showAlert(`无法使用${card.name}：场地魔法“禁忌果实”生效，非场地及失灵类魔法卡无法使用`);
            return;
        }
    }

    // 神之宣告：卡面顺序是「先选定自己两艘船死亡，再选择要发动的效果」。
    // 两步都走完才算出牌 —— 第一步由 needsTargetSelection 的 own_ships 收集，
    // 第二步在 confirmMagicTarget 里接着问（见 promptDivineDecreeChoice）。

    // 检查是否需要目标选择
    if (needsTargetSelection(card.name)) {
        showMagicTargetSelection(card, index);
    } else {
        // 不需要目标，直接发送
        sendMagicCard(index, []);
    }
}

// 添加发送魔法卡的辅助函数
function sendMagicCard(index, targets) {
    const card = gameState.hand[index];
    if (!card) return;
    playSfx('play_card');

    // ⚠️ 先记下这张牌的【身份】和出牌那一刻它在手牌里的位置。
    // 服务器响应是异步的，回来之前可能已经收到 hand_updated
    // （对方打无中生有 / 自己因效果摸牌 / 连锁里别人改手牌…），
    // 那时 gameState.hand 已经是新数组，旧下标指向的完全是另一张牌。
    // 实测（tools/repro_splice_index.mjs）：手牌 ["饮血","冻结"] 打出饮血，
    // 期间摸到一张「八方来财」插到 0 号位，回调里 splice(0,1) 删掉的是
    // 【八方来财】—— 打出去的饮血还留在手上，玩家看到的是"手牌被莫名吞掉"。
    const sentKey = cardSelectionKey(card);
    const sentIndex = index;

    console.log('发送魔法卡:', card.name);
    gameState.socket.emit('use_magic_card', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        card: card,
        targets: targets
    }, (response) => {
        // 只有在服务器确认成功后才更新本地状态
        if (response && response.status === 'success') {
            console.log('魔法卡使用成功');
            // 从手牌中移除：只按身份找，找不到就什么都不删。
            //
            // ⚠️ 这里以前有一个"找不到就按下标兜底"的分支：
            //     removeAt = (gameState.hand.length === sentIndex + 1) ? sentIndex : -1
            // 它是**永远错的**：能走到这个分支，就说明打出的那张牌已经不在手牌里了
            // （手牌里没有任何一张的 name+speed 和它相同），也就是说服务端早已推过
            // 新手牌；这时再按旧下标删一张，删掉的必然是【别的牌】。
            //
            // 实测（tools/hand_play_check.mjs，真实浏览器 + 真服务端）：
            //   手牌 ["五险一金","看破！"]，点第 0 张打出。
            //   handle_use_magic_card 扣牌后会走 _advance_chain_window，
            //   对方手上没有速阶3 → 它【在同一个请求里同步 resolve_chain】，
            //   而 resolve_chain 收尾会向双方各推一次 hand_updated（此时只剩 "看破！"）。
            //   所以真实时序是 "hand_updated(1 张)" 先到、ack 后到（工具里有断言守这条）。
            //   ack 里按身份找不到 → 兜底条件 1 === 0+1 成立 → 把 "看破！" 删掉
            //   → 界面手牌变成 0 张，而服务端还有 1 张。玩家看到的就是
            //   「打完一张，剩下的手牌莫名其妙全没了，刷新页面又回来」。
            //
            // 同名同速阶的卡（如 3 张「失灵！」）会有多张命中，这时仍用
            // "出牌时它在第几位"来消歧 —— 取第 sentIndex 个命中项。
            const hits = [];
            for (let i = 0; i < gameState.hand.length; i++) {
                if (cardSelectionKey(gameState.hand[i]) === sentKey) hits.push(i);
            }
            if (hits.length) {
                gameState.hand.splice(hits[Math.min(sentIndex, hits.length - 1)], 1);
            } else {
                // 牌已经不在手牌里了 —— 服务端才是权威，等它的 hand_updated，
                // 绝不按下标猜着删一张。
                console.log('打出的牌已不在本地手牌中（服务端已同步），不本地删除');
            }
            // 添加到弃牌堆
            gameState.discardPile.push(card);
            // 手牌少了一张，旧下标会落到别的牌上 —— 先清选中态再刷新
            gameState.selectedCardIndex = -1;
            gameState.selectedCardKey = null;
            // 更新UI
            updateHandUI();
        } else {
            // 出牌失败同样要清选中态：否则这张卡还挂着「已选中」，
            // 玩家下一次单击就会立刻重试，提示连弹两遍。
            clearCardSelection();
            console.error('魔法卡使用失败:', response && response.message);
            showAlert(`使用魔法卡失败：${(response && response.message) || '未知错误'}`);
        }
    });
}

// 神之宣告：第二步 —— 两艘要牺牲的船选完之后，选择要触发的效果
// （1=摧毁对方一艘战舰，2=跳过对方本回合）。
// ctx：第一步入口处抓好的上下文 { card, cardIndex, chainPending }。
//      card 允许显式传入，是因为连锁响应窗口里打出的卡未必在手牌同下标。
// basePayload：第一步（own_ships）收集到的 selected_cells，确认后与效果一起提交。
function promptDivineDecreeChoice(ctx, basePayload) {
    const context = ctx || {};
    const card = context.card || gameState.hand[context.cardIndex];
    if (!card) return;
    const picked = basePayload || null;

    const overlay = document.createElement('div');
    overlay.className = 'taoyuan-choice-overlay';
    overlay.style.zIndex = '10000';
    overlay.innerHTML = `
        <div class="taoyuan-choice-container">
            <div class="taoyuan-choice-header">
                <h3>神之宣告</h3>
                <p>已选定牺牲的两艘战舰，请选择要触发的效果：</p>
            </div>
            <div class="divine-decree-options" style="display:flex;flex-direction:column;gap:10px;padding:12px 0;">
                <button class="phase-btn" data-choice="1">摧毁对方一艘战舰</button>
                <button class="phase-btn" data-choice="2">跳过对方本回合所有阶段</button>
                <button class="phase-btn" data-choice="0" style="opacity:.7;">取消</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    overlay.querySelectorAll('button[data-choice]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const choice = parseInt(btn.dataset.choice, 10);
            document.body.removeChild(overlay);
            if (choice === 0) {
                // 取消：卡牌不打出，清掉选区状态
                gameState.pendingEffectChoice = null;
                gameState.currentMagicCard = null;
                gameState.currentCardIndex = null;
                return;
            }

            if (picked) {
                // 两步都齐了：并到一起提交（上下文沿用第一步的，state 已被清理也不怕）
                gameState.pendingEffectChoice = null;
                _dispatchMagicTarget(
                    Object.assign({}, picked, { effect_choice: choice }), context);
                return;
            }

            // 兜底：没有第一步的结果时，退回「先点选两艘自己的船」。
            // 服务端收不到 selected_cells 会随机补两艘，玩家就没有选择权了。
            gameState.pendingEffectChoice = choice;
            gameState.currentMagicCard = card;
            gameState.currentCardIndex = context.cardIndex;
            showMagicTargetSelection(card, context.cardIndex);
        });
    });
}

// 修改目标选择后的确认函数
function confirmMagicTarget(targetData) {
    // 优先权询问里选好目标的情况：pendingPriorityCard 已记下要打的卡，
    // currentMagicCard 也在 showPriorityPrompt 里同步设过，两者取其一即可。
    if (!gameState.currentMagicCard && !gameState.pendingPriorityCard) return;
    if (gameState.currentCardIndex === null && !gameState.pendingPriorityCard) return;

    // ⚠️ 先把「提交这张卡所需的全部上下文」抓进局部变量。
    // showMagicTargetSelection 的「确认」监听器在 confirmMagicTarget 返回之后
    // 会把 currentMagicCard / currentCardIndex / pendingChainCard / pendingEffectChoice
    // 统统清空；而神之宣告是两段式（先选船、再选效果），等效果选完再去读 gameState
    // 只会读到 null —— 轻则卡牌索引丢失打不出去，重则把连锁响应误发成普通出牌。
    const ctx = {
        card: gameState.currentMagicCard,
        cardIndex: gameState.currentCardIndex,
        chainPending: gameState.pendingChainCard,
        priorityPending: gameState.pendingPriorityCard,
    };

    // 兼容多种 targetData 格式：
    // - { target_area: {x1,y1,x2,y2} } （来自对手真实棋盘）
    // - { selected_cells: [ {x,y}, ... ] } （来自小面板或选舰）
    // - { target_line: {...} } （行/列选择）
    // - { target_cells: [ {x,y}, ... ] } （显式格子集合）
    // - legacy array [ {x,y}, ... ]

    let payload = {};

    if (Array.isArray(targetData)) {
        // 旧格式数组 -> 计算包围盒
        const xs = targetData.map(c => c.x);
        const ys = targetData.map(c => c.y);
        payload.target_area = {
            x1: Math.min(...xs),
            y1: Math.min(...ys),
            x2: Math.max(...xs),
            y2: Math.max(...ys)
        };
        payload.selected_cells = targetData;
    } else if (targetData && targetData.selected_cells) {
        const arr = targetData.selected_cells;
        const xs = arr.map(c => c.x);
        const ys = arr.map(c => c.y);
        payload.target_area = {
            x1: Math.min(...xs),
            y1: Math.min(...ys),
            x2: Math.max(...xs),
            y2: Math.max(...ys)
        };
        payload.selected_cells = arr;
    } else if (targetData && targetData.target_area) {
        payload.target_area = targetData.target_area; // 直接传递 { target_area: {...} }
        if (targetData.board) payload.board = targetData.board; // 神威！：作用棋盘
    } else if (targetData && targetData.target_line) {
        payload.target_line = targetData.target_line; // 行/列选择
    } else if (targetData && targetData.target_cells) {
        payload.target_cells = targetData.target_cells; // 显式格子集合（如连续选择）
    } else if (targetData && targetData.x !== undefined && targetData.y !== undefined) {
        // 单格位置
        payload.target_area = { x1: targetData.x, y1: targetData.y, x2: targetData.x, y2: targetData.y };
    } else {
        // 未识别格式，直接发送原始数据
        payload = targetData;
    }

    // 神之宣告：船已经选好了，接着问要发动哪个效果 —— 效果选完才真正提交。
    // 卡面是「选定自己的两艘船死亡，并选择接下来两个效果其一发动」，船在前、效果在后。
    if (ctx.card.name === '神之宣告' && !gameState.pendingEffectChoice) {
        promptDivineDecreeChoice(ctx, payload);
        return;
    }

    // 神之宣告：把选好的效果一并带上（否则服务端只能退回默认效果）
    if (gameState.pendingEffectChoice) {
        payload.effect_choice = gameState.pendingEffectChoice;
        gameState.pendingEffectChoice = null;
    }

    _dispatchMagicTarget(payload, ctx);
}

// 真正把目标选择结果提交出去：
// 连锁响应窗口里打出的卡回填给 chain_response，否则走 use_magic_card。
// ctx 必须由调用方在入口处抓好传进来 —— 走到这里时 gameState 里的选择状态可能已被清理。
function _dispatchMagicTarget(payload, ctx) {
    const context = ctx || {};
    const cardIndex = (context.cardIndex === undefined || context.cardIndex === null)
        ? gameState.currentCardIndex
        : context.cardIndex;
    const chainPending = (context.chainPending === undefined)
        ? gameState.pendingChainCard
        : context.chainPending;
    // 优先权询问里打的速阶3（方案 D）：与连锁同构，
    // 目标选好后回填给 priority_response，而不是 use_magic_card。
    const priorityPending = (context.priorityPending === undefined)
        ? gameState.pendingPriorityCard
        : context.priorityPending;

    if (priorityPending) {
        gameState.pendingPriorityCard = null;
        gameState.pendingChainCard = null;
        gameState.pendingEffectChoice = null;
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
        gameState.socket.emit('priority_response', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            respond: true,
            card: priorityPending.card,
            targets: payload,
            decline_all: !!gameState.declinePriority
        });
        return;
    }

    if (chainPending) {
        gameState.pendingChainCard = null;
        gameState.pendingEffectChoice = null;
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
        gameState.socket.emit('chain_response', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            chain: true,
            card: chainPending.card,
            targets: payload
        });
        return;
    }

    // 发送并清理当前魔法卡选择状态
    sendMagicCard(cardIndex, payload);
    gameState.currentMagicCard = null;
    gameState.currentCardIndex = null;
}


// 扩展applyCardEffect函数
function applyCardEffect(card, casterId) {
    console.log(`应用魔法效果: ${card.name}`);
    // 显示魔法效果动画
    showMagicAnimation(card);

    switch (card.name) {
        case '余音绕梁':
            showMessage('余音绕梁效果生效，接下来两个攻击阶段将造成强制击杀');
            break;

        case '桃园结义':
            showMessage('桃园结义效果生效，请选择卡牌');
            break;

        case '无中生有':
            showMessage('无中生有效果生效，抽2张牌，本回合双方无法获得魔法卡');
            gameState.noMagicCardsThisTurn = true;
            break;

        case '极限增援':
            showMessage('极限增援效果生效，两个大回合后船少的一方获胜');
            break;

        case '无暇圣心':
            showMessage('无暇圣心效果生效，两个大回合后若双方都未造成伤害则你获胜');
            break;

        case '火力全开':
            showMessage('火力全开效果生效，本回合攻击次数翻倍');
            break;

        case '灵气复苏':
            showMessage('灵气复苏效果生效，双方船数已调整');
            break;

        case '溅射':
            showMessage('溅射效果生效，对周围格子造成伤害');
            // 显示溅射动画
            showSplashAnimation(gameState.lastAttack.x, gameState.lastAttack.y);
            break;

        case '雷达子弹':
            showMessage('雷达子弹效果生效，已扫描周围战舰位置');
            // 请求显示扫描结果
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            });
            break;

        case '越战越勇':
            showMessage('越战越勇效果生效，接下来击沉对方战舰时攻击次数净增加1');
            break;

        case '神威！':
            showMessage('神威！生效，目标区域战舰被暂时除外');
            break;

        case '冻结':
            showMessage('冻结效果生效，目标区域战舰被冻结');
            break;

        case '轰炸':
            showMessage('轰炸效果生效，目标行/列受到攻击');
            // 轰炸的实际结算走 use_magic_card（target_line）链路，此处无需额外请求
            break;

        case '探测雷达':
            showMessage('探测雷达效果生效，已显示目标区域战舰');
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            });
            break;

        case '饮血':
            showMessage('饮血效果生效，接下来每击杀一艘船抽一张牌');
            break;

        case '克苏鲁之眼':
            showMessage('克苏鲁之眼效果生效，双方各暴露一艘战舰位置');
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            });
            break;

        case 'Freezing！':
            showMessage('Freezing效果生效，对方回合被跳过');
            break;

        case '明智埋葬':
            // 这一刻还什么都没埋、也没摸牌（要等玩家点选后服务端才结算）。
            // 旧文案「埋葬卡牌并抽一张新牌」会让人以为效果已完成 —— 而且双方都会看到。
            showMessage(casterId === gameState.playerId
                ? '明智埋葬：请选择要埋葬的卡牌（牌堆或对方手牌）'
                : '对方发动了明智埋葬，正在选择要埋葬的卡牌');
            break;

        case '仁王之盾':
            showMessage('仁王之盾效果生效， selected ships are protected');
            break;

        case '八方来财':
            showMessage('八方来财效果生效，战舰数目变化时抽一张牌');
            break;

        case '平等条约':
            showMessage('平等条约效果生效，船数改变效果被无效化');
            break;

        case '百亿补贴':
            showMessage('百亿补贴效果生效，船被击败时攻击次数加3');
            // 角标不在这里挂 —— 由服务端 active_effects 广播统一渲染。
            // 以前这里是 `indicatorBox.innerHTML += ...`，只加不删：
            // 服务端其实每回合切换就把 subsidy 清掉了，角标却永远亮着，
            // 玩家会以为效果是永久的。
            break;

        case '绝处逢生':
            // ★ 2026-09-20 同批修：绝处逢生也只重摆**施法者自己**的棋盘
            // （服务端只清 caster 的船）。这里以前不看 casterId 就 `initBoard`,
            // 会把**对手本地那份棋盘状态**一起抹掉 —— 对手的船明明还在，
            // 界面上却被清空了。与上面回光返照是同一个形状的缺陷。
            if (casterId && casterId !== gameState.playerId) {
                showMessage('对方发动了绝处逢生，击杀其任何一艘战舰可直接获胜');
                break;
            }
            showMessage('绝处逢生效果生效，击杀任何船直接获胜');
            // 重新初始化棋盘
            initBoard(playerBoard, true);
            gameState.ships = [];
            gameState.placedShips = 0;
            shipsPlaced.textContent = '0';
            confirmShipsBtn.classList.add('hidden');
            break;

        case '死者苏生':
        case '疗愈':
            showMessage('复活效果生效，战舰已复活');
            break;

        case '盗亦有道':
            showMessage('盗亦有道效果生效，获取对方上一张魔法卡');
            break;

        case '回光返照':
            // ★ 2026-09-20 修：界面不再由这里驱动 —— 改走服务端的 `reset_gameboard`
            //（按 sid 单发给施法者，见 server.py 回光返照分支）。
            //
            // 为什么必须改掉：本函数是**广播**处理器（双方都会跑），
            // 在这里 `switchScreen(shipPlacementScreen)` 会把**对手**也拽进布船界面
            // （作者实测：「对手也需要重新布船」）。
            // 而且"谁该重摆"这件事一旦这里也判一遍，就等于**两份实现** ——
            // 本项目的老病根（第 10 节第 1 条）。服务端 `room.state='placing_ships'`
            // + 单发 `reset_gameboard` 已经是唯一真相。
            //
            // 这里只负责给双方各一句提示。
            showMessage(casterId === gameState.playerId
                ? '回光返照生效，请重新摆放战舰'
                : '对方发动了回光返照，正在重新摆放战舰');
            break;

        case '加百列之光':
            // 场地拆除完全交给服务端：它按 field_magic_owner 判断归属，
            // 只拆对方的场地，并广播 field_magic_updated 刷新双方 UI。
            // 这里此前又 emit 了一次 remove_field_magic，而服务端允许归属者
            // 删除自己的场地 —— 施法者自己的场地就这样被前端「补刀」拆掉了。
            showMessage('加百列之光效果生效，对方魔法和场地魔法被无效化');
            break;

        case '钢筋铁骨':
            showMessage('钢筋铁骨效果生效，其他战舰进入无敌状态');
            break;

        case '神机妙算':
            showMessage('神机妙算效果生效，已宣言船数减少数目');
            break;

        // 场地魔法
        case '恶魔契约':
            showMessage('场地魔法【恶魔契约】生效，双方船数增减绑定');
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        case '禁忌果实':
            showMessage('场地魔法【禁忌果实】生效，双方只能使用失灵！和场地魔法');
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        case '伊甸园':
            showMessage('场地魔法【伊甸园】生效，攻击次数变为6-n');
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        case '教皇旨意':
            showMessage('场地魔法【教皇旨意】生效，攻击需要弃置魔法卡');
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        // 判定魔法卡：命运骰子的动画与效果播报由 dice_rolled 事件统一驱动
        // （双方都收到，能同步看到同一个骰子结果）。
        case '命运骰子':
            // 不在这里显示，避免与 dice_rolled 事件重复
            break;

        // 已实现的魔法卡
        case '失灵！':
            showMessage('失灵！效果生效，对方魔法被无效化');
            break;

        case '看破！':
            showMessage('看破！效果生效，本回合对方魔法卡被无效化');
            break;

        case '增援':
            showMessage('增援效果生效，请选择部署位置');
            break;
    }
}

// 添加魔法效果动画和UI辅助函数
function showMagicAnimation(card) {
    const animation = document.createElement('div');
    animation.className = 'magic-animation';
    animation.innerHTML = `<div class="magic-card-name">${card.name}</div>`;
    document.body.appendChild(animation);

    setTimeout(() => {
        animation.classList.add('active');
        setTimeout(() => {
            animation.classList.add('fade-out');
            setTimeout(() => document.body.removeChild(animation), 1000);
        }, 1000);
    }, 100);
}

// ============ 命运骰子：摇骰子动画 + 弃牌选择 ============
// 摇骰子动画：全屏覆盖层，一个翻滚的骰子，最终定格在 roll 点。
// 双方都会收到 dice_rolled 事件，所以双方都能看到同一个动画 + 结果。
function showDiceRollAnimation(roll, effectText, casterId) {
    // 同时只有一个骰子动画，新的来了先把旧的清掉
    const old = document.getElementById('dice-roll-overlay');
    if (old) old.parentNode.removeChild(old);

    const overlay = document.createElement('div');
    overlay.id = 'dice-roll-overlay';
    overlay.className = 'dice-roll-overlay';

    const isMine = !casterId || casterId === gameState.playerId;
    const titleText = isMine ? '你摇出了' : '对方摇出了';

    overlay.innerHTML =
        '<div class="dice-roll-card">' +
            '<div class="dice-roll-title">' + escapeHtml(titleText) + '</div>' +
            '<div class="dice-3d">' +
                '<div class="dice-3d-face" data-face="1">1</div>' +
                '<div class="dice-3d-face" data-face="2">2</div>' +
                '<div class="dice-3d-face" data-face="3">3</div>' +
                '<div class="dice-3d-face" data-face="4">4</div>' +
                '<div class="dice-3d-face" data-face="5">5</div>' +
                '<div class="dice-3d-face" data-face="6">6</div>' +
            '</div>' +
            '<div class="dice-roll-result"></div>' +
            '<div class="dice-roll-effect"></div>' +
        '</div>';
    document.body.appendChild(overlay);

    const resultEl = overlay.querySelector('.dice-roll-result');
    const effectEl = overlay.querySelector('.dice-roll-effect');
    const diceEl = overlay.querySelector('.dice-3d');

    // 摇骰阶段：快速翻滚 1.2 秒，期间随机闪现数字
    const rollDuration = 1200;
    const startTime = Date.now();
    const rollTimer = setInterval(() => {
        const elapsed = Date.now() - startTime;
        if (elapsed >= rollDuration) {
            clearInterval(rollTimer);
            return;
        }
        const n = 1 + Math.floor(Math.random() * 6);
        if (diceEl) diceEl.setAttribute('data-show', String(n));
    }, 80);

    // 定格到最终结果
    setTimeout(() => {
        clearInterval(rollTimer);
        if (diceEl) diceEl.setAttribute('data-show', String(roll));
        if (resultEl) {
            resultEl.textContent = String(roll) + ' 点';
            resultEl.classList.add('dice-roll-result-show');
        }
    }, rollDuration + 50);

    // 显示效果文案 + 播报
    setTimeout(() => {
        if (effectEl && effectText) {
            effectEl.textContent = '效果：' + effectText;
            effectEl.classList.add('dice-roll-effect-show');
        }
        showMessage(`命运骰子摇出 ${roll} 点：${effectText || ''}`, { type: 'warning', duration: 4500 });
    }, rollDuration + 700);

    // 整体淡出
    setTimeout(() => {
        overlay.classList.add('dice-roll-fade-out');
        setTimeout(() => {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        }, 500);
    }, rollDuration + 2800);
}

// 弃牌选择浮层：列出当前手牌，点一张弃掉
let _diceDiscardOverlay = null;
function showDiceDiscardPrompt(message) {
    hideDiceDiscardPrompt();
    const hand = gameState.hand || [];
    if (!hand.length) {
        // 没牌可弃：直接通知服务端跳过
        if (gameState.socket) {
            gameState.socket.emit('dice_discard_choose', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                card_index: 0
            });
        }
        return;
    }

    const overlay = document.createElement('div');
    overlay.id = 'dice-discard-overlay';
    overlay.className = 'dice-discard-overlay';
    overlay.innerHTML =
        '<div class="dice-discard-card">' +
            '<div class="dice-discard-title">' + escapeHtml(message || '命运骰子：请选择一张手牌弃置') + '</div>' +
            '<div class="dice-discard-hand"></div>' +
        '</div>';
    document.body.appendChild(overlay);

    const handEl = overlay.querySelector('.dice-discard-hand');
    hand.forEach((card, idx) => {
        const el = document.createElement('div');
        el.className = 'dice-discard-card-item';
        el.innerHTML =
            '<div class="card-name">' + escapeHtml(card.name) + '</div>' +
            '<div class="card-speed">速阶 ' + escapeHtml(String(card.speed)) + '</div>' +
            '<div class="card-type">' + escapeHtml(card.type || '') + '魔法</div>';
        el.addEventListener('click', () => {
            if (!gameState.socket) return;
            gameState.socket.emit('dice_discard_choose', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                card_index: idx
            });
            // 乐观关闭：服务端确认后会推 dice_discard_complete / hand_updated
            hideDiceDiscardPrompt();
        });
        handEl.appendChild(el);
    });

    _diceDiscardOverlay = overlay;
}

function hideDiceDiscardPrompt() {
    if (_diceDiscardOverlay && _diceDiscardOverlay.parentNode) {
        _diceDiscardOverlay.parentNode.removeChild(_diceDiscardOverlay);
    }
    _diceDiscardOverlay = null;
}

// 溅射动画：以最近攻击点为中心，对周围格子展示涟漪（支持形状与半径）
// options: { radius: number=1, shape: 'square'|'cross'|'diamond', target: 'opponent'|'self' }
function showSplashAnimation(x, y, options = {}) {
    const coordValid = Number.isInteger(x) && Number.isInteger(y);
    if (!coordValid && gameState.lastAttack) {
        x = gameState.lastAttack.x;
        y = gameState.lastAttack.y;
    }
    if (!Number.isInteger(x) || !Number.isInteger(y)) {
        console.warn('溅射动画缺少有效坐标');
        return;
    }

    const { radius = 1, shape = 'square', target } = options;
    const attackerId = gameState.lastAttack?.attacker || gameState.playerId;
    let targetBoard = attackerId === gameState.playerId ? opponentBoard : gamePlayerBoard;
    if (target === 'opponent') targetBoard = opponentBoard;
    if (target === 'self') targetBoard = gamePlayerBoard;
    if (!targetBoard) return;

    const maxSize = 6;
    const positions = [];

    for (let dy = -radius; dy <= radius; dy++) {
        for (let dx = -radius; dx <= radius; dx++) {
            const nx = x + dx;
            const ny = y + dy;
            if (nx < 0 || nx >= maxSize || ny < 0 || ny >= maxSize) continue;

            const manhattan = Math.abs(dx) + Math.abs(dy);
            const chebyshev = Math.max(Math.abs(dx), Math.abs(dy));
            let inShape = false;

            switch (shape) {
                case 'cross':
                    // 十字：在 x 或 y 方向的直线，距离不超过 radius
                    inShape = (dx === 0 || dy === 0) && manhattan <= radius;
                    break;
                case 'diamond':
                    // 菱形：曼哈顿距离不超过 radius
                    inShape = manhattan <= radius;
                    break;
                case 'square':
                default:
                    // 方形：切比雪夫距离不超过 radius
                    inShape = chebyshev <= radius;
                    break;
            }

            if (inShape) {
                const delayBase = shape === 'cross' ? manhattan : (manhattan + chebyshev) / 2;
                positions.push({ x: nx, y: ny, delay: Math.floor(delayBase * 70) });
            }
        }
    }

    positions.forEach(pos => {
        const cell = targetBoard.querySelector(`.cell[data-x="${pos.x}"][data-y="${pos.y}"]`);
        if (!cell) return;

        const ripple = document.createElement('div');
        ripple.className = 'splash-effect';
        ripple.style.animationDelay = `${pos.delay}ms`;
        cell.querySelectorAll('.splash-effect').forEach(n => n.remove());
        cell.appendChild(ripple);
        setTimeout(() => { if (ripple.parentNode === cell) ripple.remove(); }, 800 + pos.delay);
    });
}

// 更新场地魔法UI显示
function updateFieldMagicUI(playerId, card) {
    const fieldElement = document.getElementById('current-field-magic');

    if (card) {
        // 获取当前场地魔法的拥有者
        const owner = playerId === gameState.playerId ? '你的' : '对方的';
        fieldElement.innerHTML = `当前生效的场地魔法：<span class="field-magic-card">${owner}${card.name}</span>`;
        fieldElement.className = `field-magic active`;
        gameState.fieldMagic = card.name;
    } else {
        fieldElement.innerHTML = `当前生效的场地魔法：<span class="no-magic">无</span>`;
        fieldElement.className = 'field-magic';
        // 场地被拆除/顶替时必须同步清掉本地状态：此前只改文案，
        // gameState.fieldMagic 仍留着旧卡名（教皇旨意等判断会读到过期的场地）。
        gameState.fieldMagic = null;
    }
    // 教皇旨意会改变"怎么攻击"，按钮显隐要跟着场地走
    if (typeof updatePapalDiscardButton === 'function') updatePapalDiscardButton();
}

// 恶魔契约：在自己棋盘上点选要牺牲的战舰（不弹额外窗口，直接点格子）
//
// ⚠️ 这里刻意【不】给每个格子单独绑点击，而是用事件委托 + 状态驱动高亮：
// 击沉结算时服务端先发 sacrifice_request、后发 attack_result，而后者会调用
// initGameBoards() 把整个棋盘 innerHTML 重建 —— 逐格绑的监听和 pick-ship
// 高亮会被瞬间冲掉，表现就是「弹窗还在，但怎么点都没反应」。
// 现在：委托监听挂在容器上（重建格子也不失效），高亮由 paintSacrificeCells()
// 根据 gameState.pendingSacrifice 每次重绘后重刷。
// 待选效果的中文名（只用于**给玩家看的提示**；判据一律用 reason 本身）。
// 与 `needsTargetSelection` 的卡名表互补：这里是"服务端推过来的 reason → 名字"。
const SACRIFICE_LABELS = {
    demon_contract: '恶魔契约',
    divine_decree: '神之宣告',
    kraken_eye: '克苏鲁之眼',
    shield_choice: '仁王之盾',
    trap_setup: '守株待兔',
    trap_sacrifice: '守株待兔',
    dice_sacrifice: '命运骰子',
};

// ★ 选船优先级（2026-09-20）：**前端只镜像服务端那一份**（server.py 的
// `SHIP_PICK_PRIORITY`），用途仅限"把被挡的卡置灰并给出提示"。
// ⚠️ 真正的放行/拒绝由服务端裁决（`_ship_pick_blocked_reason`）——
//    这里只是让玩家不必先点一下才知道不行。**不要**在这里实现第二套判据逻辑。
const SHIP_PICK_PRIORITIES = {
    demon_contract: 100,
    divine_decree: 80,
    trap_setup: 75,
    dice_sacrifice: 70,
    kraken_eye: 60,
    shield_choice: 40,
};

// "打这张卡会触发选船"的卡名 → 它对应的 reason
const SHIP_PICK_CARD_NAMES = {
    '克苏鲁之眼': 'kraken_eye',
    '神之宣告': 'divine_decree',
    '仁王之盾': 'shield_choice',
    '守株待兔': 'trap_setup',
    '命运骰子': 'dice_sacrifice',
};

// 当前是否有**更高优先级**的选船待办挡着这张卡；返回提示文案（空串 = 可用）。
function shipPickBlockedFor(cardName) {
    const want = SHIP_PICK_CARD_NAMES[cardName];
    if (!want) return '';
    const cur = gameState.boardSelection;
    if (!cur || cur.kind !== 'sacrifice') return '';
    const curP = SHIP_PICK_PRIORITIES[cur.reason] || 0;
    const wantP = SHIP_PICK_PRIORITIES[want] || 0;
    if (curP <= wantP) return '';
    const label = cur.label || SACRIFICE_LABELS[cur.reason] || '战舰点选';
    return `请先完成「${label}」的选船，再使用这张卡`;
}

function clearSacrificeSelection() {
    gameState.pendingSacrifice = null;
    gameState.selectingOnBoard = false;
    gameState.selectionCleanup = null;
    // ★ 2026-09-20：棋盘选区的**归属**一并释放（供 createBoardAreaPicker 仲裁与提示）
    gameState.boardSelection = null;
    document.querySelectorAll('.cell.pick-ship, .cell.pick-disabled')
        .forEach(c => c.classList.remove('pick-ship', 'pick-disabled'));
    document.querySelectorAll('.magic-target-prompt').forEach(el => el.remove());
}

// 按当前 pendingSacrifice 状态把「可点/不可点」刷到棋盘上。
// 幂等：initGameBoards 每次重绘后都会调它。
function paintSacrificeCells() {
    if (!gameState.pendingSacrifice || !gamePlayerBoard) return;

    // 可点格子只认【服务端下发的候选】：它已经滤掉了已沉的船。
    // 以前是从 gameState.ships 自己推 —— 沉船还留在那个列表里，于是
    // 「点自己沉船的格子」也会被点亮，克苏鲁之眼就能拿沉船来抵账。
    const ownCells = new Set();
    (gameState.pendingSacrifice.ships || []).forEach(sh => {
        (sh.positions || []).forEach(p => ownCells.add(p.x + ',' + p.y));
    });

    gamePlayerBoard.querySelectorAll('.cell').forEach(cell => {
        const key = cell.dataset.x + ',' + cell.dataset.y;
        cell.classList.remove('pick-ship', 'pick-disabled');
        cell.classList.add(ownCells.has(key) ? 'pick-ship' : 'pick-disabled');
    });
}

function showSacrificePrompt(data) {
    // 清理可能残留的选区状态，避免 selectingOnBoard 卡死
    if (typeof gameState.selectionCleanup === 'function') {
        try { gameState.selectionCleanup(); } catch (_) { }
    }
    clearSacrificeSelection();

    const prompt = document.createElement('div');
    prompt.className = 'magic-target-prompt';
    prompt.innerHTML = `
        <h3>恶魔契约：选择要牺牲的战舰</h3>
        <p class="magic-hint">点自己战舰所在的格子（绿色高亮）即可，不需要再确认</p>
    `;
    document.body.appendChild(prompt);
    showMessage((data && data.message) || '恶魔契约生效，请选择一艘自己的战舰牺牲',
                { type: 'warning' });

    // 记下「正等着选船」这个状态：棋盘重绘后由 paintSacrificeCells() 据此补回高亮。
    // ships 用服务端下发的那份（已滤掉沉船），前端不再自己从 gameState.ships 推。
    gameState.pendingSacrifice = {
        reason: (data && data.reason) || 'demon_contract',
        message: (data && data.message) || '',
        ships: (data && Array.isArray(data.ships)) ? data.ships : []
    };
    gameState.selectingOnBoard = true;
    // ★ 2026-09-20：登记**棋盘选区的归属**。
    // 恶魔契约 / 神之宣告 / 克苏鲁之眼 这类"强制点选"优先级最高，
    // 卡牌自己的目标选择（`createBoardAreaPicker` 等）遇到它必须让路并给出提示，
    // 而不是静默失败（那正是玩家报的"点了没反应"）。
    gameState.boardSelection = {
        kind: 'sacrifice',
        reason: gameState.pendingSacrifice.reason,
        label: SACRIFICE_LABELS[gameState.pendingSacrifice.reason] || '战舰点选',
    };

    // 事件委托：只绑一次，且绑在容器上 —— 格子被重建也不影响
    const onClick = (e) => {
        const el = e.target && e.target.closest ? e.target.closest('.cell.pick-ship') : null;
        if (!el || !gamePlayerBoard.contains(el)) return;
        e.stopPropagation();
        e.preventDefault();

        const x = parseInt(el.dataset.x, 10);
        const y = parseInt(el.dataset.y, 10);
        // 先清掉选区再发请求：否则服务端的 ships_updated 重绘棋盘时，
        // 玩家已经点过的格子还亮着，看起来像没点。
        clearSacrificeSelection();
        gameState.socket.emit('confirm_sacrifice', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            position: { x, y }
        }, (resp) => {
            if (resp && resp.status === 'error') {
                showAlert(resp.message || '牺牲失败，请重新选择');
            }
        });
    };

    if (gamePlayerBoard) {
        gamePlayerBoard.addEventListener('click', onClick, true);
        gameState.selectionCleanup = () => {
            gamePlayerBoard.removeEventListener('click', onClick, true);
            clearSacrificeSelection();
        };
    }

    paintSacrificeCells();
}

// 增援 / 复活：统一放置弹窗（灰格不可选、可确认、可放弃）
function showPlacementPrompt(data) {
    data = data || {};
    const isRevive = data.kind === 'revive';
    const isLastStand = data.kind === 'last_stand';
    // 神机妙算预言成功：把"原本会减少的船"重新部署（原位置 或 对方未打过的格子）
    const isShenji = data.kind === 'shenji_redeploy';
    // 滥竽充数：补充满船数，大回合结束时强制收回
    const isLanyu = data.kind === 'lanyu';
    const total = data.total || 1;
    const placed = data.placed || 0;
    const remaining = (data.remaining != null) ? data.remaining : 1;

    const existing = document.getElementById('placement-prompt');
    if (existing) existing.remove();

    const title = isLastStand ? '绝处逢生·放置唯一一艘战舰'
        : (isShenji ? '神机妙算·预言成功，重新部署战舰'
            : (isLanyu ? '滥竽充数·选择补充战舰位置'
                : (isRevive ? '复活战舰·选择部署位置' : '增援战舰·选择部署位置')));
    const step = total > 1 ? `（第 ${placed + 1}/${total} 艘）` : '';
    const hint = isLastStand
        ? `牺牲了全部战舰后，只能在${step}原本有自己战舰的格子（亮色）上放置唯一一艘。`
        : (isShenji
            ? `预言成功，这些战舰不会沉没。${step}可以把它们放回原位置（亮色格子），或者放到对方没有打过的空格。点一个亮色格子选中，再点「确认」。`
            : (isLanyu
                ? `滥竽充数会补充战舰到满船数。${step}点一个亮色格子选中，再点「确认」。这些战舰在大回合结束时会被强制收回（不会显示沉没）。灰色格子不能用（对方打过 / 已占用 / 被神威扣掉）。`
                : (isRevive
                    ? `这张卡会把阵亡的战舰重新部署到你的棋盘上。${step}点一个亮色格子选中，再点「确认」。灰色格子不能用（对方打过 / 已占用 / 被神威扣掉）。`
                    : `这张卡会给你补充一艘新战舰。${step}点一个亮色格子选中，再点「确认」。灰色格子不能用（对方打过 / 已占用 / 被神威扣掉）。`)));

    const prompt = document.createElement('div');
    prompt.id = 'placement-prompt';
    prompt.className = 'placement-prompt';

    let cellsHtml = '';
    for (let y = 0; y < 6; y++) {
        for (let x = 0; x < 6; x++) {
            cellsHtml += `<div class="placement-cell" data-x="${x}" data-y="${y}"></div>`;
        }
    }
    prompt.innerHTML = `
        <h3>${title}</h3>
        <p class="placement-hint">${hint}</p>
        <div class="placement-grid">${cellsHtml}</div>
        <div class="placement-actions">
            <button id="placement-confirm" disabled>确认</button>
            <button id="placement-cancel">放弃${remaining > 1 ? '剩余' : ''}</button>
        </div>
        <p class="placement-note">放弃后未放置的战舰作废，不影响本局继续。</p>
    `;
    document.body.appendChild(prompt);

    const blocked = new Set((data.blocked || []).map(b => b.x + ',' + b.y));
    // 绝处逢生：服务端只给"原本有战舰"的合法格（allowed），其余一律禁点
    const allowed = Array.isArray(data.allowed)
        ? new Set(data.allowed.map(a => (a.x != null ? a.x : a[0]) + ',' + (a.y != null ? a.y : a[1])))
        : null;
    let selected = null;

    prompt.querySelectorAll('.placement-cell').forEach(cell => {
        const key = cell.dataset.x + ',' + cell.dataset.y;
        if (blocked.has(key) || (allowed && !allowed.has(key))) {
            cell.classList.add('blocked');
            return;
        }
        cell.addEventListener('click', () => {
            prompt.querySelectorAll('.placement-cell.selected').forEach(c => c.classList.remove('selected'));
            cell.classList.add('selected');
            selected = { x: parseInt(cell.dataset.x, 10), y: parseInt(cell.dataset.y, 10) };
            const btn = document.getElementById('placement-confirm');
            if (btn) btn.disabled = false;
        });
    });

    document.getElementById('placement-cancel').addEventListener('click', () => {
        gameState.socket.emit('cancel_placement', {
            room_id: gameState.roomId, player_id: gameState.playerId
        });
        prompt.remove();
    });

    document.getElementById('placement-confirm').addEventListener('click', () => {
        if (!selected) return;
        gameState.socket.emit('confirm_reinforcement_position', {
            room_id: gameState.roomId, player_id: gameState.playerId, position: selected
        }, (resp) => {
            if (resp && resp.status === 'error') {
                // 关键：选错不关面板，把原因显示出来
                showAlert(resp.message || '放置失败，请重新选择');
                return;
            }
            // 成功：若还有剩余，服务端会再发 placement_request 刷新本面板
            const p = document.getElementById('placement-prompt');
            if (p) p.remove();
        });
    });
}

// 更新手牌UI
// 更新卡牌预览信息
function updateCardPreview(card, index) {
    const cardName = document.querySelector('#magic-card-preview .card-name');
    const previewSpeed = document.getElementById('preview-speed');
    const previewType = document.getElementById('preview-type');
    const previewDescription = document.getElementById('preview-description');
    const cancelBtn = document.getElementById('cancel-magic');

    if (card) {
        cardName.textContent = card.name;
        previewSpeed.textContent = card.speed;
        previewType.textContent = card.type;
        previewDescription.textContent = card.description;
        cancelBtn.style.display = 'block';
    } else {
        cardName.textContent = '未选择魔法卡';
        previewSpeed.textContent = '-';
        previewType.textContent = '-';
        previewDescription.textContent = '请选择一张魔法卡查看详细信息';
        cancelBtn.style.display = 'none';
    }
}

// 初始化卡牌预览功能
function initCardPreview() {
    const cancelBtn = document.getElementById('cancel-magic');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            gameState.selectedCardIndex = -1;
            updateHandUI();
            updateCardPreview(null);
        });
    }

    // 初始更新预览
    updateCardPreview(null);

    // 添加拖拽功能
    initPreviewDrag();
    // 初始化日志容器拖拽
    initLogDrag();
    setChatVisible(true);
    initInGameChatSocket();
    // 初始化投降按钮
    initSurrenderBtn();
}

// 初始化投降按钮功能
function initSurrenderBtn() {
    const surrenderBtn = document.getElementById('surrender-btn');
    if (surrenderBtn) {
        surrenderBtn.addEventListener('click', handleSurrender);
    }
}

// 处理投降逻辑
function handleSurrender() {
    // 显示确认对话框，防止误操作
    if (!confirm('确定要投降吗？投降后游戏将结束。')) {
        return;
    }

    // 向服务器发送投降请求
    if (gameState.socket) {
        gameState.socket.emit('surrender', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            if (response.status === 'success') {
                // 投降成功，游戏结束
                showMessage('你已投降，游戏结束', { type: 'warning' });
                // 等待服务器发送game_over事件
            } else {
                // 投降失败
                showMessage(`投降失败：${response.message}`, { type: 'error' });
            }
        });
    }
}

// ============ 浮动窗拖拽（2026-09-10 重写） ============
// 适用于 fixed 定位的浮窗（日志窗 / 聊天窗）。拖动时按真实坐标重定位，
// 始终至少保留一部分在视口内，可记住位置（localStorage）。支持鼠标与触摸。
function makeFloatingDraggable(el, handle, storageKey) {
    if (!el || !handle || el.dataset.floatDragBound === '1') return;
    el.dataset.floatDragBound = '1';

    const KEEP_VISIBLE = 48;   // 至少留多少像素在视口内
    let dragging = false, startX = 0, startY = 0, startLeft = 0, startTop = 0;

    function bounds() {
        const w = el.offsetWidth || 200;
        const h = el.offsetHeight || 120;
        return { w: w, h: h };
    }

    function place(left, top) {
        const b = bounds();
        const maxLeft = Math.max(0, window.innerWidth - b.w);
        const maxTop = Math.max(0, window.innerHeight - Math.min(b.h, KEEP_VISIBLE));
        const minTop = -(b.h - Math.min(b.h, KEEP_VISIBLE));
        el.style.left = Math.min(Math.max(-(b.w - KEEP_VISIBLE), left), maxLeft) + 'px';
        el.style.top = Math.min(Math.max(minTop, top), maxTop) + 'px';
        el.style.right = 'auto';
        el.style.bottom = 'auto';
    }

    function restore() {
        if (!storageKey) return false;
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
            if (saved && typeof saved.left === 'number' && typeof saved.top === 'number') {
                place(saved.left, saved.top);
                return true;
            }
        } catch (_) { }
        return false;
    }

    function save() {
        if (!storageKey) return;
        const r = el.getBoundingClientRect();
        try { localStorage.setItem(storageKey, JSON.stringify({ left: r.left, top: r.top })); } catch (_) { }
    }

    function begin(cx, cy) {
        // 紧凑（移动端）布局下浮窗已回到文档流，拖拽既无意义又会和滚动抢手势
        if (window.__adaptiveDragDisabled) return;
        const r = el.getBoundingClientRect();
        startX = cx; startY = cy;
        startLeft = r.left; startTop = r.top;
        dragging = true;
        el.classList.add('dragging');
    }

    function move(cx, cy) {
        if (!dragging) return;
        place(startLeft + (cx - startX), startTop + (cy - startY));
    }

    function end() {
        if (!dragging) return;
        dragging = false;
        el.classList.remove('dragging');
        save();
    }

    handle.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        if (e.target.closest('button, a, input, select, textarea')) return;
        begin(e.clientX, e.clientY);
        e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => move(e.clientX, e.clientY));
    window.addEventListener('mouseup', end);

    handle.addEventListener('touchstart', (e) => {
        if (!e.touches || !e.touches.length) return;
        if (e.target.closest('button, a, input, select, textarea')) return;
        begin(e.touches[0].clientX, e.touches[0].clientY);
        e.preventDefault();
    }, { passive: false });
    window.addEventListener('touchmove', (e) => {
        if (!dragging || !e.touches || !e.touches.length) return;
        move(e.touches[0].clientX, e.touches[0].clientY);
        e.preventDefault();
    }, { passive: false });
    window.addEventListener('touchend', end);

    window.addEventListener('resize', () => {
        // 紧凑布局下这些浮窗已经被搬进文档流（面板槽），此处的 rect 是流内位置，
        // 回写成 left/top 会把宽屏下的浮窗坐标写坏（表现为聊天框跑到左上角）
        if (window.__adaptiveDragDisabled) return;
        const r = el.getBoundingClientRect();
        place(r.left, r.top);
    });

    const restored = restore();
    el.style.cursor = 'grab';
    return { restore: restore, save: save, restored: restored };
}


// 文档流内元素的拖拽：只改 transform 做视觉偏移，不改 position/left/top，
// 因此元素仍留在原布局中（与“待使用魔法卡”窗口一致）。带边界钳制 + 触摸支持。
function makeVisualDraggable(el, handle) {
    if (!el || !handle || el.dataset.visualDragBound === '1') return;
    el.dataset.visualDragBound = '1';

    let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

    function readOffset() {
        const m = /translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/.exec(el.style.transform || '');
        return m ? [parseFloat(m[1]), parseFloat(m[2])] : [0, 0];
    }

    function begin(cx, cy) {
        // 同上：紧凑布局下不做视觉拖拽
        if (window.__adaptiveDragDisabled) return;
        [ox, oy] = readOffset();
        sx = cx; sy = cy;
        dragging = true;
        el.style.cursor = 'grabbing';
    }

    function move(cx, cy) {
        if (!dragging) return;
        const rect = el.getBoundingClientRect();
        const baseLeft = rect.left - ox;   // 未偏移时的位置
        const baseTop = rect.top - oy;
        const maxDx = window.innerWidth - rect.width - baseLeft;
        const maxDy = window.innerHeight - rect.height - baseTop;
        const dx = clamp(ox + (cx - sx), -baseLeft, Math.max(-baseLeft, maxDx));
        const dy = clamp(oy + (cy - sy), -baseTop, Math.max(-baseTop, maxDy));
        el.style.transform = `translate(${dx}px, ${dy}px)`;
    }

    function end() {
        if (!dragging) return;
        dragging = false;
        el.style.cursor = 'grab';
    }

    handle.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        if (e.target.closest('button, a, input, select, textarea')) return;
        begin(e.clientX, e.clientY);
        e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => move(e.clientX, e.clientY));
    document.addEventListener('mouseup', end);

    handle.addEventListener('touchstart', (e) => {
        if (!e.touches || !e.touches.length) return;
        if (e.target.closest('button, a, input, select, textarea')) return;
        begin(e.touches[0].clientX, e.touches[0].clientY);
        e.preventDefault();
    }, { passive: false });
    document.addEventListener('touchmove', (e) => {
        if (!dragging || !e.touches || !e.touches.length) return;
        move(e.touches[0].clientX, e.touches[0].clientY);
        e.preventDefault();
    }, { passive: false });
    document.addEventListener('touchend', end);

    el.style.cursor = 'grab';
}


// 初始化预览框拖拽功能（页面内元素：只做视觉偏移）
function initPreviewDrag() {
    const el = document.getElementById('magic-card-preview');
    if (!el) return;
    makeVisualDraggable(el, el.querySelector('.preview-header') || el);
}


// 初始化日志容器拖拽功能（页面内元素：只做视觉偏移）
function initLogDrag() {
    const logEl = document.querySelector('.log-container');
    if (!logEl) return;
    const drag = makeFloatingDraggable(logEl, logEl.querySelector('.log-header') || logEl, 'game_log_pos');
    // 手机窄屏且从未拖动过：默认折叠，避免挡住棋盘
    if (drag && !drag.restored && window.innerWidth < 768 && !logEl.classList.contains('collapsed')) {
        toggleGameLog();
    }
}

// 清掉手牌的「选中」状态。
// 选中态以前从不重置，会出两种事：
//   · 出牌被拒后卡仍算「已选中」→ 下一次单击是【立刻重试】而不是先选中，
//     提示弹两遍，看起来像重复投递
//   · 手牌变化后旧下标落到别的牌上 → 那张牌被【自动标成选中】，点一下直接进出牌流程
// 所有会让选中失效的时机都要调它。
function clearCardSelection() {
    if (gameState.selectedCardIndex < 0 && !gameState.selectedCardKey) return;
    gameState.selectedCardIndex = -1;
    gameState.selectedCardKey = null;
    updateHandUI();
}

// 选中态的「身份标识」：光记下标不够 —— 手牌一增一减，同一个下标就指向别的牌了。
function cardSelectionKey(card) {
    return card ? (card.name + '\u0000' + card.speed) : null;
}

// 服务端下发的「一份手牌」统一入口：校验 → 落地 → 渲染。
//
// 为什么不让各处自己赋值：手牌只有一个权威来源（服务端），而前端有多个会读到它的
// 地方（渲染、出牌、连锁、教皇旨意弃牌）。任何一处把 gameState.hand 写坏，界面就会
// 一脸空白且再也回不来 —— 必须把校验收在一个地方。
function applyHandPayload(data, source) {
    const incoming = data && data.hand;
    if (!Array.isArray(incoming)) {
        // 结构不对：宁可保持现状也不要覆盖。同时向服务端要一份权威手牌，
        // 让界面自己纠正过来（不必等玩家刷新页面）。
        console.warn(`[hand] ${source} 没带 hand 数组，已忽略：`, data);
        requestHandSync(`${source}:no-hand-array`);
        return false;
    }
    const clean = incoming.filter((c) => c && typeof c === 'object' && c.name);
    if (clean.length !== incoming.length) {
        // payload 里有坏条目：剔掉，但同样要一份权威数据兜底
        console.warn(`[hand] ${source} 含 ${incoming.length - clean.length} 个无效条目，已剔除`);
        requestHandSync(`${source}:bad-entries`);
    }
    const grew = clean.length > (Array.isArray(gameState.hand) ? gameState.hand.length : 0);
    gameState.hand = clean;
    updateHandUI();
    if (grew) playSfx('draw');
    return true;
}

// 主动向服务端要一份权威手牌。
// 节流：同一个原因 2 秒内只发一次，避免"推错了 → 要同步 → 又推错"打转。
let lastHandSyncAt = 0;
function requestHandSync(reason) {
    if (!gameState.socket || !gameState.roomId || !gameState.playerId) return;
    const now = Date.now();
    if (now - lastHandSyncAt < 2000) return;
    lastHandSyncAt = now;
    console.warn(`[hand] 请求服务端重发手牌（原因：${reason}）`);
    gameState.socket.emit('request_hand_sync', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
    }, (resp) => {
        if (resp && resp.status === 'error') {
            console.warn('[hand] 重同步失败：', resp.message);
        }
    });
}

function updateHandUI() {
    const handElement = document.getElementById('magic-hand');
    if (!handElement) return;

    // hand 被写坏时不要让它继续坏下去：先纠正成空数组再要一份权威数据。
    // （这里必须在清空 DOM 之前处理 —— 以前是清空之后才遍历，一抛异常就是整块空白。）
    if (!Array.isArray(gameState.hand)) {
        console.warn('[hand] gameState.hand 不是数组，已重置并请求重同步：', gameState.hand);
        gameState.hand = [];
        requestHandSync('hand-not-array');
    }

    // 手牌可能刚变过（出牌 / 摸牌 / 被埋葬）。按下标取到的牌若已不是当初选的那张，
    // 就把选中态清掉 —— 否则会出现「打完一张，下一张自动选中、点一下直接出牌」。
    if (gameState.selectedCardIndex >= 0) {
        const current = gameState.hand[gameState.selectedCardIndex];
        if (cardSelectionKey(current) !== gameState.selectedCardKey) {
            gameState.selectedCardIndex = -1;
            gameState.selectedCardKey = null;
        }
    }

    // 先在一个 Fragment 里把整份手牌搭好，最后一次性换掉容器内容。
    // 好处：中途任何一张牌出问题都不会留下"清空了却没填回去"的空白手牌区。
    const frag = document.createDocumentFragment();
    let rendered = 0;
    gameState.hand.forEach((card, index) => {
        if (!card || !card.name) return;   // 坏条目直接跳过，renderd 计数会暴露它
        const cardElement = document.createElement('div');
        cardElement.classList.add('magic-card');
        cardElement.dataset.index = index;

        // 如果是选中状态，添加selected类
        if (gameState.selectedCardIndex === index) {
            cardElement.classList.add('selected');
        }

        // ★ 2026-09-20：被更高优先级选船效果挡住的卡 —— 置灰 + 悬停说明。
        // 只是"提前告知"，真正的拒绝在服务端（那里才是唯一判据）。
        const pickBlocked = shipPickBlockedFor(card.name);
        if (pickBlocked) {
            cardElement.classList.add('pick-blocked');
            cardElement.title = pickBlocked;
        }

        cardElement.innerHTML = `
            <div class="card-name">${escapeHtml(card.name)}</div>
            <div class="card-speed">速阶：${escapeHtml(card.speed)}</div>
            <div class="card-type">${escapeHtml(card.type)}魔法</div>
        `;

        // 添加点击事件，实现点击选择/使用功能
        cardElement.addEventListener('click', () => {
            // ★ 被更高优先级选船效果挡住时，直接给出原因并中止
            //   （不中止的话玩家会走完一整套目标选择再被服务端拒绝）
            const blockedNow = shipPickBlockedFor(card.name);
            if (blockedNow) {
                showAlert(blockedNow);
                return;
            }
            // 如果是已选中状态，尝试使用卡牌
            if (gameState.selectedCardIndex === index
                    && gameState.selectedCardKey === cardSelectionKey(card)) {
                // 尝试使用卡牌
                playMagicCard(index);
            } else {
                // 选中卡牌，更新预览（记下身份，手牌一变就能识别出下标已失效）
                gameState.selectedCardIndex = index;
                gameState.selectedCardKey = cardSelectionKey(card);
                updateHandUI(); // 重新渲染手牌，更新选中状态
                updateCardPreview(card, index); // 更新卡牌预览信息
            }
        });

        frag.appendChild(cardElement);
        rendered += 1;
    });

    handElement.replaceChildren(frag);

    if (rendered !== gameState.hand.length) {
        // 渲染出来的张数和状态里的不一致 —— 状态被污染了，要一份权威数据纠正
        requestHandSync('render-count-mismatch');
    }

    // 更新卡牌预览
    if (gameState.selectedCardIndex >= 0 && gameState.selectedCardIndex < gameState.hand.length) {
        updateCardPreview(gameState.hand[gameState.selectedCardIndex], gameState.selectedCardIndex);
    } else {
        updateCardPreview(null);
    }
}

// 弃牌堆查看功能
function setupDiscardPileUI() {
    // 获取弃牌堆查看按钮
    const viewDiscardBtn = document.getElementById('view-discard-pile');
    const discardModal = document.getElementById('discard-pile-modal');
    const discardModalClose = document.getElementById('discard-pile-modal-close');

    if (viewDiscardBtn && discardModal && discardModalClose) {
        // 显示弃牌堆弹窗
        viewDiscardBtn.addEventListener('click', () => {
            discardModal.classList.remove('hidden');
            loadDiscardPile();
        });

        // 关闭弃牌堆弹窗
        function closeDiscardModal() {
            discardModal.classList.add('hidden');
        }

        // 点击X关闭
        discardModalClose.addEventListener('click', closeDiscardModal);

        // 点击弹窗外部关闭
        discardModal.addEventListener('click', (e) => {
            if (e.target === discardModal) {
                closeDiscardModal();
            }
        });

        // ESC键关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !discardModal.classList.contains('hidden')) {
                closeDiscardModal();
            }
        });
    }
}

// 加载弃牌堆数据
function loadDiscardPile() {
    gameState.socket.emit('get_discard_pile', {
        room_id: gameState.roomId,
        player_id: gameState.playerId
    }, (response) => {
        if (response.status === 'success') {
            displayDiscardPile(response.discard_pile);
        } else {
            showMessage(`加载弃牌堆失败：${response.message}`, { type: 'error' });
        }
    });
}

// 显示弃牌堆卡牌
function displayDiscardPile(discardPile) {
    const cardsContainer = document.getElementById('discard-pile-cards');
    if (!cardsContainer) return;

    // 清空容器
    cardsContainer.innerHTML = '';

    // 如果弃牌堆为空
    if (!discardPile || discardPile.length === 0) {
        cardsContainer.innerHTML = '<p style="text-align: center; color: var(--muted);">弃牌堆为空</p>';
        return;
    }

    // 显示弃牌堆卡牌
    discardPile.forEach((card, index) => {
        const cardElement = document.createElement('div');
        cardElement.className = 'discard-pile-card';
        cardElement.innerHTML = `
            <div class="discard-pile-card-name">${escapeHtml(card.name)}</div>
            <div class="discard-pile-card-type">${escapeHtml(card.type)}·速阶${escapeHtml(card.speed)}</div>
            <div class="discard-pile-card-desc">${escapeHtml(card.description)}</div>
        `;
        cardsContainer.appendChild(cardElement);
    });
}

// 在游戏初始化时设置弃牌堆UI
setupDiscardPileUI();

// 添加卡牌悬停提示功能
function initCardTooltip() {
    const tooltip = document.createElement('div');
    tooltip.id = 'card-tooltip';
    tooltip.style.position = 'absolute';
    tooltip.style.backgroundColor = 'white';
    tooltip.style.border = '1px solid #333';
    tooltip.style.borderRadius = '5px';
    tooltip.style.padding = '10px';
    tooltip.style.boxShadow = '0 2px 10px rgba(0,0,0,0.2)';
    tooltip.style.zIndex = '1000';
    tooltip.style.display = 'none';
    document.body.appendChild(tooltip);
}


// 创建魔法卡UI元素
function createMagicCardUI() {
    // 检查是否已经存在魔法卡系统，避免重复创建
    if (document.getElementById('magic-system')) {
        return;
    }
    
    const gameScreen = document.getElementById('game-screen');
    const magicUI = document.createElement('div');
    magicUI.id = 'magic-system';
    magicUI.innerHTML = `
        <div class="magic-hand-container">
            <h3>你的手牌</h3>
            <div id="magic-hand" class="magic-hand"></div>
        </div>
        <div id="chain-display" class="chain-display"></div>
    `;
    gameScreen.appendChild(magicUI);
}

// 状态显示栏（极限增援 / 无暇圣心）容器显隐同步：
// 两个子项都隐藏时整个容器要收起，否则它只剩 padding + border，会渲染成一条空白横条。
function initEffectStatusBarSync() {
    const bar = document.getElementById('effect-status-bar');
    if (!bar) return;
    const items = Array.from(bar.querySelectorAll('.status-item'));
    if (!items.length) return;
    const sync = () => {
        const anyVisible = items.some((el) => !el.classList.contains('hidden'));
        bar.classList.toggle('hidden', !anyVisible);
    };
    if (bar.dataset.statusSyncBound !== '1') {
        bar.dataset.statusSyncBound = '1';
        const observer = new MutationObserver(sync);
        items.forEach((el) => observer.observe(el, { attributes: true, attributeFilter: ['class'] }));
    }
    sync();
}

// 当前生效效果角标：按服务端广播的列表【整体重画】。
// 关键在「整体重画」——以前是 innerHTML += 追加，挂上就永远没人摘：
// 百亿补贴每回合切换其实就会被服务端清掉，角标却一直亮着，看着像永久生效。
// 服务端每次 effect_flags 变化（出牌结算完 / 回合切换 / 新大回合）都会推一份最新列表。
// 角标该挂在哪个容器里。
//
// ⚠️ 对局中玩家真正看到的头像是左上/右上两个【固定定位】的角落头像
// （#avatar-corner / #opponent-avatar-corner，由本文件开头那段脚本把
// <img> 从 .player-info 里搬过去）。所以角标必须挂进这两个容器，
// 挂在 .player-info 里的话根本不挨着头像。
// 兜底：角落头像还没建出来时先挂到 .player-info，免得渲染不出来。
function effectBoxFor(side) {
    const id = side === 'opponent' ? 'opponent-effect-indicators' : 'my-effect-indicators';
    const cornerId = side === 'opponent' ? 'opponent-avatar-corner' : 'avatar-corner';

    // 角落头像存在就一定要挂它下面；不存在才退到 .player-info。
    // ⚠️ 不能"建好了就不再动"：首次渲染可能早于角落头像创建，
    // 那样容器会一直留在兜底位置，永远不挨着头像。
    const host = document.getElementById(cornerId)
        || document.querySelectorAll('.players-info .player-info')[side === 'opponent' ? 1 : 0]
        || document.body;

    let box = document.getElementById(id);
    if (!box) {
        box = document.createElement('div');
        box.id = id;
        box.className = 'effect-indicators';
        box.dataset.side = side;
    }
    if (box.parentElement !== host) {
        // appendChild 会把它挪到 host 末尾，正好落在头像+名字下面
        host.appendChild(box);
    }
    return box;
}

function renderActiveEffects(payload) {
    // 兼容：旧调用点传的是纯字符串数组（表示"我自己的效果"）
    const data = Array.isArray(payload)
        ? { self: payload, opponent: [] }
        : (payload || { self: [], opponent: [] });
    const mine = normalizeEffectList(data.self);
    const theirs = normalizeEffectList(data.opponent);

    // 记住原始数据：浮层靠角标上的 data 属性回查，重绘后依然可用
    gameState.activeEffectsSelf = mine;
    gameState.activeEffectsOpponent = theirs;

    effectBoxFor('self').innerHTML = mine.map((e) => effectBadgeHTML(e, 'self')).join('');
    effectBoxFor('opponent').innerHTML = theirs.map((e) => effectBadgeHTML(e, 'opponent')).join('');

    // 角标重绘后旧浮层失去锚点，直接收起
    hideEffectPopover();
}

// 兼容旧的纯字符串数组（老快照 / 老客户端），避免升级瞬间渲染不出来。
// ⚠️ name / key / label 三个字段各有各的用处，不能互相顶替：
//   · name  = 卡名（浮层靠它回查卡面原文）—— 绝处逢生的两条角标**卡名相同**
//   · key   = 标记名（last_stand / last_stand_win）—— 出牌门禁靠它区分
//   · label = 显示名（卡名 + 可选后缀，如「绝处逢生·击杀即胜」）—— 只用于展示
// 拿显示名去开门禁是最容易犯的错：两个显示名都含"绝处逢生"，
// 于是"击杀即胜"那条会一直被当成"锁卡"，把玩家的牌白拦下来。
function normalizeEffectList(list) {
    if (!Array.isArray(list)) return [];
    return list.map((e) => {
        if (typeof e === 'string') {
            return { name: e, key: e, label: e, description: '', expires: '' };
        }
        const name = String((e && e.name) || '');
        return {
            name,
            key: String((e && e.key) || ''),
            label: String((e && e.label) || name),
            description: String((e && e.description) || ''),
            expires: String((e && e.expires) || ''),
        };
    }).filter((e) => e.name);
}

function effectBadgeHTML(effect, side) {
    // 显示用 label（可带后缀），浮层回查仍用 name（卡名）
    const safeLabel = escapeHtml(effect.label || effect.name);
    const safeName = escapeHtml(effect.name);
    return `<button type="button" class="effect-icon" data-side="${side}"`
        + ` data-effect-name="${safeName}"`
        + ` data-effect-key="${escapeHtml(effect.key || '')}"`
        + ` aria-label="查看效果：${safeLabel}">${safeLabel}</button>`;
}

// ---------------------------------------------------------------- 效果浮层
// 桌面：鼠标移上去显示、移开隐藏。
// 手机：点一下打开，再点一下（或点别处）关闭 —— 触屏没有 hover。
let effectPopoverEl = null;
let effectPopoverTimer = null;

function ensureEffectPopover() {
    if (effectPopoverEl && document.body.contains(effectPopoverEl)) return effectPopoverEl;
    const el = document.createElement('div');
    el.className = 'effect-popover hidden';
    el.setAttribute('role', 'tooltip');
    document.body.appendChild(el);
    effectPopoverEl = el;
    return el;
}

function hideEffectPopover() {
    if (effectPopoverTimer) { clearTimeout(effectPopoverTimer); effectPopoverTimer = null; }
    if (effectPopoverEl) {
        effectPopoverEl.classList.add('hidden');
        effectPopoverEl.dataset.for = '';
    }
}

function showEffectPopover(anchor, effect) {
    if (!anchor || !effect) return;
    const el = ensureEffectPopover();
    if (effectPopoverTimer) { clearTimeout(effectPopoverTimer); effectPopoverTimer = null; }
    const who = anchor.dataset.side === 'opponent' ? '对方' : '你';
    el.innerHTML = `
        <div class="effect-popover-head">
            <span class="effect-popover-who">${escapeHtml(who)}</span>
            <span class="effect-popover-name">${escapeHtml(effect.name)}</span>
        </div>
        <div class="effect-popover-body">${escapeHtml(effect.description || '这张卡没有额外说明')}</div>
        ${effect.expires ? `<div class="effect-popover-expiry">⏳ ${escapeHtml(effect.expires)}</div>` : ''}
    `;
    el.classList.remove('hidden');
    // 浮层身份用**标记名**（卡名不唯一：绝处逢生有两条角标，卡名相同）
    el.dataset.for = effect.key || effect.name;

    // 贴着角标定位，并保证不超出视口
    const r = anchor.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    let left = r.left + r.width / 2 - box.width / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - box.width - 8));
    let top = r.bottom + 8;
    if (top + box.height > window.innerHeight - 8) top = Math.max(8, r.top - box.height - 8);
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
}

// 从角标反查它对应的效果数据（重绘后依然有效，不依赖闭包里的对象）
//
// ⚠️ 必须同时按**标记名 key** 匹配，不能只按卡名 name。
// 绝处逢生挂着两条角标（last_stand / last_stand_win），两条的 name 都是
// 「绝处逢生」（这是有意的：浮层靠 name 回查卡面原文），只按 name 查会
// 永远命中列表里的第一条 —— 于是「击杀即胜」那枚角标弹出来的浮层写着
// 「本回合结束时失效」，与它"活到对局结束"的真实生命周期自相矛盾。
// 两条角标的 description 恰好相同，所以正文看不出问题，只有失效时机露馅。
function effectOfBadge(btn) {
    const side = btn.dataset.side === 'opponent' ? 'opponent' : 'self';
    const list = side === 'opponent'
        ? (gameState.activeEffectsOpponent || [])
        : (gameState.activeEffectsSelf || []);
    const key = btn.dataset.effectKey || '';
    const name = btn.dataset.effectName || '';
    if (key) {
        // 先按标记名精确匹配（同一条卡挂多个效果时这是唯一可靠的键）
        const byKey = list.find((e) => e.key === key);
        if (byKey) return byKey;
    }
    // 兜底：旧形状没有 key（normalizeEffectList 会把 key 填成卡名），
    // 或者服务端还没下发 key —— 这时按卡名查，保持升级瞬间可用。
    return list.find((e) => e.name === name) || null;
}

// 事件委托挂一次即可（角标会被反复重绘，逐个绑定会漏）
function bindEffectIndicators() {
    // 挂在 document 上：既覆盖角标，也能捕获"点别处关闭浮层"。
    // 角标数量很少，closest 判空的开销可以忽略。
    if (document.documentElement.dataset.effectBound === '1') return;
    document.documentElement.dataset.effectBound = '1';

    document.addEventListener('mouseover', (ev) => {
        const btn = ev.target.closest && ev.target.closest('.effect-icon');
        if (!btn) return;
        const effect = effectOfBadge(btn);
        if (effect) showEffectPopover(btn, effect);
    });
    document.addEventListener('mouseout', (ev) => {
        const btn = ev.target.closest && ev.target.closest('.effect-icon');
        if (!btn) return;
        // 留一点缓冲，避免鼠标经过边缘时闪一下
        if (effectPopoverTimer) clearTimeout(effectPopoverTimer);
        effectPopoverTimer = setTimeout(hideEffectPopover, 130);
    });
    // 手机端：触屏没有 hover，点一下切换
    document.addEventListener('click', (ev) => {
        const btn = ev.target.closest && ev.target.closest('.effect-icon');
        if (!btn) { hideEffectPopover(); return; }
        const el = ensureEffectPopover();
        // 同一个角标再点一下 = 收起。这里也用标记名比对（见 effectOfBadge 的注释：
        // 绝处逢生两条角标卡名相同，拿卡名比会把两条当成同一个，点第二条反而不开）
        const mine = btn.dataset.effectKey || btn.dataset.effectName;
        const sameOpen = !el.classList.contains('hidden') && el.dataset.for === mine;
        if (sameOpen) {
            hideEffectPopover();
        } else {
            const effect = effectOfBadge(btn);
            if (effect) showEffectPopover(btn, effect);
        }
    });
    window.addEventListener('scroll', hideEffectPopover, true);
    window.addEventListener('resize', hideEffectPopover);
}

// 初始化
// 防止 DOMContentLoaded 与 window.load 各调一次 init() 导致事件被重复绑定
// （重复绑定会让"日志折叠"等 toggle 类按钮连点两次而失效）
let __initialized = false;

function init() {
    if (__initialized) return;
    __initialized = true;
    // 绑定事件监听器
    bindEventListeners();
    // 状态显示栏容器显隐（避免出现空横条）
    initEffectStatusBarSync();
    // 效果角标的事件委托（桌面 hover / 手机点击）。角标会被反复重绘，
    // 所以用委托挂一次，绝不能逐个绑定。
    bindEffectIndicators();
    // 「拒绝所有阶段转换时点」开关（对局界面里那个入口）
    bindDeclinePriorityToggle();
    // 局内快捷语入口（第 4 批）：入口 / 面板 / 收起 三件事都绑在这里
    initQuickChatUI();
    // 好友功能（好友批）：入口按钮 / 面板 / 邀战提示条 / 四个 socket 事件。
    // ⚠️ 只绑事件、**不拉数据** —— /api/friends 必须等玩家点开面板才请求
    //    （首页无谓地打一次接口，游客还会白吃一个 401）。
    initFriendsUI();
    // 更新公告（公告批）：绑定入口 + 「有没有新公告」那一次判断。
    // ⚠️ 这里**只绑事件**（面板的取数等玩家点开才做）；"自动弹一次"是异步且可失败的，
    //    拉不到就什么都不做（见 initChangelogUI 的注释）。
    initChangelogUI();
    // 「我是谁」+ 可编辑项池子：登录态才有（游客 401），只用于判断名片上要不要
    // 显示「编辑资料」，绝不用它做权限判断 —— 保存时服务端还会再判一次。
    loadSelfIdentity();
    // 如果服务端传来了用户名，预填并设置为当前玩家名
    if (window.__USERNAME) {
        gameState.playerName = window.__USERNAME || gameState.playerName;
        if (playerNameInput) playerNameInput.value = gameState.playerName;
    }

    // SPA: 基于路径显示对应视图
    if (window.location.pathname.startsWith('/leaderboard')) {
        showLeaderboard();
    } else if (window.location.pathname.startsWith('/login')) {
        showLogin();
    } else if (window.location.pathname.startsWith('/register')) {
        showRegister();
    } else if (window.location.pathname.startsWith('/lobby')) {
        showLobby();
    }

    // 检查 URL 是否包含 room 参数，如果有则在连接后自动加入。
    // ⚠️ 入房只有一份实现（joinRoomById，模块作用域）—— 好友邀战的「进入房间」也走它，
    //    两处各写一套的话 `?room=` 与好友邀战迟早会漂移（CLAUDE.md 第 10 节第 1 条）。
    const urlParams = new URLSearchParams(window.location.search);
    const autoRoom = urlParams.get('room');
    if (autoRoom) {
        // quiet：邀请链接失效（房间不存在 / 已满）时**不弹**提示 ——
        // 这里只有 room_id，没有"是谁邀的你"，弹一句光秃秃的失败更让人困惑。
        joinRoomById(autoRoom, { quiet: true });
    }

    // 创建魔法手牌区域
    createMagicCardUI();
    // 初始化卡牌提示框
    initCardTooltip();
}

// ==================== 按房间号入房（唯一的入房实现） ====================
//
// 两条入口共用它，**不许再写第二套**：
//   ① 页加载时 URL 上的 `?room=XXXX`（邀请链接）—— init() 末尾那段；
//   ② 收到好友邀战（事件 `friend_invite`）后点「进入房间」—— 好友面板那边。
//
// ⚠️ 刻意放在模块作用域：它是"要复用的助手"，一旦写在某个函数体里，
//    另一个入口就会在运行时抛 ReferenceError，而调用点往往是 `.then()` / socket 回调，
//    异常会被**吞掉**、页面上零提示（CLAUDE.md 第 10 节第 6 条，本项目一天踩过两次）。
//
// 返回值：一个 Promise（true = 已进房）。调用方按需 `.then()`，不 await 也不影响既有行为。
// 画出"房间已就绪、等对手进来"这一态：房号 + 复制邀请链接 +「等待其他玩家加入...」。
// ⚠️ **复用创建房间那条路用的同一个面板**（`#custom-room-info` 就在 `#custom-room-screen` 里），
//    别另造一套等待 UI：两份实现必然漂移（本项目的老病根），而且 index.html 那个面板已经
//    带好了房号、复制链接与"等待其他玩家加入"文案，正是这里要的。
function showCustomRoomWaiting(roomId) {
    if (customCurrentRoomId) customCurrentRoomId.textContent = roomId || '';
    if (customRoomInfo) customRoomInfo.classList.remove('hidden');
    if (customRoomScreen && typeof switchScreen === 'function') switchScreen(customRoomScreen);
}

function joinRoomById(roomId, opts) {
    const options = opts || {};
    if (!roomId) return Promise.resolve(false);
    if (typeof ensureSocket === 'function') ensureSocket();
    const socket = gameState.socket;
    if (!socket) return Promise.resolve(false);

    // ⚠️ 名字必须在这里现取，**不能**直接用 `gameState.playerName`：
    //    - `playerNameInput` 在某些布局下压根不存在（下面那行 `if (playerNameInput)` 就是证据），
    //      那时它是 null；
    //    - 页加载早期 `gameState.playerName` 还可能是空串。
    //    直接发出去的话服务端会按"匿名玩家"入座，而**症状是"入房失败、页面上什么都没发生"**
    //    （实测踩过：`?room=` 自动入房返回 false，地址栏没同步、也没进放置界面，且不报错）。
    //    取值顺序与服务端 fallback 一致：当前状态 → 登录用户名 → 输入框 → 兜底字面量。
    const playerName = (gameState.playerName && String(gameState.playerName).trim())
        || window.__USERNAME
        || (playerNameInput && playerNameInput.value)
        || '玩家';

    const attempt = () => new Promise((resolve) => {
        socket.emit('join_room', { room_id: roomId, player_name: playerName }, (resp) => {
            if (resp && resp.status === 'success') {
                gameState.roomId = roomId;
                // 房号也写进地址栏：页内刷新 / 掉线重连用的还是既有那条 `?room=`
                // 自动入房逻辑，这里只是把状态同步过去（history.replaceState 不触发导航，
                // 不会把当前这局打断）。失败时静默忽略（file:// 等场景没有 history API）。
                try {
                    const url = new URL(window.location.href);
                    url.searchParams.set('room', roomId);
                    window.history.replaceState(null, '', url.pathname + url.search);
                } catch (e) { /* 无所谓，入房已经成功 */ }
                // ⚠️⚠️ **不要在这里切布船屏**：`handle_join_room` 只在**满 2 人**时才把阶段推到
                //     `placing_ships` 并下发 `game_state`；一个人先进房时服务端**什么都不发**。
                //     早先这里是无条件 `switchScreen(shipPlacementScreen)`，于是"先进房那个人"
                //     会停在一块**没有对手、也永远不会推进**的布船棋盘上 —— 用户实测报的
                //     "卡死在错误的布船界面"就是这个形状（被邀请方等不到发起方时也一样）。
                //     正确口径与 `customCreateRoom()` 那条路**完全一致**：先停在房间等待面板，
                //     等 `game_state(state='placing_ships')` 到了再由它切屏（见那个 handler 的注释）。
                showCustomRoomWaiting(roomId);
                resolve(true);
            } else {
                if (options.quiet !== true) {
                    // 服务端会带中文原因（房间不存在 / 房间已满）
                    showAlert((resp && resp.message) || '加入房间失败');
                }
                resolve(false);
            }
        });
    });

    if (socket.connected) return attempt();
    // 还没连上：等一次 connect 再发（照抄原来 `onceConnect` 的写法，用 off 摘钩子）
    return new Promise((resolve) => {
        const onceConnect = () => {
            socket.off('connect', onceConnect);
            attempt().then(resolve);
        };
        socket.on('connect', onceConnect);
        // 兜底：连不上也别把 Promise 永远挂着（8 秒后放行，调用方自行判断）
        setTimeout(() => resolve(false), 8000);
    });
}
window.joinRoomById = joinRoomById;

// 更新连锁UI显示
function updateChainUI() {
    const chainElement = document.getElementById('chain-display');
    if (!chainElement) return;

    chainElement.innerHTML = `<h3>当前连锁 (${gameState.chain.length})</h3>`;
    gameState.chain.forEach((item, index) => {
        const chainItem = document.createElement('div');
        chainItem.className = 'chain-item';
        chainItem.innerHTML = `
            <div>连锁 ${index + 1}：${item.card.name}</div>
            <div>玩家：${(item.playerId || item.player_id || item.caster) === gameState.playerId ? '你' : '对手'}</div>
        `;
        chainElement.appendChild(chainItem);
    });
}

// 添加显示可连锁卡牌的函数
// 更新阶段UI
function updatePhaseUI() {    const phaseElement = document.getElementById('current-phase');
    const enterBattleBtn = document.getElementById('enter-battle-phase');
    const enterEndBtn = document.getElementById('enter-end-phase');
    const endTurnBtn = document.getElementById('end-turn-btn');

    // 显示当前阶段
    phaseElement.textContent = {
        'preparation': '准备阶段',
        'battle': '战斗阶段',
        'end': '结束阶段'
    }[gameState.currentPhase] || gameState.currentPhase;

    // 更新按钮文本
    enterBattleBtn.textContent = '进入战斗阶段';
    enterEndBtn.textContent = '进入结束阶段';
    endTurnBtn.textContent = '结束结束阶段';

    // 按钮显示逻辑
    const isMyTurn = gameState.currentAttacker === gameState.playerId;

    // 隐藏所有按钮
    enterBattleBtn.style.display = 'none';
    enterEndBtn.style.display = 'none';
    endTurnBtn.style.display = 'none';

    // 根据当前阶段和回合显示相应按钮
    if (isMyTurn) {
        // 用 inline-block 而不是 block：block 级按钮不再受 #turn-indicator 的
        // text-align:center 影响，会贴在阶段卡片左边，和居中的状态文字错位。
        switch (gameState.currentPhase) {
            case 'preparation':
                enterBattleBtn.style.display = 'inline-block';
                break;
            case 'battle':
                enterEndBtn.style.display = 'inline-block';
                break;
            case 'end':
                endTurnBtn.style.display = 'inline-block';
                break;
        }
    }

    // 我发起的阶段转换正被拦下（在等对方响应）：按钮留着但禁用。
    // 不能直接隐藏 —— 玩家会以为界面坏了；保留 + 置灰 + 横幅说明才看得懂。
    const waiting = !!gameState.priorityWaiting || !!gameState.shenjiWaiting;
    [enterBattleBtn, enterEndBtn, endTurnBtn].forEach((b) => {
        if (!b) return;
        b.disabled = waiting;
        b.classList.toggle('is-waiting', waiting);
    });

    // 教皇旨意：战斗阶段给我方一个「弃卡换攻击 +2」的显式入口。
    // 不靠"点棋盘才发现次数是 0"才弹窗 —— 那样玩家根本不知道有这条路。
    if (typeof updatePapalDiscardButton === 'function') updatePapalDiscardButton();
    // 设置面板里那个勾选框要跟当前状态一致（弹窗里勾过也要同步过来），
    // 并且把本地偏好推给服务端 —— 服务端那份是房间级的，换房就重置了
    syncDeclinePriorityUI();
    ensureDeclinePrioritySynced();
}

// 添加阶段按钮事件监听
function setupPhaseButtons() {
    // 进入战斗阶段按钮
    document.getElementById('enter-battle-phase').addEventListener('click', () => {
        if (freezeAlert()) return;
        gameState.socket.emit('enter_battle_phase', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            // ack 可能是 undefined（服务端 handler 没回值），直接读 .status 会抛
            // TypeError 把错误提示吞掉，所以这里必须先判空。
            if (response && response.status === 'error') {
                showAlert(response.message);
            }
        });
    });

    // 进入结束阶段按钮
    document.getElementById('enter-end-phase').addEventListener('click', () => {
        if (freezeAlert()) return;
        // 获取当前剩余攻击次数
        const remainingAttacks = parseInt(attacksRemaining.textContent, 10);

        // 检查是否还有剩余攻击次数
        if (remainingAttacks > 0) {
            showAlert('你还有剩余攻击次数，无法进入结束阶段');
            return; // 阻止进入结束阶段
        }

        gameState.socket.emit('enter_end_phase', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            if (response && response.status === 'error') {
                showAlert(response.message);
            }
        });
    });

    // 教皇旨意：弃卡换攻击次数（显式入口；点棋盘发现次数为 0 时也会弹同一个窗）
    const papalBtn = document.getElementById('papal-discard-btn');
    if (papalBtn) {
        papalBtn.addEventListener('click', () => {
            if (freezeAlert()) return;
            if (!gameState.hand || gameState.hand.length === 0) {
                showAlert('没有可弃置的魔法卡，无法换取攻击次数');
                return;
            }
            showPapalDiscardChoice();
        });
    }

    // 结束回合按钮
    document.getElementById('end-turn-btn').addEventListener('click', () => {
        if (freezeAlert()) return;
        gameState.socket.emit('end_turn', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            if (response && response.status === 'error') {
                showAlert(response.message);
            }
        });
    });
}


// 神机妙算宣言弹窗
function showShenjiDeclarePrompt() {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10001;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center';
    const box = document.createElement('div');
    box.style.cssText = 'background:#fff;color:#222;padding:20px 24px;border-radius:10px;min-width:280px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.3)';
    box.innerHTML =
        '<div style="font-weight:bold;margin-bottom:8px">神机妙算 · 宣言预测</div>' +
        '<div style="font-size:13px;color:#555;margin-bottom:10px">预测：对方结束阶段结束时，你的船数会减少多少（0-6）？</div>' +
        '<input type="number" min="0" max="6" step="1" value="0" style="width:80px;padding:6px;text-align:center;font-size:16px">' +
        '<div style="margin-top:12px"><button id="shenji-ok" style="padding:6px 20px;cursor:pointer">确定</button></div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    const input = box.querySelector('input');
    const ok = box.querySelector('#shenji-ok');
    const close = function () { try { document.body.removeChild(overlay); } catch (e) {} };
    ok.onclick = function () {
        const v = Math.max(0, Math.min(6, parseInt(input.value || '0', 10) || 0));
        if (gameState.socket) {
            gameState.socket.emit('confirm_shenji_declare', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                prediction: v
            }, function (resp) {
                if (resp && resp.status === 'success') showMessage(resp.message || '宣言成功');
                else if (resp) showAlert(resp.message || '宣言失败');
            });
        }
        close();
    };
}

// 教皇旨意：选一张手牌弃置，换来 2 次攻击次数。
//
// ⚠️ 这个函数【不再接 x/y】：作者裁定弃卡只负责"加次数"，
// 攻击本身交给玩家点格子走普通 attack（和正常攻击逻辑一致）。
// 旧版是"先点格子 → 弹窗选卡 → 服务端对着那个格子一次性打两发"，
// 导致玩家无法选择打哪两格，也享受不到普通攻击路径的联动。
function showPapalDiscardChoice() {
    const overlay = document.createElement('div');
    overlay.className = 'papal-discard-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10002;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center';
    const box = document.createElement('div');
    box.className = 'papal-discard-box';
    box.style.cssText = 'background:#fff;color:#222;padding:18px 22px;border-radius:10px;min-width:300px;max-width:80vw;max-height:70vh;overflow:auto;text-align:center';
    box.innerHTML = '<div style="font-weight:bold;margin-bottom:6px">教皇旨意 · 弃一张魔法卡</div>'
        + '<div style="font-size:13px;opacity:.75;margin-bottom:10px">弃置后攻击次数 +2，然后点对手棋盘就能正常攻击</div>';
    const list = document.createElement('div');
    list.style.cssText = 'display:flex;flex-direction:column;gap:6px;text-align:left';
    if (!gameState.hand || gameState.hand.length === 0) {
        list.innerHTML = '<div style="color:#c0392b">没有可弃置的魔法卡</div>';
    } else {
        gameState.hand.forEach((card, i) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'papal-discard-card';
            b.textContent = (card.name || '') + '（速阶' + card.speed + '）';
            b.style.cssText = 'padding:6px 10px;cursor:pointer;text-align:left';
            b.onclick = () => {
                if (gameState.socket) {
                    gameState.socket.emit('papal_discard', {
                        room_id: gameState.roomId,
                        player_id: gameState.playerId,
                        discard_card_index: i
                    }, (resp) => {
                        if (resp && resp.status === 'error') {
                            showAlert(resp.message);
                        } else if (resp && resp.status === 'success') {
                            showMessage(resp.message || '攻击次数 +2，现在可以正常攻击了');
                            // ⚠️ 绝不能在这里本地删牌：服务端 _papal_discard_grant 扣牌后
                            // 【已经】推了一次权威 hand_updated（3 张→2 张），ack 只是后到。
                            // 旧实现在这里又 `hand.splice(i, 1)` 删一张 → 多删一张，
                            // 作者实测「3 张弃掉 1 张，结果只剩 1 张」。
                            // 与 2026-09-14 修的 sendMagicCard 是同一族：服务端才是权威，
                            // 前端的本地删牌兜底一律不要。
                            // 回归：tools/papal_discard_check.mjs 的 ★★ 那条断言。
                        }
                    });
                }
                try { document.body.removeChild(overlay); } catch (e) {}
            };
            list.appendChild(b);
        });
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = '取消';
    close.style.cssText = 'margin-top:12px;padding:6px 16px;cursor:pointer';
    close.onclick = () => { try { document.body.removeChild(overlay); } catch (e) {} };
    box.appendChild(list);
    box.appendChild(close);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
}

// 教皇旨意生效时，给玩家一个显式入口主动换次数
// （否则只能靠"点棋盘发现次数是 0"才会弹出来）。
function updatePapalDiscardButton() {
    const btn = document.getElementById('papal-discard-btn');
    if (!btn) return;
    const active = gameState.fieldMagic === '教皇旨意';
    const mine = gameState.currentAttacker === gameState.playerId
        && gameState.currentPhase === 'battle';
    btn.style.display = (active && mine) ? 'inline-block' : 'none';
}

// ── 「不再询问阶段转换时点」开关 ────────────────────────────────
// 两个入口，共用同一份状态：
//   · 局内开关 #phase-timing-toggle（阶段卡片右上角，常驻、随时可切）
//   · 优先权弹窗里的 #decline-priority-toggle（弹窗里顺手勾）
// ⚠️ 局内那个常驻入口是必须的：勾上之后就不再弹窗了，只有弹窗内那个开关的话
// 玩家永远没机会取消勾选 —— 相当于把自己锁死。
// 作者 2026-09-14 明确要求"做成一个开关放在局内，而不是在设置中"，
// 所以设置面板里那份已删掉，只留局内这一个。
//
// 偏好存在 localStorage：服务端那份是【房间级】的，切房间就重置；
// 但玩家说"不想被问"是个跨局的意愿，所以本地记住，进新局时再同步上去。
const DECLINE_PRIORITY_KEY = 'battleship_decline_priority';

function loadDeclinePriorityPref() {
    try {
        return localStorage.getItem(DECLINE_PRIORITY_KEY) === '1';
    } catch (e) {
        return false;
    }
}

function saveDeclinePriorityPref(on) {
    try {
        localStorage.setItem(DECLINE_PRIORITY_KEY, on ? '1' : '0');
    } catch (e) { /* 隐私模式下写不了，忽略即可 */ }
}

// 进了新房间要把本地偏好同步给服务端（否则新房间又会开始询问）
function pushDeclinePriorityPref() {
    if (!gameState.socket || !gameState.roomId || !gameState.playerId) return;
    gameState.socket.emit('set_decline_priority', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        decline: !!gameState.declinePriority,
    });
}

// 每个房间只需同步一次（updatePhaseUI 会被频繁调用）
function ensureDeclinePrioritySynced() {
    if (!gameState.roomId) return;
    if (gameState.declinePrioritySyncedRoom === gameState.roomId) return;
    gameState.declinePrioritySyncedRoom = gameState.roomId;
    pushDeclinePriorityPref();
}

function setDeclinePriority(on, opts) {
    const options = opts || {};
    gameState.declinePriority = !!on;
    saveDeclinePriorityPref(gameState.declinePriority);
    syncDeclinePriorityUI();
    if (options.notify !== false && gameState.socket && gameState.roomId) {
        gameState.socket.emit('set_decline_priority', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            decline: gameState.declinePriority,
        }, (resp) => {
            if (resp && resp.status === 'error') showAlert(resp.message);
        });
    }
    if (options.silent !== true) {
        showMessage(gameState.declinePriority
            ? '已关闭阶段转换时点询问（点阶段卡片右上角的开关可随时恢复）'
            : '已恢复阶段转换时点询问');
    }
}

// 三个入口共用同一份状态：局内开关 / 优先权弹窗里的勾选框 / 本地偏好。
function syncDeclinePriorityUI() {
    const on = !!gameState.declinePriority;
    const inPrompt = document.getElementById('decline-priority-toggle');
    if (inPrompt) inPrompt.checked = on;
    const inGame = document.getElementById('phase-timing-toggle');
    if (inGame) {
        inGame.setAttribute('aria-pressed', on ? 'true' : 'false');
        inGame.classList.toggle('is-off', on);
        const state = document.getElementById('phase-timing-state');
        if (state) state.textContent = on ? '已关闭' : '询问中';
    }
}

function bindDeclinePriorityToggle() {
    const btn = document.getElementById('phase-timing-toggle');
    if (btn && btn.dataset.bound !== '1') {
        btn.dataset.bound = '1';
        btn.addEventListener('click', () => setDeclinePriority(!gameState.declinePriority));
    }
    // 启动时把本地偏好读进来（弹窗里那个勾选框、局内开关都据此显示）
    gameState.declinePriority = loadDeclinePriorityPref();
    syncDeclinePriorityUI();
}

// 仁王之盾：选择至多 3 艘自己的船进入护盾状态。
//
// 2026-09-17 改版（作者要求）：旧实现弹一个「选择船 1 (3,4) / 选择船 2 …」的
// 按钮列表 —— 玩家得自己在坐标里猜哪艘是哪艘。改为与克苏鲁之眼同一套交互：
// **直接在【自己的棋盘】上点船**，绿框高亮可点、再点一下取消，选满后点确认提交。
//
// ⚠️ 必须用「状态 + 事件委托 + 重绘后重刷」这套写法（与恶魔契约/神之宣告同款）：
// showRenwangChoice() 是在 chain_resolved 处理器里被调用的，而服务端紧接着还会推
// ships_updated / player_ships_updated —— 前端一收到就 initGameBoards() 把棋盘
// innerHTML 整块重建。第一版是「逐格绑 click + 逐格加 class」，重绘后高亮和监听
// 全被冲掉，玩家实测就是「正在选择的时候点不了任何有船的格子、也没有绿色高亮」。
// 现在：委托监听挂在 #game-player-board 容器上（格子重建也不失效），高亮由
// paintRenwangCells() 根据 gameState.renwangPick 在每次重绘后重刷。
function renwangPickableCells() {
    // 只收【还活着】的船：沉船仍留在 gameState.ships 里（alive === false），
    // 服务端也会跳过它们。返回 {「x,y」: player.ships 里的原始下标}，
    // 下标要原样回传（服务端 ship_indices 就是按这个顺序取的）。
    const map = new Map();
    (gameState.ships || []).forEach((ship, idx) => {
        if (ship.alive === false) return;
        (ship.positions || []).forEach(p => map.set(p.x + ',' + p.y, idx));
    });
    return map;
}

function clearRenwangPick() {
    gameState.renwangPick = null;
    gameState.selectingOnBoard = false;
    if (gameState.selectionCleanup === clearRenwangPick) gameState.selectionCleanup = null;
    document.querySelectorAll('.cell.pick-ship, .cell.pick-disabled, .cell.pick-selected')
        .forEach(c => c.classList.remove('pick-ship', 'pick-disabled', 'pick-selected'));
    document.querySelectorAll('.magic-target-prompt').forEach(el => el.remove());
}

// 按当前 renwangPick 状态把「可点 / 灰掉 / 已选」刷到棋盘上。
// 幂等：initGameBoards() 每次重绘后都会调它（同 paintSacrificeCells）。
function paintRenwangCells() {
    const pick = gameState.renwangPick;
    if (!pick || !gamePlayerBoard) return;

    const map = renwangPickableCells();
    pick.cells = map;
    // 期间被打沉的船不再算数（否则会把死船的下标提交上去、白白浪费一次选择）
    pick.picked = pick.picked.filter(key => map.has(key));

    gamePlayerBoard.querySelectorAll('.cell').forEach(cell => {
        const key = cell.dataset.x + ',' + cell.dataset.y;
        cell.classList.remove('pick-ship', 'pick-disabled', 'pick-selected');
        if (!map.has(key)) {
            cell.classList.add('pick-disabled');   // 空格 / 沉船格：灰掉，点了没用
            return;
        }
        cell.classList.add('pick-ship');
        if (pick.picked.indexOf(key) >= 0) cell.classList.add('pick-selected');
    });

    const info = document.getElementById('renwang-info');
    if (info) {
        info.className = pick.picked.length ? 'selection-info' : 'selection-info pending';
        info.innerHTML = `<span class="sel-dot"></span>已选 ${pick.picked.length} / ${pick.max} 艘` +
            (pick.picked.length ? ' — 可以确认了' : '');
    }
    const btn = document.getElementById('renwang-confirm');
    if (btn) btn.disabled = pick.picked.length === 0;
}

// 事件委托：只绑一次，且绑在容器上 —— 格子被重建也不影响
function bindRenwangBoardClick() {
    if (!gamePlayerBoard || gamePlayerBoard.dataset.renwangBound === '1') return;
    gamePlayerBoard.dataset.renwangBound = '1';
    gamePlayerBoard.addEventListener('click', (e) => {
        const pick = gameState.renwangPick;
        if (!pick) return;   // 没在选船：完全不干预棋盘的其它点击
        const el = e.target && e.target.closest ? e.target.closest('.cell.pick-ship') : null;
        if (!el || !gamePlayerBoard.contains(el)) return;
        e.stopPropagation();
        e.preventDefault();
        const key = el.dataset.x + ',' + el.dataset.y;
        const at = pick.picked.indexOf(key);
        if (at >= 0) {
            pick.picked.splice(at, 1);          // 再点一次 = 取消这艘
        } else {
            if (pick.picked.length >= pick.max) {
                showAlert(`最多选择 ${pick.max} 艘战舰`);
                return;
            }
            pick.picked.push(key);
        }
        paintRenwangCells();
    }, true);
}

function showRenwangChoice() {
    const MAX_SHIPS = 3;
    if (!gamePlayerBoard) {
        showAlert('棋盘还没准备好，请稍后再试');
        return;
    }
    // 自愈：上一次选区若没清理干净，先收尾（否则 selectingOnBoard 卡住）
    if (typeof gameState.selectionCleanup === 'function') {
        try { gameState.selectionCleanup(); } catch (_) { }
    }
    clearRenwangPick();

    gameState.renwangPick = { max: MAX_SHIPS, picked: [], cells: new Map() };
    gameState.selectingOnBoard = true;
    gameState.selectionCleanup = clearRenwangPick;

    const prompt = document.createElement('div');
    prompt.className = 'magic-target-prompt';
    prompt.id = 'renwang-prompt';
    prompt.innerHTML = `
        <h3>仁王之盾 · 选择要保护的战舰（至多 ${MAX_SHIPS} 艘）</h3>
        <p class="magic-hint">直接点你自己棋盘上绿色高亮的战舰格；再点一次取消选择。</p>
        <div class="selection-info pending" id="renwang-info">已选 0 / ${MAX_SHIPS} 艘</div>
        <div style="text-align:center;margin-top:8px;">
            <button id="renwang-confirm" disabled>确认</button>
            <button id="renwang-cancel">取消</button>
        </div>`;
    document.body.appendChild(prompt);

    bindRenwangBoardClick();
    paintRenwangCells();

    if (!renwangPickableCells().size) {
        showMessage('你没有可保护的战舰（已沉没的船不能加护盾）', { type: 'warning' });
    }

    prompt.querySelector('#renwang-confirm').addEventListener('click', () => {
        const pick = gameState.renwangPick;
        if (!pick) return;
        // 用【当前】最新的下标映射换算，避免棋盘重绘/船被击沉后下标过期
        const map = pick.cells && pick.cells.size ? pick.cells : renwangPickableCells();
        const idxs = [];
        pick.picked.forEach(key => {
            const idx = map.get(key);
            if (idx !== undefined && idxs.indexOf(idx) < 0) idxs.push(idx);
        });
        if (!idxs.length) { showAlert('请至少选择一艘战舰'); return; }
        if (!gameState.socket) { clearRenwangPick(); return; }
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'shield_choice',
            target_data: { ship_indices: idxs }
        }, (resp) => {
            if (resp && resp.status === 'success') showMessage(resp.message || '护盾已添加');
            else if (resp) showAlert(resp.message || '选择失败');
            clearRenwangPick();
        });
    });

    prompt.querySelector('#renwang-cancel').addEventListener('click', () => {
        // 取消要告诉服务端释放待选择状态，否则 magic_temp_data 会一直挂着
        // shield_choice（玩家之后的操作都被当成"还在选护盾"）。
        if (gameState.socket && gameState.roomId) {
            gameState.socket.emit('cancel_magic_selection', {
                room_id: gameState.roomId, player_id: gameState.playerId
            });
        }
        clearRenwangPick();
    });
}


/* ============================================================================
 * 好友功能（好友批，2026-09-19）—— 面板 / 入口红点 / 查看面加好友 / 邀战提示 / 结算加好友
 *
 * 契约（后端在并行实现，字段名与事件名一个都不能改）：
 *   GET  /api/friends            → {friends:[{user_id,username,avatar,level,rank_label,online,in_game,unread}],
 *                                   incoming:[{user_id,username,avatar,created_at}],
 *                                   outgoing:[{user_id,username,avatar,created_at}],
 *                                   limits:{max_friends,requests_per_hour},
 *                                   counts:{friends,incoming,unread_total}}
 *   POST /api/friends/request  {username} → {status:'sent'|'already_friends'|'already_pending'|'blocked'|'self'|'error'}
 *   POST /api/friends/respond  {username, accept:bool} → {status:'accepted'|'declined'|'error'}
 *   POST /api/friends/remove   {username} → {status:'ok'|'error'}
 *   POST /api/friends/block    {username} → {status:'ok'|'error'}
 *   POST /api/friends/invite   {username} → {status:'ok',room_id} 或 {status:'error',error:'中文原因'}
 *   好友私聊（私聊批，契约见 docs/FRIEND_DM_2026_09_19.md §4）：
 *   GET  /api/friends/messages?username=<name>&limit=50&before=<id>
 *                                → {status:'ok',has_more:bool,messages:[{id,from_uid,to_uid,body,created_at,stamp,mine}]}
 *   POST /api/friends/messages {username, body} → {status:'ok',message:{…同一条…}}
 *   POST /api/friends/messages/read {username}  → {status:'ok',read:3}
 *   ⚠️ 时间只渲染服务端给的 `stamp`；未读数**只认** `friend.unread` 与 /read 的成功回执，
 *      前端不自增也不自算（规则只有一份实现，在 dm.py）。
 *   未登录一律 401；申请过频 429；好友满 400。
 *   ⚠️ 服务端给的是 `{status:'error', error:'中文原因'}` —— 前端**原样显示那个 error**，
 *      绝不自己编一套文案（自己编的那套迟早跟后端的真实原因对不上）。
 *
 * 三条本项目硬规矩在本节的具体落法：
 *   ① **模块级函数不许引用函数作用域里的东西**（第 10 节第 6 条）：
 *      本节的每一个函数、每一个 let 都在模块作用域，互相引用不会抛 ReferenceError。
 *      唯一从函数作用域里带出来的东西是 socket 事件回调的 `data` —— 那是**参数**，不是闭包变量。
 *   ② **"先清空再填充"必须先校验数据、失败时保留上一帧**（第 10 节第 3 条）：
 *      三个分区容器只在读到**合法**响应之后才重写；请求失败只更新 #friends-msg 那一行错误位，
 *      容器里留上一帧的内容（`updateHandUI` 清空后没填回来 → 空白手牌，就是这条的出处）。
 *   ③ **含 position:fixed 后代的元素不许加 transform/filter/backdrop-filter**（第 11 节第 7 条）：
 *      面板走既有的 .modal-overlay 那套；邀战提示条自己就是 fixed、挂在 body 上，
 *      它的祖先链（body → #friend-invite-toast）里一个 transform/filter 都没有。
 * ============================================================================ */

// 关系态取值。'self' 只用于内部（自己看自己 → 按钮不渲染）。
// ⚠️ 服务端还会下发 `blocked_by_me` / `blocked_me`（与 server.py 的同名常量对应）——
//    本表是"这个取值合不合法"的**白名单**，少一个就会被判非法并**降级成 `none`**：
//    症状是"被拉黑的人照样看到一个**可点**的「加好友」"（端到端实测钉出来的 PB3：
//    点了服务端只会回一句中文原因，白让用户点一次）。
const FRIEND_RELATIONS = ['none', 'pending_out', 'pending_in', 'friends', 'self',
    'blocked_by_me', 'blocked_me'];
// 邀战提示条自动消失时间（与局内轻提示同一个量级）
const FRIEND_INVITE_TOAST_MS = 12000;
// 面板当前这一帧的数据 + 三个容器的"上一帧"（保留上一帧就靠它）
let friendsState = null;
// 入口红点的当前值（配 counts.incoming；服务端事件先到也不会被面板的一次拉取冲乱）
let friendPendingCount = 0;
let friendPendingSynced = false;      // 是否已经用一次真实的 /api/friends 校准过
// 当前查看面里那个人（点 #add-friend-btn 时要发给他）
let currentFriendTarget = '';
let currentFriendRelation = 'none';
// 每个人这次会话里**已经算出来的关系**（username → 'none'|'pending_out'|'pending_in'|'friends'）。
// ⚠️ 为什么必须按人缓存、而不是用一个全局布尔哨兵：
//    从「不是好友」变成「好友」要在按钮旁**多一个「邀战」**，而那张卡永远先按 'none' 画，
//    所以只能重渲染一次。第一版用一个全局布尔，而 `showUserProfile` 一进去就把它复位 ——
//    回到关系判断时又当成"没重渲染过" → **无限重渲染**（页面永远停在「加载中…」，且不报错）。
//    第二版改成 Set（只记"重渲染过"），结果第二次打开同一个人的名片时**直接跳过关系计算**，
//    按钮永远停在「加好友」。所以缓存的是**关系本身**：第二次进来不再打接口、
//    直接把缓存的关系写上去（要重渲染的那一次也已经做过了，不会再递归）。
//    任何一次写操作（加/接受/删除）之后都应当把这个人的缓存清掉（见 forgetFriendRelation）。
const friendRelationCache = new Map();
// 正在同步渲染查看面那张卡（重入保护）。见 reRenderProfileCard。
let profileCardRendering = false;
// 当前挂着的邀战（点「进入房间」时用）。房间号是**服务端给的**，前端不拼。
let activeInviteRoom = '';
// 邀战提示条的自动收起定时器（模块级：show/hide 两个函数都要用它）
let friendInviteTimer = null;
// 结算界面那一行的最近对手（`recent_opponent` 事件落下来的）
let recentOpponentState = { name: '', relation: '', userId: null };

// ---------- 通用小助手 ----------

// 后端中文原因：契约是 `{status:'error', error:'...'}`；个别接口可能用 `message`。
// 两个都没有时返回''（调用方自己去兜一句通用文案）。
function apiReason(body, fallback) {
    if (body && typeof body === 'object') {
        if (typeof body.error === 'string' && body.error) return body.error;
        if (typeof body.message === 'string' && body.message) return body.message;
    }
    return fallback || '';
}

// 统一的写接口调用。**永不 reject** —— 返回值统一是
//   {ok:true, data} | {ok:false, code:401|429|400|0, reason:'中文原因'}
// 这样调用点不用各自写 try/catch，也不会出现"异常被 .then() 吞掉、页面上零提示"那种情况。
function friendApiPost(path, payload) {
    return fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload || {})
    }).then(resp => resp.text().then(text => {
        let body = null;
        try { body = text ? JSON.parse(text) : null; } catch (e) { body = null; }
        // 未登录：契约是 401；真机上加一个"其实是登录 HTML"的形状兜一下
        if (resp.status === 401 ||
            (resp.status === 200 && /<html|<!doctype/i.test(text) && /登录/.test(text))) {
            return { ok: false, code: 401, reason: '请先登录' };
        }
        if (!resp.ok) {
            // 429 过频 / 400 好友满 —— 原因一律用服务端给的那个中文串
            return { ok: false, code: resp.status, reason: apiReason(body, '操作失败（' + resp.status + '）') };
        }
        if (!body || typeof body !== 'object') {
            return { ok: false, code: 0, reason: '服务端返回了无法解析的内容' };
        }
        return { ok: true, data: body };
    })).catch(() => ({ ok: false, code: 0, reason: '网络错误，请稍后重试' }));
}

// 面板底部那一行提示位（成功/失败都写这里；失败用红色）
function setFriendsMsg(text, isError) {
    const el = document.getElementById('friends-msg');
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('is-error', isError === true);
}

// ---------- 关系计算（本批的核心妥协点，务必看清） ----------
//
// ⚠️ 为什么不在 /user_stats 或 /api/profile 的响应里取 relation？
//    因为那两个接口的响应里**根本没有这个字段**，而本批只有前端授权
//    （server.py / api.py / db.py 由另外两个智能体在并行改，前端一个字都不许碰）。
//    所以这里退一步：打开查看面时**单独拉一次 GET /api/friends**
//    （它里面本来就有我的全部好友 + 我发出的 + 我收到的），
//    再按 username 在本地比对，算出 none / pending_out / pending_in / friends。
//    拿到之后经 opts.friendRelation 传进名片渲染（见 profileCardModel 那段注释）。
// ⚠️ 拉取失败（游客 401 / 接口还没上线）**兜成 'none'**：名片照常渲染，
//    按钮显示「加好友」，真正点下去时由服务端裁决 —— 绝不让"拿不到关系"变成"名片打不开"。
// ⚠️ 用 username 比而不是 user_id：查看面的入口（排行榜、游客对局、对局内头像）
//    手里只有 username，没有对方的 user_id。
function resolveFriendRelation(username, isSelfHint) {
    if (isSelfHint === true) return Promise.resolve('self');
    const name = String(username || '');
    if (!name) return Promise.resolve('self');
    // ⚠️ 游客（页面没有 window.__USERNAME）**不打这个接口**：一定 401，
    //    而 401 的结论跟"没登录所以没有关系"是同一件事。省掉这一次往返不是为了省流量，
    //    是为了**不把既有链路拖慢** —— 查看面现在多了这一次取数，
    //    而"点开头像立刻读名片"那几个回归断言对这几毫秒很敏感（实测踩过）。
    if (!window.__USERNAME) return Promise.resolve('none');
    return fetchFriends().then(res => {
        if (!res.ok || !res.data) return 'none';
        return computeRelationByName(res.data, name);
    }).catch(() => 'none');
}

// 纯函数：从一次 /api/friends 的响应里，按 username 算出关系。
// 单独拎出来是为了能在回归工具里直接对着同一份数据断言（不必再打一次接口）。
function computeRelationByName(data, username) {
    const name = String(username || '');
    if (!name || !data) return 'none';
    const hit = (list) => (Array.isArray(list) ? list : []).some((u) =>
        u && String(u.username || '').toLowerCase() === name.toLowerCase());
    if (hit(data.friends)) return 'friends';
    if (hit(data.incoming)) return 'pending_in';
    if (hit(data.outgoing)) return 'pending_out';
    return 'none';
}

// ---------- 入口红点 ----------
// 数字**只认服务端**：优先用 counts.incoming；没有 counts 时退回 incoming.length。
// 为 0 一律隐藏（不显示一个"0"的红点）。
function renderFriendsBadge() {
    const badge = document.getElementById('friends-badge');
    if (!badge) return;
    const n = Number(friendPendingCount) || 0;
    if (n > 0) {
        badge.textContent = String(n);
        badge.classList.remove('hidden');
    } else {
        badge.textContent = '0';
        badge.classList.add('hidden');
    }
}

// 用一次真实响应对齐红点。
// ⚠️ `friendPendingSynced` 的用途：`friend_request` 事件可能**先于**面板的第一次拉取到达，
//    那时候数字已经 +1 了，若这次拉取的响应里还没把新申请算进去（服务端写入与读的时序），
//    直接覆盖会把数字冲回去。所以只在"还没被事件改过"或"这次响应非零"时才覆盖。
function syncFriendsBadge(data) {
    if (!data || typeof data !== 'object') return;
    const counts = data.counts;
    const raw = (counts && counts.incoming !== undefined)
        ? counts.incoming
        : (Array.isArray(data.incoming) ? data.incoming.length : null);
    if (raw === null || raw === undefined) return;
    const n = Math.max(0, Number(raw) || 0);
    if (!friendPendingSynced || n > 0) {
        friendPendingCount = n;
        friendPendingSynced = true;
    }
    renderFriendsBadge();
}

// ---------- 行渲染 ----------

// 好友行：头像 + 用户名 + 等级 + 段位 label + 状态点 + 未读数 + 私聊 / 邀战 / 删除。
// ⚠️ 排序**不在前端做** —— 服务端已经把「在线在前、对局中次之」排好了，照序渲染即可
//    （CLAUDE.md 第 10 节第 1 条：同一个业务判断有两份实现就一定会漂移）。
// ⚠️ 未读数**只认服务端给的 `f.unread`**（§4）：前端既不自增也不自算总数，
//    数字为 0（或字段缺失/不是数）时摘 `hidden` 的**只有**这个 span，不影响这一行的其它部分。
function friendRowHtml(f) {
    const online = f.online === true;
    const inGame = f.in_game === true;
    const cls = inGame ? 'friend-ingame' : (online ? 'friend-online' : 'friend-offline');
    const stateText = inGame ? '对局中' : (online ? '在线' : '离线');
    // 离线时「邀战」禁用，并把**原因写在按钮上**（不是只灰掉不给理由）
    const inviteTitle = online ? '邀请他打一局' : '对方不在线，暂时不能邀战';
    const unread = Math.max(0, Number(f.unread) || 0);
    return '<div class="friend-row ' + cls + '" data-username="' + escapeHtml(f.username) + '">'
        + '<img class="friend-avatar" alt="头像" src="' + escapeHtml(String(f.avatar || '/static/avatars/default.png')) + '"'
        + ' onerror="this.onerror=null;this.src=\'/static/avatars/default.png\'">'
        + '<div class="friend-main">'
        + '<span class="friend-name">' + escapeHtml(String(f.username || '未知玩家')) + '</span>'
        + '<span class="friend-meta">' + escapeHtml(friendsMetaText(f)) + '</span>'
        + '</div>'
        + '<span class="friend-state"><i class="friend-dot"></i>' + stateText + '</span>'
        + '<span class="friend-unread"' + (unread > 0 ? '' : ' hidden') + '>' + unread + '</span>'
        + '<div class="friend-ops">'
        // 「私聊」排在「邀战」前面：本批的入口就是它，别让它在窄屏落行后被挤到看不见的地方。
        // ⚠️ 它**不受在线状态影响**（离线也能留言，消息落库、对方下次打开就能看到）。
        + '<button type="button" class="friend-op friend-op-dm" data-friend-action="dm"'
        + ' title="和 TA 私聊">私聊</button>'
        + '<button type="button" class="friend-op friend-op-invite" data-friend-action="invite"'
        + (online ? '' : ' disabled') + ' title="' + escapeHtml(inviteTitle) + '">邀战</button>'
        + '<button type="button" class="friend-op friend-op-danger" data-friend-action="remove"'
        + ' title="解除好友关系（会问一次）">删除</button>'
        + '</div></div>';
}

// 等级 / 段位 / 加入时间：服务端给了才显示，没给就不显示那一段
// （绝不用「Lv.0」「暂无段位」这种假数据顶上去 —— 那比不显示更糟）。
function friendsMetaText(f) {
    const parts = [];
    if (f.level !== undefined && f.level !== null && f.level !== '') parts.push('Lv.' + f.level);
    if (f.rank_label) parts.push(String(f.rank_label));
    if (f.created_at) {
        const t = new Date(Number(f.created_at) * 1000);
        if (!isNaN(t.getTime())) parts.push('申请于 ' + t.toLocaleDateString());
    }
    return parts.length ? parts.join(' · ') : '—';
}

function friendRequestRowHtml(u, kind) {
    const ops = kind === 'incoming'
        ? '<button type="button" class="friend-op" data-friend-action="accept" title="同意这条好友申请">接受</button>'
            + '<button type="button" class="friend-op friend-op-danger" data-friend-action="decline" title="拒绝这条好友申请">拒绝</button>'
        : '<button type="button" class="friend-op" data-friend-action="cancel" title="撤回我发出的这条申请">撤回</button>';
    return '<div class="friend-row" data-username="' + escapeHtml(u.username) + '">'
        + '<img class="friend-avatar" alt="头像" src="' + escapeHtml(String(u.avatar || '/static/avatars/default.png')) + '"'
        + ' onerror="this.onerror=null;this.src=\'/static/avatars/default.png\'">'
        + '<div class="friend-main">'
        + '<span class="friend-name">' + escapeHtml(String(u.username || '未知玩家')) + '</span>'
        + '<span class="friend-meta">' + escapeHtml(friendsMetaText(u)) + '</span>'
        + '</div>'
        + '<div class="friend-ops">' + ops + '</div>'
        + '</div>';
}

// ---------- 面板渲染 ----------
//
// ⚠️ 三个容器 + 空状态是**分开写**的，绝不用一次 innerHTML 把 #friends-modal 整块重建 ——
//    重建会把「上一帧」也一起扔掉，接口一抖面板就空白（项目硬教训第 3 条）。
function renderFriendsPanel(data) {
    const list = document.getElementById('friends-list');
    const reqs = document.getElementById('friends-requests');
    const outs = document.getElementById('friends-outgoing');
    const empty = document.getElementById('friends-empty');
    if (!list || !reqs || !outs) return;      // 骨架没了就什么都不动（别把数据丢弃成半截）
    const friends = Array.isArray(data.friends) ? data.friends : [];
    const incoming = Array.isArray(data.incoming) ? data.incoming : [];
    const outgoing = Array.isArray(data.outgoing) ? data.outgoing : [];

    list.innerHTML = friends.map(friendRowHtml).join('');
    reqs.innerHTML = incoming.map((u) => friendRequestRowHtml(u, 'incoming')).join('');
    outs.innerHTML = outgoing.map((u) => friendRequestRowHtml(u, 'outgoing')).join('');

    if (empty) {
        if (!friends.length && !incoming.length && !outgoing.length) empty.classList.remove('hidden');
        else empty.classList.add('hidden');
    }
}

function openFriendsModal() {
    const modal = document.getElementById('friends-modal');
    if (!modal) return;
    if (typeof closeOverlaysExcept === 'function') closeOverlaysExcept('friends-modal');
    // ⚠️ 每次打开都回到**列表视图**（私聊批）：会话视图要么接着显示"上次那个人的聊天记录"，
    //    要么就得自己记住"要不要恢复"——两样都会让「点好友 → 私聊」的入口时灵时不灵。
    //    统一回列表视图，行为只有一种（§5：两个视图共用 #friends-modal，用 hidden 切换）。
    closeDmConversation();
    modal.classList.remove('hidden');
    refreshFriendsPanel();
}

function closeFriendsModal() {
    const modal = document.getElementById('friends-modal');
    if (modal) modal.classList.add('hidden');
}

// 取一次好友数据。**永不 reject**：区分"响应到了但不合法"与"请求失败"，
// 两种都不 throw（throw 出去只会被调用点的 .then() 吞掉）。
function fetchFriends() {
    return fetch('/api/friends', { headers: { 'Accept': 'application/json' } })
        .then(resp => {
            if (resp.status === 401) return { ok: false, guest: true, data: null };
            if (!resp.ok) return { ok: false, guest: false, data: null };
            return resp.json().then(
                body => ({ ok: true, data: body }),
                () => ({ ok: false, guest: false, data: null }));
        })
        .catch(() => ({ ok: false, guest: false, data: null }));
}

// 拉一次并渲染。三个分区都空时显示 #friends-empty。
function refreshFriendsPanel() {
    return fetchFriends().then(res => {
        if (!res.ok || !res.data) {
            // ⚠️ 失败**保留上一帧**：只写错误位，一个容器都不动。
            setFriendsMsg(res.guest ? '请先登录' : '好友列表加载失败，请稍后重试', true);
            return false;
        }
        // 数据合法性：三个分区至少有一个是数组才算一份能用的响应，
        // 否则宁可继续显示上一帧（后端在改，半截响应不该把面板清空）。
        const d = res.data;
        const usable = Array.isArray(d.friends) || Array.isArray(d.incoming) || Array.isArray(d.outgoing);
        if (!usable) {
            setFriendsMsg('好友列表数据格式不对，已保留上一次的内容', true);
            return false;
        }
        friendsState = d;
        syncFriendsBadge(d);
        renderFriendsPanel(d);
        // ⚠️ 「标已读」与这一趟重拉会打架（私聊批）：如果**标已读还在飞**，而这次响应是
        //    它之前快照的（服务端还没把 read_at 写进去），行上就会把未读数又画回来 ——
        //    症状是"打开了会话，未读闪一下又出现"。这里等它回来时把那个人的数字再抹一次。
        //    抹的依据仍然是服务端（POST /read 的成功回执），不是前端自己减。
        if (dmReadInFlightFor) setFriendRowUnread(dmReadInFlightFor, 0);
        setFriendsMsg('', false);
        // 面板开着的时候顺手校准查看面里那个按钮的关系态（不用重新拉接口）
        const modalOpen = document.getElementById('friends-modal');
        if (modalOpen && !modalOpen.classList.contains('hidden') && currentFriendTarget) {
            applyProfileFriendRelation(computeRelationByName(d, currentFriendTarget));
        }
        return true;
    });
}

// ---------- 查看面「加好友 / 邀战」 ----------

// 关系 → 按钮文案。'self' → null（按钮压根不渲染）。
function friendRelationLabel(relation) {
    if (relation === 'friends') return '好友';
    if (relation === 'pending_out') return '已申请';
    if (relation === 'pending_in') return '接受申请';
    if (relation === 'self') return null;
    return '加好友';
}

// 查看面那一排的「加好友 / 邀战」按钮。只在 withIds（= 查看面）时被调用。
// ⚠️ `id="add-friend-btn"` 必须写成**字面量**：tools/dom_contract_check.mjs 靠源码里的
//    `id="…"` 字面量判断这个契约 id 是由 JS 运行期渲染的，拼出来的它认不出来（会误报悬空 id）。
function friendActionButtonsHtml(m) {
    if (m.self === true) return '';        // 自己看自己 → 按钮不显示
    const label = friendRelationLabel(m.friendRelation);
    if (label === null) return '';
    let html = '<button type="button" class="fri-add-btn fri-rel-' + escapeHtml(m.friendRelation) + '"'
        + ' id="add-friend-btn" data-relation="' + escapeHtml(m.friendRelation) + '"'
        + ' data-username="' + escapeHtml(m.name) + '"'
        + (m.friendRelation === 'pending_out' || m.friendRelation === 'friends' ? ' disabled' : '')
        + '>' + escapeHtml(label) + '</button>';
    if (m.friendRelation === 'friends') {
        // 已是好友 → 旁边多一个「邀战」。⚠️ 这个按钮**刻意不给 id**：
        //    它跟 #add-friend-btn 在同一个文档里，再要一个 id 只多一处撞 id 的机会，
        //    用类走事件委托就够了。
        html += '<button type="button" class="fri-invite-btn" data-username="' + escapeHtml(m.name) + '"'
            + ' title="邀请他打一局">邀战</button>';
    }
    return html;
}

// 就地把按钮改成新的关系态（**不重渲染整张名片** —— 重渲染会冲掉留言草稿与滚动位置，
// 这是第 3 批那条"不许整卡重渲染"的硬要求，这里沿用）。
// 只在需要"多一个 / 少一个按钮"的跃迁上才退回重渲染整张卡。
function applyProfileFriendRelation(relation) {
    if (FRIEND_RELATIONS.indexOf(relation) < 0) relation = 'none';
    currentFriendRelation = relation;
    const btn = document.getElementById('add-friend-btn');
    if (!btn) return;
    const label = friendRelationLabel(relation);
    if (label === null) {   // 变成自己了（不该发生）：把按钮摘掉
        if (btn.remove) btn.remove();
        return;
    }
    const hasInvite = !!document.querySelector('.fri-invite-btn');
    if (relation === 'friends' && !hasInvite) {
        // 关系是「好友」但卡上还没有「邀战」——只有这一种跃迁需要重渲染（按钮要多一个）。
        // ⚠️ 重渲染走 `reRenderProfileCard`，而它最终会回到 `showUserProfile` ——
        //    所以**必须让那一趟带上"关系=friends"**（fetchProfile 的 opts.friendRelation
        //    现在就是这么接的）：不然重渲染出来的卡还是没有「邀战」按钮，
        //    这里就会一趟一趟重渲染下去（实测 8 秒 830 次，页面永远停在「加载中…」）。
        //    另外 reRenderProfileCard 自带重入保护：同一次同步渲染里不会发起第二次。
        // 万一还是没画出来（例如卡片被别人换掉了），就地补一个，**绝不递归**。
        const target = btn.dataset.username || currentFriendTarget || '';
        reRenderProfileCard();
        if (!document.querySelector('.fri-invite-btn')) addInviteButtonInPlace(target);
        // ⚠️⚠️ 补完按钮**不能直接 return**（2026-09-19 修）：以前这里 `return` 掉了，
        //    于是"已经是好友、卡上也有邀战按钮"的那一趟**走不到下面的文案更新** ——
        //    现场是「邀战」在、左边那个按钮却还写着「加好友」且可点（T2l 判的就是这一条）。
        //    重渲染那趟已经把按钮画成「好友」，用现值判断，别再白重渲染一次。
        const after = document.getElementById('add-friend-btn');
        const relAfter = (after && after.dataset) ? String(after.dataset.relation || '') : '';
        if (relAfter === relation) return;
    } else if (relation !== 'friends' && hasInvite) {
        // 从好友变回非好友（比如刚把对方删了）：把「邀战」收掉（就地删，不重渲染）
        const inv = document.querySelector('.fri-invite-btn');
        if (inv && inv.remove) inv.remove();
    }
    // 走到这里时先确认这张卡还是"那个人"的，别把过期的关系写到新卡上
    if (btn.dataset.username && currentFriendTarget
        && btn.dataset.username !== currentFriendTarget) return;
    btn.textContent = label;
    btn.dataset.relation = relation;
    btn.className = 'fri-add-btn fri-rel-' + relation;
    btn.disabled = (relation === 'friends' || relation === 'pending_out');
}

// 重新渲染查看面那张卡（只在关系跃迁、按钮数量变化时才用）。
//
// ⚠️ 两个坑都在这一小段里，都是本项目第 10 节第 6 条的同一个形状：
//   ① **必须走 `window.showUserProfile`**，不能直接写 `showUserProfile(...)` ——
//      那个函数声明在 `document.addEventListener('DOMContentLoaded', …)` 的回调里
//      （块作用域），模块作用域看不见它，直接写就是 ReferenceError。
//   ② **名字要现从 DOM 取**，不能读 `currentProfileUsername` ——
//      那个变量声明在另一个 IIFE 里面（`const` 是块作用域），这里同样看不见。
//      这两处都会抛 ReferenceError，而调用点在 `.then()` 里 → 异常被吞掉、
//      页面上零提示，症状只是"「邀战」按钮永远不出现"（实测就是这样红的）。
//      DOM 是这两个作用域唯一的公共面：`#add-friend-btn[data-username]` 就是当前那个人，
//      `window.__viewedProfileName` 是 showUserProfile 每次都会写的第二份凭据。
function reRenderProfileCard() {
    // ⚠️ 重入保护（2026-09-19 加）：`window.showUserProfile` 会**同步**把容器设成
    //    「加载中…」，而它的 `.then` 回调是微任务 —— 也就是说外面那次渲染还没落地时，
    //    这一趟重渲染就会把容器清空、绕过「加好友」按钮。实测过的最坏形状是无限重渲染：
    //    每次重渲染都把卡冲掉 → 调用方永远看不到「邀战」→ 再重渲染。
    //    根因（fetchProfile 里 friendRelation 写死 'none'）已经单独修掉了，这里只留一道
    //    保险：同一次同步渲染里绝不发起第二次重渲染 —— 返回 false 让调用方走
    //    「就地补一个按钮」那条兜底，页面最差也只是少一次自动刷新，不会卡死在「加载中…」。
    if (profileCardRendering) return false;
    const btn = document.getElementById('add-friend-btn');
    const name = (btn && btn.dataset && btn.dataset.username)
        || window.__viewedProfileName || '';
    if (!name) return false;
    if (typeof window.showUserProfile === 'function') window.showUserProfile(name);
    return true;
}

// 就地补一个「邀战」按钮（**不重渲染整卡**）。
// 它是 applyProfileFriendRelation 的最后一道兜底：重渲染那条路万一没走通，
// 这里直接把按钮插进同一排，避免"关系是好友、却没有邀战入口"的半截状态。
function addInviteButtonInPlace(username) {
    if (!username || document.querySelector('.fri-invite-btn')) return;
    const add = document.getElementById('add-friend-btn');
    const host = (add && add.parentNode) || (document.querySelector('#profile-view .pf-actions'));
    if (!host || !document.createElement) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'fri-invite-btn';
    btn.dataset.username = username;
    btn.title = '邀请他打一局';
    btn.textContent = '邀战';
    if (add && add.nextSibling) host.insertBefore(btn, add.nextSibling);
    else host.appendChild(btn);
}

// 点「加好友」/「接受申请」/「邀战」
function handleAddFriendClick(btn) {
    const username = String((btn && btn.dataset && btn.dataset.username) || currentFriendTarget || '');
    if (!username) return;
    const relation = String((btn && btn.dataset && btn.dataset.relation) || currentFriendRelation || 'none');
    if (btn.disabled) return;

    const done = (msg, isError) => {
        if (isError) { showAlert(msg); return; }
        showMessage(msg, { type: 'success' });
    };

    if (relation === 'pending_in') {
        friendApiPost('/api/friends/respond', { username: username, accept: true }).then(res => {
            if (res.ok && res.data.status === 'accepted') {
                applyProfileFriendRelation('friends');
                syncFriendsAfterMutation(username);
                done('已接受 ' + username + ' 的好友申请');
            } else {
                // ⚠️ 服务端给的中文原因**原样显示**，不自编文案
                done(res.ok ? apiReason(res.data, '接受申请失败') : res.reason, true);
            }
        });
        return;
    }

    // relation === 'none'（pending_out / friends 的按钮是 disabled，走不到这里）
    friendApiPost('/api/friends/request', { username: username }).then(res => {
        if (res.ok) {
            const st = res.data.status;
            if (st === 'sent' || st === 'already_pending') {
                applyProfileFriendRelation('pending_out');
                syncFriendsAfterMutation(username);
                done(st === 'sent' ? ('已向 ' + username + ' 发出好友申请') : '已经申请过了，等对方确认');
            } else if (st === 'already_friends') {
                applyProfileFriendRelation('friends');
                syncFriendsAfterMutation(username);
                done('你们已经是好友了');
            } else {
                // blocked / self / error —— 原因一律用服务端那句中文
                done(apiReason(res.data, '发送好友申请失败'), true);
            }
        } else {
            done(res.reason, true);
        }
    });
}

// 点「邀战」（查看面 / 好友面板里都走它）
function sendFriendInvite(username, btn) {
    const name = String(username || '');
    if (!name) return;
    if (btn) btn.disabled = true;
    friendApiPost('/api/friends/invite', { username: name }).then(res => {
        if (btn) btn.disabled = false;
        if (res.ok && res.data.status === 'ok' && res.data.room_id) {
            const inviteRoom = String(res.data.room_id);
            showMessage('已邀请 ' + name + '，正在房间里等 TA…', { type: 'success' });
            // 提示位顺手说一句房间号，方便口头确认
            setFriendsMsg('已邀请 ' + name + '（房间 ' + inviteRoom + '）', false);
            // ⚠️⚠️ **发起方必须自己进这间房** —— 漏了这一步整条链就是死的：
            //    `POST /api/friends/invite` 建出来的是一间**空房**（服务端只建房、不坐人），
            //    而 `join_room` 只在**满 2 人**时才把阶段推到 `placing_ships`。
            //    所以发起方不进房 = 房间里永远只有被邀请那一个人 → **永远开不了局**，
            //    对方还会一直停在"布船界面等对手"（用户实测报的正是这个）。
            //    入房走**既有那份实现**（`joinRoomById`），与 toast 里的「进入房间」同一条路 ——
            //    绝不在这里另写一套 emit + switchScreen。
            if (typeof closeFriendsModal === 'function') closeFriendsModal();
            joinRoomById(inviteRoom, { quiet: true }).then(ok => {
                if (!ok) {
                    showAlert('房间已建好（' + inviteRoom + '），但自动进入失败，'
                        + '请让好友用这个房间号进来，或重开一间');
                }
            });
        } else {
            // 契约里 `error` 字段就是服务端给的中文原因（例如「对方不在线」）——原样显示
            showAlert(res.ok ? apiReason(res.data, '邀请失败') : res.reason);
        }
    });
}

// 任何一次成功的写操作之后，**重新拉一次**接口（数字与列表都以服务端为准，
// 绝不在前端自己加减数组 —— 那是"两份实现"的老病根）。
// ⚠️ 同时**把这个人的关系缓存丢掉**：不快照的话，刚把他加成好友、再点开他的名片，
//    按钮会按缓存里的旧关系显示（"点了没反应"那一类，且不报错）。
function syncFriendsAfterMutation(username) {
    if (username) friendRelationCache.delete(String(username));
    return refreshFriendsPanel();
}
// 关系缓存的显式失效入口（供需要的地方调用）
function forgetFriendRelation(username) {
    if (username) friendRelationCache.delete(String(username));
}

// ---------- 面板里的操作（事件委托） ----------
// 三个列表每渲染一次就换一批节点，逐个绑定必然失效 → 全部委托在 #friends-modal 上。
function bindFriendsModal() {
    const modal = document.getElementById('friends-modal');
    if (!modal) return;
    modal.addEventListener('click', (e) => { e.stopPropagation(); });

    const closeBtn = document.getElementById('friends-close');
    if (closeBtn) closeBtn.addEventListener('click', (e) => { e.preventDefault(); closeFriendsModal(); });

    // 点遮罩空白处关闭（与既有弹窗一致的手感）
    modal.addEventListener('click', (e) => { if (e.target === modal) closeFriendsModal(); });

    modal.addEventListener('click', (e) => {
        const el = (e.target && e.target.closest) ? e.target.closest('[data-friend-action]') : null;
        if (!el) return;
        e.preventDefault();
        const row = el.closest('.friend-row');
        const username = String((row && row.dataset && row.dataset.username) || el.dataset.username || '');
        if (!username || el.disabled) return;
        const action = el.dataset.friendAction;

        if (action === 'accept') {
            friendApiPost('/api/friends/respond', { username: username, accept: true }).then(res => {
                if (res.ok && res.data.status === 'accepted') { setFriendsMsg('已接受 ' + username + ' 的好友申请', false); syncFriendsAfterMutation(username); }
                else setFriendsMsg(res.ok ? apiReason(res.data, '接受申请失败') : res.reason, true);
            });
        } else if (action === 'decline') {
            friendApiPost('/api/friends/respond', { username: username, accept: false }).then(res => {
                if (res.ok && (res.data.status === 'declined' || res.data.status === 'ok')) { setFriendsMsg('已拒绝 ' + username + ' 的申请', false); syncFriendsAfterMutation(username); }
                else setFriendsMsg(res.ok ? apiReason(res.data, '拒绝失败') : res.reason, true);
            });
        } else if (action === 'cancel') {
            // 撤销我发出的申请 —— 契约里没有单独的 withdraw，走 remove（后端把"没有好友关系"
            // 的删除当成撤回申请处理）。⚠️ 这里是**契约之外的一处推测**，回执一律以服务端为准。
            friendApiPost('/api/friends/remove', { username: username }).then(res => {
                if (res.ok && (res.data.status === 'ok' || res.data.status === 'removed')) { setFriendsMsg('已撤回对 ' + username + ' 的申请', false); syncFriendsAfterMutation(username); }
                else setFriendsMsg(res.ok ? apiReason(res.data, '撤回失败') : res.reason, true);
            });
        } else if (action === 'remove') {
            // 删除好友：二次确认（票面要求）。用原生 confirm —— 项目里所有二次确认都是它，
            // 不新造一套确认弹窗（新造的那套还得自己处理 Esc / 焦点）。
            if (!window.confirm('确定解除与「' + username + '」的好友关系吗？')) return;
            friendApiPost('/api/friends/remove', { username: username }).then(res => {
                if (res.ok && (res.data.status === 'ok' || res.data.status === 'removed')) { setFriendsMsg('已解除与 ' + username + ' 的好友关系', false); syncFriendsAfterMutation(username); }
                else setFriendsMsg(res.ok ? apiReason(res.data, '删除失败') : res.reason, true);
            });
        } else if (action === 'invite') {
            sendFriendInvite(username, el);
        } else if (action === 'dm') {
            // 打开这个人的会话（私聊批）：**同一个弹窗内切换视图**，不新开弹窗。
            // 置灰判断放在 openDmConversation 里（它要先清掉上一场的行），这里不重复判。
            openDmConversation(username);
        }
    });
}

// 查看面里那两个按钮（委托在 #opponent-stats-content 上；那张卡会被反复重渲染）—— 
// 走与 bindProfileCardButtons 同一条委托（那边已经绑过一次容器，这里是第二类目标）。
function bindProfileFriendButtons() {
    const box = document.getElementById('opponent-stats-content');
    if (!box || box.dataset.friendButtonsBound === '1') return;
    box.dataset.friendButtonsBound = '1';
    box.addEventListener('click', (e) => {
        const add = (e.target && e.target.closest) ? e.target.closest('#add-friend-btn') : null;
        if (add) { e.preventDefault(); handleAddFriendClick(add); return; }
        const invite = (e.target && e.target.closest) ? e.target.closest('.fri-invite-btn') : null;
        if (invite) {
            e.preventDefault();
            sendFriendInvite(invite.dataset.username || currentFriendTarget, invite);
        }
    });
}

// ---------- 邀战提示条 ----------

function showFriendInviteToast(username, roomId) {
    const box = document.getElementById('friend-invite-toast');
    const text = document.getElementById('friend-invite-text');
    if (!box) return;
    if (text) text.textContent = username + ' 邀你打一局（房间 ' + roomId + '）';
    box.classList.remove('hidden');
    // 按钮不是"只弹一次"：条子自动收起来后，activeInviteRoom 仍然留着，
    // 手动点过「进入房间」才会清掉（避免"手一抖没点着，条子就永远没了"）。
    if (friendInviteTimer) clearTimeout(friendInviteTimer);
    friendInviteTimer = setTimeout(hideFriendInviteToast, FRIEND_INVITE_TOAST_MS);
}

function hideFriendInviteToast() {
    const box = document.getElementById('friend-invite-toast');
    if (box) box.classList.add('hidden');
    if (friendInviteTimer) { clearTimeout(friendInviteTimer); friendInviteTimer = null; }
}

function bindFriendInviteToast() {
    const enter = document.getElementById('friend-invite-enter');
    if (!enter) return;
    enter.addEventListener('click', (e) => {
        e.preventDefault();
        if (!activeInviteRoom) { hideFriendInviteToast(); return; }
        const room = activeInviteRoom;
        activeInviteRoom = '';            // 点过就消费掉（失败也不会重复入房）
        enter.disabled = true;
        // ⚠️ 入房走**既有那份实现**（joinRoomById，模块作用域，页加载时的 `?room=` 也用它），
        //    绝不在这里另写一套 emit join_room + switchScreen。
        joinRoomById(room).then(ok => {
            enter.disabled = false;
            if (ok) hideFriendInviteToast();
            else showAlert('加入房间失败（房间可能已满或已关闭）');
        });
    });
}

// ---------- 结算界面：最近对手那一行的「加好友」 ----------

// 找结算屏里"对手那一行"的落点：优先 .game-over-buttons（结算屏里唯一的按钮行），
// 找不到就退回 #game-result 之后。⚠️ 落点用**兜底链**而不是写死一个 id ——
// 结算屏的 DOM 由别的批次在改，硬绑一个容器会"加了但看不见"（点了没反应那类症状）。
function recentOpponentHost() {
    return document.querySelector('#game-over-screen .game-over-buttons')
        || document.getElementById('game-result');
}

// `relation='friends'` 时不显示按钮（或显示一个不可点的「已是好友」）；
// `pending_out` / `pending_in` 都当「已申请」处理（票面）。
function renderRecentOpponentAdd(username, relation) {
    const name = String(username || '');
    if (!name) return;                       // 没有对手名（人机局 / 数据没到）→ 什么都不做
    const host = recentOpponentHost();
    if (!host) return;

    const old = document.getElementById('recent-opponent-add');
    if (old) old.remove();

    const rel = FRIEND_RELATIONS.indexOf(relation) >= 0 ? relation : 'none';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'recent-opponent-add';           // 契约 id（字面量，dom_contract_check 认它）
    btn.className = 'recent-opponent-add';
    btn.dataset.username = name;
    btn.dataset.relation = rel;

    if (rel === 'friends') {
        btn.textContent = '已是好友';
        btn.disabled = true;
    } else if (rel === 'pending_out' || rel === 'pending_in') {
        btn.textContent = '已申请';
        btn.disabled = true;
    } else if (rel === 'blocked_by_me' || rel === 'blocked_me') {
        // 拉黑关系**绝不能落进下面的 else** —— 那会渲染成一个可点的「加好友」，
        // 点下去服务端只会回一句「暂时无法向该玩家发送好友申请」。
        // ⚠️ 文案两个方向共用一句：服务端有意不告诉客户端"是谁拉黑了谁"。
        btn.textContent = '不能加好友';
        btn.disabled = true;
    } else {
        btn.textContent = '加好友';
        btn.disabled = false;
    }
    // 对手那条关系用 title 说清楚是谁（结算屏上往往只有一句"你很遗憾"）
    btn.title = '向 ' + name + ' 发送好友申请';
    btn.addEventListener('click', () => {
        if (btn.disabled) return;
        friendApiPost('/api/friends/request', { username: name }).then(res => {
            if (res.ok && (res.data.status === 'sent' || res.data.status === 'already_pending')) {
                btn.textContent = '已申请';
                btn.disabled = true;
                showMessage(res.data.status === 'sent' ? ('已向 ' + name + ' 发出好友申请') : '已经申请过了，等对方确认');
            } else if (res.ok && res.data.status === 'already_friends') {
                btn.textContent = '已是好友';
                btn.disabled = true;
                showMessage('你们已经是好友了');
            } else {
                showAlert(res.ok ? apiReason(res.data, '发送好友申请失败') : res.reason);
            }
        });
    });

    // 插在按钮行的**最前面**（"再来一局 / 返回主菜单"是既有按钮，插后面会顶掉它们的位置）
    if (host.classList && host.classList.contains('game-over-buttons')) host.insertBefore(btn, host.firstChild);
    else host.appendChild(btn);
}

// `recent_opponent` 事件：结算时双方各收一条。名字与关系都记下来，
// 之后无论 game_over 先到还是后到，结算屏里都能把按钮补上。
function handleRecentOpponentEvent(data) {
    const name = String((data && data.username) || '');
    if (!name) return;
    const rel = FRIEND_RELATIONS.indexOf(data && data.relation) >= 0 ? data.relation : 'none';
    recentOpponentState = { name: name, relation: rel, userId: (data && data.user_id) || null };
    // 如果结算屏此刻已经切上来了（game_over 先到），当场就补
    if (gameOverScreen && gameOverScreen.classList.contains('active')) {
        renderRecentOpponentAdd(name, rel);
    }
}

// ---------- 好友私聊（私聊批，2026-09-19） ----------
//
// 契约见 docs/FRIEND_DM_2026_09_19.md §3（纯规则）/ §4（接口）/ §5（DOM，冻结 id）。
// 三条硬规矩在本节的具体落法（与前几批同一口径，别在这里破例）：
//   ① **时间只渲染服务端给的 `stamp`**（'09-19 15:40'）—— 前端一个字都不重算格式。
//      格式化规则只有一份实现，在 `dm.py` 的 `stamp()`；前端再算一次就是"两份实现必然漂移"。
//   ② **未读只认服务端**：要么来自 `GET /api/friends` 的 `friend.unread`（渲染时），
//      要么来自 `POST /api/friends/messages/read` 的成功回执（那条会话归零）。
//      本节的**唯一一种累加方式**是"面板开着时重拉一次 GET /api/friends"，
//      绝不在前端 `+1`（自增与"重拉"两处各算一遍 = 同一个数两份实现）。
//   ③ **发送成功用响应里那条 message 追加**，不自己造一条 —— 自己造的 id / stamp
//      会与库里那一条对不上（§5 最后一条）。
//
// ⚠️ 视图互斥：`#friends-body`（列表）与 `#dm-panel`（会话）共用 `#friends-modal`，
//    用 `hidden` 属性切换（§5）；`#friends-title` 也跟着在两个标题之间切。

const DM_PAGE_LIMIT = 50;                 // 与服务端默认分页一致（§4 的 limit 参数）
const DM_NEAR_BOTTOM_PX = 40;             // "贴在底部"的判定带；超出就说明玩家正在往上翻
const DM_ANCHOR_TOLERANCE_PX = 2;         // 插到顶部后允许的位置偏差（回归工具按同一口径断言）

// 当前会话对象（关掉视图后**刻意保留**：这时来的实时消息要归到"不是当前会话"那一类）
let dmFriendName = '';
// 屏幕上**此刻真的在显示**谁的会话（'' = 没在显示）。
// ⚠️ 它与 dmFriendName 必须分开：前者管"实时消息要不要当场标已读"，
//    后者管"这条消息属于谁"。合成一个变量就会出现"面板关了也当正在看"→ 未读永远不亮。
let dmOpenName = '';
let dmHasMore = false;                    // 服务端给的 has_more（只有它说了算，前端不推算）
let dmLoadMoreBusy = false;
let dmSending = false;                    // 发送中：禁用按钮防重复提交
// 已经渲染过的消息 id（换会话时重建）。用它做去重：同一会话的重拉与实时推送可能交错，
// 没有它就会出现同一条消息渲染两遍（而两遍的 id 相同，肉眼很难发现）。
let dmRenderedIds = new Set();
// 已读那一路的"在途"状态：避免连点/连续收消息时把同一段会话反复标已读。
let dmReadBusy = false;
// 标已读请求发出**之后**又到达的实时消息 id：在途时不能丢，回来要补一次（见 markDmRead）。
let dmPendingReadIds = new Set();
// 非空 = 那个人的会话**正在标已读**（用来挡"重拉回来的旧帧把未读数写回去"，见 refreshFriendsPanel）。
let dmReadInFlightFor = '';
// 「加载更早」那一次**自己量的**滚动位置偏差（像素；null = 还没量过）。
// 为什么放模块级：它是给**回归工具**看的证据（tools/friend_dm_check.mjs 的 D7f 直接读
// `dmAnchorDrift`），而工具拿不到函数内部的局部量。产品逻辑不读它，只写。
let dmAnchorDriftPx = null;
function dmAnchorDrift() { return dmAnchorDriftPx; }

// 面板开着（两个视图都算）
function isFriendsModalOpen() {
    const m = document.getElementById('friends-modal');
    return !!(m && !m.classList.contains('hidden'));
}
// 会话视图**真的**在屏幕上：视图开着 + 面板开着 + 看的就是这个人。
// ⚠️ `document.hasFocus()` 一起判：浏览器被切到后台时不该把消息悄悄标已读（否则未读等于没有）。
//    无头回归里 `document.hasFocus()` 为 true（窗口是前台），所以这条不会让断言假红。
function isDmConversationVisible(username) {
    const name = String(username || '');
    if (!name || !dmOpenName || dmOpenName !== name) return false;
    const panel = document.getElementById('dm-panel');
    if (!panel || panel.hidden) return false;
    if (!isFriendsModalOpen()) return false;
    return (typeof document.hasFocus !== 'function') || document.hasFocus();
}
// 把未读数写回某个好友行 —— **改的是 DOM 里那一个 span**，不碰任何模块级计数
// （未读数在页面上只有这一个落点，不存在"两份状态"）。digit 为空 → 隐藏。
function setFriendRowUnread(username, value) {
    const name = String(username || '');
    if (!name) return;
    const rows = document.querySelectorAll('#friends-list .friend-row');
    for (let i = 0; i < rows.length; i++) {
        if (String(rows[i].dataset.username || '') !== name) continue;
        const badge = rows[i].querySelector('.friend-unread');
        if (!badge) return;
        const n = Math.max(0, Number(value) || 0);
        badge.textContent = String(n);
        badge.hidden = !(n > 0);
        return;
    }
}
// 撤回关系缓存用的 `forgetFriendRelation`（既有实现）在这里**用不上**：
// 私聊不改变好友关系，缓存里那份关系照旧有效。留着这句注释是免得下一个人以为漏了。

// ---------- 消息渲染 ----------
// 一条消息 → 一行。`id` 写进 data-id，滚动锚定与去重都靠它。
// ⚠️ data-mine 是§5 冻结的属性（"1"=我发的 / "0"=对方发的）：视觉左右分栏走 CSS，
//    断言只认这个属性 —— 别用 class 兼职表达"谁发的"。
function dmRowHtml(m) {
    // ⚠️ 只有**会话接口**（GET/POST /messages）那一条路才带 `mine`；
    //    socket 推送的 payload **没有**这个字段（服务端有意不下发发送方视角的字段），
    //    所以这里必须用 `=== true` 判，缺字段时自然落到"对方发的"。
    const mine = (m && m.mine === true) ? '1' : '0';
    const id = (m && m.id !== undefined && m.id !== null) ? String(m.id) : '';
    return '<div class="dm-row" data-mine="' + mine + '" data-id="' + escapeHtml(id) + '">'
        + '<span class="dm-body">' + escapeHtml(String((m && m.body) || '')) + '</span>'
        // 时间戳就是服务端那句 stamp，原样贴出来（不 new Date、不补零、不换格式）
        + '<span class="dm-stamp">' + escapeHtml(String((m && m.stamp) || '')) + '</span>'
        + '</div>';
}
function dmIsNearBottom(box) {
    if (!box) return true;
    return (box.scrollHeight - box.scrollTop - box.clientHeight) <= DM_NEAR_BOTTOM_PX;
}
function dmScrollToBottom() {
    const box = document.getElementById('dm-list');
    if (!box) return;
    box.scrollTop = box.scrollHeight;
}
// 渲染整段会话（换会话 / "加载更早"看的是**这一整帧**）。
// `stickBottom`：把视口钉到底部（进会话、自己发消息时用；往上翻出来的旧帧一律 false）。
function renderDmMessages(messages, stickBottom) {
    const box = document.getElementById('dm-list');
    if (!box) return;
    const list = Array.isArray(messages) ? messages : [];
    box.innerHTML = list.map(dmRowHtml).join('');
    dmRenderedIds = new Set();
    list.forEach((m) => { if (m && m.id !== undefined && m.id !== null) dmRenderedIds.add(String(m.id)); });
    updateDmEmpty();
    if (stickBottom) dmScrollToBottom();
}
// 空会话占位：#dm-empty 只在"确实一条都没有"时显示（§5）。
function updateDmEmpty() {
    const box = document.getElementById('dm-list');
    const empty = document.getElementById('dm-empty');
    if (!box || !empty) return;
    empty.hidden = box.querySelector('.dm-row') !== null;
}
// 「加载更早的消息」按 has_more 显隐。⚠️ 前端**不推算** has_more（服务端用一条 EXISTS 问库，
// 见 §6.2 坑 3：靠"这页取满了"推会在恰好剩一整页时多一个点了没反应的按钮）。
// ⚠️ 按钮自己就是 `#dm-load-more`，所以这里同时管"加载中"的禁用态（防连点重复取同一页）。
function updateDmLoadMore() {
    const btn = document.getElementById('dm-load-more');
    if (!btn) return;
    btn.hidden = !dmHasMore;
    btn.disabled = dmLoadMoreBusy;
}
// 追加一条（实时消息 / 自己刚发出的那条）。
// 两个 defensive 点：
//   · 正在会话头里看的不是这个人 → 不追加（调用方判过，这里再兜一层）；
//   · id 已经渲染过 → 不追加（同一会话的重拉与推送交错时会出现重复）。
function appendDmMessage(m, stickBottom) {
    const box = document.getElementById('dm-list');
    if (!box || !m) return false;
    const id = (m.id !== undefined && m.id !== null) ? String(m.id) : '';
    if (id && dmRenderedIds.has(id)) return false;
    if (id) dmRenderedIds.add(id);
    box.insertAdjacentHTML('beforeend', dmRowHtml(m));
    updateDmEmpty();
    if (stickBottom) dmScrollToBottom();
    return true;
}
// 取一次会话。resolve **永不 reject**：网络/解析失败一律 {ok:false}，
// 免得异常被 .then() 吞掉、页面上零提示（本项目第 10 节第 6 条同形状）。
function fetchDmMessages(username, beforeId) {
    const name = String(username || '');
    if (!name) return Promise.resolve({ ok: false, messages: [], hasMore: false });
    let url = '/api/friends/messages?username=' + encodeURIComponent(name);
    if (beforeId) url += '&before=' + encodeURIComponent(String(beforeId));
    return fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(resp => resp.text().then(text => {
            let body = null;
            try { body = text ? JSON.parse(text) : null; } catch (e) { body = null; }
            if (!resp.ok || !body || body.status !== 'ok' || !Array.isArray(body.messages)) {
                return { ok: false, messages: [], hasMore: false, reason: apiReason(body, '') };
            }
            // ⚠️ 服务端按 id 正序返回（最新的在后）—— 前端**不再排序**，照序渲染。
            return { ok: true, messages: body.messages, hasMore: body.has_more === true };
        }))
        .catch(() => ({ ok: false, messages: [], hasMore: false }));
}

// ---------- 会话视图的开关 ----------
// 进会话：标题 = 对方用户名（§5）。先清空上一场（输入框 / 消息列表 / 分页按钮），
// 因为那里的"上一帧"属于**另一个人**，留着才是真的错（与三个列表容器"保留上一帧"相反）。
function openDmConversation(username) {
    const name = String(username || '');
    if (!name) return;
    const panel = document.getElementById('dm-panel');
    const body = document.getElementById('friends-body');
    if (!panel || !body) return;

    dmFriendName = name;
    dmOpenName = name;
    dmHasMore = false;
    dmLoadMoreBusy = false;
    dmReadBusy = false;
    dmPendingReadIds = new Set();
    dmRenderedIds = new Set();
    const title = document.getElementById('dm-title');
    if (title) title.textContent = name;
    const input = document.getElementById('dm-input');
    if (input) input.value = '';
    const box = document.getElementById('dm-list');
    if (box) box.innerHTML = '';
    updateDmEmpty();
    updateDmLoadMore();
    if (input && input.focus && typeof input.focus === 'function') {
        // 打开就把光标放进输入框，少一步点击（键盘用户尤其明显）
        try { input.focus(); } catch (e) { /* 无头环境下 focus 可能不生效，不影响别的 */ }
    }

    body.hidden = true;
    panel.hidden = false;
    const h2 = document.getElementById('friends-title');
    if (h2) h2.hidden = true;      // 标题由 .dm-head 里的 #dm-title 承担，避免两个标题叠着

    // 先取最新一页（含 has_more / 每条 mine），再标已读。
    // ⚠️ 顺序不能反：先标已读再取数，中间到达的消息会被这一次"标已读"连坐，而它其实还没渲染出来。
    return fetchDmMessages(name).then(res => {
        if (dmOpenName !== name) return false;        // 这趟回来时玩家已经走了 → 一个字都不写
        if (!res.ok) {
            setDmMsg('聊天记录加载失败，请稍后重试', true);
            return false;
        }
        dmHasMore = res.hasMore === true;
        renderDmMessages(res.messages, true);
        updateDmLoadMore();
        setDmMsg('', false);
        // 视图已经在屏幕上了 → 这一刻起这个人的消息都算"当面看的"，立刻标已读。
        markDmRead(name);
        return true;
    });
}
// 回列表视图。**保留 dmFriendName**（这时来的实时消息要归到"不是当前会话"那一类，
// 于是未读数计进好友行）；只把 dmOpenName 清掉 —— 它才是"此刻正显示"的那个判据。
function closeDmConversation() {
    dmOpenName = '';
    const panel = document.getElementById('dm-panel');
    const body = document.getElementById('friends-body');
    if (panel) panel.hidden = true;
    if (body) body.hidden = false;
    const h2 = document.getElementById('friends-title');
    if (h2) h2.hidden = false;
    setDmMsg('', false);
}
// 会话视图里那一行提示位（发送失败的中文原因 / 加载失败）。
function setDmMsg(text, isError) {
    const el = document.getElementById('dm-msg');
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('is-error', isError === true);
}

// ---------- 标已读 ----------
// 打开会话即标已读；成功后**就地**把这个好友行的未读数归零。
// ⚠️ 归零的依据是**服务端的成功回执**，不是前端自己减 1（§5：数字只认服务端）。
//    `read: 0` 也照常归零：那表示服务端那边已经没有未读了（例如别的标签页刚标过）。
// ⚠️ 重入保护：标已读期间又来了消息（dmPendingReadIds 非空）→ 回来补一次，
//    否则最后那几条会一直挂着未读，直到玩家下次打开会话。
function markDmRead(username) {
    const name = String(username || '');
    if (!name || !window.__USERNAME) return Promise.resolve(false);   // 游客：接口一定 401，省掉这次往返
    if (dmReadBusy) return Promise.resolve(false);
    dmReadBusy = true;
    dmReadInFlightFor = name;
    return friendApiPost('/api/friends/messages/read', { username: name }).then(res => {
        dmReadBusy = false;
        dmReadInFlightFor = '';
        if (!res.ok || !res.data || res.data.status !== 'ok') {
            // 失败不改任何数字：留给下一次打开会话 / 重拉接口去对齐
            return false;
        }
        setFriendRowUnread(name, 0);
        const again = dmPendingReadIds.size > 0;
        dmPendingReadIds = new Set();
        if (again) markDmRead(name);        // 在途期间又到了新消息 → 补一次
        return true;
    });
}

// ---------- 往上翻：加载更早的消息 ----------
// ⚠️⚠️ 这一段是整个私聊最容易做错的地方：**把旧消息插到列表顶部时必须不跳滚动位置**。
//     `prepend` 之后容器的内容高度变高、而 `scrollTop` 不变 —— 玩家眼里就是"画面整个
//     往下跳了一屏"（正在读的那条跑掉了）。所以：插之前记下首条的屏幕位置，
//     插完按高度差把 scrollTop 补回去，并用同一口径自检偏差。
function loadEarlierDmMessages() {
    const name = dmOpenName;
    if (!name || dmLoadMoreBusy || !dmHasMore) return Promise.resolve(false);
    const box = document.getElementById('dm-list');
    if (!box) return Promise.resolve(false);
    const first = box.querySelector('.dm-row');
    const beforeId = (first && first.dataset) ? String(first.dataset.id || '') : '';
    if (!beforeId) return Promise.resolve(false);        // 没有游标（列表是空的）→ 无从往上翻

    // ⚠️⚠️ 量"要补多少"不能用 `box.scrollHeight` 的前后差：`insertAdjacentHTML` 之后
    //    **同步**读 `box.scrollHeight` 会读到**过期值** —— 实测（tools/friend_dm_check.mjs
    //    的 D7f）它比真实内容高度少 17.66px，于是 scrollTop 补少了那么多，画面往下一跳。
    //    改成量**锚点自己在屏幕上的位置**：它在屏幕上被推下去多少，scrollTop 就补多少。
    //    好处是它同时把"列表之外"的位移也一起算进去了 —— 实测还有第二处位移：
    //    取完最后一页后 `#dm-load-more` 变成 `hidden`，弹窗矮了 17.66px，上面的内容
    //    整体上移，正在读的那条消息也跟着上移。只补列表内部的高度差是**补不掉**这一处的。
    // ⚠️ 选择器里的 id 用 escapeHtml 转义（与渲染那条路同一套），不用 CSS.escape：
    //    id 来自服务端、是纯数字，但万一它带了引号，escapeHtml 之后放进双引号里一定安全。
    const anchorSel = '.dm-row[data-id="' + escapeHtml(beforeId) + '"]';
    const anchorNode = box.querySelector(anchorSel);
    const prevTop = anchorNode ? anchorNode.getBoundingClientRect().top : null;
    dmAnchorDriftPx = null;                              // 本次的自检结果（null = 还没测）

    dmLoadMoreBusy = true;
    updateDmLoadMore();
    return fetchDmMessages(name, beforeId).then(res => {
        dmLoadMoreBusy = false;
        if (dmOpenName !== name) {                       // 这趟回来时已经换了会话 → 一个字都不写
            updateDmLoadMore();
            return false;
        }
        if (!res.ok) {
            updateDmLoadMore();
            setDmMsg('更早的消息加载失败，请稍后重试', true);
            return false;
        }
        dmHasMore = res.hasMore === true;
        // ⚠️ 只插"没渲染过的"（本页与已有内容可能重叠，插重了会多出重复行）
        const older = res.messages.filter(m => m && m.id !== undefined && m.id !== null
            && !dmRenderedIds.has(String(m.id)));
        older.forEach(m => { dmRenderedIds.add(String(m.id)); });
        if (older.length) box.insertAdjacentHTML('afterbegin', older.map(dmRowHtml).join(''));
        // 还原：先把**列表之外**的位移补掉（`#dm-load-more` 的显隐会改弹窗高度），
        // 再把列表内部因插入而产生的偏移补掉 —— 两步一起做，锚点就**精确**停在原处。
        updateDmEmpty();
        updateDmLoadMore();
        const afterOuter = box.querySelector(anchorSel);
        if (anchorNode && prevTop !== null && afterOuter) {
            box.scrollTop = box.scrollTop + (afterOuter.getBoundingClientRect().top - prevTop);
        }
        // 自检：偏差超过容差说明上面那条补法失效（比如别处也改了高度）。记进模块级变量给
        // 回归工具断言（`window.dmAnchorDrift`），控制台只留一句，不打断玩家。
        const anchor = box.querySelector(anchorSel);
        if (anchor && prevTop !== null) {
            dmAnchorDriftPx = Math.abs(anchor.getBoundingClientRect().top - prevTop);
            if (dmAnchorDriftPx > DM_ANCHOR_TOLERANCE_PX) {
                console.warn('插入更早的消息后滚动位置漂移 ' + Math.round(dmAnchorDriftPx) + 'px（容忍 '
                    + DM_ANCHOR_TOLERANCE_PX + 'px）');
            }
        }
        setDmMsg('', false);
        return true;
    });
}

// ---------- 发送 ----------
function sendDmMessage() {
    const input = document.getElementById('dm-input');
    const btn = document.getElementById('dm-send');
    const name = dmOpenName;
    if (!input || !name || dmSending) return Promise.resolve(false);
    const body = String(input.value || '').trim();
    if (!body) return Promise.resolve(false);           // 空消息本地就挡掉，不发这一趟
    dmSending = true;
    if (btn) btn.disabled = true;                       // 防重复提交（票面要求）

    return friendApiPost('/api/friends/messages', { username: name, body: body }).then(res => {
        dmSending = false;
        if (btn) btn.disabled = false;
        if (!res.ok || !res.data || res.data.status !== 'ok' || !res.data.message) {
            // 失败原因**原样**用服务端那句中文（超长 / 太频繁 / 不是好友…），绝不自己编文案
            setDmMsg(res.ok ? apiReason(res.data, '发送失败') : res.reason, true);
            return false;
        }
        // ⚠️ 用**响应里那条 message** 追加（§5）：自己造一条的话 id 与 stamp 会跟库里不一致，
        //    而 id 是往上翻的游标、stamp 是唯一的"时间真源"。
        appendDmMessage(res.data.message, true);
        input.value = '';
        setDmMsg('', false);
        return true;
    });
}

// ---------- 实时：收到一条私聊 ----------
// 两种归处，二选一（**不在两处各算一遍**）：
//   · 属于**当前正打开的会话** → 当场追加 + 立刻标已读（沿用 markDmRead 那一条路）；
//   · 否则 → 重拉一次 `GET /api/friends`，未读数由**服务端算好的 `friend.unread`** 渲染出来。
//     （为什么选"重拉"而不是"前端给那一行 +1"：+1 就是第二份实现 —— 它与服务端的
//      count_unread_messages 迟早对不上，而且那行不在屏幕上时还得先想"要不要补拉"。）
function handleFriendMessageEvent(data) {
    const fromName = String((data && data.from_username) || '');
    const body = String((data && data.body) || '');
    if (!fromName) return;                              // 没有来处就无从归位（只记日志也没有落点）
    if (isDmConversationVisible(fromName)) {
        appendDmMessage(data, true);
        dmPendingReadIds.add(String((data && data.id) || ''));   // 在途标已读时的"补一次"用得上
        markDmRead(fromName);
        return;
    }
    // 面板开着才重拉：不打开面板的话未读数根本不在屏幕上（入口红点按 §1 **不读未读**），
    // 下次打开面板本来就会拉一次最新的。
    if (isFriendsModalOpen()) refreshFriendsPanel();
    // 顺手提一句（复用既有 showMessage，不新造 toast）。对局中也会弹，与其它三条好友事件一致。
    showMessage(fromName + '：' + body, { type: 'info', duration: 5000 });
}

// ---------- DM 的按钮绑定 ----------
// ⚠️ 与三个列表不同：会话视图的骨架是**常驻**的（#dm-list / #dm-input / #dm-send 从不被重建），
//    所以这里的监听器只绑一次就够，不需要走事件委托。
function bindDmPanel() {
    const back = document.getElementById('dm-back');
    if (back) back.addEventListener('click', (e) => {
        e.preventDefault();
        closeDmConversation();
        // 回到列表视图：数字以服务端为准（刚才标过已读，这一次会把最新值画回来）
        refreshFriendsPanel();
    });
    const more = document.getElementById('dm-load-more');
    if (more) more.addEventListener('click', (e) => { e.preventDefault(); loadEarlierDmMessages(); });
    const send = document.getElementById('dm-send');
    if (send) send.addEventListener('click', (e) => { e.preventDefault(); sendDmMessage(); });
    const input = document.getElementById('dm-input');
    if (input) input.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' || e.isComposing) return;   // 中文输入法组字中按回车不算发送
        e.preventDefault();
        sendDmMessage();
    });
}

// ---------- 四个 socket 事件的业务处理（注册在 init 的 socket 段落里） ----------

// 收到好友申请：红点 +1，并弹一条**轻提示**（复用既有 showMessage，不新造 toast）。
function handleFriendRequestEvent(data) {
    const name = String((data && data.from_username) || '玩家');
    friendPendingCount = Math.max(0, Number(friendPendingCount) || 0) + 1;
    friendPendingSynced = true;      // 事件已经改过数字，别让一次旧响应把它冲回去
    renderFriendsBadge();
    showMessage(name + ' 想加你为好友，打开「好友」看看', { type: 'info', duration: 5000 });
    // 面板开着的话顺手刷新（重新拉一次接口，不以这次事件的数据渲染 —— 事件 payload
    // 只有 from_* 三个字段，缺 avatar/created_at，拿它渲染会漏字段）
    const modal = document.getElementById('friends-modal');
    if (modal && !modal.classList.contains('hidden')) refreshFriendsPanel();
}

// 申请被通过：提示一句，并把面板/红点对齐服务端
function handleFriendAcceptedEvent(data) {
    const name = String((data && data.username) || '对方');
    showMessage(name + ' 已成为你的好友；现在可以邀他打一局', { type: 'success', duration: 5000 });
    const modal = document.getElementById('friends-modal');
    if (modal && !modal.classList.contains('hidden')) refreshFriendsPanel();
}

// 收到邀战：显示提示条，点「进入房间」走既有入房逻辑
function handleFriendInviteEvent(data) {
    const room = String((data && data.room_id) || '');
    const name = String((data && data.from_username) || '好友');
    if (!room) return;
    activeInviteRoom = room;
    showFriendInviteToast(name, room);
}

// ---------- 入口与初始化 ----------

function initFriendsUI() {
    const btn = document.getElementById('friends-btn');
    if (btn) {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            // ⚠️ 点开才拉 GET /api/friends —— 页加载时**不拉**（票面要求）：
            //    少一次无谓请求，游客也不会白吃一个 401。
            openFriendsModal();
        });
    }
    bindFriendsModal();
    bindProfileFriendButtons();
    bindFriendInviteToast();
    bindDmPanel();            // 好友私聊：会话视图那几个常驻按钮（私聊批）
    // 红点初始状态：0 → 隐藏（只在收到 friend_request 事件后才亮）
    renderFriendsBadge();
}
window.initFriendsUI = initFriendsUI;
window.showFriendsModal = openFriendsModal;
// 私聊那一次"往上翻"自己量到的滚动偏差（像素）。导出到 window 是为了**回归工具**能读到它：
// 工具已经在页面里用 getBoundingClientRect 独立量了一遍（D7f），这一份是产品代码的自证，
// 两边口径相同（容差 DM_ANCHOR_TOLERANCE_PX）—— 对不上就说明"页面上的补法"和"量法"不是一回事。
window.dmAnchorDrift = dmAnchorDrift;

// ===========================================================================
// 更新公告（公告批，2026-09-19）
// ---------------------------------------------------------------------------
// 数据只有**一个来源**：`GET /api/changelog`（文案写在 `changelog.py` 里）。
// 前端不写死任何一条 —— 两份实现必然漂移（本项目的老病根），所以这里只做三件事：
//   ① 把服务端给的「时间 + 一句话」渲染出来（时间**原样渲染**，前端不重算格式，
//      与私聊的 `stamp` 同一原则）；
//   ② 有比本地记录更新的条目时，**已登录**用户进站自动弹一次；
//   ③ 入口上留一个小红点，直到看过为止。
// ⚠️ 三条纪律：
//   · 拉不到就**静默**（公告是锦上添花，绝不许挡住任何东西：不加 loading、不弹错误）；
//   · 用 `textContent` 渲染，不把服务端文本塞进 `innerHTML`；
//   · 这里全是**模块级**函数，只能引用同为模块级的东西（本项目栽过两次
//     「模块级函数引用了函数作用域里的变量 → ReferenceError 被 .then() 吞掉」）。
// ===========================================================================

// 「看过的最新时间」：存的就是接口给的 `latest` 字符串本身（不自己造版本号）
const CHANGELOG_SEEN_KEY = 'battleship_seen_changelog';
// 取到的公告（整个响应缓存一次）：面板渲染与"有没有新公告"共用同一份，不重复打接口
let changelogPayload = null;

function fetchChangelog() {
    if (changelogPayload) return Promise.resolve(changelogPayload);
    return fetch('/api/changelog', { headers: { 'Accept': 'application/json' } })
        .then(resp => (resp.ok ? resp.json() : null))
        .then(body => {
            if (!body || !Array.isArray(body.entries)) return null;
            changelogPayload = body;
            return body;
        })
        .catch(() => null);         // 网络失败：静默，调用方按 null 处理
}

function renderChangelog(body) {
    const box = document.getElementById('changelog-list');
    if (!box) return;
    box.textContent = '';           // 一次性重建（公告是静态内容，不需要保留上一帧）
    const entries = (body && Array.isArray(body.entries)) ? body.entries : [];
    entries.forEach(entry => {
        const sec = document.createElement('section');
        sec.className = 'changelog-entry';
        const date = document.createElement('h3');
        date.className = 'changelog-date';
        date.textContent = String((entry && entry.date) || '');
        sec.appendChild(date);
        const ul = document.createElement('ul');
        ul.className = 'changelog-items';
        ((entry && entry.items) || []).forEach(text => {
            const li = document.createElement('li');
            li.textContent = String(text);      // ⚠️ textContent：服务端文本不进 innerHTML
            ul.appendChild(li);
        });
        sec.appendChild(ul);
        box.appendChild(sec);
    });
}

function updateChangelogDot(hasNew) {
    const dot = document.getElementById('changelog-dot');
    if (dot) dot.classList.toggle('hidden', !hasNew);
}

function closeChangelog() {
    const modal = document.getElementById('changelog-modal');
    if (modal) modal.classList.add('hidden');
}

function markChangelogSeen(latest) {
    // 写失败（无痕模式 / 存储被禁）**不算错**，只是下次可能再弹一次
    if (latest) {
        try { localStorage.setItem(CHANGELOG_SEEN_KEY, String(latest)); } catch (e) { /* 忽略 */ }
    }
    updateChangelogDot(false);
}

function openChangelog() {
    const modal = document.getElementById('changelog-modal');
    if (!modal) return;
    // 浮层互斥：按类名取全量 `.modal-overlay`（见 closeOverlaysExcept）—— 手抄 id 清单会漏
    if (typeof closeOverlaysExcept === 'function') closeOverlaysExcept('changelog-modal');
    modal.classList.remove('hidden');
    fetchChangelog().then(body => {
        if (body) {
            renderChangelog(body);
            markChangelogSeen(body.latest);     // 打开过就算看过（顺手清红点）
        }
        // body 为 null（拉不到）时保持空面板：不弹错误、不挡住任何东西
    });
}
window.openChangelog = openChangelog;

function readSeenChangelog() {
    try { return String(localStorage.getItem(CHANGELOG_SEEN_KEY) || ''); } catch (e) { return ''; }
}

function maybeAnnounceChangelog() {
    // ⚠️ **游客不自动弹，但红点照常算**：红点是"有更新"的提示、不是打断，而弹窗会打断
    //    登录动作。所以这里先分叉，别一刀切 return（一刀切会让游客连红点都看不到）。
    if (!window.__USERNAME) {
        fetchChangelog().then(body => {
            if (!body || !body.latest) return;
            updateChangelogDot(readSeenChangelog() !== String(body.latest));
        });
        return;
    }
    // 正在一局里（本地记着"进行中的对局"）就不打扰：那种情况页面自己会去重连
    try { if (localStorage.getItem(ACTIVE_GAME_KEY)) return; } catch (e) { /* 忽略 */ }
    fetchChangelog().then(body => {
        if (!body || !body.latest) return;
        const hasNew = readSeenChangelog() !== String(body.latest);
        updateChangelogDot(hasNew);
        if (!hasNew) return;
        // 已经有别的浮层开着（登录 / 注册 / 名片…）就先不抢：红点留着，玩家点入口照样看得到
        const opened = document.querySelector('.modal-overlay:not(.hidden)');
        if (opened) return;
        openChangelog();
    });
}

function initChangelogUI() {
    const btn = document.getElementById('changelog-btn');
    const close = document.getElementById('changelog-close');
    const modal = document.getElementById('changelog-modal');
    if (btn) btn.addEventListener('click', (e) => { e.preventDefault(); openChangelog(); });
    if (close) close.addEventListener('click', (e) => { e.preventDefault(); closeChangelog(); });
    // 点遮罩空白处关闭（与既有弹窗一致的手感）
    if (modal) modal.addEventListener('click', (e) => { if (e.target === modal) closeChangelog(); });
    // ⚠️ 自动弹延后一点：init() 里还有"恢复上一局 / 登录态"等收尾要做，
    //    立刻弹会和它们抢屏幕（`maybeAnnounceChangelog` 自己也会再确认一次"没有别的浮层开着"）
    setTimeout(maybeAnnounceChangelog, 900);
}
window.initChangelogUI = initChangelogUI;
