// 背景音乐播放器模块
class BackgroundMusicPlayer {
    constructor() {
        this.audio = null;
        this.playlist = [];
        this.currentIndex = 0;
        this.volume = 0.5;
        this.isPlaying = false;
        this.isMuted = false;
        this.loopMode = 'all'; // 'all' (全部循环), 'single' (单曲循环), 'none' (不循环)
        this.autoPlay = true;
        this.initialized = false;
        this.synth = null;   // 内置合成环境音（music/ 下没有 mp3 时的兜底）
    }

    // 初始化播放器
    init() {
        if (this.initialized) return;
        
        this.audio = new Audio();
        this.audio.volume = this.volume;
        
        // 监听播放结束事件
        this.audio.addEventListener('ended', () => {
            this.onTrackEnded();
        });

        // 监听播放错误事件。
        // static/music/ 目录在仓库里并不存在，6 条预设路径全是 404 —— 原实现只是
        // console.error 后静默 playNext()，轮完一圈就无声无息地停下，玩家完全不知道
        // 发生了什么。这里统计失败音轨：整轮都失败就明确报出来并停止重试。
        this.audio.addEventListener('error', () => {
            if (!this.failedTracks) this.failedTracks = new Set();
            this.failedTracks.add(this.currentIndex);
            if (this.failedTracks.size >= this.playlist.length) {
                this.reportAllTracksMissing();
                return;
            }
            this.playNext();
        });

        this.initialized = true;
    }

    // 设置播放列表
    setPlaylist(musicFiles) {
        this.playlist = musicFiles;
        this.currentIndex = 0;
        this.failedTracks = new Set();
    }

    // 整轮音轨都加载不出来：改为播放**内置合成环境音**（不再只是报个错就没了）。
    // 与 sfx.js 同一思路：用 Web Audio 现场合成，仓库里不需要任何 mp3。
    reportAllTracksMissing() {
        const started = this.autoPlay ? this.startSynthFallback() : false;
        this.isPlaying = started;
        const msg = started
            ? '内置合成环境音（未找到 static/music/ 下的 mp3，已自动切换）'
            : '未找到背景音乐文件（把 mp3 放进 static/music/ 并同步列表即可）';
        const trackEl = document.getElementById('current-track');
        if (trackEl) trackEl.textContent = msg;
        const statusEl = document.getElementById('music-status');
        if (statusEl) statusEl.textContent = msg;
        console.warn('[BGM] ' + msg);
    }

    // 合成环境音：三个低频正弦叠一层极慢的 LFO 扫低通，当成"不刺耳的背景垫音"
    startSynthFallback() {
        if (this.synth) return true;
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return false;
        try {
            const ctx = new AC();
            const master = ctx.createGain();
            master.gain.value = this.isMuted ? 0 : this.volume * 0.2;
            master.connect(ctx.destination);

            const filter = ctx.createBiquadFilter();
            filter.type = 'lowpass';
            filter.frequency.value = 800;
            filter.connect(master);

            const oscs = [110, 164.81, 220].map((freq, i) => {
                const osc = ctx.createOscillator();
                osc.type = i === 2 ? 'triangle' : 'sine';
                osc.frequency.value = freq;
                const g = ctx.createGain();
                g.gain.value = 0.3;
                osc.connect(g);
                g.connect(filter);
                osc.start();
                return osc;
            });

            const lfo = ctx.createOscillator();
            lfo.frequency.value = 0.06;
            const lfoGain = ctx.createGain();
            lfoGain.gain.value = 200;
            lfo.connect(lfoGain);
            lfoGain.connect(filter.frequency);
            lfo.start();

            this.synth = { ctx: ctx, master: master, filter: filter, oscs: oscs, lfo: lfo };
            // 浏览器自动播放策略：没有用户手势时上下文是 suspended，等第一次交互再恢复
            if (ctx.state === 'suspended' && ctx.resume) {
                try { ctx.resume(); } catch (e) { /* 等手势 */ }
            }
            ['pointerdown', 'keydown'].forEach((evt) => {
                window.addEventListener(evt, () => {
                    if (this.synth && this.synth.ctx.state === 'suspended' && this.synth.ctx.resume) {
                        try { this.synth.ctx.resume(); } catch (e) { /* ignore */ }
                    }
                }, { once: true });
            });
            return true;
        } catch (e) {
            console.warn('[BGM] 合成环境音启动失败:', e);
            this.synth = null;
            return false;
        }
    }

    stopSynthFallback() {
        if (!this.synth) return;
        try {
            this.synth.oscs.forEach((o) => o.stop());
            this.synth.lfo.stop();
            this.synth.ctx.close();
        } catch (e) { /* ignore */ }
        this.synth = null;
    }

    isSynthActive() {
        return !!this.synth;
    }

    // 音量/静音同步到合成音（环境音整体压低到 20%）
    applySynthVolume() {
        if (this.synth) {
            this.synth.master.gain.value = this.isMuted ? 0 : this.volume * 0.2;
        }
    }

    // 播放指定索引的歌曲
    playTrack(index) {
        if (index < 0 || index >= this.playlist.length) {
            console.error('无效的音乐索引:', index);
            return;
        }
        if (!this.failedTracks) this.failedTracks = new Set();

        this.currentIndex = index;
        const musicFile = this.playlist[index];
        
        if (this.audio) {
            this.audio.src = musicFile;
            this.audio.load();
            
            // 尝试播放
            const playPromise = this.audio.play();
            if (playPromise !== undefined) {
                playPromise.then(() => {
                    this.isPlaying = true;
                    console.log('正在播放:', musicFile);
                }).catch(error => {
                    // 已经切到合成环境音了：不能因为这条音轨的失败把播放状态覆盖回"未播放"
                    if (this.synth) { this.isPlaying = true; return; }
                    // 自动播放策略拦截（页面还没被交互过）是预期情况，不该刷一屏红字
                    if (error && error.name === 'NotAllowedError') {
                        console.debug('背景音乐自动播放被浏览器拦截，等待用户交互');
                        return;
                    }
                    console.error('播放失败:', error);
                    this.isPlaying = false;
                });
            }
        }
    }

    // 播放当前歌曲
    play() {
        if (this.synth) {
            const c = this.synth.ctx;
            if (c.state === 'suspended' && c.resume) {
                try { c.resume(); } catch (e) { /* ignore */ }
            }
            this.isPlaying = true;
            return;
        }
        if (!this.audio || this.playlist.length === 0) return;

        if (!this.audio.src) {
            this.playTrack(this.currentIndex);
        } else {
            const playPromise = this.audio.play();
            if (playPromise !== undefined) {
                playPromise.then(() => {
                    this.isPlaying = true;
                }).catch(error => {
                    if (this.synth) { this.isPlaying = true; return; }
                    if (error && error.name === 'NotAllowedError') {
                        console.debug('背景音乐自动播放被浏览器拦截，等待用户交互');
                        return;
                    }
                    console.error('播放失败:', error);
                });
            }
        }
    }

    // 暂停播放
    pause() {
        if (this.synth) {
            const c = this.synth.ctx;
            if (c.state === 'running' && c.suspend) {
                try { c.suspend(); } catch (e) { /* ignore */ }
            }
            this.isPlaying = false;
            return;
        }
        if (this.audio) {
            this.audio.pause();
            this.isPlaying = false;
        }
    }

    // 切换播放/暂停
    togglePlay() {
        if (this.isPlaying) {
            this.pause();
        } else {
            this.play();
        }
    }

    // 播放下一首
    playNext() {
        if (this.synth) return;      // 内置合成音没有"下一首"
        if (this.playlist.length === 0) return;

        if (this.loopMode === 'single') {
            this.playTrack(this.currentIndex);
        } else if (this.loopMode === 'all') {
            this.currentIndex = (this.currentIndex + 1) % this.playlist.length;
            this.playTrack(this.currentIndex);
        } else {
            if (this.currentIndex < this.playlist.length - 1) {
                this.currentIndex++;
                this.playTrack(this.currentIndex);
            } else {
                this.pause();
            }
        }
    }

    // 播放上一首
    playPrevious() {
        if (this.synth) return;
        if (this.playlist.length === 0) return;

        if (this.loopMode === 'single') {
            this.playTrack(this.currentIndex);
        } else {
            this.currentIndex = (this.currentIndex - 1 + this.playlist.length) % this.playlist.length;
            this.playTrack(this.currentIndex);
        }
    }

    // 歌曲播放结束时的处理
    onTrackEnded() {
        if (this.autoPlay) {
            this.playNext();
        } else {
            this.isPlaying = false;
        }
    }

    // 设置音量 (0-1)
    setVolume(volume) {
        this.volume = Math.max(0, Math.min(1, volume));
        if (this.audio) {
            this.audio.volume = this.volume;
        }
        this.applySynthVolume();
    }

    // 增加音量
    increaseVolume(amount = 0.1) {
        this.setVolume(this.volume + amount);
    }

    // 减少音量
    decreaseVolume(amount = 0.1) {
        this.setVolume(this.volume - amount);
    }

    // 静音/取消静音
    toggleMute() {
        this.isMuted = !this.isMuted;
        if (this.audio) {
            this.audio.muted = this.isMuted;
        }
        this.applySynthVolume();
    }

    // 设置循环模式
    setLoopMode(mode) {
        if (['all', 'single', 'none'].includes(mode)) {
            this.loopMode = mode;
        }
    }

    // 获取当前播放状态
    getStatus() {
        return {
            isPlaying: this.isPlaying,
            isMuted: this.isMuted,
            volume: this.volume,
            currentIndex: this.currentIndex,
            currentTrack: this.playlist[this.currentIndex] || null,
            loopMode: this.loopMode,
            playlistLength: this.playlist.length,
            synthFallback: !!this.synth
        };
    }

    // 销毁播放器
    destroy() {
        this.stopSynthFallback();
        if (this.audio) {
            this.audio.pause();
            this.audio.src = '';
            this.audio = null;
        }
        this.playlist = [];
        this.isPlaying = false;
        this.initialized = false;
    }
}

// 创建全局音乐播放器实例
window.bgMusicPlayer = new BackgroundMusicPlayer();

// 预设的背景音乐列表（根据实际文件名修改）
const backgroundMusicList = [
    '/static/music/Rapeter - NOT GOOD [music].mp3',
    '/static/music/滑雪大冒险.mp3',
    '/static/music/Zenia - seven.mp3',
    '/static/music/Nora En Pure - Lake Arrowhead (Radio Mix).mp3',
    '/static/music/Марув - Drunk Groove.mp3',
    '/static/music/Rapeter - 主场Pt.2.mp3'
];

// 初始化背景音乐
function initBackgroundMusic() {
    window.bgMusicPlayer.init();
    window.bgMusicPlayer.setPlaylist(backgroundMusicList);
    
    // 从本地存储恢复音量设置
    const savedVolume = localStorage.getItem('bgm_volume');
    if (savedVolume !== null) {
        window.bgMusicPlayer.setVolume(parseFloat(savedVolume));
    }
    
    // 从本地存储恢复静音状态
    const savedMuted = localStorage.getItem('bgm_muted');
    if (savedMuted !== null) {
        window.bgMusicPlayer.isMuted = savedMuted === 'true';
        if (window.bgMusicPlayer.audio) {
            window.bgMusicPlayer.audio.muted = window.bgMusicPlayer.isMuted;
        }
        window.bgMusicPlayer.applySynthVolume();
    }
    
    // 从本地存储恢复循环模式
    const savedLoopMode = localStorage.getItem('bgm_loop_mode');
    if (savedLoopMode !== null) {
        window.bgMusicPlayer.setLoopMode(savedLoopMode);
    }
    
    console.log('背景音乐播放器初始化完成');
}

// 开始播放背景音乐
function startBackgroundMusic() {
    if (window.bgMusicPlayer && !window.bgMusicPlayer.isPlaying) {
        window.bgMusicPlayer.play();
    }
}

// 停止背景音乐
function stopBackgroundMusic() {
    if (window.bgMusicPlayer) {
        window.bgMusicPlayer.pause();
    }
}

// 页面加载完成后初始化背景音乐
document.addEventListener('DOMContentLoaded', () => {
    initBackgroundMusic();
});