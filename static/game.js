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

// 战绩弹窗容器：优先复用 index.html 里的静态弹窗。
// 旧实现每次都 document.createElement 一个 id 同为 user-stats-modal 的弹窗并 append 到 body，
// 关闭时只加 hidden 不移除 —— 每点一次头像就多一个重复 id 的遮罩，永不回收。
function getStatsModalContent() {
    let modal = document.getElementById('user-stats-modal');
    let content = document.getElementById('user-stats-content');
    if (modal && modal.dataset.dynamic === '1' && content) return content;
    if (!modal || !content) {
        modal = document.createElement('div');
        modal.id = 'user-stats-modal';
        modal.className = 'modal-overlay';
        modal.dataset.dynamic = '1';
        modal.innerHTML = '<div class="modal-content"><span class="modal-close">×</span>'
            + '<h2>个人战绩</h2><div id="user-stats-content"></div></div>';
        document.body.appendChild(modal);
        content = modal.querySelector('#user-stats-content');
        const close = () => { modal.classList.add('hidden'); };
        modal.querySelector('.modal-close').onclick = close;
        modal.onclick = (e) => { if (e.target === modal) close(); };
    }
    return content;
}

// 迷你战绩表（头像入口用）。
// 旧实现把 <table> 包在 <p> 里 —— 非法嵌套，解析器会提前闭合 <p>。
function renderMiniStatsTable(s) {
    if (!s) return '<p>未找到战绩数据</p>';
    return '<table class="user-stats-table">'
        + '<tr><td>用户名</td><td>' + escapeHtml(s.username) + '</td></tr>'
        + '<tr><td>胜场</td><td>' + s.wins + '</td></tr>'
        + '<tr><td>负场</td><td>' + s.losses + '</td></tr>'
        + '<tr><td>当前连胜</td><td>' + s.current_streak + '</td></tr>'
        + '<tr><td>最长连胜</td><td>' + s.longest_streak + '</td></tr>'
        + '</table>';
}

// 点击头像查看战绩
if (myAvatarInGame) {
    myAvatarInGame.style.cursor = 'pointer';
    myAvatarInGame.addEventListener('click', () => {
        // 优先使用 gameState.playerName，再退回到服务器渲染的全局用户名或页面元素
        const username = (window.gameState && window.gameState.playerName) || window.__USERNAME || (document.getElementById('profile-username') && document.getElementById('profile-username').textContent) || '';
        if (!username) {
            showMessage('未登录，无法查看战绩', { type: 'warning' });
            return;
        }
        fetch('/user_stats?username=' + encodeURIComponent(username))
            .then(r => r.json()).then(data => {
                if (!data.stats) {
                    showMessage('未找到战绩数据', { type: 'warning' });
                    return;
                }
                const content = getStatsModalContent();
                if (!content) return;
                content.innerHTML = renderMiniStatsTable(data.stats);
                document.getElementById('user-stats-modal').classList.remove('hidden');
            }).catch(err => {
                showMessage('获取战绩失败' + err, { type: 'error' });
            });
    });
}

if (opponentAvatarInGame) {
    opponentAvatarInGame.style.cursor = 'pointer';
    opponentAvatarInGame.addEventListener('click', () => {
        const username = (window.gameState && window.gameState.opponentName) || (document.getElementById('opponent-username-info') && document.getElementById('opponent-username-info').textContent) || '';
        if (!username) return showMessage('对手信息不可用', { type: 'warning' });
        fetch('/user_stats?username=' + encodeURIComponent(username))
            .then(r => r.json()).then(data => {
                if (!data.stats) {
                    showMessage('未找到对手战绩', { type: 'warning' });
                    return;
                }
                const content = getStatsModalContent();
                if (!content) return;
                content.innerHTML = renderMiniStatsTable(data.stats);
                document.getElementById('user-stats-modal').classList.remove('hidden');
            }).catch(err => showMessage('获取战绩失败' + err, { type: 'error' }));
    });
}
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

// 个人信息弹窗逻辑
if (showProfileBtn && profileModal && profileModalClose) {
    showProfileBtn.onclick = () => {
        fetch('/api/profile').then(r => r.json()).then(res => {
            if (res.profile) {
                profileUsername.textContent = res.profile.username;
                profileSignature.value = res.profile.signature || '';
                profileAvatar.src = res.profile.avatar || '/static/avatars/default.png';
            }
        });
        profileModal.classList.remove('hidden');
        profileSaveMsg.textContent = '';
    };
    profileModalClose.onclick = () => profileModal.classList.add('hidden');
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
                } else {
                    profileSaveMsg.textContent = '保存失败';
                    profileSaveMsg.style.color = 'red';
                }
            });
    };
}

// 头像上传
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
        // 读取当前主色
        const cur = localStorage.getItem('battleship_primary_color') || getComputedStyle(document.documentElement).getPropertyValue('--primary') || '#1976d2';
        if (primaryColorPicker) primaryColorPicker.value = cur.trim().replace(/^#|^rgb\((.+)\)$/g, m => m.startsWith('#') ? m : '#1976d2');
        settingsModal.classList.remove('hidden');
    };
    settingsModalClose.onclick = () => settingsModal.classList.add('hidden');
    settingsModal.onclick = (e) => {
        if (e.target === settingsModal) settingsModal.classList.add('hidden');
    };
}

if (settingsSaveBtn && primaryColorPicker) {
    settingsSaveBtn.onclick = () => {
        const color = primaryColorPicker.value;
        localStorage.setItem('battleship_primary_color', color);
        applyPrimaryColor(color);
        if (settingsModal) settingsModal.classList.add('hidden');
    };
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

// 页面加载时自动应用自定义主色
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
        const color = localStorage.getItem('battleship_primary_color');
        if (color) applyPrimaryColor(color);
    });
} else {
    const color = localStorage.getItem('battleship_primary_color');
    if (color) applyPrimaryColor(color);
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
if (musicBtn) {
    musicBtn.onclick = () => {
        if (settingsModal) {
            settingsModal.classList.remove('hidden');
        }
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

// 大厅界面元素
const lobbyScreen = document.getElementById('lobby-screen');
const joinLobbyBtn = document.getElementById('join-lobby-match');
const leaveLobbyBtn = document.getElementById('leave-lobby-match');
const backFromLobbyBtn = document.getElementById('back-to-main-from-lobby');
const lobbyPlayerCount = document.getElementById('lobby-player-count');
const lobbyPlayersList = document.getElementById('lobby-players-list');


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
    inRoom: false,          // 是否在对局房间中（用于掉线重连）
    reconnectToken: null,   // 对局重连 token
    frozen: false,          // 对手掉线宽限期内冻结操作
    opponentGone: null,     // 对手掉线信息 {deadline}
    sacrificedSelf: [],     // 自己因效果（恶魔契约等）牺牲的格子 → 画在自己棋盘上
    sacrificedOpponent: []  // 对方牺牲的格子（公开信息）→ 画在对方棋盘上
}

let opponentGoneTimer = null;
let opponentGoneEl = null;
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
    gameState.hand = data.hand || [];
    gameState.ships = data.ships || [];
    gameState.myAttacks = data.attacks || [];
    // 对手打在我棋盘上的格：不恢复的话，重连后自己的伤损/沉船会全部显示成完好
    gameState.opponentAttacks = data.opponent_attacks || [];
    gameState.shenweiHoles = data.shenwei_holes || [];
    // 连锁/效果上下文：重连后恢复连锁显示与响应窗口
    if (Array.isArray(data.chain)) {
        gameState.chain = data.chain;
        if (typeof updateChainUI === 'function') updateChainUI();
    }
    if (typeof data.chain_waiting !== 'undefined') gameState.chainWaiting = data.chain_waiting;
    if (typeof data.chain_window !== 'undefined') gameState.chainWindow = data.chain_window;
    // 重连正好落在连锁响应窗口内：把响应弹窗补回来（否则窗口一过就再也没有机会响应）
    if (data.chain_waiting && data.chain_window && data.chain_window === gameState.playerId) {
        const speed3 = (gameState.hand || []).filter(c => c && c.speed === 3);
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
    if (data.pending_placement && typeof showPlacementPrompt === 'function') {
        showPlacementPrompt({
            kind: data.pending_placement.kind,
            remaining: data.pending_placement.remaining,
            total: data.pending_placement.total,
            placed: data.pending_placement.placed,
            blocked: data.pending_placement_blocked || [],
        });
    }
    if (data.field_magic) gameState.fieldMagic = data.field_magic;
    if (data.opponent_name) {
        gameState.opponentName = data.opponent_name;
        if (typeof opponentUsernameInfo !== 'undefined' && opponentUsernameInfo) opponentUsernameInfo.textContent = data.opponent_name;
    }
    saveActiveGame(data.room_id, data.player_id);

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
    if (typeof customRoomInfo !== 'undefined') addHidden(customRoomInfo);
    if (typeof customRoomIdInput !== 'undefined') addHidden(customRoomIdInput);
    if (typeof lobbyScreen !== 'undefined') addHidden(lobbyScreen);
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
    const typeLabel = { attack: '攻击', magic: '魔法', result: '结果', info: '信息' }[entry.type] || '信息';
    addGameLog(
        `<span class="log-time">${escapeHtml(time)}</span>` +
        `<span class="log-badge log-badge-${escapeHtml(entry.type || 'info')}">${typeLabel}</span>` +
        renderLogTextHtml(entry),
        entry.type
    );
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
        if (helpModal) helpModal.classList.remove('hidden');
        renderCardCompendium();
        // 先按已有数据画出来，统计到了再重绘一次（拉不到也不会卡住图鉴）
        loadCardUsage().then(() => renderCardCompendium());
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
        showOpponentStats();
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

    function buildStatsTable(s) {
        return '<table class="user-stats-table">'
            + '<tr><td>用户名</td><td>' + escapeHtml(s.username) + '</td></tr>'
            + '<tr><td>胜场</td><td>' + s.wins + '</td></tr>'
            + '<tr><td>负场</td><td>' + s.losses + '</td></tr>'
            + '<tr><td>当前连胜</td><td>' + s.current_streak + '</td></tr>'
            + '<tr><td>最长连胜</td><td>' + s.longest_streak + '</td></tr>'
            + '</table>';
    }

    // 历史战绩列表：必须用 div 列表承载。
    // 旧写法把 <button> 塞进 table 的 tbody —— 那并非合法的表格子元素，HTML 解析器会
    // 启用 foster parenting 把它挪到 table 之前，表头于是孤立地留在整段列表下方
    // （2026-09-13 修复）。
    function buildHistoryList(history, s) {
        if (!history.length) return '<p class="history-empty">暂无历史战绩</p>';
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

    // 战绩正文（无头 UI 回归检查直接调用 window.renderUserStatsHTML）
    function renderUserStatsHTML(s, history, opts) {
        const options = opts || {};
        const hasAi = history.some(h => isAiOpponent(h, s.id));
        return buildStatsTable(s)
            + (hasAi ? '<p class="user-stats-note">人机对局保留在历史中，不计入胜场 / 连胜，也不进排行榜。</p>' : '')
            + '<div class="user-history">'
            + '<h3>历史战绩</h3>'
            + '<div class="history-list">' + buildHistoryList(history, s) + '</div>'
            + (options.hasMore ? '<button type="button" class="history-more">加载更多</button>' : '')
            + '</div>';
    }
    window.renderUserStatsHTML = renderUserStatsHTML;

    // 单次 20 条，最多 100 条（与服务端 db.get_match_history 的上限一致）
    const STATS_PAGE_SIZE = 20;
    const STATS_MAX_ROWS = 100;
    let statsHistoryLimit = STATS_PAGE_SIZE;

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
                showUserStats();
            });
        }
    }

    // 显示个人战绩弹窗并请求数据
    function showUserStats() {
        if (!userStatsModal || !userStatsContent) {
            console.error('DOM元素不存在：userStatsModal 或 userStatsContent');
            return;
        }
        userStatsModal.classList.remove('hidden');
        userStatsContent.innerHTML = '<p>加载中...</p>';

        fetch('/user_stats?limit=' + statsHistoryLimit).then(resp => {
            if (!resp.ok) throw new Error('未登录或获取失败');
            return resp.json();
        }).then(data => {
            if (!data.stats) {
                userStatsContent.innerHTML = '<p>未找到战绩数据</p>';
                return;
            }
            const s = data.stats;
            const history = data.history || [];
            userStatsContent.innerHTML = renderUserStatsHTML(s, history, {
                hasMore: history.length >= statsHistoryLimit && statsHistoryLimit < STATS_MAX_ROWS
            });
            // innerHTML 赋值后节点已同步就绪，直接绑定即可
            // （原先用 setTimeout(..., 100) 等 DOM，纯属多余且可能被重建打断）
            bindHistoryButtons(userStatsContent, history, s.id);
        }).catch(err => {
            console.error('获取个人战绩失败:', err);
            userStatsContent.innerHTML = '<p style="color:red;">获取个人战绩失败：' + err.message + '</p>';
        });
    }

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
    playAgainBtn.addEventListener('click', resetGame);

    // 返回主菜单按钮事件处理
    returnToMenuBtn.addEventListener('click', resetGame);

    // 自定义房间游戏界面
    customCreateRoomBtn.addEventListener('click', customCreateRoom);
if (copyInviteLinkBtn) copyInviteLinkBtn.addEventListener('click', copyInviteLink);
    customJoinRoomBtn.addEventListener('click', () => customRoomIdInput.classList.remove('hidden'));
    customConfirmJoinBtn.addEventListener('click', customJoinRoom);
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

    // 大厅按钮事件绑定
    if (joinLobbyBtn) joinLobbyBtn.addEventListener('click', joinLobbyMatch);
    if (leaveLobbyBtn) leaveLobbyBtn.addEventListener('click', leaveLobbyMatch);
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

    // 复用/建立连接（ensureSocket 内部保证不重复建连）
    ensureSocket();

    // 发送匹配请求
    gameState.socket.emit('find_match', {
        player_name: gameState.playerName
    }, (response) => {
        if (response.status === 'error') {
            showAlert(response.message);
        }
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
        matchStatus.classList.remove('hidden');
        // 大厅按钮同步（服务端没有 lobby_joined/lobby_left 这类事件）
        if (joinLobbyBtn) joinLobbyBtn.classList.add('hidden');
        if (leaveLobbyBtn) leaveLobbyBtn.classList.remove('hidden');
    });

    socket.on('match_canceled', (response) => {
        console.log('匹配已取消:', response);
        matchStatus.classList.add('hidden');
        if (joinLobbyBtn) joinLobbyBtn.classList.remove('hidden');
        if (leaveLobbyBtn) leaveLobbyBtn.classList.add('hidden');
    });

    socket.on('game_state', (data) => {
        console.log('Game state received:', data);
        // 隐藏所有屏幕和信息面板
        customRoomInfo.classList.add('hidden');
        customRoomIdInput.classList.add('hidden');
        startScreen.classList.remove('active');
        customRoomScreen.classList.remove('active');
        matchSuccessScreen.classList.remove('active');
        shipPlacementScreen.classList.remove('active');
        rpsScreen.classList.remove('active');
        gameScreen.classList.remove('active');
        gameOverScreen.classList.remove('active');

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
        function showOpponentStats() {
            if (!opponentStatsModal || !opponentStatsContent || !gameState.opponentName) return;
            opponentStatsModal.classList.remove('hidden');
            opponentStatsContent.innerHTML = '<p>加载中...</p>';
            fetch('/user_stats?username=' + encodeURIComponent(gameState.opponentName)).then(resp => {
                if (!resp.ok) throw new Error('未找到对手或未登录');
                return resp.json();
            }).then(data => {
                if (data.stats) {
                    const s = data.stats;
                    opponentStatsContent.innerHTML = `
                        <table class="user-stats-table">
                            <tr><td>用户名</td><td>${escapeHtml(s.username)}</td></tr>
                            <tr><td>胜场</td><td>${s.wins}</td></tr>
                            <tr><td>负场</td><td>${s.losses}</td></tr>
                            <tr><td>当前连胜</td><td>${s.current_streak}</td></tr>
                            <tr><td>最长连胜</td><td>${s.longest_streak}</td></tr>
                        </table>
                    `;
                } else {
                    opponentStatsContent.innerHTML = '<p>未找到对手战绩数据</p>';
                }
            }).catch(err => {
                opponentStatsContent.innerHTML = `<p style="color:red;">${err.message}</p>`;
            });
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
                        // 确保界面正确切换
                        startScreen.classList.add('hidden');
                        customRoomScreen.classList.add('hidden');
                        matchStatus.classList.add('hidden');
                        lobbyScreen.classList.add('hidden');
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

        switchScreen(gameOverScreen);
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
            applyCardEffect(result.card, result.caster);
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

    // 连锁响应弹窗（10 秒倒计时 + 点选速阶 3 卡）。
    // 抽成具名函数是为了让「重连正好落在响应窗口内」也能把弹窗补回来。
    function showChainRequestPrompt(data) {
        playSfx('chain');
        // 显示连锁选择对话框
        const chainPrompt = document.createElement('div');
        chainPrompt.className = 'magic-prompt';

        // 生成速阶3卡牌列表HTML
        let speed3CardsHTML = '';
        data.speed3_cards.forEach((card, index) => {
            speed3CardsHTML += `<div class="chain-card-item" data-card-index="${index}" data-card-name="${card.name}" data-card-speed="${card.speed}">
                <div class="chain-card-name">${card.name}</div>
                <div class="chain-card-speed">速阶：${card.speed}</div>
            </div>`;
        });

        chainPrompt.innerHTML = `
            <h3>连锁请求</h3>
            <p>${data.caster && data.caster === gameState.playerId ? '你发动了' : '对方发动了'}魔法卡【${data.card.name}】</p>
            <div class="chain-countdown">剩余时间：<span id="chain-countdown-time">10</span>秒</div>
            <div class="chain-speed3-cards">
                <h4>你拥有的速阶3魔法卡：</h4>
                ${speed3CardsHTML}
            </div>
            <p class="chain-prompt-text">是否打出接续连锁？</p>
            <div class="chain-options">
                <button id="chain-cancel" class="chain-cancel-btn">取消</button>
            </div>
        `;
        document.body.appendChild(chainPrompt);

        // 倒计时功能
        let countdown = data.countdown || 10;
        const countdownTimer = setInterval(() => {
            countdown--;
            // 使用chainPrompt.querySelector获取当前对话框内的倒计时元素
            const countdownTimeElement = chainPrompt.querySelector('#chain-countdown-time');
            if (countdownTimeElement) {
                countdownTimeElement.textContent = countdown;
            }
            if (countdown <= 0) {
                clearInterval(countdownTimer);
                // 倒计时结束，自动默认"否"
                gameState.socket.emit('chain_response', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    chain: false
                });
                document.body.removeChild(chainPrompt);
            }
        }, 1000);

        // 取消按钮 - 使用chainPrompt.querySelector获取当前对话框内的按钮
        const cancelButton = chainPrompt.querySelector('#chain-cancel');
        if (cancelButton) {
            cancelButton.addEventListener('click', () => {
                clearInterval(countdownTimer);
                gameState.socket.emit('chain_response', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    chain: false
                });
                document.body.removeChild(chainPrompt);
            });
        }

        // 点击速阶3卡牌选择连锁 - 使用chainPrompt.querySelectorAll获取当前对话框内的卡牌元素
        const cardItems = chainPrompt.querySelectorAll('.chain-card-item');
        cardItems.forEach(cardElement => {
            cardElement.addEventListener('click', () => {
                clearInterval(countdownTimer);
                const cardIndex = parseInt(cardElement.dataset.cardIndex);
                const selectedCard = data.speed3_cards[cardIndex];
                document.body.removeChild(chainPrompt);

                // 需要目标的速阶3卡（神威！/轰炸/冻结/硫磺火焰/探测雷达）此前
                // 一律发 targets: []，服务端缺目标直接失败 —— 等于这些卡在连锁
                // 响应窗口里根本打不出来。改为先走目标选择器，再回填 targets。
                if (needsTargetSelection(selectedCard.name) || selectedCard.name === '神之宣告') {
                    gameState.pendingChainCard = { card: selectedCard, index: cardIndex };
                    if (selectedCard.name === '神之宣告') {
                        // 先选效果，再点选要牺牲的两艘船
                        promptDivineDecreeChoice(cardIndex, selectedCard);
                    } else {
                        gameState.currentMagicCard = selectedCard;
                        gameState.currentCardIndex = cardIndex;
                        showMagicTargetSelection(selectedCard, cardIndex);
                    }
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
        gameState.remainingShips = 0;
        gameState.opponentRemainingShips = 0;
        gameState.maxShips = data.new_max_ships;
        gameState.placedShips = 0;

        // 隐藏所有其他屏幕
        startScreen.classList.remove('active');
        customRoomScreen.classList.remove('active');
        matchSuccessScreen.classList.remove('active');
        rpsScreen.classList.remove('active');
        gameScreen.classList.remove('active');
        gameOverScreen.classList.remove('active');

        // 直接进入放置战舰界面
        shipPlacementScreen.classList.add('active');
        initBoard(playerBoard, true);

        // 确保界面正确切换
        startScreen.classList.add('hidden');
        customRoomScreen.classList.add('hidden');
        matchStatus.classList.add('hidden');
        lobbyScreen.classList.add('hidden');

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

    // 说明：服务端从来没有 lobby_update / lobby_joined / lobby_left / match_found
    // 这些事件（历史遗留空壳，已删除）。大厅按钮状态改由上面真实的
    // match_queued / match_canceled 处理器同步。

    // 新增：监听手牌更新事件
    socket.on('hand_updated', (data) => {
        const grew = Array.isArray(data.hand) && data.hand.length > (gameState.hand || []).length;
        gameState.hand = data.hand;
        updateHandUI();
        if (grew) playSfx('draw');
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
        // 卡片名按来源显示：恶魔契约 / 神之宣告 都走这条公开事件
        const reasonText = data.reason === 'divine_decree' ? '神之宣告' : '恶魔契约';
        showMessage(mine ? `${reasonText}：你牺牲了一艘战舰` : `${reasonText}：对方牺牲了一艘战舰`,
                    { type: 'warning' });
    });

    // 服务端统一推送的局内日志
    socket.on('game_log', (entry) => {
        renderServerLog(entry);
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
        showMessage((data && data.kind === 'revive') ? '复活部署完成' : '增援部署完成');
        if (typeof initGameBoards === 'function') initGameBoards();
    });
    // 自己棋盘上的战舰变化（复活/增援后同步显示）
    socket.on('player_ships_updated', (data) => {
        if (data && Array.isArray(data.ships)) {
            gameState.ships = data.ships;
            if (typeof initGameBoards === 'function') initGameBoards();
        }
    });

    // 新增：监听战舰数更新事件
    socket.on('ships_updated', (data) => {
        // 更新双方剩余战舰数
        yourShips.textContent = data.player_remaining_ships;
        opponentShips.textContent = data.opponent_remaining_ships;
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
        // 移除等待提示
        const waitingOverlay = document.querySelector('.taoyuan-waiting-overlay');
        if (waitingOverlay) {
            waitingOverlay.remove();
        }
        showMessage(data.message);
    });

    // 服务器返回的被揭示的位置（仅对触发方发送）
    socket.on('revealed_positions', (data) => {
        if (!data || !Array.isArray(data.positions)) return;
        // 卡面是「显形」，服务端也是持久记录（只有重开棋盘类效果才清空）——
        // 原先只高亮 4 秒就撤掉，玩家一眨眼就再也找不到那艘船了。
        data.positions.forEach(pos => {
            if (!gameState.revealedCells.some(c => c.x === pos.x && c.y === pos.y)) {
                gameState.revealedCells.push({ x: pos.x, y: pos.y });
            }
            const cell = opponentBoard.querySelector(`.cell[data-x='${pos.x}'][data-y='${pos.y}']`);
            if (cell) cell.classList.add('revealed');
        });
    });

}

// 切换屏幕
function switchScreen(screen) {
    const screens = [startScreen, customRoomScreen, shipPlacementScreen, rpsScreen, gameScreen,
                     leaderboardScreen, lobbyScreen, gameOverScreen, matchSuccessScreen];
    screens.forEach(s => {
        if (s) s.classList.remove('active');
    });
    if (screen) screen.classList.add('active');

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
    fetchLeaderboard();
}

// 显示大厅
function showLobby() {
    switchScreen(lobbyScreen);
    // 复用/建立连接
    ensureSocket();
    // 重置按钮状态（显示加入匹配，隐藏离开匹配）
    joinLobbyBtn.classList.remove('hidden');
    leaveLobbyBtn.classList.add('hidden');
    // 请求大厅更新
    updateLobbyDisplay();
}

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
            tr.innerHTML = `<td>${idx + 1}</td><td>${escapeHtml(row.username)}</td><td>${wins}</td><td>${losses}</td><td>${winrate}</td><td>${row.longest_streak || 0}</td>`;
            leaderboardTableBody.appendChild(tr);
        });
    }).catch(err => {
        leaderboardTableBody.innerHTML = '';
        leaderboardError.classList.remove('hidden');
        leaderboardError.textContent = '无法加载排行榜：' + err.message;
    });
}

// 更新大厅显示：在线人数取真实接口（服务端没有 lobby_update 事件）
function updateLobbyDisplay() {
    fetch('/api/online_count').then(r => r.json()).then(data => {
        if (lobbyPlayerCount && typeof data.online_count === 'number') {
            lobbyPlayerCount.textContent = data.online_count;
        }
        if (lobbyPlayersList) {
            lobbyPlayersList.innerHTML = '<li>匹配由服务器自动配对，点击「加入匹配」即可</li>';
        }
    }).catch(() => {});
}

// 加入大厅匹配：走真实的 find_match（后端无 join_lobby handler）
function joinLobbyMatch() {
    ensureSocket();
    gameState.socket.emit('find_match', { player_name: gameState.playerName });
}

// 离开大厅匹配：走真实的 cancel_match（后端无 leave_lobby handler）
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
                if (ownShip.frozen) {
                    cell.classList.add('frozen');
                    cell.title = '这艘船被冻结了：本回合不提供攻击次数';
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

            // 已被卡牌显形的格子：重绘棋盘后也要保留（否则一次 initGameBoards 就把线索擦没了）
            if ((gameState.revealedCells || []).some(c => c.x === x && c.y === y)) {
                cell.classList.add('revealed');
            }

            opponentBoard.appendChild(cell);
        }
    }

    applyShenweiHoles();
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

    // 教皇旨意：攻击需先弃一张魔法卡（服务端一次弃卡=攻击两次）
    if (gameState.fieldMagic === '教皇旨意') {
        if (!gameState.hand || gameState.hand.length === 0) {
            showAlert('教皇旨意需要弃一张魔法卡才能攻击，但你没有手牌');
            return;
        }
        showPapalDiscardChoice(x, y);
        return;
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
    // 如果是自己的攻击
    if (result.attacker === gameState.playerId) {
        gameState.myAttacks.push({
            x: result.x,
            y: result.y,
            hit: result.hit
        });
        // 更新自己和对手的剩余战舰数
        yourShips.textContent = result.attacker_remaining_ships;
        opponentShips.textContent = result.defender_remaining_ships;
    } else {
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

    // 记录最近一次攻击坐标与来源，供溅射动画使用
    gameState.lastAttack = {
        x: result.x,
        y: result.y,
        attacker: result.attacker,
        hit: result.hit
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
function resetGame() {
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

// 修改canPlayCard函数
function canPlayCard(card) {
    // 特例：Freezing！ 只能在自己先手回合的结束阶段发动
    if (END_PHASE_PLAYABLE_CARDS.indexOf(card.name) >= 0) {
        return isFirstPlayer() &&
            gameState.currentPhase === 'end' &&
            gameState.currentAttacker === gameState.playerId;
    }
    // 速阶1: 只能在自己的准备阶段使用
    if (card.speed === 1) {
        return gameState.currentPhase === 'preparation' && gameState.currentAttacker === gameState.playerId;
    }
    // 速阶2: 可以在自己的准备阶段和战斗阶段使用
    else if (card.speed === 2) {
        return (gameState.currentPhase === 'preparation' || gameState.currentPhase === 'battle') &&
            gameState.currentAttacker === gameState.playerId;
    }
    // 速阶3: 任何时候都可以使用
    else if (card.speed === 3) {
        return true;
    }
    return false;
}

// 限制需命中后才能发动的卡
function canPlayAfterHit(card) {
    const needHit = card.name === '溅射' || card.name === '雷达子弹';
    if (!needHit) return true;
    const last = gameState.lastAttack;
    return !!(last && last.attacker === gameState.playerId && last.hit);
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
        gameState.pendingEffectChoice = null;
    }

    // AREA selection (square) —— 点选定位 + 确认，触摸可用
    if (descriptor.type === 'area') {
        const size = descriptor.size;
        targetPrompt.innerHTML = `
            <h3>在对手棋盘上选择 ${size}x${size} 区域</h3>
            <p class="magic-hint">点一下定位区域，再点「确认」</p>
        `;
        document.body.appendChild(targetPrompt);

        const picker = createBoardAreaPicker(opponentBoard, size, (areaObj) => {
            confirmMagicTarget(areaObj);
            cleanupPrompt();
        }, cleanupPrompt);
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
        // ensure styles
        if (!document.getElementById('magic-selection-styles')) {
            const s = document.createElement('style');
            s.id = 'magic-selection-styles';
            s.textContent = `
                .magic-selection-overlay { background-color: rgba(255,69,0,0.28); transition: background-color .12s ease, box-shadow .12s ease; }
                .magic-selection-overlay.col { background-color: rgba(30,144,255,0.28); }
                .magic-selection-controls { display:flex; gap:8px; justify-content:center; margin-top:8px; }
                .inline-confirm { background:#222; color:#fff; padding:8px; border-radius:4px; box-shadow:0 4px 14px rgba(0,0,0,.5); }
            `;
            document.head.appendChild(s);
        }

        targetPrompt.innerHTML = `
            <h3>拖拽或点击选择一整行/列（拖拽时松开确认）</h3>
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
        });

        const cells = Array.from(boardEl.querySelectorAll('.cell'));
        let isMouseDown = false;
        let lastIndex = null;

        function clearHighlights() {
            cells.forEach(c => c.classList.remove('magic-selection-overlay'));
        }

        function highlightIndex(idx) {
            clearHighlights();
            if (mode === 'row') {
                boardEl.querySelectorAll(`.cell[data-y="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay'));
            } else {
                boardEl.querySelectorAll(`.cell[data-x="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay', 'col'));
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
                cell.classList.remove('magic-selection-overlay', 'col');
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
        // ensure styles
        if (!document.getElementById('magic-selection-styles')) {
            const s = document.createElement('style');
            s.id = 'magic-selection-styles';
            s.textContent = `
                .magic-selection-overlay { background-color: rgba(255,140,0,0.24); transition: background-color .12s ease, transform .12s ease; }
                .magic-selection-overlay.vert { background-color: rgba(34,139,34,0.24); }
            `;
            document.head.appendChild(s);
        }

        targetPrompt.innerHTML = `
            <h3>自由选择连续 ${L} 个格子（点击选中/取消，每个新增格需与已选格相邻）</h3>
            <div style="text-align:center;margin-top:8px;">
                <button id="confirm-continuous">确认</button>
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
            cells.forEach(c => c.classList.remove('magic-selection-overlay', 'vert'));
            cells.forEach(c => {
                const cx = parseInt(c.dataset.x, 10);
                const cy = parseInt(c.dataset.y, 10);
                if (selected.has(key(cx, cy))) c.classList.add('magic-selection-overlay');
            });
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
                cell.classList.remove('magic-selection-overlay', 'vert');
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
            (gameState.ships || []).forEach(ship => {
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
function createBoardAreaPicker(boardEl, size, onConfirm, onCancel) {
    if (!boardEl || gameState.selectingOnBoard) return null;
    gameState.selectingOnBoard = true;

    const listeners = [];
    let highlighted = [];
    let current = null;

    const clampStart = (mx, my) => ({
        sx: Math.max(0, Math.min(mx, 6 - size)),
        sy: Math.max(0, Math.min(my, 6 - size))
    });

    function clearHighlights() {
        highlighted.forEach(c => c.classList.remove('selection-highlight'));
        highlighted = [];
    }

    function highlight(sx, sy) {
        clearHighlights();
        for (let y = sy; y < sy + size; y++) {
            for (let x = sx; x < sx + size; x++) {
                if (x < 0 || x > 5 || y < 0 || y > 5) continue;
                const cell = boardEl.querySelector(`.cell[data-x="${x}"][data-y="${y}"]`);
                if (cell) { cell.classList.add('selection-highlight'); highlighted.push(cell); }
            }
        }
        current = { x1: sx, y1: sy, x2: sx + size - 1, y2: sy + size - 1 };
        const btn = document.getElementById('area-confirm');
        if (btn) btn.disabled = false;
    }

    // 浮动确认条
    const bar = document.createElement('div');
    bar.className = 'area-picker-bar';
    bar.innerHTML = `<button id="area-confirm" disabled>确认</button><button id="area-cancel">取消</button>`;
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
    if (freezeAlert()) return;

    // 检查卡牌是否可以在当前阶段使用
    if (!canPlayCard(card)) {
        if (END_PHASE_PLAYABLE_CARDS.indexOf(card.name) >= 0) {
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

    // 特殊限制：溅射、雷达子弹需在自己上一击命中后才可使用
    if (!canPlayAfterHit(card)) {
        showAlert(`${card.name} 需要你上一次攻击命中后才能发动`);
        return;
    }
    if (gameState.fieldMagic === "禁忌果实") {
        if (!(card.name === "失灵！" || card.type === "场地")) {
            showAlert(`无法使用${card.name}：场地魔法“禁忌果实”生效，非场地及失灵类魔法卡无法使用`);
            return;
        }
    }

    // 神之宣告：两步都走完才算出牌 —— 先选要发动的效果（promptDivineDecreeChoice），
    // 再由 needsTargetSelection 的 own_ships 收集要牺牲的两艘船，
    // 最后在 confirmMagicTarget 里把「效果 + 两艘船」一次性提交。
    if (card.name === '神之宣告') {
        promptDivineDecreeChoice(index);
        return;
    }

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

    console.log('发送魔法卡:', card.name);
    gameState.socket.emit('use_magic_card', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        card: card,
        targets: targets
    }, (response) => {
        // 只有在服务器确认成功后才更新本地状态
        if (response.status === 'success') {
            console.log('魔法卡使用成功');
            // 从手牌中移除
            gameState.hand.splice(index, 1);
            // 添加到弃牌堆
            gameState.discardPile.push(card);
            // 更新UI
            updateHandUI();
        } else {
            console.error('魔法卡使用失败:', response.message);
            showAlert(`使用魔法卡失败：${response.message || '未知错误'}`);
        }
    });
}

// 神之宣告：第一步 —— 选择要触发的效果（1=摧毁对方一艘战舰，2=跳过对方本回合）。
// 选完效果再走 own_ships 点选两艘要牺牲的船，最后一起提交（见 confirmMagicTarget）。
function promptDivineDecreeChoice(cardIndex, cardOverride) {
    // 连锁响应窗口里打出的神之宣告未必存在于「手牌同下标」，
    // 因此允许显式传入卡牌对象（默认仍按手牌下标取）。
    const card = cardOverride || gameState.hand[cardIndex];
    if (!card) return;

    const overlay = document.createElement('div');
    overlay.className = 'taoyuan-choice-overlay';
    overlay.style.zIndex = '10000';
    overlay.innerHTML = `
        <div class="taoyuan-choice-container">
            <div class="taoyuan-choice-header">
                <h3>神之宣告</h3>
                <p>牺牲两艘战舰，选择要触发的效果：</p>
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
            if (choice === 0) return;
            // 卡面要求牺牲两艘自己的战舰。此前这里直接 sendMagicCard，
            // 服务端收不到 selected_cells，只能 random.shuffle 随机补两艘，
            // 玩家根本没有选择权（own_ships 选择器也因此永远不可达）。
            // 现在把效果选择挂起，走「点选两艘自己的船」→ confirmMagicTarget。
            gameState.pendingEffectChoice = choice;
            gameState.currentMagicCard = card;
            gameState.currentCardIndex = cardIndex;
            showMagicTargetSelection(card, cardIndex);
        });
    });
}

// 修改目标选择后的确认函数
function confirmMagicTarget(targetData) {
    if (!gameState.currentMagicCard || gameState.currentCardIndex === null) return;

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

    // 神之宣告：把出牌前选好的效果一并带上（否则服务端只能退回默认效果）
    if (gameState.pendingEffectChoice) {
        payload.effect_choice = gameState.pendingEffectChoice;
        gameState.pendingEffectChoice = null;
    }

    // 连锁响应窗口里打出的卡：目标要回填给 chain_response，而不是 use_magic_card
    if (gameState.pendingChainCard) {
        const pending = gameState.pendingChainCard;
        gameState.pendingChainCard = null;
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
        gameState.pendingChainCard = null;
        gameState.pendingEffectChoice = null;
        gameState.socket.emit('chain_response', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            chain: true,
            card: pending.card,
            targets: payload
        });
        return;
    }

    // 发送并清理当前魔法卡选择状态
    sendMagicCard(gameState.currentCardIndex, payload);
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
            // 添加状态图标显示（元素不存在时静默跳过，避免抛错）
            {
                const indicatorBox = document.getElementById('effect-indicators');
                if (indicatorBox) {
                    indicatorBox.innerHTML += '<div class="effect-icon" title="百亿补贴">补贴</div>';
                }
            }
            break;

        case '绝处逢生':
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
            showMessage('回光返照效果生效，请重新摆放战舰');
            // 重新初始化棋盘
            initBoard(playerBoard, true);
            gameState.ships = [];
            gameState.placedShips = 0;
            shipsPlaced.textContent = '0';
            confirmShipsBtn.classList.remove('hidden');
            switchScreen(shipPlacementScreen);
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
}

// 恶魔契约：在自己棋盘上点选要牺牲的战舰（不弹额外窗口，直接点格子）
function showSacrificePrompt(data) {
    // 清理可能残留的选区状态，避免 selectingOnBoard 卡死
    if (typeof gameState.selectionCleanup === 'function') {
        try { gameState.selectionCleanup(); } catch (_) { }
        gameState.selectionCleanup = null;
    }
    gameState.selectingOnBoard = false;
    document.querySelectorAll('.magic-target-prompt').forEach(el => el.remove());
    document.querySelectorAll('.cell.pick-ship, .cell.pick-disabled')
        .forEach(c => c.classList.remove('pick-ship', 'pick-disabled'));

    const prompt = document.createElement('div');
    prompt.className = 'magic-target-prompt';
    prompt.innerHTML = `
        <h3>恶魔契约：选择要牺牲的战舰</h3>
        <p class="magic-hint">点自己战舰所在的格子（绿色高亮）即可，不需要再确认</p>
    `;
    document.body.appendChild(prompt);
    showMessage((data && data.message) || '恶魔契约生效，请选择一艘自己的战舰牺牲',
                { type: 'warning' });

    gameState.selectingOnBoard = true;
    const listeners = [];

    // 自己船所在的格子
    const ownCells = new Set();
    (gameState.ships || []).forEach(ship => {
        (ship.positions || []).forEach(p => ownCells.add(p.x + ',' + p.y));
    });

    const cleanup = () => {
        listeners.forEach(({ el, handler }) => el.removeEventListener('click', handler, true));
        document.querySelectorAll('.cell.pick-ship, .cell.pick-disabled')
            .forEach(c => c.classList.remove('pick-ship', 'pick-disabled'));
        gameState.selectingOnBoard = false;
        if (document.body.contains(prompt)) document.body.removeChild(prompt);
        gameState.selectionCleanup = null;
    };

    const onClick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        const el = e.currentTarget;
        const x = parseInt(el.dataset.x, 10);
        const y = parseInt(el.dataset.y, 10);
        gameState.socket.emit('confirm_sacrifice', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            position: { x, y }
        }, (resp) => {
            if (resp && resp.status === 'error') {
                showAlert(resp.message || '牺牲失败，请重新选择');
            }
        });
        cleanup();
    };

    (gamePlayerBoard ? gamePlayerBoard.querySelectorAll('.cell') : []).forEach(cell => {
        const x = parseInt(cell.dataset.x, 10);
        const y = parseInt(cell.dataset.y, 10);
        if (!ownCells.has(x + ',' + y)) {
            cell.classList.add('pick-disabled');   // 空格：灰掉，不可点
            return;
        }
        cell.classList.add('pick-ship');
        cell.addEventListener('click', onClick, true);
        listeners.push({ el: cell, handler: onClick });
    });

    gameState.selectionCleanup = cleanup;
}

// 增援 / 复活：统一放置弹窗（灰格不可选、可确认、可放弃）
function showPlacementPrompt(data) {
    data = data || {};
    const isRevive = data.kind === 'revive';
    const isLastStand = data.kind === 'last_stand';
    const total = data.total || 1;
    const placed = data.placed || 0;
    const remaining = (data.remaining != null) ? data.remaining : 1;

    const existing = document.getElementById('placement-prompt');
    if (existing) existing.remove();

    const title = isLastStand ? '绝处逢生·放置唯一一艘战舰'
        : (isRevive ? '复活战舰·选择部署位置' : '增援战舰·选择部署位置');
    const step = total > 1 ? `（第 ${placed + 1}/${total} 艘）` : '';
    const hint = isLastStand
        ? `牺牲了全部战舰后，只能在${step}原本有自己战舰的格子（亮色）上放置唯一一艘。`
        : (isRevive
            ? `这张卡会把阵亡的战舰重新部署到你的棋盘上。${step}点一个亮色格子选中，再点「确认」。灰色格子不能用（对方打过 / 已占用 / 被神威扣掉）。`
            : `这张卡会给你补充一艘新战舰。${step}点一个亮色格子选中，再点「确认」。灰色格子不能用（对方打过 / 已占用 / 被神威扣掉）。`);

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

function updateHandUI() {
    const handElement = document.getElementById('magic-hand');
    if (!handElement) return;

    handElement.innerHTML = '';
    gameState.hand.forEach((card, index) => {
        const cardElement = document.createElement('div');
        cardElement.classList.add('magic-card');
        cardElement.dataset.index = index;

        // 如果是选中状态，添加selected类
        if (gameState.selectedCardIndex === index) {
            cardElement.classList.add('selected');
        }

        cardElement.innerHTML = `
            <div class="card-name">${escapeHtml(card.name)}</div>
            <div class="card-speed">速阶：${escapeHtml(card.speed)}</div>
            <div class="card-type">${escapeHtml(card.type)}魔法</div>
        `;

        // 添加点击事件，实现点击选择/使用功能
        cardElement.addEventListener('click', () => {
            // 如果是已选中状态，尝试使用卡牌
            if (gameState.selectedCardIndex === index) {
                // 尝试使用卡牌
                playMagicCard(index);
            } else {
                // 选中卡牌，更新预览
                gameState.selectedCardIndex = index;
                updateHandUI(); // 重新渲染手牌，更新选中状态
                updateCardPreview(card, index); // 更新卡牌预览信息
            }
        });

        handElement.appendChild(cardElement);
    });

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

    // 检查 URL 是否包含 room 参数，如果有则在连接后自动加入
    const urlParams = new URLSearchParams(window.location.search);
    const autoRoom = urlParams.get('room');
    if (autoRoom) {
        // Ensure socket exists and listeners are set up
        ensureSocket();
        // 在 socket 连接后尝试加入房间
        if (gameState.socket.connected) {
            gameState.socket.emit('join_room', { room_id: autoRoom, player_name: gameState.playerName }, (resp) => {
                if (resp && resp.status === 'success') {
                    gameState.roomId = autoRoom;
                    switchScreen(shipPlacementScreen);
                }
            });
        } else {
            // 等待连接建立后加入
            const onceConnect = () => {
                gameState.socket.emit('join_room', { room_id: autoRoom, player_name: gameState.playerName }, (resp) => {
                    if (resp && resp.status === 'success') {
                        gameState.roomId = autoRoom;
                        switchScreen(shipPlacementScreen);
                    }
                    gameState.socket.off('connect', onceConnect);
                });
            };
            gameState.socket.on('connect', onceConnect);
        }
    }

    // 创建魔法手牌区域
    createMagicCardUI();
    // 初始化卡牌提示框
    initCardTooltip();
}

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
function updatePhaseUI() {
    const phaseElement = document.getElementById('current-phase');
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

// 教皇旨意：选择一张手牌弃置后攻击（一次弃卡=攻击两次，由服务端执行）
function showPapalDiscardChoice(x, y) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10002;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center';
    const box = document.createElement('div');
    box.style.cssText = 'background:#fff;color:#222;padding:18px 22px;border-radius:10px;min-width:300px;max-width:80vw;max-height:70vh;overflow:auto;text-align:center';
    box.innerHTML = '<div style="font-weight:bold;margin-bottom:10px">教皇旨意 · 弃一张魔法卡攻击两次</div>';
    const list = document.createElement('div');
    list.style.cssText = 'display:flex;flex-direction:column;gap:6px;text-align:left';
    if (!gameState.hand || gameState.hand.length === 0) {
        list.innerHTML = '<div style="color:#c0392b">没有可弃置的魔法卡</div>';
    } else {
        gameState.hand.forEach((card, i) => {
            const b = document.createElement('button');
            b.textContent = (card.name || card.name) + '（速阶' + card.speed + '）';
            b.style.cssText = 'padding:6px 10px;cursor:pointer;text-align:left';
            b.onclick = () => {
                if (gameState.socket) {
                    gameState.socket.emit('papal_attack', {
                        room_id: gameState.roomId,
                        player_id: gameState.playerId,
                        x: x, y: y,
                        discard_card_index: i
                    }, (resp) => {
                        if (resp && resp.status === 'error') showAlert(resp.message);
                    });
                }
                try { document.body.removeChild(overlay); } catch (e) {}
            };
            list.appendChild(b);
        });
    }
    const close = document.createElement('button');
    close.textContent = '取消';
    close.style.cssText = 'margin-top:12px;padding:6px 16px;cursor:pointer';
    close.onclick = () => { try { document.body.removeChild(overlay); } catch (e) {} };
    box.appendChild(list);
    box.appendChild(close);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
}

// 仁王之盾：选择至多3艘自己的船进入护盾状态
function showRenwangChoice() {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10003;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center';
    const box = document.createElement('div');
    box.style.cssText = 'background:#fff;color:#222;padding:18px 22px;border-radius:10px;min-width:300px;text-align:center';
    box.innerHTML = '<div style="font-weight:bold;margin-bottom:6px">仁王之盾 · 选择要保护的船（至多3艘）</div>';
    const list = document.createElement('div');
    list.style.cssText = 'display:flex;flex-direction:column;gap:6px;text-align:left;margin:8px 0';
    const ships = gameState.ships || [];
    const picked = new Set();
    if (ships.length === 0) {
        list.innerHTML = '<div style="color:#c0392b">没有可保护的战舰</div>';
    } else {
        ships.forEach((ship, idx) => {
            const b = document.createElement('button');
            const p = (ship.positions && ship.positions[0]) ? ('(' + ship.positions[0].x + ',' + ship.positions[0].y + ')') : ('#' + idx);
            b.textContent = '选择船 ' + (idx + 1) + ' ' + p;
            b.style.cssText = 'padding:6px 10px;cursor:pointer;text-align:left';
            b.onclick = () => {
                if (picked.has(idx)) { picked.delete(idx); b.style.borderColor = ''; }
                else {
                    if (picked.size >= 3) { showAlert('最多选择3艘船'); return; }
                    picked.add(idx); b.style.borderColor = '#1976d2'; b.style.borderWidth = '2px';
                }
            };
            list.appendChild(b);
        });
    }
    const ok = document.createElement('button');
    ok.textContent = '确定';
    ok.style.cssText = 'margin:4px 6px 0 0;padding:6px 20px;cursor:pointer';
    ok.onclick = () => {
        const idxs = Array.from(picked);
        if (idxs.length === 0) { showAlert('请至少选择一艘船'); return; }
        if (gameState.socket) {
            gameState.socket.emit('confirm_magic_target', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                temp_data_id: 'shield_choice',
                target_data: { ship_indices: idxs }
            }, (resp) => {
                if (resp && resp.status === 'success') showMessage(resp.message || '护盾已添加');
                else if (resp) showAlert(resp.message || '选择失败');
            });
        }
        try { document.body.removeChild(overlay); } catch (e) {}
    };
    const cancel = document.createElement('button');
    cancel.textContent = '取消';
    cancel.style.cssText = 'padding:6px 16px;cursor:pointer';
    cancel.onclick = () => { try { document.body.removeChild(overlay); } catch (e) {} };
    box.appendChild(list);
    const row = document.createElement('div');
    row.appendChild(ok); row.appendChild(cancel);
    box.appendChild(row);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
}
