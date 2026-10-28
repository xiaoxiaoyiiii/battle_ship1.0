# 卡牌与胜负音效

2026-10-28 接入并更新已验收精修。23 枚成品均为 48 kHz、双声道、16-bit PCM WAV，合计约 7.11 MB。轰炸、加百列之光、恶魔契约保留用户验收的第三版原文件；七枚后续精修逐字节采用验收样板。原始采样、渲染工具、制作脚本和测试证据均在仓外。

## 设计与映射

家族内共享声音，以实际牌意区分强弱；增益采用装甲铆合，保护与治疗保留神圣人声，邪恶魔法采用低声部仪式，伤害保留实体爆裂和低频落点。完整牌名映射以 [cardSounds.ts](./cardSounds.ts) 为准，素材与相对增益以 [samples.ts](./samples.ts) 为准。

| 素材 | 秒 | 代表卡牌或事件 |
|---|---:|---|
| `bombardment.wav` | 2.65 | 轰炸 |
| `gabriel.wav` | 3.15 | 加百列之光、神之宣告、教皇旨意 |
| `dark_pact.wav` | 2.85 | 恶魔契约、禁忌果实、饮血 |
| `freeze.wav` | 1.08 | 冻结：冰岩封固 |
| `divine_banish.wav` | 2.16 | 神威！的空间转移 |
| `resurrect.wav` | 2.48 | 死者苏生、绝处逢生、灵气复苏 |
| `heal.wav` | 2.02 | 疗愈、伊甸园 |
| `holy_shield.wav` | 1.48 | 仁王之盾、无暇圣心、卧薪尝胆 |
| `steel_buff.wav` | 1.12 | 百亿补贴、钢筋铁骨、守株待兔 |
| `recon.wav` | 1.03 | 探测雷达、克苏鲁之眼 |
| `summon.wav` | 1.77 | 增援、神机妙算、滥竽充数 |
| `card_transfer.wav` | 0.76 | 盗亦有道、桃园结义、亡羊补牢 |
| `draw.wav` | 0.27 | 实际摸牌 |
| `discard.wav` | 0.48 | 明智埋葬、兵粮寸断、摸牌直接弃置 |
| `time_warp.wav` | 2.78 | Freezing！、回光返照、败者食尘、极限增援 |
| `dice.wav` | 1.04 | 真实掷骰事件 |
| `fire.wav` | 1.77 | 硫磺火焰：爆燃横扫 |
| `splash.wav` | 0.90 | 溅射：冲击扩散 |
| `negate.wav` | 0.65 | 失灵！：截断掐灭 |
| `seal.wav` | 1.15 | 看破！：识破封锁 |
| `electric.wav` | 1.07 | 雷达子弹 |
| `victory.wav` | 2.32 | 胜利 |
| `defeat.wav` | 2.03 | 失败 |

Freezing！是跳过回合，极限增援是延迟判胜，均使用时间家族；神威！可以合法除外空区域，因此使用空间撕裂而非击沉声。纸牌、冰裂、火焰与掷骰为采样材质重组和合成设计，不标作这些动作的现场录音。

## 来源与许可

### GeneralUser GS v2.0.3

作者 S. Christian Collins，[上游仓库](https://github.com/mrbumpy409/GeneralUser-GS)、[作者官网](https://www.schristiancollins.com/)。本目录保存原样 [GeneralUser-LICENSE.txt](./GeneralUser-LICENSE.txt)。

该库不是 CC0。作者许可个人或商业音乐制作和软件使用，并保留对部分早期采样最初出处无法百分之百追溯的说明；应一并保留该原文。使用音色包括弦乐、Choir Aahs、Voice Oohs、French Horn、Brass Section、Flute、Woodblock。人声是采样乐器渲染，没有本轮真人录制的咒语或可辨歌词。

原音色库 SHA256：`9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe`。

使用 [FluidSynth 2.6.1](https://github.com/FluidSynth/fluidsynth/releases/tag/v2.6.1) 在仓外渲染，无工具二进制或音色库随游戏分发。

### CC0 实体材质

以下来源沿用第三版样板保存的下载及许可记录，页面标注 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)。本次未重新下载，未使用商业音效库试听音轨。

| 作者 | 作品与原始页面 | 使用材质 |
|---|---|---|
| Iwan Gabovitch / qubodup | [Tiny Naval Battle Sounds Set](https://opengameart.org/content/tiny-naval-battle-sounds-set) | ExplosionMetal、Splash、BattleShipMovementAmbient |
| Spring Spring | [Mechanical Explosion](https://opengameart.org/content/mechanical-explosion) | 机械爆裂、装甲起音与颗粒 |
| Peludo | [Water Splash and sand footsteps](https://opengameart.org/content/water-splash-and-sand-footsteps) | splash1 的水体、气流和摩擦微纹理 |

Peludo 另请求引用其 itch.io 项目，保留 [RNAn](https://rnan.itch.io/) 链接。Naval 使用修正后的 version 2，其 README 说明旧 version 1 的 ExplosionMetal 来源存在问题；version 2 替换为 [qubodup 的录音 67474](https://freesound.org/people/qubodup/sounds/67474/)，本项目未使用 version 1。

### 后续已验收的七枚精修

空间转移与时间回卷以用户提供的 `10月28日.mp3` 为主体，剪辑、变速和重组后形成两枚已验收成品。参考音频由用户提供，原始作品来源及授权信息未另外确认；原 MP3 未加入仓库。原件 SHA256 为 `d20f8c4f5817c4ac763ad5129aea3c9aad84204a4a220fd39915f10f4c250a6b`。

冻结、硫磺火焰、溅射、失灵！、看破！分别使用独立成品，新增 CC0 原料：

- Julie Damsgaard / Spring Spring / Spring Enterprises：[Various sound effects](https://opengameart.org/content/various-sound-effects-0)，石块破裂与撞击。
- bart：[Steam release sounds](https://opengameart.org/content/steam-release-sounds)，喷气材质；作者欢迎署名。
- AntumDeluge：[Fire crackling](https://opengameart.org/content/fire-crackling/)，壁炉火焰爆裂纹理。

上述原料页面没有逐枚明确现场录制方法，因此不全部标为现场实录；没有使用干冰专门录音。制作应用材质剪辑、变速、局部并行饱和、声像运动与短反射，未从商业演示或视频截取声音。

本地制作与验收记录保存在仓外 `battle-ship-sfx-rewind-revision-20261028` 和 `battle-ship-sfx-polish-audition-20261028`，包括原料许可、哈希与独立验证。游戏仅包含用户验收的七枚成品，不包含原料、脚本或测试。

## 触发与验证

- 服务端在真实执行效果后发出公开 `magic_sfx`，只有房间、施法者、牌名和去重编号，不包含手牌或目标坐标。普通结算音在单张卡面离场后播放。
- 选船、选牌、部署、重摆等待完成；失败、被无效、退款、打开待选窗口及零部署取消不播放完成音。AI 的同步确认使用相同原则。
- 摸牌使用真实 `card_drawn`，不以手牌张数增加推断；掷骰以 `dice_rolled` 触发。胜负页每局只播放一次对应结果。
- 音量总线即时控制短音效，静音停止当前声音；BGM 独立。未解锁、未解码或离开对局时跳过，不在之后补播旧事件。减少动态效果不关闭声音。
- 数值复验覆盖文件格式、时长、峰值、端点、无满幅样本和无重复哈希；七枚精修与验收原件逐字节一致。主观听感已由用户试听验收；制作工具的数值检查和原生解码检查仅负责文件质量。

验收脚本与输出位于仓外 `battle-ship-sfx-implementation-20261028`，不随仓库提交。类型检查、生产构建、真实服务确认路径和双客户端播放验证见本批实施计划。
