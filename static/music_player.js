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

        // 监听播放错误事件
        this.audio.addEventListener('error', (e) => {
            console.error('音乐播放错误:', e);
            this.playNext();
        });

        this.initialized = true;
    }

    // 设置播放列表
    setPlaylist(musicFiles) {
        this.playlist = musicFiles;
        this.currentIndex = 0;
    }

    // 播放指定索引的歌曲
    playTrack(index) {
        if (index < 0 || index >= this.playlist.length) {
            console.error('无效的音乐索引:', index);
            return;
        }

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
                    console.error('播放失败:', error);
                    this.isPlaying = false;
                });
            }
        }
    }

    // 播放当前歌曲
    play() {
        if (!this.audio || this.playlist.length === 0) return;
        
        if (!this.audio.src) {
            this.playTrack(this.currentIndex);
        } else {
            const playPromise = this.audio.play();
            if (playPromise !== undefined) {
                playPromise.then(() => {
                    this.isPlaying = true;
                }).catch(error => {
                    console.error('播放失败:', error);
                });
            }
        }
    }

    // 暂停播放
    pause() {
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
            playlistLength: this.playlist.length
        };
    }

    // 销毁播放器
    destroy() {
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