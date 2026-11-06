import pygame
import sys
import os
from pathlib import Path
from PIL import Image, ImageSequence

# Pygameの初期化
pygame.init()
pygame.mixer.init()
pygame.mixer.set_num_channels(8)
# チャンネル0を叩きつけ音などの重要効果音専用に予約。
# BGM(mixer.music)は別チャンネルなので影響なく、他の効果音と被って叩きつけ音が消えるのを防ぐ。
pygame.mixer.set_reserved(1)

# 画面設定
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
CEILING_Y = 0
MID_BOSS_CEILING_Y = 0
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN)


def load_sprite(file_path, size, fallback_color=(180, 180, 180), outline_color=(0, 0, 0), rotate=0):
    path = Path(file_path)
    if path.exists():
        try:
            image = pygame.image.load(str(path)).convert_alpha()
            # 読み込み時に原寸のまま回転させてから縮小する（縮小後の回転は画質が落ちるため）
            if rotate:
                image = pygame.transform.rotate(image, rotate)
            return pygame.transform.scale(image, size)
        except (pygame.error, OSError):
            print(f"画像読み込みに失敗しました: {path}")

    print(f"画像が見つかりません: {path}。プレースホルダーを使用します。")
    surface = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(surface, fallback_color, (0, 0, size[0], size[1]), border_radius=max(6, min(size) // 10))
    pygame.draw.rect(surface, outline_color, (0, 0, size[0], size[1]), 2, border_radius=max(6, min(size) // 10))
    return surface


def remove_white_background(rgba, threshold=90):
    """白背景を透明にしたRGBA画像を返す

    単純な閾値判定で切ると、衣装の白い部分まで消してしまうため、
    「画像の外周につながっている白」だけを背景として扱う。
    輪郭の内側に回り込んだ白い部分は絵の一部なので、そのまま残す。
    """
    pixels = rgba.load()
    width, height = rgba.size

    is_white = bytearray(width * height)
    for y in range(height):
        row = y * width
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if abs(r - 255) + abs(g - 255) + abs(b - 255) <= threshold:
                is_white[row + x] = 1

    # 外周の白から塗りつぶして、背景と繋がっている白だけを探す
    background = bytearray(width * height)
    stack = []

    def mark(index):
        if is_white[index] and not background[index]:
            background[index] = 1
            stack.append(index)

    for x in range(width):
        mark(x)
        mark((height - 1) * width + x)
    for y in range(height):
        mark(y * width)
        mark(y * width + width - 1)

    while stack:
        index = stack.pop()
        x = index % width
        y = index // width
        if x > 0:
            mark(index - 1)
        if x < width - 1:
            mark(index + 1)
        if y > 0:
            mark(index - width)
        if y < height - 1:
            mark(index + width)

    for y in range(height):
        row = y * width
        for x in range(width):
            if background[row + x]:
                pixels[x, y] = (255, 255, 255, 0)
    return rgba


def load_animated_gif_frames(path, size, cut_background=False, with_durations=False):
    """GIFをフレーム列にして返す

    cut_background=True にすると、白背景を透明にしてから使う。
    既に透過背景のGIFや、絵の一部に白を配色している素材には向きえないため
    既定は False にして、既存の呼び出しの挙動を変えない。

    with_durations=True にすると (フレーム列, 各コマの表示時間ms) のタプルを返す。
    コマの時間を指定どおりに再生するために使う。
    """
    gif_path = Path(path)
    frames = []
    durations = []
    if not gif_path.exists():
        return (frames, durations) if with_durations else frames

    try:
        with Image.open(gif_path) as img:
            for frame in ImageSequence.Iterator(img):
                rgba = frame.convert("RGBA")
                rgba = rgba.resize(size, Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
                if cut_background:
                    rgba = remove_white_background(rgba)
                else:
                    pixels = rgba.load()
                    width, height = rgba.size
                    for y in range(height):
                        for x in range(width):
                            r, g, b, a = pixels[x, y]
                            if r > 245 and g > 245 and b > 245:
                                pixels[x, y] = (255, 255, 255, 0)
                surface = pygame.image.frombuffer(rgba.tobytes(), rgba.size, "RGBA")
                frames.append(surface)
                durations.append(int(frame.info.get("duration") or 100))
    except Exception as exc:
        print(f"GIF読み込みに失敗しました: {gif_path} ({exc})")
        return ([], []) if with_durations else []

    if not frames:
        return ([], []) if with_durations else []
    return (frames, durations) if with_durations else frames


def align_frames_bottom_center(frames, margin=6):
    """GIFの各フレームを「下端中央がそろった1枚のキャンバス」に焼き込んで返す

    GIFの各ポーズは切り取られた位置と大きさが少しずつ違い（頭上の光球の有無で
    高さも変わる）ため、そのまま描くとボスがコマごとに上下左右に揺れて見える。
    全フレームの外接矩形の「下端中央」を基準に揃えることで、ポーズが変わっても
    ボスの立ち位置は動かない。

    戻り値は (揃えたフレーム列, 基準点のキャンバス内座標) のタプル。
    基準点は左右反転しても変わらないよう、キャンバスの中央に取る。
    """
    if not frames:
        return [], None

    union = None
    for frame in frames:
        bounds = get_opaque_bounds(frame)
        if bounds.width <= 0 or bounds.height <= 0:
            continue
        union = bounds.copy() if union is None else union.union(bounds)
    if union is None:
        return [], None

    # 左右反転で基準点がずれないよう、キャンバスの幅は偶数にしておく
    canvas_width = union.width + margin * 2
    if canvas_width % 2:
        canvas_width += 1
    canvas_height = union.height + margin * 2
    anchor_x = canvas_width // 2
    anchor_y = canvas_height - margin

    aligned = []
    for frame in frames:
        bounds = get_opaque_bounds(frame)
        if bounds.width <= 0 or bounds.height <= 0:
            aligned.append(frame)
            continue
        canvas = pygame.Surface((canvas_width, canvas_height), pygame.SRCALPHA)
        canvas.blit(frame, (anchor_x - bounds.centerx, anchor_y - bounds.bottom))
        aligned.append(canvas)
    return aligned, (anchor_x, anchor_y)


def get_opaque_bounds(surface, alpha_threshold=8):
    """スプライトの不透明ピクセルが占める範囲をRectで返す。

    当たり判定を見た目と一致させるために使う。画像端の透明な余白を判定に含めないようにし、
    スプライトが全面透明だった場合のみ画像全体の大きさにフォールバックする。
    """
    bounds = surface.get_bounding_rect(alpha_threshold)
    if bounds.width <= 0 or bounds.height <= 0:
        return pygame.Rect(0, 0, surface.get_width(), surface.get_height())
    return bounds


def union_opaque_bounds(surfaces):
    """複数のスプライトの不透明範囲をまとめた外接Rectを返す（すべて透明ならNone）"""
    union = None
    for surface in surfaces:
        bounds = get_opaque_bounds(surface)
        if bounds.width <= 0 or bounds.height <= 0:
            continue
        union = bounds.copy() if union is None else union.union(bounds)
    return union


def load_sprite_fit_height(file_path, target_height, fallback_color=(180, 180, 180), outline_color=(0, 0, 0)):
    """アスペクト比を保ったまま「不透明部分の高さ」が target_height になるよう読み込む。

    戻り値は (surface, bounds)。bounds は不透明ピクセルの範囲。
    横長の素材（例: 叩きつけのポーズ）を 200x200 に無理やり潰さず、
    立ち絵と同じ背丈に揃えるために使う。
    """
    path = Path(file_path)
    if path.exists():
        try:
            image = pygame.image.load(str(path)).convert_alpha()
            bounds = get_opaque_bounds(image)
            if bounds.height > 0:
                scale = target_height / bounds.height
                new_size = (
                    max(1, round(image.get_width() * scale)),
                    max(1, round(image.get_height() * scale)),
                )
                image = pygame.transform.smoothscale(image, new_size)
            return image, get_opaque_bounds(image)
        except (pygame.error, OSError):
            print(f"画像読み込みに失敗しました: {path}")

    print(f"画像が見つかりません: {path}。プレースホルダーを使用します。")
    surface = load_sprite(file_path, (max(1, round(target_height)), max(1, round(target_height))), fallback_color, outline_color)
    return surface, get_opaque_bounds(surface)


asset_dir = Path(__file__).resolve().parent
fallback_asset = asset_dir / "m (2)-animated.gif"
player_asset_candidates = [
    asset_dir / "nagatanoshio" / "rufi.png",
    fallback_asset,
    asset_dir / "斬.png"
]

player_image = None
for asset_path in player_asset_candidates:
    if asset_path.exists():
        player_image = load_sprite(asset_path, (40, 73), fallback_color=(120, 170, 255), outline_color=(30, 30, 80))
        break
if player_image is None:
    player_image = load_sprite("", (40, 73), fallback_color=(120, 170, 255), outline_color=(30, 30, 80))

PLAYER_GIF_SIZE = (120, 120)
# 攻撃アニメーションGIFはplayer枠の中で小さく見えるため、通常時の見え方に合わせて描画サイズを少し大きくする
ATTACK_GIF_SIZE = (160, 160)



idle_sprite_path = asset_dir / "主人公立ち絵.png"
idle_sprite = None
if idle_sprite_path.exists():
    # 主人公の立ち絵（静止画）。歩行GIFの1コマではなく、専用の立ち絵を平常時の姿として使う。
    # 512x512のキャンバスなので、歩行GIFと同じPLAYER_GIF_SIZE(120x120)に縮小して足元基準で描画する。
    idle_sprite = load_sprite(idle_sprite_path, PLAYER_GIF_SIZE)

attack_sprite_path = asset_dir / "新攻撃.gif"
attack_frames = load_animated_gif_frames(attack_sprite_path, ATTACK_GIF_SIZE)

# 回避アニメーションGIF (白背景はローダー既定の白抜き処理で透過される。
# キャンバス下端が足元なので歩行と同じPLAYER_GIFサイズで地面に揃う)
# 新ダッシュ.gifを使う(無い場合のみ回避.gifに切り替える)
_evade_asset = asset_dir / "新ダッシュ.gif"
if not _evade_asset.exists():
    _evade_asset = asset_dir / "回避.gif"
evade_frames = load_animated_gif_frames(_evade_asset, PLAYER_GIF_SIZE)

hidden_boss_asset_candidates = [
    asset_dir / "タマミツネ.png",
    asset_dir / "nagatanoshio" / "pe.png",
    asset_dir / "斬.png",
    fallback_asset,
]
hidden_boss_image = None
hidden_boss_idle_frames = []
hidden_boss_idle_durations = []
for asset_path in hidden_boss_asset_candidates:
    if not asset_path.exists():
        continue
    if asset_path.suffix.lower() == ".gif":
        # GIF素材（白背景アニメーション）を使う場合は、白を透明にしてから240x240に読み込む。
        # 背景が白のままだと絵のまわりに白い四角が出るため flood-fill で抜く。
        # ※通常時は タマミツネ.png（静止画）を使用しているため、現在はここには入らない。
        gif_frames, gif_durations = load_animated_gif_frames(
            asset_path, (240, 240), cut_background=True, with_durations=True
        )
        if gif_frames:
            hidden_boss_idle_frames = gif_frames
            hidden_boss_idle_durations = gif_durations
            hidden_boss_image = gif_frames[0]
            break
    else:
        hidden_boss_image = load_sprite(asset_path, (240, 240), fallback_color=(120, 0, 160), outline_color=(50, 10, 60))
        break
if hidden_boss_image is None:
    hidden_boss_image = load_sprite("", (240, 240), fallback_color=(120, 0, 160), outline_color=(50, 10, 60))

# 待機アニメーション素材（富裕.gif）を使う場合に備えて、コマの下端中央を揃え、
# 攻撃ポーズと同じく描画位置の計算式を共有できるようにしておく。
# 現在の通常時は タマミツネ.png（静止画）なので hidden_boss_idle_frames は空で、アニメは再生されない。
hidden_boss_idle_frames, HIDDEN_BOSS_IDLE_ANCHOR = align_frames_bottom_center(
    hidden_boss_idle_frames
)
# 1コマあたりの表示フレーム数（ゲームループは60fps固定なのでmsをフレーム数に換算する）。
# GIFの指定時間にできるだけ忠実な長さにするため、端数は四捨五入で丸め、
# 表示時間が極端に短いコマでも最低1フレームは必ず残す。
HIDDEN_BOSS_IDLE_FRAME_FRAMES = [
    max(1, round(duration / 1000 * 60)) for duration in hidden_boss_idle_durations
]
# 1周するまでのフレーム数（アニメーションをループさせるのに使う）
HIDDEN_BOSS_IDLE_CYCLE_FRAMES = sum(HIDDEN_BOSS_IDLE_FRAME_FRAMES) or 1

# 攻撃ポーズも読み込んでから、判定に使う箱を「全コマの外接矩形」で確定させる。
# こうしないと待機アニメーションや攻撃ポーズのコマごとに当たり判定が揺れてしまい、
# 見た目と判定がずれる（見た目より当たり判定が広すぎたり狭すぎたりする）。
HIDDEN_BOSS_ATTACK_GIF_SIZE = (240, 240)
# GIFのどのコマがどの動きに対応するか（下の表で参照するコマ番号）
#   0: 通常（腕を広げた立ち姿）
#   1: 構え（腕を引き寄せ、力を集中するポーズ）
#   2: チャージ（頭上に小さな光の玉が現れる）
#   3: チャージ（玉が大きくなり、身体に光が走る）
#   4: 発射（頭上から縦のエネルギーが伸びる）
hidden_boss_attack_frames_raw = load_animated_gif_frames(
    asset_dir / "ビーム動き.gif",
    HIDDEN_BOSS_ATTACK_GIF_SIZE,
    cut_background=True,
)
# コマごとに位置と大きさが違うとボスが揺れて見えるので、下端中央を揃えてから使う
hidden_boss_attack_frames, HIDDEN_BOSS_ATTACK_ANCHOR = align_frames_bottom_center(
    hidden_boss_attack_frames_raw
)

# 上級ボスはスプライトの不透明部分そのものを当たり判定にするため、
# 描画オフセットと「見た目の幅・高さ」をここで1箇所にまとめる。
# 描画と判定の両方がこの定数を使うことで、見た目と当たり判定がずれるのを防ぐ。
HIDDEN_BOSS_DRAW_OFFSET_Y = 128
# 通常時のスプライト（タマミツネ.png）と、待機アニメ・攻撃ポーズの全コマをまとめて外接矩形を取る。
# これにより、どのコマを表示していても当たり判定は動かず、
# 「見た目（描画）」と「当たり判定」が常に一致した状態を保てる。
HIDDEN_BOSS_ALL_FRAMES = (
    [hidden_boss_image]
    + list(hidden_boss_idle_frames)
    + list(hidden_boss_attack_frames)
)
HIDDEN_BOSS_BOX = (
    union_opaque_bounds(HIDDEN_BOSS_ALL_FRAMES)
    or get_opaque_bounds(hidden_boss_image)
)
# 左右反転時にflipする分だけ左オフセットを反転させる（幅は変わらない）
HIDDEN_BOSS_BOX_FLIPPED = HIDDEN_BOSS_BOX.copy()
HIDDEN_BOSS_BOX_FLIPPED.x = hidden_boss_image.get_width() - HIDDEN_BOSS_BOX.right

# 攻撃フェーズごとのポーズ変化（このフレーム数以上になったらGIFのコマ番号に変える）の並び。
# 「実際に攻撃が当たるフレーム」とポーズがずれないように、
# 判定が発生するフレームで発射ポーズに切り替わるように組んでいる。
HIDDEN_BOSS_ATTACK_POSES = {
    # 収縮レーザー: 45フレームかけて左右のレーザー境界が内側に縮むので、
    # 前半はチャージし、左右が閉じる45フレーム目に発射ポーズへ切り替える
    "SHRINK_LASER": ((0, 0), (8, 1), (18, 2), (32, 3), (45, 4)),
    # 近接攻撃: 40フレームの予兆をチャージしてから、衝撃波を撃つ
    "MELEE": ((0, 0), (10, 1), (24, 2), (34, 3), (40, 4)),
    # 大ビーム: 90フレームの予測線のあいだ長くチャージし、90フレーム目に発射
    "TRIPLE_COLUMN": ((0, 0), (14, 1), (34, 2), (56, 3), (72, 2), (90, 4)),
    # Overdrive前の演出: 90フレームかけて溜め、終盤のコマで溜め切りを見せる
    "OVERDRIVE_INTRO": ((0, 0), (12, 1), (36, 2), (62, 3), (82, 4)),
}

# ビーム系攻撃の「効果音を鳴らすタイミング」は、当たり判定が有効になる
# 0.9秒前（clock.tick(60) なので54フレーム）に固定する。
# ゲームループは60fps固定なので、phase_timerはそのままフレーム数として数えられる。
BEAM_SOUND_LEAD_FRAMES = 54
# ビーム攻撃ごとに「phase_timer が何フレーム目のときに当たり判定が発生するか」。
# phase_timer が 0 になったフレームを1フレーム目として数える（既存の判定と同じ数え方）。
# 実際にビームが描画され始めるフレームと一致させている。
BEAM_PHASE_HIT_FRAMES = {
    "LASER": (42,),
    "CROSS_LASER": (42, 76),
    "SHRINK_LASER": (45,),
    "ALTERNATE_LASER": (40, 64, 88, 112),
}

# 「画面の三分の一」を覆う大ビーム(TRIPLE_COLUMN)は、たまに3連続する。
# 連続するかどうかは攻撃の開始時にランダムで決める（3連続する確率）。
TRIPLE_COLUMN_CHAIN_CHANCE = 0.35
TRIPLE_COLUMN_CHAIN_LENGTH = 3
# 上級ボスが最終段階(Overdrive)に入るとき、いきなり撃ち始めず先に前演出を流す。
# 溜めの時間そのものが「大技が来るよ」という予告になり、プレイヤーが躲ける
# 余裕を与える。長さはビーム砲チャージ音(BEAM_WARNING_SECONDS = 1.5秒)に合わせる。
OVERDRIVE_INTRO_FRAMES = 90        # 演出全体の長さ（1.5秒）
OVERDRIVE_INTRO_FLASH_FRAMES = 8   # 溜め切りの瞬間の白フラッシュの長さ

# Overdrive前演出の文字。毎フレーム生成するのは重いのでサイズ単位で使い回す
overdrive_intro_fonts = {}


def get_overdrive_intro_font(size):
    """Overdrive前演出で表示する文字のフォント（初回だけ生成してキャッシュする）"""
    font = overdrive_intro_fonts.get(size)
    if font is None:
        font = pygame.font.SysFont("msgothic", size, bold=True)
        overdrive_intro_fonts[size] = font
    return font


boss_image = load_sprite(
    asset_dir / "唐笠.png",
    (136, 136),
    fallback_color=(100, 0, 0),
    outline_color=(255, 215, 0)
)
boss_image_bounds = get_opaque_bounds(boss_image)
# 唐笠お化け(初級ボス)のジャンプ攻撃アニメ(唐笠新ジャンプ.gif)。
# 立ち絵(唐笠.png)の背丈に合わせてから読み込み、ジャンプ攻撃の間だけ再生する。
# 新素材が無い場合は従来の唐笠攻撃.gifを使う。
_kasa_jump_asset = asset_dir / "唐笠新ジャンプ.gif"
if not _kasa_jump_asset.exists():
    _kasa_jump_asset = asset_dir / "唐笠攻撃.gif"
boss_jump_gif_raw, boss_jump_gif_durations = load_animated_gif_frames(
    _kasa_jump_asset,
    (200, 200),
    with_durations=True,
)
_boss_jump_union = None
for _frame in boss_jump_gif_raw:
    _bounds = get_opaque_bounds(_frame)
    if _bounds.width <= 0 or _bounds.height <= 0:
        continue
    if _boss_jump_union is None:
        _boss_jump_union = pygame.Rect(_bounds)
    else:
        _boss_jump_union.union_ip(_bounds)
if boss_jump_gif_raw and _boss_jump_union is not None and _boss_jump_union.height > 0:
    _boss_jump_scale = boss_image_bounds.height / _boss_jump_union.height
    if abs(_boss_jump_scale - 1.0) > 1e-6:
        boss_jump_gif_raw = [
            pygame.transform.scale(
                _frame,
                (
                    max(1, round(_frame.get_width() * _boss_jump_scale)),
                    max(1, round(_frame.get_height() * _boss_jump_scale)),
                ),
            )
            for _frame in boss_jump_gif_raw
        ]
boss_jump_frames, BOSS_JUMP_ANCHOR = align_frames_bottom_center(boss_jump_gif_raw)
# 1コマあたりの表示フレーム数(60fps固定なのでmsをフレーム数に換算)
BOSS_JUMP_FRAME_FRAMES = [
    max(1, round(duration / 1000 * 60)) for duration in boss_jump_gif_durations
]
BOSS_JUMP_CYCLE_FRAMES = sum(BOSS_JUMP_FRAME_FRAMES) or 1
# ジャンプ攻撃アニメ全体の長さ(60fps換算)。滞空時間に合わせて1周するのに使う。
BOSS_JUMP_GIF_TOTAL_FRAMES = sum(BOSS_JUMP_FRAME_FRAMES)
# ジャンプの発射速度と重力(update内の physics と同じ値)。滞空フレーム数の見積もりに使う。
BOSS_JUMP_LAUNCH_VY = -13
BOSS_JUMP_GRAVITY = 0.8
# 唐笠お化けの突き上げ攻撃(下から傘を突き上げる)。
# 傘突き上げ.png(1024x1024、透明背景)を小さなサイズに縮め、
# ボス→プレイヤー方向の地面から、小さな波のように複数の傘を順に生やして突き上げる。
# 予告中は各波の出現位置を赤い小柱で点滅させる。
boss_upthrust_image = load_sprite(
    asset_dir / "傘突き上げ.png",
    (160, 160),
    fallback_color=(120, 0, 0),
)
boss_upthrust_bounds = get_opaque_bounds(boss_upthrust_image)
# タイムライン(60fps): 予告(溜め→出現位置の順次表示) → 発生(波が地面から順に生える)
BOSS_UPTHRUST_WINDUP_FRAMES = 80          # 予告全体(約1.3秒)。十分な準備時間で回避の猶予を作る
BOSS_UPTHRUST_MARKER_FIRST_FRAME = 24     # 予告何フレーム目から出現位置マーカーを出すか
BOSS_UPTHRUST_MARKER_STAGGER = 8          # マーカー表示の間隔(発射順と同順に表示)
# 地面から生える小さな傘の波。ボス→プレイヤー方向に等間隔で順に突き上げる。
BOSS_UPTHRUST_WAVE_COUNT = 5
BOSS_UPTHRUST_WAVE_SPACING_FRAMES = 6   # 波と波の発生間隔
BOSS_UPTHRUST_WAVE_RISE_FRAMES = 14     # 1本が下から伸び上がる時間
BOSS_UPTHRUST_WAVE_HOLD_FRAMES = 10     # 伸び上がった後どのくらい残すか
BOSS_UPTHRUST_WAVE_MAX_REACH = 420      # 波が届く最大距離
BOSS_UPTHRUST_WAVE_HIT_W = 60
BOSS_UPTHRUST_WAVE_HIT_H = 100
BOSS_UPTHRUST_TOTAL_FRAMES = (
    BOSS_UPTHRUST_WINDUP_FRAMES
    + (BOSS_UPTHRUST_WAVE_COUNT - 1) * BOSS_UPTHRUST_WAVE_SPACING_FRAMES
    + BOSS_UPTHRUST_WAVE_RISE_FRAMES
    + BOSS_UPTHRUST_WAVE_HOLD_FRAMES
)
BOSS_UPTHRUST_COOLDOWN = 150
# 中級ボスは専用の立ち絵（鬼立ち絵.png）を使う。
# 元絵は1024x1024でキャラクターがほぼ全面を埋めているため、
# ボス戦で見やすい大きさに縮小して読み込む（基準ボスの唐笠.pngより大きく）。
mid_boss_image = load_sprite(
    asset_dir / "鬼立ち絵.png",
    (200, 200),
    fallback_color=(120, 0, 0),
    outline_color=(255, 120, 0)
)
mid_boss_image_bounds = get_opaque_bounds(mid_boss_image)
# 中級ボスが突進前に見せる構えポーズ（鬼構え.png）。立ち絵と同じ200x200で読み込む。
mid_boss_stance_image = load_sprite(
    asset_dir / "鬼構え.png",
    (200, 200),
    fallback_color=(120, 0, 0),
    outline_color=(255, 120, 0)
)
mid_boss_stance_image_bounds = get_opaque_bounds(mid_boss_stance_image)
# 中級ボスの叩きつけ攻撃(SLAM)のポーズ。立ち絵と同じ見た目の背丈に揃えて読み込む。
#  予備動作(SLAM_WINDUP) → 鬼ジャンプ予備.png
#  ジャンプ/落下中(SLAM_JUMP/SLAM_FALL) → 鬼ジャンプ.png
#  着地して攻撃判定を出した瞬間(SLAM_RECOVER) → 鬼叩きつけ.png
# 3つとも立ち絵と同じ背丈(高さ)に合わせる（叩きつけは横長なので横幅だけ大きくなる）。
mid_boss_slam_windup_image, mid_boss_slam_windup_bounds = load_sprite_fit_height(
    asset_dir / "鬼ジャンプ予備.png",
    mid_boss_image_bounds.height,
    fallback_color=(120, 0, 0),
    outline_color=(255, 120, 0)
)
mid_boss_slam_jump_image, mid_boss_slam_jump_bounds = load_sprite_fit_height(
    asset_dir / "鬼ジャンプ.png",
    mid_boss_image_bounds.height,
    fallback_color=(120, 0, 0),
    outline_color=(255, 120, 0)
)
# 叩きつけは横長の素材。高さは立ち絵と同じ背丈に合わせたうえで、
# 見た目の横幅を333に合わせる（水平方向のみ拡縮し、高さは維持）。
# smoothscale後に透明境界の丸めで±1pxずれることがあるため、実測しながら補正する。
mid_boss_slam_impact_image, mid_boss_slam_impact_bounds = load_sprite_fit_height(
    asset_dir / "鬼叩きつけ.png",
    mid_boss_image_bounds.height,
    fallback_color=(120, 0, 0),
    outline_color=(255, 120, 0)
)
for _ in range(3):
    if mid_boss_slam_impact_bounds.width <= 0:
        break
    if mid_boss_slam_impact_bounds.width == 333:
        break
    _slam_scale_x = 333 / mid_boss_slam_impact_bounds.width
    if abs(_slam_scale_x - 1.0) < 1e-6:
        break
    _slam_new_w = max(1, round(mid_boss_slam_impact_image.get_width() * _slam_scale_x))
    _slam_new_h = mid_boss_slam_impact_image.get_height()
    mid_boss_slam_impact_image = pygame.transform.smoothscale(
        mid_boss_slam_impact_image, (_slam_new_w, _slam_new_h)
    )
    mid_boss_slam_impact_bounds = get_opaque_bounds(mid_boss_slam_impact_image)
# 中級ボスの遠距離攻撃（扇状弾・狙い撃ち）で飛ばすクナイ（鬼クナイ.png）。
# 原絵はクナイの先が左下向き（画面座標で約135度）なので、読み込み時に+135度回転させて
# 「先が右向き（0度）」にしておく。進行方向0ラジアン（=右向き）の弾が、回転なしで
# 先っちょを進行方向へ向けた状態になり、あとは進行方向へ合わせて回転すればよい。
mid_boss_kunai_image = load_sprite(
    asset_dir / "鬼クナイ.png",
    (48, 48),
    rotate=135,
    fallback_color=(200, 200, 210),
    outline_color=(20, 20, 30)
)
# 中級ボスの突進攻撃の見た目（鬼新突進.gif）。
# 白背景を抜いて読み込み、キャラクターの見た目の大きさを立ち絵（鬼立ち絵.png）の
# 高さに合わせてから、コマごとに下端中央を揃える（立ち絵と同じ基準で足元が動かないように）。
mid_boss_dash_gif_frames, mid_boss_dash_gif_durations = load_animated_gif_frames(
    asset_dir / "鬼新突進.gif",
    (200, 200),
    cut_background=True,
    with_durations=True,
)
# 立ち絵と同じ見た目の大きさになるよう、突進ポーズの高さを立ち絵の高さに合わせて
# 一律に拡大する（アスペクト比は保つ。横幅は突進ポーズの分だけ立ち絵よりやや広くなる）。
_mid_boss_dash_union = None
for _frame in mid_boss_dash_gif_frames:
    _bounds = get_opaque_bounds(_frame)
    if _bounds.width <= 0 or _bounds.height <= 0:
        continue
    _mid_boss_dash_union = _bounds.copy() if _mid_boss_dash_union is None else _mid_boss_dash_union.union(_bounds)
if _mid_boss_dash_union is not None and mid_boss_image_bounds.height > 0:
    _dash_scale = mid_boss_image_bounds.height / _mid_boss_dash_union.height
    if abs(_dash_scale - 1.0) > 1e-6:
        mid_boss_dash_gif_frames = [
            pygame.transform.scale(
                _frame,
                (max(1, round(_frame.get_width() * _dash_scale)),
                 max(1, round(_frame.get_height() * _dash_scale))),
            )
            for _frame in mid_boss_dash_gif_frames
        ]
mid_boss_dash_frames, MID_BOSS_DASH_ANCHOR = align_frames_bottom_center(
    mid_boss_dash_gif_frames
)
# 1コマあたりの表示フレーム数（ゲームループは60fps固定なのでmsをフレーム数に換算）。
# 表示時間が極端に短いコマでも最低1フレームは必ず残す。
MID_BOSS_DASH_FRAME_FRAMES = [
    max(1, round(duration / 1000 * 60)) for duration in mid_boss_dash_gif_durations
]
# 1周するまでのフレーム数（突進が長いときにアニメをループさせるのに使う）
MID_BOSS_DASH_CYCLE_FRAMES = sum(MID_BOSS_DASH_FRAME_FRAMES) or 1
hidden_boss_background = load_sprite(
    asset_dir / "背景.png",
    (SCREEN_WIDTH, SCREEN_HEIGHT),
    fallback_color=(0, 0, 0)
)
# 中級ボス(ステージ5)の背景。鬼の世界観に合わせて鬼背景.pngを使う。
mid_boss_background = load_sprite(
    asset_dir / "鬼背景.png",
    (SCREEN_WIDTH, SCREEN_HEIGHT),
    fallback_color=(0, 0, 0)
)
# 初級ボス(ステージ4)の背景。唐笠お化けに合わせて唐笠背景.pngを使う。
normal_boss_background = load_sprite(
    asset_dir / "唐笠背景.png",
    (SCREEN_WIDTH, SCREEN_HEIGHT),
    fallback_color=(0, 0, 0)
)
# 練習場(ステージ1)の背景。神殿.pngを使う(無い場合は白背景に切り替える)。
practice_background = None
try:
    _practice_path = asset_dir / "神殿.png"
    if _practice_path.exists():
        practice_background = load_sprite(
            _practice_path,
            (SCREEN_WIDTH, SCREEN_HEIGHT),
            fallback_color=(0, 0, 0),
        )
    else:
        print("神殿.pngが見つかりません。練習場は白背景に切り替えます。")
except Exception as exc:
    print(f"神殿.pngの読み込みに失敗しました: {exc}")
    practice_background = None
hidden_boss_platform_source = load_sprite(
    asset_dir / "足場.png",
    (1024, 1024),
    fallback_color=(100, 100, 100)
)
hidden_boss_platform_bounds = get_opaque_bounds(hidden_boss_platform_source)
hidden_boss_platform_image = hidden_boss_platform_source.subsurface(
    hidden_boss_platform_bounds
).copy()
hidden_boss_platform_tiles = {}

# 上級ボスの足場の見せ方。
# 背景(背景.png)には橋や屋根の輪郭など暗い横線がたくさんあり、
# 足場を素材のまま描いただけでは同じ細い横線に紛れて「乗れる高さ」が分からない。
#   y=  0.. 39 : 欄干(不透明率は13.6%で、ほとんどが穴)
#   y=104..167 : 歩けるデッキ面(最も明るく、上面の縁が赤く光る)
#   y=168..215 : 暗い土台
# 薄い足場(高さ20px)に橋の画像全体を潰すと欄干もデッキも1px潰れ何も読めないので、
# 薄い足場だけは「歩けるデッキ面」の帯を等倍で縮小して横方向に並べる。
# さらに踏める面(矩形の上端)を明るい縁取りで明示し、背景から離す暗い輪郭を付ける。
HIDDEN_BOSS_DECK_BAND = pygame.Rect(0, 110, 880, 66)
# この高さ以上の足場は欄干ごと描けるので素材をそのまま使う
HIDDEN_BOSS_FULL_ART_MIN_HEIGHT = 40
# 乗れる面の縁取りの色(背景の灯りに合わせて暖かい琥珀色にする)と、
# 背景の線と混ざらないようにするための暗い輪郭の色
HIDDEN_BOSS_EDGE_COLOR = (255, 198, 128)
HIDDEN_BOSS_RIM_COLOR = (14, 7, 14)
HIDDEN_BOSS_EDGE_THICKNESS = 3


def build_hidden_boss_platform_tile(size):
    """上級ボスの足場タイル(size)を作る。生成結果はキャッシュして使い回す。

    足場の当たり判定は矩形の上端なので、見た目もその上端を「乗れる面」として
    明るい縁取りで明示する。薄い足場では橋の画像全体を潰すと歩ける面が読めなくなるため、
    デッキ面だけを等倍で縮小して横に並べる。
    """
    width, height = size
    piece = (
        hidden_boss_platform_image
        if height >= HIDDEN_BOSS_FULL_ART_MIN_HEIGHT
        else hidden_boss_platform_image.subsurface(HIDDEN_BOSS_DECK_BAND)
    )

    # 高さを基準に等倍縮小し、横には継ぎ目なく並べる
    scale = height / piece.get_height()
    unit_width = max(1, min(width, int(round(piece.get_width() * scale))))
    strip = pygame.transform.smoothscale(piece, (unit_width, height))
    tile = pygame.Surface(size, pygame.SRCALPHA)
    x = 0
    while x < width:
        tile.blit(strip, (x, 0), (0, 0, min(unit_width, width - x), height))
        x += unit_width

    # 乗れる面(上面)を明るい縁取りで明示する。上段ほど明るくして面として目立たせる
    for i in range(HIDDEN_BOSS_EDGE_THICKNESS):
        ratio = 1.0 - i / (HIDDEN_BOSS_EDGE_THICKNESS + 1.0)
        color = tuple(int(HIDDEN_BOSS_EDGE_COLOR[ch] * ratio) for ch in range(3))
        pygame.draw.line(tile, color, (0, i), (width - 1, i))
    return tile

# 地面の上面y座標。
# ステージ6(上級ボス)だけは背景画像("背景.png")に描かれた歩道(橋のデッキ)に
# プレイヤーの足を乗せたいので、他のステージの535より上にずらす。
# 背景.png は 1672x941 を 800x600 に拡大して使うため、縦の換算係数は 600/941 ≈ 0.6376。
#   ・歩道のタイル面 : 元画像 y=811..822 → 画面 y=517..524
#   ・前端の金飾り   : 元画像 y=825..827 → 画面 y=526..527
# プレイヤーの足元(スプライトの不透明ピクセルの最下端)は床の上面 + 2px に降りるので、
# 足元が歩道の前端に乗る 523 を上級ボスの床の上面とする。
GROUND_TOP_Y = 535
HIDDEN_BOSS_GROUND_TOP_Y = 523
# 練習場(ステージ1)の床の上面。神殿.pngの土手(水面の手前)に合わせる。
# 画像を800x600に縮めると水面がy≈505から始まるため、その直前の土手上面500を使う。
PRACTICE_GROUND_TOP_Y = 500

# 練習場のボス入口(床置き)。唐笠お化け=右、赤鬼=左、玉藻前=中央。
PRACTICE_PORTAL_W, PRACTICE_PORTAL_H = 44, 90
# ポートの足元は練習場の床(神殿.pngの土手)に立たせる
PRACTICE_PORTAL_Y = PRACTICE_GROUND_TOP_Y - PRACTICE_PORTAL_H
PRACTICE_PORTALS = {
    5: pygame.Rect(80, PRACTICE_PORTAL_Y, PRACTICE_PORTAL_W, PRACTICE_PORTAL_H),
    6: pygame.Rect(
        (SCREEN_WIDTH - PRACTICE_PORTAL_W) // 2,
        PRACTICE_PORTAL_Y,
        PRACTICE_PORTAL_W,
        PRACTICE_PORTAL_H,
    ),
    4: pygame.Rect(
        SCREEN_WIDTH - 80 - PRACTICE_PORTAL_W,
        PRACTICE_PORTAL_Y,
        PRACTICE_PORTAL_W,
        PRACTICE_PORTAL_H,
    ),
}

# 上級ボスの入場演出。ステージ6に入ると画面外からゆっくり降りてきて、
# 着地した瞬間に和風BGMが流れ出して戦闘が始まる（BGMは演出が終わるまで流さない）。
HIDDEN_BOSS_ENTRANCE_START_Y = -160                        # 降下の開始位置（画面外）
HIDDEN_BOSS_ENTRANCE_LANDING_Y = HIDDEN_BOSS_GROUND_TOP_Y - 50  # 着地位置（床の上面に立つ）
HIDDEN_BOSS_ENTRANCE_FRAMES = 150        # 降下時間（2.5秒）
HIDDEN_BOSS_ENTRANCE_LANDING_FRAMES = 36 # 着地ダスト・名乗りフェードの時間
HIDDEN_BOSS_ENTRANCE_BANNER_IN_FRAMES = 12   # 名乗りを出し始めるフレーム
HIDDEN_BOSS_ENTRANCE_BANNER_FADE = 24    # 名乗りのフェードイン時間

# 入場演出の名乗り文字。毎フレーム生成するのは重いのでサイズ単位で使い回す
hidden_boss_banner_fonts = {}

# 赤鬼(中級ボス)の登場演出に使う赤鬼文字.png。
# タマモ文字.pngと同じく白背景を透過してから使う。
akaoni_title_image = None
try:
    _akaoni_path = asset_dir / "赤鬼文字.png"
    if _akaoni_path.exists():
        from PIL import Image as _AkaoniPILImage

        with _AkaoniPILImage.open(_akaoni_path) as _img:
            _rgba = _img.convert("RGBA")
            _rgba = remove_white_background(_rgba)
            akaoni_title_image = pygame.image.frombuffer(
                _rgba.tobytes(), _rgba.size, "RGBA"
            )
    if akaoni_title_image is None:
        print("赤鬼文字.pngが見つかりません。名乗りは文字表示に切り替えます。")
except Exception as exc:
    print(f"赤鬼文字.pngの読み込みに失敗しました: {exc}")
    akaoni_title_image = None

# 赤鬼の登場演出(ステージ5開始時)。画面左へ叩きつけ+赤鬼文字の名乗り。
MID_BOSS_ENTRANCE_TARGET_X = 180        # 登場時の叩きつけ位置(画面左)
MID_BOSS_ENTRANCE_BANNER_FRAMES = 90   # 赤鬼文字の表示時間(1.5秒)
MID_BOSS_ENTRANCE_BANNER_IN = 8        # 名乗りのフェードイン開始
MID_BOSS_ENTRANCE_BANNER_FADE = 20     # 名乗りのフェードイン時間
# 叩きつけ着地ポーズ(鬼叩きつけ.png)の見た目だけの微調整。
# 予告・当たり判定(slam_hit_rect)は動かさず、描画と被弾判定だけ左へ寄せる。
MID_BOSS_SLAM_IMPACT_DRAW_SHIFT_X = -16
# 玉藻前(上級ボス)の名乗り演出に使うタマモ文字.png。
# 白背景の素材なので、GIFローダーと同じ白抜き処理で透過してから使う。
tamamo_title_image = None
try:
    _tamamo_path = asset_dir / "タマモ文字.png"
    if _tamamo_path.exists():
        from PIL import Image as _TamamoPILImage

        with _TamamoPILImage.open(_tamamo_path) as _img:
            _rgba = _img.convert("RGBA")
            _rgba = remove_white_background(_rgba)
            tamamo_title_image = pygame.image.frombuffer(
                _rgba.tobytes(), _rgba.size, "RGBA"
            )
    if tamamo_title_image is None:
        print("タマモ文字.pngが見つかりません。名乗りは文字表示に切り替えます。")
except Exception as exc:
    print(f"タマモ文字.pngの読み込みに失敗しました: {exc}")
    tamamo_title_image = None


def get_hidden_boss_banner_font(size):
    """上級ボス入場演出の名乗りに使うフォント（初回だけ生成してキャッシュする）"""
    font = hidden_boss_banner_fonts.get(size)
    if font is None:
        font = pygame.font.SysFont("msgothic", size, bold=True)
        hidden_boss_banner_fonts[size] = font
    return font



pygame.display.set_caption("アクションゲーム試作 - [W/Space/↑]:Jump [X/Click]:Attack")

slash_sound = None
slash_sound_path = asset_dir / "斬撃音.mp3"
if slash_sound_path.exists():
    try:
        slash_sound = pygame.mixer.Sound(str(slash_sound_path))
    except Exception as exc:
        print(f"斬撃音の読み込みに失敗しました: {exc}")

hit_sound = None
hit_sound_path = asset_dir / "被弾音.mp3"
if hit_sound_path.exists():
    try:
        hit_sound = pygame.mixer.Sound(str(hit_sound_path))
    except Exception as exc:
        print(f"被弾音の読み込みに失敗しました: {exc}")

beam_sound = None
beam_sound_path = asset_dir / "ビーム.mp3"
if beam_sound_path.exists():
    try:
        beam_sound = pygame.mixer.Sound(str(beam_sound_path))
        beam_sound.set_volume(0.75)
    except Exception as exc:
        print(f"ビーム音の読み込みに失敗しました: {exc}")

# 「画面の三分の一」を占める大きなビーム(TRIPLE_COLUMN)用の効果音。
# 予測線が出ている間(1.5秒)はチャージ音を鳴らし、当たり判定が出るときに砲撃音を鳴らす。
# 音量は環境に合わせてここで調整する
BEAM_CHARGE_VOLUME = 0.8
BEAM_CANNON_VOLUME = 0.9
# 予測線の表示時間(phase_timer 0〜89 = 90フレーム)。チャージ音の長さもこれに合わせて用意する
BEAM_WARNING_SECONDS = 1.5

beam_charge_sound = None
beam_charge_path = asset_dir / "ビーム砲チャージ.mp3"
if beam_charge_path.exists():
    try:
        beam_charge_sound = pygame.mixer.Sound(str(beam_charge_path))
        beam_charge_sound.set_volume(BEAM_CHARGE_VOLUME)
        # 長さの確認。予測線の表示時間とズレている場合はお知らせ
        charge_length = beam_charge_sound.get_length()
        if abs(charge_length - BEAM_WARNING_SECONDS) > 0.3:
            print(
                f"注意: ビーム砲チャージ音は{charge_length:.2f}秒ですが、"
                f"予測線の表示時間は{BEAM_WARNING_SECONDS:.1f}秒です"
            )
    except Exception as exc:
        print(f"ビーム砲チャージ音の読み込みに失敗しました: {exc}")
else:
    print(f"ビーム砲チャージ音が見つかりません: {beam_charge_path}")

beam_cannon_sound = None
beam_cannon_path = asset_dir / "ビーム砲2.mp3"
if beam_cannon_path.exists():
    try:
        beam_cannon_sound = pygame.mixer.Sound(str(beam_cannon_path))
        beam_cannon_sound.set_volume(BEAM_CANNON_VOLUME)
    except Exception as exc:
        print(f"ビーム砲音の読み込みに失敗しました: {exc}")
else:
    print(f"ビーム砲音が見つかりません: {beam_cannon_path}")

# 上級ボスが弾を発射するときの効果音。1発の弾につき1回鳴らす
SHOT_SOUND_VOLUME = 0.6
# 斉射の音がすべて同時に鳴ると1音に潰れて聞こえないため、
# 発射音を何フレームごとに1回鳴らすか（2フレーム ≒ 0.03秒）
SHOT_SOUND_STAGGER = 2

shot_sound = None
shot_sound_path = asset_dir / "ショット.mp3"
if shot_sound_path.exists():
    try:
        shot_sound = pygame.mixer.Sound(str(shot_sound_path))
        shot_sound.set_volume(SHOT_SOUND_VOLUME)
    except Exception as exc:
        print(f"ショット音の読み込みに失敗しました: {exc}")
else:
    print(f"ショット音が見つかりません: {shot_sound_path}")

# 中級ボス(赤鬼)のジャンプ叩きつけ攻撃用の効果音。
# 攻撃発生(着地)の瞬間に1回だけ鳴らす。登場演出の着地でも鳴らす。
SLAM_SOUND_VOLUME = 1.0
slam_sound = None
slam_sound_path = asset_dir / "叩きつけ音.mp3"
if slam_sound_path.exists():
    try:
        slam_sound = pygame.mixer.Sound(str(slam_sound_path))
        slam_sound.set_volume(SLAM_SOUND_VOLUME)
    except Exception as exc:
        print(f"叩きつけ音の読み込みに失敗しました: {exc}")
else:
    print(f"叩きつけ音が見つかりません: {slam_sound_path}")


hidden_boss_bgm_loaded = False
hidden_boss_bgm_path = asset_dir / "和風.mp3"
if hidden_boss_bgm_path.exists():
    try:
        pygame.mixer.music.load(str(hidden_boss_bgm_path))
        pygame.mixer.music.set_volume(0.5)
        hidden_boss_bgm_loaded = True
    except Exception as exc:
        print(f"上級ボスBGMの読み込みに失敗しました: {exc}")
else:
    print(f"上級ボスBGMが見つかりません: {hidden_boss_bgm_path}")

hidden_boss_bgm_started = False


# 中級ボス(ステージ5)のBGM。鬼の世界観に合わせて鬼BGM.mp3を使う。
# mixer.music は再生する音源を1つだけ保持する単一チャンネルなので、
# 他のステージのBGM(和風.mp3)を読み込んでいても、再生のたびに自分のファイルを読み直す。
mid_boss_bgm_loaded = False
mid_boss_bgm_path = asset_dir / "鬼BGM.mp3"
if mid_boss_bgm_path.exists():
    try:
        pygame.mixer.music.load(str(mid_boss_bgm_path))
        pygame.mixer.music.set_volume(0.5)
        mid_boss_bgm_loaded = True
    except Exception as exc:
        print(f"中級ボスBGMの読み込みに失敗しました: {exc}")
else:
    print(f"中級ボスBGMが見つかりません: {mid_boss_bgm_path}")

mid_boss_bgm_started = False


def set_hidden_boss_bgm(is_playing, restart=False):
    global hidden_boss_bgm_started
    if not hidden_boss_bgm_loaded:
        return

    if is_playing and (not hidden_boss_bgm_started or restart):
        # mixer.music は単一チャンネルなので、中級ボスBGM(鬼BGM.mp3)を読み込んでいる
        # 可能性がある。再生のたびに上級ボスのBGM(和風.mp3)を読み直してから鳴らす。
        try:
            pygame.mixer.music.load(str(hidden_boss_bgm_path))
            pygame.mixer.music.set_volume(0.5)
        except Exception as exc:
            print(f"上級ボスBGMの再生準備に失敗しました: {exc}")
            return
        pygame.mixer.music.play(-1)
        hidden_boss_bgm_started = True
    elif not is_playing and hidden_boss_bgm_started:
        pygame.mixer.music.stop()
        hidden_boss_bgm_started = False


def set_mid_boss_bgm(is_playing, restart=False):
    global mid_boss_bgm_started
    if not mid_boss_bgm_loaded:
        return

    if is_playing and (not mid_boss_bgm_started or restart):
        # 再生のたびに中級ボスのBGM(鬼BGM.mp3)を読み直してから鳴らす。
        try:
            pygame.mixer.music.load(str(mid_boss_bgm_path))
            pygame.mixer.music.set_volume(0.5)
        except Exception as exc:
            print(f"中級ボスBGMの再生準備に失敗しました: {exc}")
            return
        pygame.mixer.music.play(-1)
        mid_boss_bgm_started = True
    elif not is_playing and mid_boss_bgm_started:
        pygame.mixer.music.stop()
        mid_boss_bgm_started = False


def play_beam_sound():
    if beam_sound is not None:
        beam_sound.play()



# 効果音を同時再生できるように、音ごとに別チャンネルを用意
slash_channel = pygame.mixer.Channel(0)
hit_channel = pygame.mixer.Channel(1)
beam_charge_channel = pygame.mixer.Channel(3)
beam_cannon_channel = pygame.mixer.Channel(4)
shot_channel = pygame.mixer.Channel(5)

# チャージ音は「予測線が出ている間だけ」鳴らし続けるので、
# 発声中かどうかをフラグで管理して、攻撃が変わったときに止められるようにする
beam_charge_playing = False


def play_beam_charge_sound():
    """大きなビームの予測線が出ている間に鳴らすチャージ音"""
    global beam_charge_playing
    if beam_charge_sound is None:
        return
    beam_charge_channel.play(beam_charge_sound)
    beam_charge_playing = True


def stop_beam_charge_sound():
    """チャージ音が鳴りっぱなしにならないように止める"""
    global beam_charge_playing
    if not beam_charge_playing:
        return
    beam_charge_channel.stop()
    beam_charge_playing = False


def play_beam_cannon_sound():
    """当たり判定が出た瞬間に鳴らす砲撃音"""
    if beam_cannon_sound is not None:
        beam_cannon_channel.play(beam_cannon_sound)


def play_shot_sound():
    """上級ボスが弾を発射するときの効果音"""
    if shot_sound is not None:
        shot_channel.play(shot_sound)

# 色の定義
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
SKIN = (255, 220, 180)  # 肌色
SHIRT = (50, 150, 255)  # 服の色
PANTS = (50, 50, 50)    # ズボンの色
GROUND_COLOR = (100, 100, 100)
SWORD_COLOR = (192, 192, 192)
RED = (255, 0, 0)
ENEMY_SKIN = (200, 100, 100) # 敵の肌色
ENEMY_SHIRT = (150, 0, 0) # 敵の服の色
PURPLE = (150, 0, 150) # 遠距離敵の色
GOLD = (255, 215, 0) # ボスの色
DARK_PURPLE = (40, 0, 80) # 隠しボスの色
GLOW_RED = (255, 50, 50)  # 隠しボスの目の色
CYAN = (0, 255, 255)
YELLOW = (255, 240, 100)
GREEN = (0, 200, 0)

import random
import math

class Player:
    def __init__(self):
        self.x = SCREEN_WIDTH // 2
        self.y = 450
        self.speed = 5
        self.vel_y = 0
        self.jump_power = -15
        self.gravity = 0.8
        self.is_jumping = False
        self.walk_cycle = 0  # 歩行アニメーション用のカウンタ
        self.facing_right = True
        self.attack_timer = 0  # 攻撃モーションの持続時間
        self.attack_power_timer = 0  # 攻撃強化時間
        self.attack_cooldown = 0
        self.attack_interval = 18
        self.ranged_cooldown = 0  # 遠距離攻撃のクールダウン
        self.health = 5        # プレイヤーの体力（初期は最大値の5）
        self.max_health = 5
        self.invincible_timer = 0 # 被弾後の無敵時間
        self.double_jump_available = True
        self.jump_pressed = False
        self.evade_timer = 0  # 回避の残り時間
        self.evade_cooldown = 0  # 回避のクールダウン
        self.evade_dir = 1  # 回避の方向(-1: 左 / 1: 右)
        self.evade_frame_index = 0
        self.evade_anim_timer = 0
        self.score = 0
        self.rect = pygame.Rect(self.x - 10, self.y - 47, 20, 82)
        self.particles = []
        self.walk_frames = load_animated_gif_frames(asset_dir / "新歩き.gif", PLAYER_GIF_SIZE)
        self.walk_frame_index = 0
        self.walk_anim_timer = 0
        self.attack_frame_index = 0
        self.attack_anim_timer = 0

    def update(self, platforms, enemies, projectiles, powerups, effects):
        keys = pygame.key.get_pressed()
        mouse_buttons = pygame.mouse.get_pressed()
        moving = False

        # 左右入力を取得
        left_pressed = keys[pygame.K_LEFT] or keys[pygame.K_a]
        right_pressed = keys[pygame.K_RIGHT] or keys[pygame.K_d]

        # 回避の残り時間を減らす
        # (毎フレーム先頭で減らすことで、回避中のフレームは最後の1フレームまで無敵と移動が維持される)
        if self.evade_timer > 0:
            self.evade_timer -= 1

        # 回避 (Shift / 右クリック): 指定方向へ慣性なしで大きく移動し、その間は無敵
        if (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] or mouse_buttons[2]) and self.evade_cooldown <= 0:
            self.evade_timer = 16  # 回避の持続フレーム (16フレーム × 11px = 176px 進む)
            self.evade_cooldown = 90
            # 左右の入力があればその方向、なければ向いている方向へ回避する
            if left_pressed != right_pressed:
                self.evade_dir = -1 if left_pressed else 1
            else:
                self.evade_dir = 1 if self.facing_right else -1
            self.facing_right = self.evade_dir > 0
        if self.evade_cooldown > 0:
            self.evade_cooldown -= 1

        # 回避の移動: 固定方向・一定速度で進め、残り時間が0になったフレームで即停止する(慣性を持たせない)。
        # 回避中は左右の移動入力を無視し、毎回同じ飛距離に保つ。
        if self.evade_timer > 0:
            self.x += self.evade_dir * 11
            moving = True
        else:
            if left_pressed:
                self.x -= self.speed
                moving = True
                self.facing_right = False
            if right_pressed:
                self.x += self.speed
                moving = True
                self.facing_right = True

        # 回避アニメーション (回避の持続時間16フレームに合わせて全コマを流す)
        if self.evade_timer > 0 and evade_frames:
            self.evade_anim_timer += 1
            evade_interval = max(1, 16 // len(evade_frames))
            if self.evade_anim_timer >= evade_interval:
                self.evade_anim_timer = 0
                self.evade_frame_index = min(
                    self.evade_frame_index + 1,
                    len(evade_frames) - 1
                )
        else:
            self.evade_frame_index = 0
            self.evade_anim_timer = 0

        # ジャンプ処理
        if (keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]) and not self.jump_pressed:
            if not self.is_jumping:
                self.vel_y = self.jump_power
                self.is_jumping = True
            elif self.double_jump_available:
                self.vel_y = self.jump_power
                self.double_jump_available = False
            self.jump_pressed = True
        if not (keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]):
            self.jump_pressed = False
        if self.attack_cooldown > 0:
            self.attack_cooldown -= 1

        # 攻撃処理 (左クリック or X)
        if (keys[pygame.K_x] or mouse_buttons[0]) \
                and self.attack_timer <= 0 \
                and self.attack_cooldown <= 0:

            self.attack_timer = 10  # 10フレーム攻撃でさらに短くする
            self.attack_cooldown = self.attack_interval
            self.attack_frame_index = 0
            self.attack_anim_timer = 0

        # 遠距離攻撃 (Zキーのみ)
        if keys[pygame.K_z] and self.ranged_cooldown <= 0:
            self.ranged_cooldown = 18
            mx, my = pygame.mouse.get_pos()
            angle = math.atan2(my - self.y, mx - self.x)
            projectiles.append(Projectile(self.x + (12 if self.facing_right else -12), self.y - 10, angle, color=CYAN, speed=10, friendly=True))

        if moving:
            self.walk_cycle += 0.15  # 移動中にアニメーションを進める
            self.walk_anim_timer += 1
            if self.walk_anim_timer >= 5:
                self.walk_anim_timer = 0
                self.walk_frame_index = (self.walk_frame_index + 1) % max(1, len(self.walk_frames))
        else:
            self.walk_cycle = 0  # 止まったら直立
            self.walk_anim_timer = 0
            self.walk_frame_index = 0

        # 重力の適用
        self.vel_y += self.gravity
        self.y += self.vel_y

        # 攻撃強化タイマーの更新
        if self.attack_power_timer > 0:
            self.attack_power_timer -= 1

        # 遠距離攻撃のクールダウン
        if self.ranged_cooldown > 0:
            self.ranged_cooldown -= 1

        # 攻撃タイマーの更新
        if self.attack_timer > 0:
            self.attack_timer -= 1
            if attack_frames:
                self.attack_anim_timer += 1
                if self.attack_anim_timer >= 2:
                    self.attack_anim_timer = 0
                    self.attack_frame_index = min(
                        self.attack_frame_index + 1,
                        len(attack_frames) - 1
                    )
        else:
            self.attack_frame_index = 0
            self.attack_anim_timer = 0

        # 無敵タイマーの更新
        if self.invincible_timer > 0:
            self.invincible_timer -= 1

        # 画面外に出ないように制限 (左右の壁と天井)
        if self.x < 10: self.x = 10
        if self.x > SCREEN_WIDTH - 10: self.x = SCREEN_WIDTH - 10
        if self.y < CEILING_Y:
            self.y = CEILING_Y
            if self.vel_y < 0:
                self.vel_y = 0

        # 自身のRectを更新
        self.rect.x = self.x - 10
        self.rect.y = self.y - 47

        # パワーアップとの当たり判定
        for powerup in powerups[:]:
            if self.rect.colliderect(powerup.rect):
                self.collect_powerup(powerup)
                powerups.remove(powerup)

        # 敵からの攻撃判定 (回避中は無敵なので判定しない)
        if self.invincible_timer <= 0 and self.evade_timer <= 0:
            for enemy in enemies:
                # 接近戦の敵(Enemy/Boss)の攻撃判定 (ボスは猶予を増やすため判定フレームを遅らせる)
                if isinstance(enemy, Boss) and enemy.attack_timer == 10:
                    range_w = 80
                    range_h = 60
                    enemy_attack_rect = pygame.Rect(
                        enemy.x + (10 if enemy.facing_right else -(range_w + 10)),
                        enemy.y - 25, range_w, range_h
                    )
                    if self.rect.colliderect(enemy_attack_rect):
                        self.take_damage()
                        break
                
                # ボスの地響き攻撃の判定 (地面に接地している場合のみダメージ)
                if isinstance(enemy, Boss) and enemy.shockwave_enabled and enemy.shockwave_timer == 200:
                    if not self.is_jumping and self.y >= 500:
                        self.take_damage()

                # 唐笠お化けのジャンプ着地攻撃
                if isinstance(enemy, Boss) and enemy.jump_attack_effect_timer == 1:
                    distance = math.sqrt((self.x - enemy.x) ** 2 + (self.y - enemy.y) ** 2)
                    if distance < 80:
                        self.take_damage()

                # 唐笠お化けの下から突き上げる攻撃(地面から生える傘の波)
                if isinstance(enemy, Boss):
                    for hit_rect in enemy.upthrust_wave_rects():
                        if self.rect.colliderect(hit_rect):
                            self.take_damage()
                            break

            # 飛び道具(Projectile)の当たり判定
            for proj in projectiles[:]:
                if proj.friendly:
                    continue
                if self.rect.colliderect(proj.rect):
                    self.take_damage()
                    projectiles.remove(proj)
                    break

        # 攻撃の当たり判定 (攻撃開始後、判定フレームで1回だけ発生)
        # (回避中の無敵とは独立に発生する — 回避中も攻撃は通る)
        if self.invincible_timer <= 0 and self.attack_timer == 9:
            attack_w = 60 if self.attack_power_timer > 0 else 40
            attack_rect = pygame.Rect(
                self.x + (10 if self.facing_right else -attack_w),
                self.y - 25,
                attack_w,
                30
            )
            for enemy in enemies:
                if attack_rect.colliderect(enemy.rect):
                    if isinstance(enemy, (Boss, HiddenBoss)):
                        damage = 1
                    else:
                        damage = 2 if self.attack_power_timer > 0 else 1
                    enemy.health -= damage

                    slash_angle = math.atan2(
                        enemy.y - self.y,
                        enemy.x - self.x
                    )
                    effects.add_slash_effect(
                        enemy.x,
                        enemy.y - 20,
                        slash_angle,
                        WHITE,
                        90,
                        10
                    )
                    if slash_sound is not None:
                        slash_channel.play(slash_sound)

                    if enemy.health <= 0:
                        if isinstance(enemy, HiddenBoss):
                            self.score += 1200
                        elif isinstance(enemy, Boss):
                            self.score += 800

        # 当たり判定 (地面とプラットフォーム)
        self.check_collision(platforms)

    def take_damage(self):
        if self.invincible_timer > 0:
            return
        if self.evade_timer > 0:  # 回避中は無敵
            return

        self.health -= 1
        self.invincible_timer = 60  # 約1秒間の無敵時間
        if hit_sound is not None:
            hit_channel.play(hit_sound)
        # 被弾時に少し跳ね返る（ノックバック）
        self.vel_y = -10

    def collect_powerup(self, powerup):
        if powerup.kind == "HEAL":
            self.health = min(self.max_health, self.health + 1)
        elif powerup.kind == "ATTACK":
            self.attack_power_timer = 180
        elif powerup.kind == "SCORE":
            self.score += 150

    def check_collision(self, platforms):
        # 足元（y座標）の判定用仮想Rect
        foot_rect = pygame.Rect(self.x - 10, self.y + 30, 20, 5)
        
        on_platform = False
        for plat in platforms:
            if self.vel_y >= 0 and foot_rect.colliderect(plat):
                # 足元がプラットフォームの上面にある場合
                if self.y + 30 <= plat.top + self.vel_y + 1:
                    self.y = plat.top - 35
                    self.vel_y = 0
                    self.is_jumping = False
                    self.double_jump_available = True
                    on_platform = True
                    break # 衝突したらループを抜ける
        # 地面との衝突はplatformsリスト内の地面Rectで処理されるため、個別のy > 500判定は不要

    def draw(self, surface):
        # 無敵時間中は点滅させる
        if self.invincible_timer > 0 and (self.invincible_timer // 5) % 2 == 0:
            return

        pressed = pygame.key.get_pressed()
        moving = any(pressed[k] for k in (
            pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d,
            pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN
        ))

        def draw_ground_aligned(image):
            if not self.facing_right:
                image = pygame.transform.flip(image, True, False)
            foot_anchor_y = self.y + 28
            draw_y = int(foot_anchor_y - image.get_height() + 10)
            surface.blit(image, (int(self.x - image.get_width() / 2), draw_y))

        if self.attack_timer > 0 and attack_frames:
            draw_ground_aligned(attack_frames[self.attack_frame_index])
            return

        # 回避中は回避アニメーションを表示 (慣性のない回避モーションに合わせる)
        if self.evade_timer > 0 and evade_frames:
            draw_ground_aligned(evade_frames[self.evade_frame_index])
            return

        if moving and self.walk_frames:
            frame = self.walk_frames[self.walk_frame_index]
            draw_ground_aligned(frame)
            return

        if idle_sprite is not None:
            draw_ground_aligned(idle_sprite)
            return

        image = player_image if self.facing_right else pygame.transform.flip(player_image, True, False)
        foot_anchor_y = self.y + 28
        draw_y = int(foot_anchor_y - image.get_height() + 10)
        surface.blit(image, (int(self.x - image.get_width() / 2), draw_y))
        return

        # 1. 脚 (左右交互に振る)
        pygame.draw.line(surface, PANTS, (self.x, self.y + 10), (self.x - 8 + swing, self.y + 35), 8)
        pygame.draw.line(surface, PANTS, (self.x, self.y + 10), (self.x + 8 - swing, self.y + 35), 8)

        # 2. 胴体
        pygame.draw.rect(surface, SHIRT, (self.x - 10, self.y - 20, 20, 30), border_radius=5)

        # 追加エフェクト: 回避と攻撃強化
        if self.evade_timer > 0:
            pygame.draw.circle(surface, CYAN, (int(self.x), int(self.y - 20)), 18, 2)
        if self.attack_power_timer > 0:
            pygame.draw.circle(surface, YELLOW, (int(self.x), int(self.y - 20)), 22, 2)

        # 3. 腕 (攻撃中と歩行中でポーズを変える)
        if self.attack_timer > 0:
            # 攻撃モーション: 前方に腕を突き出す
            pygame.draw.line(surface, SKIN, (self.x + (10 * dir_mod), self.y - 15), (self.x + (30 * dir_mod), self.y - 5), 5)
            # 剣の描画
            pygame.draw.line(surface, SWORD_COLOR, (self.x + (25 * dir_mod), self.y - 10), (self.x + (50 * dir_mod), self.y - 20), 4)
        else:
            pygame.draw.line(surface, SKIN, (self.x - 10, self.y - 15), (self.x - 10 - (swing * 0.5), self.y + 10), 5)
            pygame.draw.line(surface, SKIN, (self.x + 10, self.y - 15), (self.x + 10 + (swing * 0.5), self.y + 10), 5)

        # 4. 頭
        pygame.draw.circle(surface, SKIN, (int(self.x), int(self.y - 35)), 12)
        # 目 (向きに合わせて位置調整)
        eye_x = self.x + (4 * dir_mod)
        pygame.draw.circle(surface, BLACK, (int(eye_x), int(self.y - 37)), 2)
        pygame.draw.circle(surface, BLACK, (int(eye_x + (4 * dir_mod)), int(self.y - 37)), 2)

# 回転させたスプライトのキャッシュ（毎フレーム rotate すると負荷が高いため角度ごとに保持）。
# クナイなどの飛び道具を進行方向へ向けて描くのに使う。
_rotated_sprite_cache = {}


def get_rotated_sprite(surface, angle_deg):
    """surface を angle_deg 度だけ回転したサーフェスをキャッシュ経由で返す。"""
    angle_key = int(round(angle_deg)) % 360
    cache_key = (id(surface), angle_key)
    cached = _rotated_sprite_cache.get(cache_key)
    if cached is None:
        cached = pygame.transform.rotate(surface, angle_key)
        _rotated_sprite_cache[cache_key] = cached
    return cached


class Projectile:
    def __init__(self, x, y, direction, color=BLACK, speed=7, friendly=False, image=None):
        self.x = x
        self.y = y
        self.speed = speed
        self.color = color
        self.friendly = friendly
        self.friendly = friendly
        # 見た目用スプライト（クナイなど）。指定があるときは進行方向へ回転して描画する。
        self.image = image
        self._display_angle = None
        if isinstance(direction, float):
            self.vel_x = self.speed * math.cos(direction)
            self.vel_y = self.speed * math.sin(direction)
            self._dir_angle = direction
        else:
            self.vel_x = self.speed * direction
            self.vel_y = 0
            self._dir_angle = 0.0
        self.rect = pygame.Rect(x - 5, y - 5, 10, 10)

    def update(self):
        self.x += self.vel_x
        self.y += self.vel_y
        self.rect.x = self.x - 5
        self.rect.y = self.y - 5

    def draw(self, surface):
        if self.image is not None:
            # 見た目の回転角。反転(flip)しても実際の進む向き(vel)に合わせて必ず「先っちょ」を進行方向へ向ける。
            if self._display_angle is None:
                self._display_angle = -math.degrees(self._dir_angle)
            draw_image = get_rotated_sprite(self.image, self._display_angle)
            draw_w = draw_image.get_width()
            draw_h = draw_image.get_height()
            surface.blit(draw_image, (int(self.x - draw_w / 2), int(self.y - draw_h / 2)))
        else:
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), 5)

class EffectManager:
    def __init__(self):
        self.particles = []
        self.screen_shake = 0
        self.flash_timer = 0
        self.flash_color = WHITE

    def add_hit_effect(self, x, y, color=YELLOW, count=12):
        for _ in range(count):
            angle = random.uniform(0, math.pi * 2)
            speed = random.uniform(2, 7)

            self.particles.append({
                "x": x,
                "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "life": random.randint(15, 30),
                "max_life": 30,
                "color": color,
                "size": random.randint(2, 5)
            })

    def add_slash_effect(self, x, y, angle, color=YELLOW, length=60, count=6):
        self.particles.append({
            "x": x,
            "y": y,
            "vx": 0,
            "vy": 0,
            "life": 18,
            "max_life": 18,
            "color": color,
            "size": 8,
            "kind": "main_slash",
            "angle": angle + random.uniform(-0.12, 0.12),
            "length": max(length * 1.1, 90),
            "offset": 0,
            "width": 34,
            "arc": random.uniform(-1.2, -0.5)
        })

    def add_explosion(self, x, y, color=RED, count=30):
        for _ in range(count):
            angle = random.uniform(0, math.pi * 2)
            speed = random.uniform(2, 9)

            self.particles.append({
                "x": x,
                "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "life": random.randint(25, 50),
                "max_life": 50,
                "color": color,
                "size": random.randint(3, 7)
            })

        self.screen_shake = max(self.screen_shake, 15)
        self.flash_timer = 8
        self.flash_color = color

    def update(self):
        for p in self.particles[:]:
            p["x"] += p["vx"]
            p["y"] += p["vy"]

            p["vx"] *= 0.96
            p["vy"] *= 0.96
            p["vy"] += 0.08

            p["life"] -= 1

            if p["life"] <= 0:
                self.particles.remove(p)

        if self.screen_shake > 0:
            self.screen_shake -= 1

        if self.flash_timer > 0:
            self.flash_timer -= 1

    def draw(self, surface):
        for p in self.particles:
            alpha = max(0, int(255 * p["life"] / p["max_life"]))

            if p.get("kind") == "main_slash":
                size = max(150, int(p["length"] * 1.2))
                slash_surface = pygame.Surface((size, size), pygame.SRCALPHA)
                cx = cy = size // 2
                r = size * 0.42
                arc_thickness = max(18, min(48, int(p["width"] * 1.1)))
                start_angle = math.radians(35)
                end_angle = math.radians(200)

                outer_rect = (cx - r, cy - r, r * 2, r * 2)
                pygame.draw.arc(slash_surface, (*p["color"], alpha), outer_rect, start_angle, end_angle, arc_thickness)

                inner_r = r * 0.72
                inner_rect = (cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
                pygame.draw.arc(slash_surface, (0, 0, 0, 0), inner_rect, start_angle, end_angle, max(8, arc_thickness - 12))

                glow = pygame.Surface((size, size), pygame.SRCALPHA)
                glow_r = r * 0.9
                glow_rect = (cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2)
                pygame.draw.arc(glow, (*p["color"], max(45, alpha // 3)), glow_rect, start_angle, end_angle, max(10, arc_thickness // 3))
                slash_surface.blit(glow, (0, 0))

                rotated = pygame.transform.rotate(slash_surface, math.degrees(p["angle"]) + 90)
                rect = rotated.get_rect(center=(int(p["x"]), int(p["y"])))
                surface.blit(rotated, rect)
                continue

            particle = pygame.Surface(
                (p["size"] * 2, p["size"] * 2),
                pygame.SRCALPHA
            )

            color = (*p["color"], alpha)

            pygame.draw.circle(
                particle,
                color,
                (p["size"], p["size"]),
                p["size"]
            )

            surface.blit(
                particle,
                (int(p["x"] - p["size"]),
                 int(p["y"] - p["size"]))
            )

class PowerUp:
    def __init__(self, x, y, kind):
        self.x = x
        self.y = y
        self.kind = kind
        self.float_timer = random.random() * math.pi
        self.rect = pygame.Rect(x - 12, y - 12, 24, 24)

    def update(self):
        self.float_timer += 0.05
        self.y += math.sin(self.float_timer) * 0.4
        self.rect.x = self.x - 12
        self.rect.y = self.y - 12

    def draw(self, surface):
        if self.kind == "HEAL":
            color = GREEN
            label = "H"
        elif self.kind == "ATTACK":
            color = YELLOW
            label = "A"
        else:
            color = CYAN
            label = "S"

        pygame.draw.circle(surface, color, (int(self.x), int(self.y)), 10)
        pygame.draw.circle(surface, BLACK, (int(self.x), int(self.y)), 10, 2)

        font = pygame.font.SysFont("msgothic", 18, bold=True)
        surface.blit(font.render(label, True, BLACK), (self.x - 6, self.y - 10))

        # 視認性を維持するため、動かないシンプルなパワーアップ見た目に統一
        pygame.draw.rect(surface, (80, 0, 80), (self.x - 10, self.y - 20, 20, 30), border_radius=5)
        pygame.draw.line(surface, PANTS, (self.x, self.y + 10), (self.x - 8, self.y + 35), 8)
        pygame.draw.line(surface, PANTS, (self.x, self.y + 10), (self.x + 8, self.y + 35), 8)

class Boss:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.max_health = 25
        self.health = self.max_health
        self.rect = pygame.Rect(x - 30, y - 80, 60, 130)
        self.vel_y = 0
        self.facing_right = False
        self.shockwave_timer = 0
        self.shockwave_enabled = False
        self.attack_timer = 0
        self.chase_speed = 1.2
        self.attack_range = 100
        self.jump_attack_active = False
        self.jump_attack_cooldown = 180
        self.jump_attack_effect_timer = 0
        self.jump_gif_frame = 0  # ジャンプ攻撃アニメ(唐笠新ジャンプ.gif)の再生位置
        self.jump_air_frames = 1  # このジャンプの滞空フレーム数(発射時に見積もり)
        # 下から傘を突き上げる攻撃の状態
        self.upthrust_timer = 0      # 残りフレーム(0で待機)
        self.upthrust_cooldown = 0
        self.upthrust_waves = []     # 地面から生える波[{"x": 出現位置, "age": 経過フレーム}]
        self.attack_pattern = 0      # ジャンプ/突き上げを使い分けるカウンタ

    def update(self, player_x, projectiles, platforms, player_y=None):
        # 重力と足場判定
        if self.jump_attack_cooldown > 0:
            self.jump_attack_cooldown -= 1
        if self.upthrust_cooldown > 0:
            self.upthrust_cooldown -= 1
        if self.upthrust_timer > 0:
            self.upthrust_timer -= 1
            for wave in self.upthrust_waves:
                wave["age"] += 1
            if self.upthrust_timer <= 0:
                self.upthrust_waves = []
        if self.jump_attack_effect_timer > 0:
            self.jump_attack_effect_timer -= 1

        # ジャンプ攻撃アニメ(唐笠新ジャンプ.gif)の再生。
        # アニメ全体が滞空時間に収まるよう早送りし、着地後は最終コマ(着地姿勢)を保持する。
        if self.jump_attack_active and BOSS_JUMP_GIF_TOTAL_FRAMES > 0:
            self.jump_gif_frame += BOSS_JUMP_GIF_TOTAL_FRAMES / max(1, self.jump_air_frames)

        was_falling_jump = self.jump_attack_active and self.vel_y >= 0
        self.vel_y += 0.8
        self.y += self.vel_y
        foot_rect = pygame.Rect(self.x - 30, self.y + 45, 60, 5)
        for plat in platforms:
            if self.vel_y >= 0 and foot_rect.colliderect(plat):
                self.y = plat.top - 50
                self.vel_y = 0
                break
        if self.y > 500: self.y = 500; self.vel_y = 0

        if was_falling_jump and self.vel_y == 0:
            self.jump_attack_active = False
            self.jump_attack_effect_timer = 45

        # AI: プレイヤーを追跡
        # ジャンプ攻撃中(空中〜着地エフェクト終了)と突き上げ攻撃中は唐笠を横に動かさない。
        if self.jump_attack_active or self.jump_attack_effect_timer > 0 or self.upthrust_timer > 0:
            pass
        elif self.attack_timer > 0:
            self.attack_timer -= 1
        else:
            if (self.upthrust_cooldown <= 0 and abs(player_x - self.x) < 170 and (
                    (player_y is not None and player_y < self.y + 30)
                    or self.attack_pattern % 2 == 1)):
                # 下から傘を突き上げる攻撃。
                # 空中ガヤへの対空として、または地上戦は交互に使う。
                self.upthrust_timer = BOSS_UPTHRUST_TOTAL_FRAMES
                self.upthrust_cooldown = BOSS_UPTHRUST_COOLDOWN + BOSS_UPTHRUST_TOTAL_FRAMES
                self.facing_right = player_x >= self.x
                self.attack_pattern += 1
                # ボス→プレイヤー方向の地面に沿って波の出現位置を等間隔で並べる。
                # ageは「開始から何フレーム経過したか」なので、溜め(WINDUP)中は
                # すべて負のままにして、溜め終了後に初めて0になり判定が生きる。
                wave_dir = 1 if self.facing_right else -1
                reach = min(abs(player_x - self.x), BOSS_UPTHRUST_WAVE_MAX_REACH)
                wave_step = max(70.0, reach / BOSS_UPTHRUST_WAVE_COUNT)
                self.upthrust_waves = []
                for wave_i in range(BOSS_UPTHRUST_WAVE_COUNT):
                    wave_x = self.x + wave_dir * wave_step * (wave_i + 1)
                    self.upthrust_waves.append({
                        "x": max(30.0, min(SCREEN_WIDTH - 30.0, wave_x)),
                        "age": -(BOSS_UPTHRUST_WINDUP_FRAMES
                                 + wave_i * BOSS_UPTHRUST_WAVE_SPACING_FRAMES),
                    })
            elif self.jump_attack_cooldown <= 0 and abs(player_x - self.x) < 260:
                self.jump_attack_active = True
                self.jump_attack_cooldown = 240
                self.vel_y = BOSS_JUMP_LAUNCH_VY
                self.jump_gif_frame = 0  # 攻撃アニメを先頭から再生
                # 発射〜同じ高さに戻るまでの滞空フレーム数を見積もる。
                # アニメ全体をこの時間に合わせて再生する(着地ちょうどに最終コマ)。
                probe_vy = float(BOSS_JUMP_LAUNCH_VY)
                probe_y = float(self.y)
                air_frames = 0
                while air_frames < 300:
                    probe_vy += BOSS_JUMP_GRAVITY
                    probe_y += probe_vy
                    air_frames += 1
                    if probe_vy >= 0 and probe_y >= self.y:
                        break
                self.jump_air_frames = max(1, air_frames)
            elif player_x < self.x - self.attack_range/2:
                self.x -= self.chase_speed
                self.facing_right = False
            elif player_x > self.x + self.attack_range/2:
                self.x += self.chase_speed
                self.facing_right = True
            else:
                self.attack_timer = 70 # 強力な攻撃 (予告時間を含めて猶予を増加)

        if self.x < 50: self.x = 50
        if self.x > SCREEN_WIDTH - 50: self.x = SCREEN_WIDTH - 50
        self.rect.x, self.rect.y = self.x - 30, self.y - 80

    def upthrust_phase(self):
        """突き上げ攻撃の現在フェーズを返す(None=使用中でない)"""
        if self.upthrust_timer <= 0:
            return None
        elapsed = BOSS_UPTHRUST_TOTAL_FRAMES - self.upthrust_timer
        if elapsed < BOSS_UPTHRUST_WINDUP_FRAMES:
            return "WINDUP"
        return "ACTIVE"

    def upthrust_wave_rects(self):
        """地面から生えている各波の当たり判定(伸び上がるほど高くなる)を返す。
        溜め(WINDUP)中は絶対に判定を出さない(溜め終了後にのみ発生する)。"""
        if self.upthrust_phase() == "WINDUP":
            return []
        rects = []
        ground_y = int(self.y + 50)
        wave_life = BOSS_UPTHRUST_WAVE_RISE_FRAMES + BOSS_UPTHRUST_WAVE_HOLD_FRAMES
        for wave in self.upthrust_waves:
            age = wave["age"]
            if age < 0 or age >= wave_life:
                continue
            progress = min(1.0, age / BOSS_UPTHRUST_WAVE_RISE_FRAMES)
            height = int(BOSS_UPTHRUST_WAVE_HIT_H * progress)
            if height <= 0:
                continue
            rects.append(pygame.Rect(
                int(wave["x"] - BOSS_UPTHRUST_WAVE_HIT_W / 2),
                ground_y - height,
                BOSS_UPTHRUST_WAVE_HIT_W,
                height,
            ))
        return rects

    def jump_gif_index(self):
        """ジャンプ攻撃アニメの現在コマ番号を返す(再生中でなければNone)

        空中では滞空時間に合わせて全体を早送り再生し、
        着地後(エフェクト表示中)は最終コマの着地姿勢を保持する。
        """
        if not self.jump_attack_active and self.jump_attack_effect_timer <= 0:
            return None
        if not boss_jump_frames:
            return None
        # 滞空中は進行度を全体長で打ち切る(見積もりより長引いても最終コマを超えない)
        if self.jump_attack_active:
            progress = min(float(self.jump_gif_frame), float(BOSS_JUMP_GIF_TOTAL_FRAMES))
        else:
            # 着地後は最終コマ固定
            progress = float(BOSS_JUMP_GIF_TOTAL_FRAMES)
        index = 0
        elapsed = 0.0
        for offset, hold_frames in enumerate(BOSS_JUMP_FRAME_FRAMES):
            elapsed += hold_frames
            if progress < elapsed:
                index = offset
                break
            index = offset
        return min(index, len(boss_jump_frames) - 1)

    def body_surface(self):
        """描画に使うスプライトと表示位置を返す（攻撃の予告などは含めない）"""
        # ジャンプ攻撃中は唐笠新ジャンプ.gifのアニメコマを使う
        gif_index = self.jump_gif_index()
        if gif_index is not None and BOSS_JUMP_ANCHOR is not None:
            image = boss_jump_frames[gif_index]
            if not self.facing_right:
                image = pygame.transform.flip(image, True, False)
            anchor_x, anchor_y = BOSS_JUMP_ANCHOR
            image_x = int(self.x - anchor_x)
            image_y = int(self.y + 50 - anchor_y)
            return image, image_x, image_y
        image = boss_image if self.facing_right else pygame.transform.flip(boss_image, True, False)
        image_bounds = boss_image_bounds if self.facing_right else pygame.Rect(
            image.get_width() - boss_image_bounds.right,
            boss_image_bounds.y,
            boss_image_bounds.width,
            boss_image_bounds.height
        )
        image_x = int(self.x - image_bounds.centerx)
        image_y = int(self.y + 50 - image_bounds.bottom)
        return image, image_x, image_y

    def draw_body(self, surface):
        """ボス本体だけを描く。撃破演出などで単独で使うため分けておく"""
        image, image_x, image_y = self.body_surface()
        surface.blit(image, (image_x, image_y))

    def draw(self, surface):
        dir_mod = 1 if self.facing_right else -1
        self.draw_body(surface)
        
        # 攻撃の予告とエフェクト
        if self.attack_timer > 10:
            # 予告: 赤い枠線で攻撃範囲を表示
            range_w = 80
            atk_x = self.x + (10 if self.facing_right else -(range_w + 10))
            pygame.draw.rect(surface, RED, (atk_x, self.y - 25, range_w, 60), 2)
        elif self.attack_timer > 0:
            # 攻撃発生時: オレンジ色のエフェクト
            swing_color = (255, 100, 0)
            atk_x = self.x + (40 * dir_mod)
            pygame.draw.ellipse(surface, swing_color, (atk_x - 40, self.y - 30, 80, 60), 5)

        # ジャンプ着地攻撃の範囲表示
        if self.jump_attack_active:
            pygame.draw.circle(surface, RED, (int(self.x), int(self.y + 45)), 110, 2)
        elif self.jump_attack_effect_timer > 0:
            radius = 80 + (45 - self.jump_attack_effect_timer) * 1
            effect_color = WHITE if self.jump_attack_effect_timer <= 15 else (255, 140, 0)
            pygame.draw.circle(surface, effect_color, (int(self.x), int(self.y + 45)), radius, 4)

        # 下から傘を突き上げる攻撃。
        # 予告は段階的: ①ボス足元の赤い溜め → ②出現位置を発射順に順次表示 →
        # ③発射直前は全マーカー白高速点滅。発生中は地面から波状に傘を生やす。
        upthrust_phase = self.upthrust_phase()
        if upthrust_phase is not None:
            ground_y = int(self.y + 50)
            if upthrust_phase == "WINDUP":
                elapsed = BOSS_UPTHRUST_TOTAL_FRAMES - self.upthrust_timer
                progress = min(1.0, elapsed / BOSS_UPTHRUST_WINDUP_FRAMES)

                # ── わかりやすい溜め演出 ──
                # ボス頭上にチャージゲージ(溜まり具合が一目で分かる)
                gauge_w = 76
                gauge_x = int(self.x - gauge_w / 2)
                gauge_y = int(self.y - 110)
                pygame.draw.rect(surface, (60, 60, 60), (gauge_x, gauge_y, gauge_w, 10))
                fill_w = int(gauge_w * progress)
                # 最後は白く光って発射直前を強調
                gauge_color = WHITE if progress >= 0.85 else (220, 40, 40)
                if fill_w > 0:
                    pygame.draw.rect(surface, gauge_color, (gauge_x, gauge_y, fill_w, 10))
                pygame.draw.rect(surface, (255, 255, 255), (gauge_x, gauge_y, gauge_w, 10), 1)

                # ボス足元の赤い溜めリング(溜めるほど広く速く脈動)
                pulse_phase = int(elapsed / max(2, 5 - int(progress * 3)))
                ring_radius = 26 + int(progress * 26) + (4 if pulse_phase % 2 == 0 else 0)
                pygame.draw.circle(surface, (220, 40, 40), (int(self.x), ground_y),
                                   ring_radius, 3)

                if elapsed < BOSS_UPTHRUST_MARKER_FIRST_FRAME:
                    # ① 前半: 溜めリングとゲージのみで「準備中」を示す
                    pass
                else:
                    # ② 後半: 各波の出現位置をボスから遠い順(=発射順)に順次表示
                    imminent = elapsed >= BOSS_UPTHRUST_WINDUP_FRAMES - 12
                    for wave_i, wave in enumerate(self.upthrust_waves):
                        marker_appear = (BOSS_UPTHRUST_MARKER_FIRST_FRAME
                                         + wave_i * BOSS_UPTHRUST_MARKER_STAGGER)
                        if elapsed < marker_appear:
                            continue
                        if imminent:
                            # ③ 発射直前: 全マーカーを白く高速点滅
                            if (elapsed // 2) % 2 == 0:
                                marker_color = WHITE
                            else:
                                continue
                        else:
                            marker_color = RED
                        wave_x = int(wave["x"])
                        pygame.draw.rect(surface, marker_color, (wave_x - 22, ground_y - 44, 44, 44), 2)
            elif boss_upthrust_bounds.width > 0 and boss_upthrust_bounds.height > 0:
                wave_life = BOSS_UPTHRUST_WAVE_RISE_FRAMES + BOSS_UPTHRUST_WAVE_HOLD_FRAMES
                rise_px = 76  # 地面から顔を出す距離(傘のサイズに合わせる)
                for wave in self.upthrust_waves:
                    age = wave["age"]
                    if age < 0 or age >= wave_life:
                        continue
                    # 伸び上がるほど下から顔を出す(波のように順に生える)
                    progress = min(1.0, age / BOSS_UPTHRUST_WAVE_RISE_FRAMES)
                    offset_y = int(rise_px * (1.0 - progress))
                    image_x = int(wave["x"] - boss_upthrust_bounds.centerx)
                    image_y = ground_y - boss_upthrust_bounds.bottom + offset_y
                    surface.blit(boss_upthrust_image, (image_x, image_y))
                    if progress < 1.0:
                        # 伸び上がり中は傘の頂点に白いラインを付けて動きを見やすくする
                        tip_top = image_y + boss_upthrust_bounds.y
                        pygame.draw.line(
                            surface, WHITE,
                            (int(wave["x"]) - 12, tip_top),
                            (int(wave["x"]) + 12, tip_top),
                            3,
                        )

class MidBoss(Boss):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.max_health = 30
        self.health = self.max_health
        self.phase = "IDLE"
        self.phase_timer = 0
        self.dash_count = 0
        self.dash_dir = 1
        # 突進は速く(5.8→8.5)。予測線を出すぶん速度で圧をかける。
        self.dash_speed = 8.5
        self.warning_timer = 0
        self.dash_dx = 1.0
        self.dash_dy = 0.0
        self.fan_attack_timer = 0
        self.ceiling_limit = MID_BOSS_CEILING_Y
        # 中級向けの攻撃パターン: ダッシュ、扇状弾、狙い撃ち3連弾
        self.attack_cycle = 0
        self.aim_angle = 0.0
        # Playerが攻撃できる隙: 攻撃と攻撃の間の待ち(IDLE)と、
        # 攻撃後の硬直(RECOVER系・FAN/AIMEDの後半)を長めに取る。
        self.idle_frames = 80
        # 突進前に鬼構え.pngの構えポーズを見せる予備動作時間。
        # 「力を溜めている」と分かるよう長めに取り、溜めの進行に合わせて
        # 赤い気合オーラを膨らませる演出(_draw_windup_charge_aura)を出す。
        self.first_windup_frames = 48
        self.bounce_windup_frames = 36
        self.dashes_before_fan = 2
        self.fan_spread_count = 3
        self.fan_fire_interval = 10
        self.fan_volley_limit = 25
        # 発射(〜25F)後に約45Fぼーっとする隙を作る
        self.fan_attack_end = 70
        self.aimed_warning_frames = 24
        # 発射(24F)後に約46F硬直する隙を作る
        self.aimed_attack_end = 70
        self.aimed_spread = 0.22
        self.aimed_bullet_speed = 4.5
        self.slam_target_x = float(x)
        self.slam_horizontal_speed = 0.0
        # 叩きつけ着地ポーズの見た目幅（横幅333に調整後）に合わせる。
        # 見た目通りに当たるよう、余白(+20)は付けない。
        self.slam_hit_width = mid_boss_slam_impact_bounds.width
        self.slam_warning_frames = 42
        # 着地後の隙を広げる(36→70F)。Playerが反撃しやすくする。
        self.slam_recover_frames = 70
        # 突進(DASH)でPlayerに当たる高さを絞る。見た目の上端・下端から
        # それぞれ何px内側に寄せるか(ジャンプでかわしやすくする用)。
        self.dash_hit_shrink_top = 28
        self.dash_hit_shrink_bottom = 18
        # 登場演出(ENTRANCE)用。ステージ開始時に画面左へ叩きつけながら現れる。
        # 演出中は無敵(battle_started=False)。赤鬼文字の表示タイマーも持つ。
        self.battle_started = True
        self.entrance_banner_timer = 0
        # 突進アニメ（鬼新突進.gif）の再生位置。DASHに入るたびに0へ戻して1周ぶん再生する
        self.dash_frame = 0
        # 被弾判定は見た目(不透明ピクセル範囲)に合わせる。基底の60x130は使わない。
        self.rect = pygame.Rect(0, 0, 10, 10)
        self.sync_hitbox()

    def start_entrance(self):
        """ステージ5開始時の登場演出を開始する。

        画面上空から画面左(MID_BOSS_ENTRANCE_TARGET_X)へ叩きつける。
        SLAM_WINDUP(予告:予測線)→SLAM_JUMP/SLAM_FALL(落下)→SLAM_RECOVER(着地)
        の流れをそのまま使い、着地後に赤鬼文字の名乗りを出して戦闘開始。
        演出中は無敵で、Playerへのダメージも与えない。
        """
        self.phase = "ENTRANCE_WINDUP"
        self.phase_timer = 0
        self.battle_started = False
        self.entrance_banner_timer = 0
        self.slam_target_x = float(MID_BOSS_ENTRANCE_TARGET_X)
        self.warning_timer = self.slam_warning_frames
        # 画面上空から落とす(天井より上から開始)
        self.x = float(MID_BOSS_ENTRANCE_TARGET_X)
        self.y = float(self.ceiling_limit - 260)
        self.vel_y = 0.0
        self.slam_horizontal_speed = 0.0
        self.facing_right = True
        self.dash_count = 0
        self.fan_attack_timer = 0
        self.sync_hitbox()

    def visual_bounds(self):
        """今のポーズの見た目(不透明ピクセル範囲)を画像内座標のRectで返す

        body_surface()と同じ向き(facing_right / dash_dx)のboundsを返す。
        毎フレームget_opaque_bounds()を回すと重いので、読み込み済みのbounds定数を使う。
        """
        dash_index = self.dash_pose_index()
        if dash_index is not None and MID_BOSS_DASH_ANCHOR is not None:
            frame = mid_boss_dash_frames[dash_index]
            # コマごとの不透明範囲は初回だけ計算して使い回す(毎フレーム走査は重い)
            if not hasattr(self, "_dash_bounds_cache"):
                self._dash_bounds_cache = {}
            bounds = self._dash_bounds_cache.get(dash_index)
            if bounds is None:
                bounds = get_opaque_bounds(frame)
                self._dash_bounds_cache[dash_index] = bounds
            if self.dash_dx >= 0:
                return bounds
            return pygame.Rect(
                frame.get_width() - bounds.right,
                bounds.y,
                bounds.width,
                bounds.height,
            )
        if self.phase == "WINDUP":
            if self.facing_right:
                return mid_boss_stance_image_bounds
            return pygame.Rect(
                200 - mid_boss_stance_image_bounds.right,
                mid_boss_stance_image_bounds.y,
                mid_boss_stance_image_bounds.width,
                mid_boss_stance_image_bounds.height,
            )
        if self.phase in ("SLAM_WINDUP", "ENTRANCE_WINDUP"):
            if self.facing_right:
                return mid_boss_slam_windup_bounds
            return pygame.Rect(
                mid_boss_slam_windup_image.get_width() - mid_boss_slam_windup_bounds.right,
                mid_boss_slam_windup_bounds.y,
                mid_boss_slam_windup_bounds.width,
                mid_boss_slam_windup_bounds.height,
            )
        if self.phase in ("SLAM_JUMP", "SLAM_FALL", "ENTRANCE_FALL"):
            if self.facing_right:
                return mid_boss_slam_jump_bounds
            return pygame.Rect(
                mid_boss_slam_jump_image.get_width() - mid_boss_slam_jump_bounds.right,
                mid_boss_slam_jump_bounds.y,
                mid_boss_slam_jump_bounds.width,
                mid_boss_slam_jump_bounds.height,
            )
        if self.phase in ("SLAM_RECOVER", "ENTRANCE_RECOVER"):
            if self.facing_right:
                return mid_boss_slam_impact_bounds
            return pygame.Rect(
                mid_boss_slam_impact_image.get_width() - mid_boss_slam_impact_bounds.right,
                mid_boss_slam_impact_bounds.y,
                mid_boss_slam_impact_bounds.width,
                mid_boss_slam_impact_bounds.height,
            )
        if self.facing_right:
            return mid_boss_image_bounds
        return pygame.Rect(
            mid_boss_image.get_width() - mid_boss_image_bounds.right,
            mid_boss_image_bounds.y,
            mid_boss_image_bounds.width,
            mid_boss_image_bounds.height,
        )

    def visual_hitbox(self):
        """今のポーズの見た目(不透明ピクセル範囲)を画面座標のRectで返す"""
        image, image_x, image_y = self.body_surface()
        bounds = self.visual_bounds()
        if bounds.width <= 0 or bounds.height <= 0:
            hitbox_shift = 0
            if self.phase in ("SLAM_RECOVER", "ENTRANCE_RECOVER"):
                hitbox_shift = MID_BOSS_SLAM_IMPACT_DRAW_SHIFT_X
            return pygame.Rect(int(self.x - 30 + hitbox_shift), int(self.y - 80), 60, 130)
        return pygame.Rect(
            int(image_x + bounds.x),
            int(image_y + bounds.y),
            bounds.width,
            bounds.height,
        )

    def sync_hitbox(self):
        """被弾判定を描画と同じ見た目に同期する（見た目と判定を常に一致させる）"""
        if self.phase in ("ENTRANCE_WINDUP", "ENTRANCE_FALL") or not self.battle_started:
            # 登場演出中は判定を外す（演出が終わるまで戦闘は開始しない＝無敵）
            # ENTRANCE_RECOVER(着地の名乗り中)も含め、battle_startedまで無敵。
            self.rect = pygame.Rect(0, 0, 0, 0)
            return
        self.rect = self.visual_hitbox()

    def dash_attack_rect(self):
        """突進(DASH)でPlayerにダメージを与える範囲。見た目より縦に絞る。

        被弾判定(self.rect / visual_hitbox)は見た目のままにして攻撃しやすさは維持し、
        Playerが受ける側の判定だけ上下を削ってジャンプでかわしやすくする。
        """
        box = self.visual_hitbox()
        top = box.y + self.dash_hit_shrink_top
        bottom = box.bottom - self.dash_hit_shrink_bottom
        if bottom <= top:
            # 絞りすぎて潰れたら中央1pxに丸める(判定消失の防止)
            mid = (box.y + box.bottom) // 2
            return pygame.Rect(box.x, mid, box.width, 1)
        return pygame.Rect(box.x, top, box.width, bottom - top)

    def slam_hit_rect(self):
        """叩きつけ着地時の当たり判定（鬼叩きつけ.pngの見た目と一致させる）"""
        bounds = mid_boss_slam_impact_bounds
        if bounds.width <= 0 or bounds.height <= 0:
            return pygame.Rect(
                int(self.slam_target_x - self.slam_hit_width / 2),
                435,
                self.slam_hit_width,
                100,
            )
        # 判定は予告位置(slam_target_x)基準。見た目の幅・高さで、足元(535)に置く。
        return pygame.Rect(
            int(self.slam_target_x - bounds.width / 2),
            int(535 - bounds.height),
            bounds.width,
            bounds.height,
        )

    def update(self, player, projectiles=None, platforms=None):
        if isinstance(player, Player):
            player_x = player.x
            player_obj = player
        else:
            player_x = player
            player_obj = None

        # プレイヤーの方向を向き、通常時は重力を適用する
        # 登場演出中(ENTRANCE_*)は専用処理なので、向き固定・重力なし。
        if self.phase not in ("ENTRANCE_WINDUP", "ENTRANCE_FALL", "ENTRANCE_RECOVER"):
            self.facing_right = player_x >= self.x
            self.dash_dir = 1 if player_x >= self.x else -1

        if self.phase not in ("DASH", "SLAM_JUMP", "SLAM_FALL", "ENTRANCE_WINDUP", "ENTRANCE_FALL", "ENTRANCE_RECOVER") and not (self.phase == "WINDUP" and self.dash_count > 0):
            self.vel_y += 0.8
            self.y += self.vel_y
            foot_rect = pygame.Rect(self.x - 30, self.y + 45, 60, 5)
            if platforms is not None:
                for plat in platforms:
                    if (self.phase != "FALL" or plat.top >= 535) and self.vel_y >= 0 and foot_rect.colliderect(plat):
                        self.y = plat.top - 50
                        self.vel_y = 0
                        break
            if self.y > 500:
                self.y = 500
                self.vel_y = 0

        # --- 登場演出: 画面左へ叩きつけ+赤鬼文字の名乗り ---
        if self.phase == "ENTRANCE_WINDUP":
            self.phase_timer += 1
            self.warning_timer = max(0, self.warning_timer - 1)
            # 予告中は上空で待機(落下はまだしない)
            if self.phase_timer >= self.slam_warning_frames:
                self.vel_y = -13
                # 落下フレーム数を数え、slam_target_xへ着地するよう水平速度を決める
                probe_vy = self.vel_y
                probe_y = self.y
                air_frames = 0
                while air_frames < 999:
                    probe_vy += 0.8
                    probe_y += probe_vy
                    air_frames += 1
                    if probe_y >= 485:
                        break
                self.slam_horizontal_speed = (self.slam_target_x - self.x) / max(1, air_frames)
                self.phase = "ENTRANCE_FALL"
                self.phase_timer = 0
            self.sync_hitbox()
            return

        if self.phase == "ENTRANCE_FALL":
            self.phase_timer += 1
            self.x += self.slam_horizontal_speed
            self.vel_y += 0.8
            self.y += self.vel_y
            if self.y >= 485:
                self.y = 485
                self.vel_y = 0
                self.phase = "ENTRANCE_RECOVER"
                self.phase_timer = 0
                self.dash_count = 0
                self.entrance_banner_timer = MID_BOSS_ENTRANCE_BANNER_FRAMES
                # 登場演出の叩きつけ着地時にも音を鳴らす（1回だけ）。
                if slam_sound is not None:
                    slam_sound.play(0)  # チャンネル0で強制再生（BGM/他効果音に負けない）
            self.sync_hitbox()
            return

        if self.phase == "ENTRANCE_RECOVER":
            self.phase_timer += 1
            if self.entrance_banner_timer > 0:
                self.entrance_banner_timer -= 1
            # 名乗りが終わったら戦闘開始(着地ポーズのままIDLEへ)
            if self.phase_timer >= self.slam_recover_frames:
                self.phase = "IDLE"
                self.phase_timer = 0
                self.battle_started = True
                self.entrance_banner_timer = 0
            self.sync_hitbox()
            return

        if self.phase == "IDLE":
            self.phase_timer += 1
            if self.phase_timer >= self.idle_frames:
                self.attack_cycle += 1
                self.phase_timer = 0
                if self.attack_cycle % 4 == 0:
                    self.phase = "SLAM_WINDUP"
                    self.slam_target_x = max(50, min(SCREEN_WIDTH - 50, player_x))
                    self.warning_timer = self.slam_warning_frames
                elif self.attack_cycle % 3 == 2:
                    self.phase = "AIMED_BURST"
                    self.warning_timer = self.aimed_warning_frames
                else:
                    self.phase = "WINDUP"
                    self.warning_timer = self.first_windup_frames
                self.dash_count = 0
                self.fan_attack_timer = 0

        elif self.phase == "WINDUP":
            self.phase_timer += 1
            self.warning_timer = max(0, self.warning_timer - 1)
            if self.phase_timer >= (self.bounce_windup_frames if self.dash_count > 0 else self.first_windup_frames):
                # 突進は地面を這う水平移動だけにする(飛ばない)。
                # プレイヤーが空中にいても縦方向は狙わず、上下の移動は一切しない。
                self.dash_dx = float(self.dash_dir)
                self.dash_dy = 0.0
                self.phase = "DASH"
                self.phase_timer = 0
                self.warning_timer = 0
                # 突進アニメを毎回先頭から再生する
                self.dash_frame = 0

        elif self.phase == "SLAM_WINDUP":
            self.phase_timer += 1
            self.warning_timer = max(0, self.warning_timer - 1)
            if self.phase_timer >= self.slam_warning_frames:
                self.slam_target_x = max(50, min(SCREEN_WIDTH - 50, self.slam_target_x))
                self.vel_y = -17
                # 実際の滞空フレーム数を縦の物理計算で数え、そのぶんで丁度 slam_target_x に
                # 着地するよう水平速度を決める。こうしないと予告や画像より奥に飛んでズレる。
                probe_vy = self.vel_y
                probe_y = self.y
                air_frames = 0
                while air_frames < 999:
                    probe_vy += 0.8
                    probe_y += probe_vy
                    air_frames += 1
                    if probe_y >= 485:
                        break
                self.slam_horizontal_speed = (self.slam_target_x - self.x) / max(1, air_frames)
                self.phase = "SLAM_JUMP"
                self.phase_timer = 0

        elif self.phase in ("SLAM_JUMP", "SLAM_FALL"):
            self.phase_timer += 1
            self.x += self.slam_horizontal_speed
            self.vel_y += 0.8
            self.y += self.vel_y
            if self.phase == "SLAM_JUMP" and self.vel_y >= 0:
                self.phase = "SLAM_FALL"
            if self.y >= 485:
                self.y = 485
                self.vel_y = 0
                self.phase = "SLAM_RECOVER"
                self.phase_timer = 0
                self.dash_count = 0
                # 攻撃発生(叩きつけ着地)の瞬間に叩きつけ音を1回だけ鳴らす。
                # SLAM_RECOVERへは1回の攻撃につき1回だけ遷移するため連鳴しない。
                if slam_sound is not None:
                    slam_sound.play(0)  # チャンネル0で強制再生（BGM/他効果音に負けない）
                if player_obj is not None:
                    # 当たり判定は鬼叩きつけ.pngの見た目の範囲に合わせる
                    hit_area = self.slam_hit_rect()
                    if player_obj.rect.colliderect(hit_area):
                        player_obj.take_damage()

        elif self.phase == "SLAM_RECOVER":
            self.phase_timer += 1
            if self.phase_timer >= self.slam_recover_frames:
                self.phase = "IDLE"
                self.phase_timer = 0

        elif self.phase == "DASH":
            self.phase_timer += 1
            # 突進アニメの再生位置を進める（立ち位置に合わせて足元が動かないよう1周ぶんループ）
            self.dash_frame += 1
            # 突進は水平方向のみ。浮かないように突進中も重力と足場判定をかける
            self.x += self.dash_dx * self.dash_speed
            self.vel_y += 0.8
            self.y += self.vel_y
            foot_rect = pygame.Rect(self.x - 30, self.y + 45, 60, 5)
            if platforms is not None:
                for plat in platforms:
                    if self.vel_y >= 0 and foot_rect.colliderect(plat):
                        self.y = plat.top - 50
                        self.vel_y = 0
                        break
            if self.y > 500:
                self.y = 500
                self.vel_y = 0

            if player_obj is not None and player_obj.rect.colliderect(self.dash_attack_rect()):
                player_obj.take_damage()

            # 突進は水平移動なので壁に当たったときだけ跳ね返る(床・天井には当たらない)
            wall_hit = self.x <= 50 or self.x >= SCREEN_WIDTH - 50
            if wall_hit:
                self.x = max(50, min(SCREEN_WIDTH - 50, self.x))
                self.phase_timer = 0
                self.dash_count += 1
                if self.dash_count >= self.dashes_before_fan:
                    self.phase = "FAN_ATTACK"
                    self.phase_timer = 0
                    self.dash_count = 0
                    self.fan_attack_timer = 0
                else:
                    self.phase = "WINDUP"
                    self.phase_timer = 0
                    self.warning_timer = self.bounce_windup_frames

        elif self.phase == "FALL":
            self.phase_timer += 1
            if self.y >= 500:
                self.y = 500
                self.phase = "RECOVER"
                self.phase_timer = 0
                self.dash_count = 0

        elif self.phase == "RECOVER":
            self.phase_timer += 1
            # 突進系の後の隙も広げる(20→50F)
            if self.phase_timer >= 50:
                self.phase = "IDLE"
                self.phase_timer = 0
                self.dash_count = 0

        elif self.phase == "FAN_ATTACK":
            self.phase_timer += 1
            self.fan_attack_timer += 1

            if self.phase_timer <= 16:
                self.y -= 0.5
            elif self.phase_timer <= 30:
                self.y += 0.35

            if self.fan_attack_timer % self.fan_fire_interval == 0 and self.fan_attack_timer <= self.fan_volley_limit:
                base_angle = 0 if self.facing_right else math.pi
                spread_count = self.fan_spread_count
                for i in range(spread_count):
                    angle = base_angle + (i - (spread_count - 1) / 2) * 0.28
                    proj = Projectile(
                        self.x + (20 if self.facing_right else -20),
                        self.y - 10,
                        angle,
                        color=(255, 140, 70),
                        speed=4.5,
                        image=mid_boss_kunai_image
                    )
                    projectiles.append(proj)

            if self.phase_timer >= self.fan_attack_end:
                self.phase = "IDLE"
                self.phase_timer = 0
                self.fan_attack_timer = 0
                self.warning_timer = 0

        elif self.phase == "AIMED_BURST":
            self.phase_timer += 1
            if self.phase_timer == 1:
                if player_obj is not None:
                    self.aim_angle = math.atan2(
                        player_obj.y - (self.y - 20),
                        player_obj.x - self.x
                    )
                else:
                    self.aim_angle = 0.0 if self.facing_right else math.pi
                self.warning_timer = self.aimed_warning_frames

            if self.phase_timer == self.aimed_warning_frames:
                for offset in (-self.aimed_spread, 0.0, self.aimed_spread):
                    projectiles.append(Projectile(
                        self.x + (20 if self.facing_right else -20),
                        self.y - 20,
                        self.aim_angle + offset,
                        color=(255, 180, 70),
                        speed=self.aimed_bullet_speed,
                        image=mid_boss_kunai_image
                    ))

            if self.phase_timer >= self.aimed_attack_end:
                self.phase = "IDLE"
                self.phase_timer = 0
                self.warning_timer = 0

        if self.x < 50:
            self.x = 50
        if self.x > SCREEN_WIDTH - 50:
            self.x = SCREEN_WIDTH - 50
        # 登場演出中は上空から落とすので天井補正をかけない
        if self.phase not in ("ENTRANCE_WINDUP", "ENTRANCE_FALL", "ENTRANCE_RECOVER"):
            if self.y < self.ceiling_limit:
                self.y = self.ceiling_limit
                if self.vel_y < 0:
                    self.vel_y = 0

        self.sync_hitbox()

    def dash_pose_index(self):
        """突進(DASH)中は鬼新突進.gifの何コマ目に見せるかを返す（それ以外はNone）

        dash_frame を1周ぶんのフレーム数で割ってGIFのコマ番号に変換する。
        突進が壁で跳ね返って間延びしても、アニメは足元を揃えたままループする。
        """
        if self.phase != "DASH" or not mid_boss_dash_frames:
            return None
        frame_in_cycle = self.dash_frame % MID_BOSS_DASH_CYCLE_FRAMES
        index = 0
        for offset, hold_frames in enumerate(MID_BOSS_DASH_FRAME_FRAMES):
            if frame_in_cycle < hold_frames:
                index = offset
                break
            frame_in_cycle -= hold_frames
        else:
            index = len(mid_boss_dash_frames) - 1
        return min(index, len(mid_boss_dash_frames) - 1)

    def body_surface(self):
        """描画に使うスプライトと表示位置を返す（攻撃の予告などは含めない）

        通常時は鬼立ち絵.pngの立ち絵、突進の予備動作(WINDUP)中は鬼構え.pngの構えポーズ、
        突進(DASH)中は鬼新突進.gifのアニメを表示する。
        叩きつけ攻撃(SLAM)では、予備動作(SLAM_WINDUP)に鬼ジャンプ予備.png、
        ジャンプ/落下中(SLAM_JUMP/SLAM_FALL)に鬼ジャンプ.png、
        着地して攻撃判定を出す(SLAM_RECOVER)に鬼叩きつけ.pngを表示する。
        登場演出(ENTRANCE_WINDUP→ENTRANCE_FALL→ENTRANCE_RECOVER)も同じ絵を使う。
        どれも足元（下端中央）が self.y + 50 に合うように置く。

        立ち絵はそのフレームの向き(facing_right)に応じて反転するが、
        突進アニメは「突進を開始したときの方向(dash_dx)」で向きを固定する。
        dash_dx は突進開始時に決まりダッシュ中は変わらないため、
        プレイヤーが動いても演出の途中で向きが反転することはない。
        構えポーズ(WINDUP)は、予備動作の間にプレイヤーの方向(facing_right)へ向けて反転する。
        """
        dash_index = self.dash_pose_index()
        if dash_index is not None and MID_BOSS_DASH_ANCHOR is not None:
            image = mid_boss_dash_frames[dash_index]
            anchor_x, anchor_y = MID_BOSS_DASH_ANCHOR
            # 下端中央を self.y+50 / self.x に揃える（コマが変わっても足元が動かない）
            image_x = int(self.x - anchor_x)
            image_y = int(self.y + 50 - anchor_y)
            # 向きは突進開始時の方向(dash_dx)で固定。左方向(dash_dx<0)のときだけ左右反転する。
            # 基準点はキャンバス中央なので反転しても描画位置は変わらない。
            if self.dash_dx < 0:
                image = pygame.transform.flip(image, True, False)
            return image, image_x, image_y

        # 突進の予備動作(WINDUP)中は鬼構え.pngの構えポーズを表示する
        if self.phase == "WINDUP":
            image = mid_boss_stance_image if self.facing_right else pygame.transform.flip(mid_boss_stance_image, True, False)
            image_bounds = mid_boss_stance_image_bounds if self.facing_right else pygame.Rect(
                200 - mid_boss_stance_image_bounds.right,
                mid_boss_stance_image_bounds.y,
                mid_boss_stance_image_bounds.width,
                mid_boss_stance_image_bounds.height
            )
            image_x = int(self.x - image_bounds.centerx)
            image_y = int(self.y + 50 - image_bounds.bottom)
            return image, image_x, image_y

        # 叩きつけ攻撃(SLAM)のポーズ。向きは予備動作〜着地までプレイヤーの方向(facing_right)に
        # 合わせて反転し、足元(下端中央)は self.y + 50 に揃える（立ち絵と同じ基準で足元が動かない）。
        if self.phase in ("SLAM_WINDUP", "ENTRANCE_WINDUP"):
            image = mid_boss_slam_windup_image if self.facing_right else pygame.transform.flip(mid_boss_slam_windup_image, True, False)
            bounds = mid_boss_slam_windup_bounds if self.facing_right else pygame.Rect(
                mid_boss_slam_windup_image.get_width() - mid_boss_slam_windup_bounds.right,
                mid_boss_slam_windup_bounds.y,
                mid_boss_slam_windup_bounds.width,
                mid_boss_slam_windup_bounds.height
            )
            image_x = int(self.x - bounds.centerx)
            image_y = int(self.y + 50 - bounds.bottom)
            return image, image_x, image_y

        if self.phase in ("SLAM_JUMP", "SLAM_FALL", "ENTRANCE_FALL"):
            image = mid_boss_slam_jump_image if self.facing_right else pygame.transform.flip(mid_boss_slam_jump_image, True, False)
            bounds = mid_boss_slam_jump_bounds if self.facing_right else pygame.Rect(
                mid_boss_slam_jump_image.get_width() - mid_boss_slam_jump_bounds.right,
                mid_boss_slam_jump_bounds.y,
                mid_boss_slam_jump_bounds.width,
                mid_boss_slam_jump_bounds.height
            )
            image_x = int(self.x - bounds.centerx)
            image_y = int(self.y + 50 - bounds.bottom)
            return image, image_x, image_y

        if self.phase in ("SLAM_RECOVER", "ENTRANCE_RECOVER"):
            image = mid_boss_slam_impact_image if self.facing_right else pygame.transform.flip(mid_boss_slam_impact_image, True, False)
            bounds = mid_boss_slam_impact_bounds if self.facing_right else pygame.Rect(
                mid_boss_slam_impact_image.get_width() - mid_boss_slam_impact_bounds.right,
                mid_boss_slam_impact_bounds.y,
                mid_boss_slam_impact_bounds.width,
                mid_boss_slam_impact_bounds.height
            )
            # 見た目だけ少し左へ寄せる(予告・攻撃判定はそのまま)
            image_x = int(self.x - bounds.centerx + MID_BOSS_SLAM_IMPACT_DRAW_SHIFT_X)
            image_y = int(self.y + 50 - bounds.bottom)
            return image, image_x, image_y

        image = mid_boss_image if self.facing_right else pygame.transform.flip(mid_boss_image, True, False)
        image_bounds = mid_boss_image_bounds if self.facing_right else pygame.Rect(
            image.get_width() - mid_boss_image_bounds.right,
            mid_boss_image_bounds.y,
            mid_boss_image_bounds.width,
            mid_boss_image_bounds.height
        )
        image_x = int(self.x - image_bounds.centerx)
        image_y = int(self.y + 50 - image_bounds.bottom)
        return image, image_x, image_y

    def _draw_kunai_marker(self, surface):
        """遠距離攻撃の予告として、赤鬼の頭上に赤いクナイマークを描く。"""
        if mid_boss_kunai_image is None:
            return
        marker_h = 36
        w, h = mid_boss_kunai_image.get_size()
        marker_w = max(1, round(w * marker_h / max(1, h)))
        marker = pygame.transform.smoothscale(mid_boss_kunai_image, (marker_w, marker_h))
        # クナイ本体を赤く色付け(白黒素材でも赤く見えるよう乗算で色を重ねる)
        red_tint = pygame.Surface((marker_w, marker_h), pygame.SRCALPHA)
        red_tint.fill((255, 60, 60, 255))
        red_tint.blit(marker, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        red_tint.set_alpha(235)
        cx = int(self.x)
        cy = int(self.y - 140)
        if cy < 34:
            cy = 34
        # 背後に赤い円で囲み「マーク」として分かりやすくする
        pygame.draw.circle(surface, (120, 16, 16), (cx, cy), 28, 3)
        surface.blit(red_tint, (cx - marker_w // 2, cy - marker_h // 2))

    def _draw_windup_charge_aura(self, surface):
        """突進の予備動作(WINDUP)中に、力を溜めていることを示すオーラを描く。

        溜めの進行に合わせてオーラが広がり・赤みが強くなり、
        終盤ほど速く明滅する。着達直前が一番熱い見た目になる。
        """
        windup_total = self.bounce_windup_frames if self.dash_count > 0 else self.first_windup_frames
        progress = min(1.0, self.phase_timer / max(1, windup_total))  # 0.0 → 1.0
        cx = int(self.x)
        cy = int(self.y + 10)
        # 準備が進むほど半径が大きくなる(60→110px)
        radius = int(60 + 50 * progress)
        # 進行後半ほど明滅が速くなる(終盤は2F周期で強く点く)
        if progress >= 0.75:
            pulse = (self.phase_timer // 2) % 2
        elif progress >= 0.4:
            pulse = (self.phase_timer // 4) % 2
        else:
            pulse = 1
        # 内側の光: 準備が進むほど赤が濃く・不透明になる
        glow_alpha = int(60 + 120 * progress)
        if pulse:
            glow_alpha = min(230, glow_alpha + 45)
        glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        glow_color = (255, int(120 - 70 * progress), int(40 - 20 * progress), glow_alpha)
        pygame.draw.circle(glow, glow_color, (radius, radius), radius)
        surface.blit(glow, (cx - radius, cy - radius))
        # 外周のリング: 準備終盤ほど太く・明るくする
        ring_width = 2 + int(3 * progress)
        ring_color = (255, int(150 - 60 * progress), 40) if not pulse else (255, 230, 150)
        pygame.draw.circle(surface, ring_color, (cx, cy), radius + 6, ring_width)

    def draw(self, surface):
        # 溜めオーラは本体の背面に出す
        if self.phase == "WINDUP":
            self._draw_windup_charge_aura(surface)
        self.draw_body(surface)

        # 遠距離攻撃(FAN_ATTACK / AIMED_BURST)の予告は予測線ではなく、
        # 発射前に赤いクナイマークを赤鬼の頭上へ点滅表示する。
        # 次の行動が遠距離になる時点で、その直前(待機IDLEの終盤・
        # 扇状弾へ繋がる直前の構えWINDUP)からも先出しする。
        kunai_marker_visible = False
        if self.phase == "FAN_ATTACK" and self.phase_timer <= self.fan_volley_limit:
            kunai_marker_visible = True
        elif self.phase == "AIMED_BURST" and self.phase_timer <= self.aimed_warning_frames:
            kunai_marker_visible = True
        elif self.phase == "WINDUP" and self.dash_count + 1 >= self.dashes_before_fan:
            # この構えのあとの突進で扇状弾に移る → 構えの時点からマークを出す
            kunai_marker_visible = True
        elif self.phase == "IDLE" and self.phase_timer >= max(0, self.idle_frames - 20):
            next_cycle = self.attack_cycle + 1
            if next_cycle % 4 != 0 and next_cycle % 3 == 2:
                # 次の攻撃が狙い撃ち(AIMED_BURST) → 待機の終盤からマークを出す
                kunai_marker_visible = True

        if kunai_marker_visible and mid_boss_kunai_image is not None:
            # 12F周期の点滅(4F消し)。消えている間も頭上の位置は分かるよう残る印象に。
            mark_blink = (self.phase_timer // 4) % 3 != 2
            if mark_blink:
                self._draw_kunai_marker(surface)

        # 叩きつけ(SLAM系)・登場演出(ENTRANCE_WINDUP/FALL)の予測線
        if self.phase in ("SLAM_WINDUP", "SLAM_JUMP", "SLAM_FALL", "ENTRANCE_WINDUP", "ENTRANCE_FALL"):
            hit_area = self.slam_hit_rect()
            warning_color = (255, 80, 80) if self.phase_timer % 12 < 6 else (255, 190, 60)
            pygame.draw.rect(surface, warning_color, hit_area, 3)
            pygame.draw.line(
                surface,
                warning_color,
                (int(self.slam_target_x), 435),
                (int(self.slam_target_x), 535),
                2
            )
            if self.phase in ("SLAM_JUMP", "SLAM_FALL", "ENTRANCE_FALL"):
                pygame.draw.line(
                    surface,
                    (255, 160, 60),
                    (int(self.x), int(self.y + 35)),
                    (int(self.slam_target_x), 435),
                    2
                )

        # --- 登場演出の名乗り「赤鬼文字.png」のみ ---
        # 叩きつけ着地後(ENTRANCE_RECOVER)に一度だけ表示する。
        # 予告中(ENTRANCE_WINDUP/FALL)には出さない。
        if self.phase == "ENTRANCE_RECOVER":
            if akaoni_title_image is not None and self.entrance_banner_timer > 0:
                # 着地直後はフェードイン→その後フェードアウトの1回表示
                elapsed = MID_BOSS_ENTRANCE_BANNER_FRAMES - self.entrance_banner_timer
                if elapsed < MID_BOSS_ENTRANCE_BANNER_FADE:
                    banner_alpha = int(255 * elapsed / MID_BOSS_ENTRANCE_BANNER_FADE)
                    banner_zoom = 1.35 - 0.35 * (elapsed / MID_BOSS_ENTRANCE_BANNER_FADE)
                else:
                    banner_alpha = int(255 * self.entrance_banner_timer / MID_BOSS_ENTRANCE_BANNER_FRAMES)
                    banner_zoom = 1.0
                if banner_alpha > 0:
                    base_w, base_h = akaoni_title_image.get_size()
                    target_w = min(460, base_w)
                    target_h = max(1, round(base_h * target_w / max(1, base_w)))
                    scaled_w = max(1, round(target_w * banner_zoom))
                    scaled_h = max(1, round(target_h * banner_zoom))
                    logo = pygame.transform.smoothscale(akaoni_title_image, (scaled_w, scaled_h))
                    logo.set_alpha(banner_alpha)
                    surface.blit(logo, (SCREEN_WIDTH // 2 - scaled_w // 2, 120))

class HiddenBoss(Boss):
    def __init__(self, x, y):
        super().__init__(x, y)
        # Strong but fair final boss: patterns are learnable instead of blind unfair kills.
        self.max_health = 80
        self.health = self.max_health
        self.phase = "IDLE"
        self.phase_timer = 0
        self.particles = []
        self.laser_xs = [0, 0]
        self.laser_y = 300
        self.safe_left = 0
        self.safe_right = SCREEN_WIDTH
        self.summon_timer = 0
        self.is_second_phase = False
        self.is_final_phase = False
        self.safe_rect = pygame.Rect(0, 0, 0, 0)
        self.recent_phases = []
        self.overdrive_target = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.laser_player_index = 0
        self.column_width = SCREEN_WIDTH / 3
        self.column_left = 0.0
        self.column_damage_applied = False
        # 大ビームの連続数（いま何連続目か / 何回まで連続するか）
        self.column_streak = 0
        self.column_streak_target = 1
        # ビーム音の予告（当たり判定の BEAM_SOUND_LEAD_FRAMES フレーム前に鳴らす）の予約
        self.beam_sound_timer = None   # 発声までの残りフレーム
        self.beam_sound_queue = []     # 予告音どうしの間隔（前の音から何フレーム後か）
        self.beam_sound_phase = None   # 予告音を予約したフェーズ名
        self.beam_sound_start_delay = None  # その予約の攻撃開始までの残りフレーム
        self.beam_sound_played = 0     # その予約で既に鳴らした回数
        self.pending_phase = None      # 予告音のために先に決めておく次のフェーズ
        self.pending_idle_limit = None # 先読みしたときの待機フレーム数
        self.pending_shot_sounds = 0   # まだ鳴らしていない発射音の残り回数
        self.shot_sound_cool = 0       # 次に発射音を鳴らすまでの残りフレーム
        # 待機アニメーションを使う素材設定のときの再生位置（通常時は静止画なので使われない）。
        self.idle_frame = 0
        # 入場演出(ENTRANCE)の状態。start_entrance() を呼ぶと False になり、
        # 着地して戦闘が始まると True になる（BGMとHPバーはこの合図で動き出す）
        self.battle_started = True
        self.entrance_banner_timer = 0   # 名乗りのフェードアウト残りフレーム
        self.landing_effect_timer = 0    # 着地ダストの残りフレーム
        # 見た目のスプライトに合わせて当たり判定を作り直す（基底クラスの60x130は使わない）
        self.rect = pygame.Rect(0, 0, HIDDEN_BOSS_BOX.width, HIDDEN_BOSS_BOX.height)
        self.sync_hitbox()

    def sync_hitbox(self):
        """描画位置と同じ計算式で当たり判定を同期する（見た目と判定を常に一致させる）"""
        if self.phase == "ENTRANCE":
            # 入場演出中は判定を外す（演出が終わるまで戦闘は開始しない＝無敵）
            self.rect = pygame.Rect(0, 0, 0, 0)
            return
        box = HIDDEN_BOSS_BOX if self.facing_right else HIDDEN_BOSS_BOX_FLIPPED
        self.rect = pygame.Rect(
            int(self.x - hidden_boss_image.get_width() / 2 + box.x),
            int(self.y - HIDDEN_BOSS_DRAW_OFFSET_Y + box.y),
            box.width,
            box.height,
        )

    def start_entrance(self):
        """ステージ6に入場するときの演出を開始する（画面上からゆっくり降りてくる）"""
        self.phase = "ENTRANCE"
        self.phase_timer = 0
        self.battle_started = False
        self.entrance_banner_timer = 0
        self.landing_effect_timer = 0
        self.y = HIDDEN_BOSS_ENTRANCE_START_Y
        self.vel_y = 0
        self.sync_hitbox()

    def pick_next_phase(self):
        """次の攻撃フェーズを決める。発声やフェーズ遷移はここでは行わない"""
        if self.is_final_phase:
            phase_weights = [
                ("LASER", 3),
                ("CROSS_LASER", 3),
                ("SHRINK_LASER", 2),
                ("ALTERNATE_LASER", 3),
                ("MELEE", 2),
                ("FAN_ATTACK", 3),
                ("TRIPLE_COLUMN", 2),
                ("WARP", 1),
            ]
        elif self.is_second_phase:
            phase_weights = [
                ("WARP", 2),
                ("LASER", 3),
                ("CROSS_LASER", 3),
                ("SHRINK_LASER", 2),
                ("ALTERNATE_LASER", 2),
                ("MELEE", 2),
                ("FAN_ATTACK", 3),
                ("TRIPLE_COLUMN", 2),
            ]
        else:
            phase_weights = [
                ("WARP", 2),
                ("LASER", 3),
                ("CROSS_LASER", 2),
                ("SHRINK_LASER", 2),
                ("ALTERNATE_LASER", 2),
                ("MELEE", 2),
                ("FAN_ATTACK", 3),
                ("TRIPLE_COLUMN", 1),
            ]

        recent = set(self.recent_phases[-2:])
        filtered = [(phase, weight) for phase, weight in phase_weights if phase not in recent]
        if not filtered:
            filtered = phase_weights

        phases = [phase for phase, _ in filtered]
        weights = [weight for _, weight in filtered]
        next_phase = random.choices(phases, weights=weights, k=1)[0]
        self.recent_phases.append(next_phase)
        if len(self.recent_phases) > 6:
            self.recent_phases.pop(0)
        return next_phase

    def start_phase(self, phase_name):
        """攻撃フェーズを開始する（ビーム音の予告は start_phase 前に予約済み）"""
        self.phase = phase_name
        self.phase_timer = 0
        self.pending_phase = None
        self.pending_idle_limit = None
        self.column_streak = 0
        if phase_name == "TRIPLE_COLUMN":
            # 大ビームはたまに3連続する。何連続するかは開始時にランダムで決める
            self.column_streak_target = (
                TRIPLE_COLUMN_CHAIN_LENGTH
                if random.random() < TRIPLE_COLUMN_CHAIN_CHANCE
                else 1
            )
        else:
            self.column_streak_target = 1

    def update_idle_phase(self, idle_limit):
        """待機フェーズを処理する

        ビーム音の予告は攻撃が始まるより前に鳴らさないといけないため、
        0.9秒ぶん余裕をみて次の攻撃を先読みしておく。
        """
        if self.pending_phase is None:
            if self.phase_timer < idle_limit - BEAM_SOUND_LEAD_FRAMES:
                return
            self.pending_phase = self.pick_next_phase()
            self.pending_idle_limit = None
            # 新しい攻撃なので予告音は1発目から鳴らす
            self.beam_sound_played = 0
        if self.pending_idle_limit != idle_limit:
            self.pending_idle_limit = idle_limit
            # 攻撃は idle_limit + 1 フレーム目の遷移で始まる。
            # 二段階目・最終段階への移行で待機時間が変わる場合は、
            # まだ1発目も鳴らしていないときだけ予約を張り直す
            # （鳴らし終えた音の時刻はもう変わらないので張り直せない）
            if self.beam_sound_played == 0:
                self.queue_beam_sounds(
                    self.pending_phase,
                    start_delay=idle_limit + 1 - self.phase_timer,
                )
        if self.phase_timer > idle_limit:
            self.start_phase(self.pending_phase)

    def fire_projectiles(self, projectiles, bullets):
        """弾をまとめて発射する。1発の弾につき1回、発射音を鳴らす

        同じフレームで play() を重ねると1音に潰れて聞こえないので、
        実際に鳴らすのは tick_shot_sounds() が一定間隔で進める。
        """
        if not bullets:
            return
        projectiles.extend(bullets)
        self.pending_shot_sounds += len(bullets)

    def tick_shot_sounds(self):
        """予約された発射音を SHOT_SOUND_STAGGER フレームごとに1回鳴らす"""
        if self.pending_shot_sounds <= 0:
            return
        if self.shot_sound_cool > 0:
            self.shot_sound_cool -= 1
            return
        self.pending_shot_sounds -= 1
        self.shot_sound_cool = SHOT_SOUND_STAGGER - 1
        play_shot_sound()

    def clear_beam_sounds(self):
        """予約済みのビーム音を破棄する"""
        self.beam_sound_timer = None
        self.beam_sound_queue = []
        self.beam_sound_phase = None
        self.beam_sound_start_delay = None
        self.beam_sound_played = 0

    def queue_beam_sounds(self, phase_name, start_delay=0):
        """phase_name の攻撃について、ビーム音を鳴らすタイミングを予約する

        start_delay はその攻撃が始まるまでの残りフレーム。
        効果音は当たり判定の BEAM_SOUND_LEAD_FRAMES フレーム（0.9秒）前に鳴らしたいので、
        1発目の予告音がフェーズ開始より前になる攻撃もある。
        その場合はフェーズ遷移前（IDLE中）に start_delay を指定して呼べば素直に前倒しできる。
        キューには「今から何フレーム後か」ではなく「前の音から何フレーム後か」を入れる。
        """
        if self.beam_sound_phase == phase_name and self.beam_sound_start_delay == start_delay:
            # フェーズ開始前に先読みして、同じ内容で予約済みなら何もしない
            return
        self.clear_beam_sounds()
        hit_frames = BEAM_PHASE_HIT_FRAMES.get(phase_name, ())
        if not hit_frames:
            return
        self.beam_sound_phase = phase_name
        self.beam_sound_start_delay = start_delay
        queue = []
        previous = 0
        for frame in hit_frames:
            # 発声は「攻撃開始から frame - BEAM_SOUND_LEAD_FRAMES フレーム後」にする
            target = start_delay + frame - BEAM_SOUND_LEAD_FRAMES
            queue.append(target - previous)
            previous = target
        self.beam_sound_queue = queue
        self.arm_beam_sound()

    def arm_beam_sound(self):
        """次に鳴らす予告音をタイマーに載せる"""
        if self.beam_sound_queue and self.beam_sound_timer is None:
            self.beam_sound_timer = self.beam_sound_queue[0]

    def tick_beam_sound(self):
        """1フレーム進める更新。鳴らすフレームに到達したらビーム音を再生する"""
        if self.beam_sound_timer is None:
            return
        self.beam_sound_timer -= 1
        if self.beam_sound_timer <= 0:
            self.beam_sound_timer = None
            self.beam_sound_played += 1
            if self.beam_sound_queue:
                self.beam_sound_queue.pop(0)
            play_beam_sound()
            self.arm_beam_sound()



    def update(self, player, projectiles, platforms, enemies):
        # 途中で攻撃が切り替わってもチャージ音が鳴りっぱなしにならないようにする
        # （Overdrive前演出の溜めの音は演出中だけ鳴らしたいので除外する）
        if self.phase not in ("TRIPLE_COLUMN", "OVERDRIVE_INTRO") and beam_charge_playing:
            stop_beam_charge_sound()

        # 重力と衝突処理 (扇状攻撃中・Overdrive前演出中・入場演出中は浮遊)
        if self.phase not in ("FAN_ATTACK", "OVERDRIVE_INTRO", "ENTRANCE"):
            self.vel_y += 0.8
            self.y += self.vel_y

            # 足場との衝突判定を追加（高台に留まれるようにする）
            foot_rect = pygame.Rect(self.x - 30, self.y + 45, 60, 5)
            for plat in platforms:
                if self.vel_y >= 0 and foot_rect.colliderect(plat):
                    self.y = plat.top - 50
                    self.vel_y = 0
                    break

            if self.y > 500: self.y = 500; self.vel_y = 0

        # Phase escalation: the final 20% HP triggers a dramatic Overdrive phase.
        if self.health <= self.max_health // 2:
            self.is_second_phase = True
        if self.health <= self.max_health // 5 and not self.is_final_phase:
            self.is_final_phase = True
            # 大技はいきなり撃たず、まず前演出(OVERDRIVE_INTRO)で溜めを見せる
            self.phase = "OVERDRIVE_INTRO"
            self.phase_timer = 0
            self.recent_phases.append("OVERDRIVE")
            # 先読みしていた攻撃とビーム音の予告はここで破棄する
            self.pending_phase = None
            self.clear_beam_sounds()
            self.column_streak = 0

        # 状態管理タイマー
        self.phase_timer += 1
        # 入場演出の名乗りフェード・着地ダストのタイマー
        if self.entrance_banner_timer > 0:
            self.entrance_banner_timer -= 1
        if self.landing_effect_timer > 0:
            self.landing_effect_timer -= 1
        # ビーム音の予告（当たり判定の0.9秒前に鳴らす）と発射音（1発ずつ）
        self.tick_beam_sound()
        self.tick_shot_sounds()

        # 攻撃間隔: Gets shorter as the boss gets closer to defeat.
        idle_limit = 24 if self.is_final_phase else (34 if self.is_second_phase else 50)
        if self.phase == "IDLE":
            self.update_idle_phase(idle_limit)

        

        if self.phase == "ENTRANCE":
            # 入場演出: 画面外からゆっくり降りて、着地した瞬間に
            # BGMが流れ出して戦闘が始まる（この間は無敵で攻撃もしてこない）
            descend_frames = HIDDEN_BOSS_ENTRANCE_FRAMES
            if self.phase_timer < descend_frames:
                p = self.phase_timer / descend_frames
                # 始まりと終わりがゆるやかになるスムーズ減速で「ゆっくり」降りる
                eased = p * p * (3.0 - 2.0 * p)
                self.y = HIDDEN_BOSS_ENTRANCE_START_Y + (
                    HIDDEN_BOSS_ENTRANCE_LANDING_Y - HIDDEN_BOSS_ENTRANCE_START_Y
                ) * eased
            elif self.phase_timer == descend_frames:
                # 着地: ダストと衝撃を出し、この瞬間から戦闘(BGM)開始
                self.y = HIDDEN_BOSS_ENTRANCE_LANDING_Y
                self.landing_effect_timer = HIDDEN_BOSS_ENTRANCE_LANDING_FRAMES
                self.entrance_banner_timer = HIDDEN_BOSS_ENTRANCE_LANDING_FRAMES
                play_beam_cannon_sound()  # 着地の地響き（砲撃音を流用）
                self.battle_started = True
                self.phase = "IDLE"
                self.phase_timer = 0

        if self.phase == "WARP":
            if self.phase_timer == 10:
                # 高台(3か所)または地上のいずれかにワープ
                dest = random.choice([(175, 250), (625, 250), (400, 370), (400, 500)])
                self.x, self.y = dest
            elif self.phase_timer > 30:
                self.phase = "IDLE"; self.phase_timer = 0

        # Laser phases are telegraphed and escalate only after the fight has started.
        elif self.phase == "LASER":
            # Basic laser walls, with a third beam in the late phase.
            if self.phase_timer == 1:
                beam_count = 3 if self.is_final_phase else 2
                base_x = max(40, min(SCREEN_WIDTH - 40, int(player.x)))
                self.laser_xs = [base_x]
                for offset in random.sample([-220, -150, -90, 90, 150, 220], beam_count - 1):
                    self.laser_xs.append(max(40, min(SCREEN_WIDTH - 40, base_x + offset)))
                self.laser_xs.sort()
            # 効果音は当たり判定の0.9秒前に鳴ら済み（queue_beam_sounds）
            if self.phase_timer == 42:
                hit_width = 30 if self.is_final_phase else 40
                for lx in self.laser_xs:
                    if abs(player.x - lx) < hit_width:
                        player.take_damage()
                        break
            if self.phase_timer >= 66:
                self.phase = "IDLE"; self.phase_timer = 0

        elif self.phase == "CROSS_LASER":
            # A two-step cross laser: first telegraph, then a delayed second cross.
            if self.phase_timer == 1:
                cross_x = max(40, min(SCREEN_WIDTH - 40, int(player.x)))
                cross_x += random.randint(-70, 70)
                self.laser_xs = [max(40, min(SCREEN_WIDTH - 40, cross_x))]
                cross_y = max(100, min(500, int(player.y)))
                self.laser_y = max(100, min(500, cross_y + random.randint(-55, 55)))
            # 効果音は当たり判定の0.9秒前に鳴ら済み（queue_beam_sounds）
            if self.phase_timer == 42:
                if abs(player.x - self.laser_xs[0]) < 40 or abs(player.y - self.laser_y) < 30:
                    player.take_damage()
            if self.phase_timer == 66:
                self.laser_xs[0] = max(40, min(SCREEN_WIDTH - 40, self.laser_xs[0] + random.choice([-120, 120])))
                self.laser_y = max(100, min(500, self.laser_y + random.choice([-70, 70])))
            if self.phase_timer == 76:
                if abs(player.x - self.laser_xs[0]) < 36 or abs(player.y - self.laser_y) < 26:
                    player.take_damage()
            if self.phase_timer >= 94:
                self.phase = "IDLE"; self.phase_timer = 0

        elif self.phase == "SHRINK_LASER":
            if self.phase_timer == 1:
                self.safe_left = 40
                self.safe_right = SCREEN_WIDTH - 40
            if self.phase_timer <= 45:
                max_shrink = 300 if self.is_final_phase else 260
                shrink = int((self.phase_timer / 45) * max_shrink)
                self.safe_left = 40 + shrink
                self.safe_right = SCREEN_WIDTH - 40 - shrink
            if self.phase_timer == 45:
                if player.x < self.safe_left or player.x > self.safe_right:
                    player.take_damage()
            if self.phase_timer >= 65:
                self.phase = "IDLE"; self.phase_timer = 0

        elif self.phase == "TRIPLE_COLUMN":
            # 画面幅の1/3を覆う大きなビーム。予測線を出してからチャージ音 → 砲撃音の順で鳴らす
            if self.phase_timer == 1:
                self.column_width = SCREEN_WIDTH / 3
                self.column_left = max(
                    0.0,
                    min(SCREEN_WIDTH - self.column_width, player.x - self.column_width / 2)
                )
                self.column_damage_applied = False
                self.column_streak += 1
                # 予測線とほぼ同時にチャージ音を鳴らす（鳴らすのは1.5秒 = 予測線の表示時間）
                play_beam_charge_sound()
            if self.phase_timer == 90:
                # 予測線が消えて攻撃判定が出るので、チャージ音を止めて砲撃音を鳴らす
                stop_beam_charge_sound()
                play_beam_cannon_sound()
                if not self.column_damage_applied and self.column_left <= player.x < self.column_left + self.column_width:
                    player.take_damage()
                self.column_damage_applied = True
            if self.phase_timer >= 126:
                # 3連続する設定なら、待機せずそのまま続けて撃つ
                if self.column_streak < self.column_streak_target:
                    self.phase_timer = 0
                else:
                    self.phase = "IDLE"
                    self.phase_timer = 0
                    self.column_streak = 0


        elif self.phase == "ALTERNATE_LASER":
            if self.phase_timer == 1:
                player_x = int(player.x)
                self.laser_xs = [40, 143, 246, 349, 451, 554, 657, 760]
                self.laser_player_index = min(
                    range(len(self.laser_xs)),
                    key=lambda index: abs(self.laser_xs[index] - player_x)
                )
                self.laser_xs[self.laser_player_index] = max(40, min(SCREEN_WIDTH - 40, player_x))
                self.laser_xs.sort()
                self.laser_player_index = min(
                    range(len(self.laser_xs)),
                    key=lambda index: abs(self.laser_xs[index] - player_x)
                )
            if self.phase_timer in (40, 64, 88, 112):
                if self.phase_timer == 40:
                    active_indices = set(range(len(self.laser_xs)))
                else:
                    parity = ((self.phase_timer - 64) // 24) % 2
                    active_indices = set(range(parity, len(self.laser_xs), 2))
                hit_width = 18 if self.is_final_phase else 14
                for index in active_indices:
                    if abs(player.x - self.laser_xs[index]) < hit_width:
                        player.take_damage()
                        break
            if self.phase_timer >= 132:
                self.phase = "IDLE"; self.phase_timer = 0

        elif self.phase == "MELEE":
            # Close-range shockwave with a readable wind-up and late-phase extra pressure.
            if self.phase_timer in (52, 76) and self.is_final_phase:
                self.fire_projectiles(projectiles, [
                    Projectile(
                        self.x,
                        self.y - 10,
                        offset,
                        color=(255, 60, 180),
                        speed=4.2
                    )
                    for offset in (-2.6, -1.8, -0.9, 0.0, 0.9, 1.8, 2.6)
                ])
            if self.phase_timer > (96 if self.is_final_phase else 78):
                self.phase = "IDLE"; self.phase_timer = 0

        elif self.phase == "FAN_ATTACK":
            if self.phase_timer < 30:
                self.y -= 10 if not self.is_final_phase else 14
                if self.y < 100:
                    self.y = 100
            elif self.phase_timer % 12 == 0 and self.phase_timer < 105:
                num_bullets = 14 if self.is_final_phase else 10
                bullet_speed = 6.5 if self.is_final_phase else 5.8
                self.fire_projectiles(projectiles, [
                    Projectile(
                        self.x,
                        self.y,
                        (i / (num_bullets - 1)) * math.pi,
                        color=PURPLE,
                        speed=bullet_speed
                    )
                    for i in range(num_bullets)
                ])
            elif self.phase_timer >= 120:
                self.phase = "IDLE"; self.phase_timer = 0

        elif self.phase == "OVERDRIVE_INTRO":
            # 大技の前の演出。溜めている間は攻撃せず、浮上してエネルギーを貯める。
            # 溜めの1.5秒がそのまま「大技が来るよ」という予告になる。
            if self.phase_timer == 1:
                play_beam_charge_sound()
            if self.phase_timer <= 40:
                # 幻の強攻撃のように、構えるためにゆっくり浮上する
                self.y -= 8
                if self.y < 150:
                    self.y = 150
            if self.phase_timer >= OVERDRIVE_INTRO_FRAMES:
                stop_beam_charge_sound()
                # 溜め切った瞬間に砲撃音を鳴らして Overdrive 本編へ移行する
                play_beam_cannon_sound()
                self.phase = "OVERDRIVE"
                self.phase_timer = 0

        elif self.phase == "OVERDRIVE":
            # Final phase entry: visible target marks, teleport pressure, and aimed volleys.
            if self.phase_timer == 1:
                self.overdrive_target = (int(player.x), int(player.y))
            if self.phase_timer in (36, 76, 116):
                self.x = max(80, min(SCREEN_WIDTH - 80, player.x + random.choice([-160, 0, 160])))
                self.y = max(120, min(470, player.y + random.choice([-100, 0, 100])))
                self.overdrive_target = (int(player.x), int(player.y))
            if self.phase_timer % 12 == 0:
                base_angle = math.atan2(
                    self.overdrive_target[1] - (self.y - 20),
                    self.overdrive_target[0] - self.x
                )
                self.fire_projectiles(projectiles, [
                    Projectile(
                        self.x + (20 if self.facing_right else -20),
                        self.y - 20,
                        base_angle + offset,
                        color=(255, 70, 70),
                        speed=5.8
                    )
                    for offset in (-0.32, -0.16, 0.0, 0.16, 0.32)
                ])
            if self.phase_timer >= 140:
                self.phase = "IDLE"; self.phase_timer = 0

        # 攻撃判定の更新 (見た目と一致するようスプライト基準で同期)
        self.sync_hitbox()

        # 待機アニメーションを使う素材設定のとき、その再生を進める。
        # 攻撃ポーズを出している間は attack_pose_index() が None を返さないので、
        # そのときは再生位置を止め、攻撃が終わったら続きから再開する。
        if self.attack_pose_index() is None:
            self.idle_frame += 1

        # 予告タイマーは LASER フェーズで表示するため専用タイマー不要

        # 影の粒子
        if len(self.particles) < 20:
            if self.is_final_phase:
                p_color = (255, 40, 40)
            elif self.is_second_phase:
                p_color = GLOW_RED
            else:
                p_color = DARK_PURPLE
            self.particles.append([self.x + random.randint(-40, 40), self.y + random.randint(-60, 40), random.randint(2, 5), p_color])
        for p in self.particles[:]:
            speed = 5 if self.is_final_phase else (4 if self.is_second_phase else 2)
            p[1] -= speed
            if p[1] < self.y - 150: self.particles.remove(p)

    def attack_pose_index(self):
        """攻撃フェーズで「ビーム動き.gif」の何コマ目に見せるかを返す（通常時はNone）

        HIDDEN_BOSS_ATTACK_POSES の表を phase_timer でなぞって、
        攻撃の進行に合わせて「構え → チャージ → 発射」のポーズを選ぶ。
        """
        timeline = HIDDEN_BOSS_ATTACK_POSES.get(self.phase)
        if timeline is None or not hidden_boss_attack_frames:
            return None
        index = timeline[0][1]
        for start_frame, frame_index in timeline:
            if self.phase_timer >= start_frame:
                index = frame_index
            else:
                break
        # 表のコマ番号がGIFのコマ数を超えても末尾で止める（落ちつけて黒画面にならないように）
        return min(index, len(hidden_boss_attack_frames) - 1)

    def idle_pose_index(self):
        """通常時（攻撃ポーズ看不出のとき）に使うスプライトの何コマ目に見せるかを返す

        攻撃ポーズ（ビーム動き.gif）を表示している間は攻撃の絵を出したいので、
        通常表示のアニメ再生位置も進めない。通常時が静止画（タマミツネ.png）の
        場合は空リストなので常に None となり、静止画がそのまま使われる。
        """
        if not hidden_boss_idle_frames:
            return None
        if self.attack_pose_index() is not None:
            return None
        # 1周したら先頭に戻して同じアニメーションを繰り返し再生する
        frame_in_cycle = self.idle_frame % HIDDEN_BOSS_IDLE_CYCLE_FRAMES
        index = 0
        for offset, hold_frames in enumerate(HIDDEN_BOSS_IDLE_FRAME_FRAMES):
            if frame_in_cycle < hold_frames:
                index = offset
                break
            frame_in_cycle -= hold_frames
        else:
            index = len(hidden_boss_idle_frames) - 1
        return min(index, len(hidden_boss_idle_frames) - 1)

    def body_surface(self):
        """描画に使うスプライトと表示位置を返す（ビームなどのエフェクトは含めない）

        収縮レーザー・近接攻撃・大ビーム攻撃のときは「ビーム動き.gif」の
        攻撃ポーズに差し替える。それ以外のときは通常時のスプライト
        （タマミツネ.png の静止画。待機GIFを使う設定ならそのアニメ）を描く。
        """
        pose_index = self.attack_pose_index()
        if pose_index is not None and HIDDEN_BOSS_ATTACK_ANCHOR is not None:
            image = hidden_boss_attack_frames[pose_index]
            anchor_x, anchor_y = HIDDEN_BOSS_ATTACK_ANCHOR
        else:
            idle_index = self.idle_pose_index()
            if idle_index is not None and HIDDEN_BOSS_IDLE_ANCHOR is not None:
                image = hidden_boss_idle_frames[idle_index]
                anchor_x, anchor_y = HIDDEN_BOSS_IDLE_ANCHOR
            else:
                image = hidden_boss_image
                # 描画位置は当たり判定と共通の定数を使うことで、見た目と判定のずれを防ぐ
                if not self.facing_right:
                    image = pygame.transform.flip(image, True, False)
                return image, int(self.x - image.get_width() / 2), int(self.y - HIDDEN_BOSS_DRAW_OFFSET_Y)
        # 通常スプライトの不透明部分の「下端中央」とGIFの基準点を同じ位置に置くことで、
        # ポーズや待機コマが切り替わってもボスの立ち位置が飛ばないようにする
        # （位置の計算はここで1箇所だけ行う）
        # 左右反転時は反転後の判定枠（centerx が鏡になる） 기준으로位置を決め直す。
        # そうしないと反転時だけ描画と当たり判定が左右にずれてしまう。
        box = HIDDEN_BOSS_BOX if self.facing_right else HIDDEN_BOSS_BOX_FLIPPED
        image_x = int(
            self.x - hidden_boss_image.get_width() / 2 + box.centerx - anchor_x
        )
        image_y = int(
            self.y - HIDDEN_BOSS_DRAW_OFFSET_Y + HIDDEN_BOSS_BOX.bottom - anchor_y
        )
        if not self.facing_right:
            image = pygame.transform.flip(image, True, False)
        return image, image_x, image_y

    def draw_body(self, surface):
        """ボス本体だけを描く。撃破演出などで単独で使うため分けておく"""
        image, image_x, image_y = self.body_surface()
        surface.blit(image, (image_x, image_y))

    def draw_entrance_column(self, surface):
        """入場演出: ボスが降りてくる背後に光の柱を敷く（降下の進行で明るくなる）"""
        progress = min(1.0, self.phase_timer / HIDDEN_BOSS_ENTRANCE_FRAMES)
        column_w = 200
        column = pygame.Surface((column_w, SCREEN_HEIGHT), pygame.SRCALPHA)
        outer_alpha = int(35 + 45 * progress)
        inner_alpha = int(50 + 60 * progress)
        column.fill((140, 80, 255, outer_alpha), pygame.Rect(0, 0, column_w, SCREEN_HEIGHT))
        column.fill((230, 200, 255, inner_alpha), pygame.Rect(column_w // 2 - 36, 0, 72, SCREEN_HEIGHT))
        column.fill((255, 255, 255, min(120, inner_alpha)), pygame.Rect(column_w // 2 - 8, 0, 16, SCREEN_HEIGHT))
        surface.blit(column, (int(self.x) - column_w // 2, 0))

    def draw_entrance_effects(self, surface):
        """入場演出: 着地のダスト・画面フラッシュと玉藻前の名乗りバナー"""
        # --- 着地エフェクト ---
        if self.landing_effect_timer > 0:
            elapsed = HIDDEN_BOSS_ENTRANCE_LANDING_FRAMES - self.landing_effect_timer
            progress = elapsed / HIDDEN_BOSS_ENTRANCE_LANDING_FRAMES
            ground_y = HIDDEN_BOSS_GROUND_TOP_Y

            # 着地直後の画面フラッシュ
            if progress < 0.25:
                flash = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                flash.fill((255, 255, 255, int(140 * (1.0 - progress / 0.25))))
                surface.blit(flash, (0, 0))

            # 床を伝わる楕円の衝撃波（2重、時間差で広がる）
            for ring_index in range(2):
                ring_p = progress * 1.2 - ring_index * 0.18
                if ring_p <= 0:
                    continue
                ring_p = min(1.0, ring_p)
                rx = int(50 + 260 * ring_p)
                ry = int(14 + 46 * ring_p)
                ring_alpha = int(230 * (1.0 - ring_p))
                if ring_alpha <= 0:
                    continue
                ring = pygame.Surface((rx * 2 + 8, ry * 2 + 8), pygame.SRCALPHA)
                pygame.draw.ellipse(ring, (255, 230, 160, ring_alpha), (4, 4, rx * 2, ry * 2), 3)
                surface.blit(ring, (int(self.x) - rx - 4, ground_y - ry - 4))

            # 舞い上がるダスト（1枚のサーフェスにまとめて描き、最後に重ねる）
            dust_layer = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            for i in range(8):
                dust_p = progress * 1.3 - i * 0.06
                if dust_p <= 0:
                    continue
                dust_p = min(1.0, dust_p)
                angle = math.pi + (i + 0.5) * (math.pi / 8)
                dist = 30 + 160 * dust_p
                dx = int(self.x + math.cos(angle) * dist)
                dy = int(ground_y - 4 - 70 * dust_p + abs(math.sin(angle)) * 18)
                dust_alpha = int(200 * (1.0 - dust_p))
                if dust_alpha > 0:
                    pygame.draw.circle(dust_layer, (215, 195, 165, dust_alpha), (dx, dy), 5 + i % 3)
            surface.blit(dust_layer, (0, 0))

        # --- 名乗り「タマモ文字.png」のみ ---
        # 降下中(ENTRANCE)はフェードイン、着地後(entrance_banner_timer)はフェードアウト。
        if self.phase == "ENTRANCE":
            if self.phase_timer < HIDDEN_BOSS_ENTRANCE_BANNER_IN_FRAMES:
                banner_alpha = 0
                banner_zoom = 1.35
            else:
                fade = (
                    (self.phase_timer - HIDDEN_BOSS_ENTRANCE_BANNER_IN_FRAMES)
                    / HIDDEN_BOSS_ENTRANCE_BANNER_FADE
                )
                banner_alpha = int(255 * min(1.0, fade))
                # 出現時は大きめから等倍へ寄せる(ズームイン演出)
                banner_zoom = 1.35 - 0.35 * min(1.0, fade)
        elif self.entrance_banner_timer > 0:
            banner_alpha = int(255 * self.entrance_banner_timer / HIDDEN_BOSS_ENTRANCE_LANDING_FRAMES)
            banner_zoom = 1.0
        else:
            banner_alpha = 0
            banner_zoom = 1.0

        if banner_alpha > 0 and tamamo_title_image is not None:
            # タマモ文字.pngだけをそのまま出す(黒背景・英語表記なし)
            base_w, base_h = tamamo_title_image.get_size()
            target_w = min(520, base_w)
            target_h = max(1, round(base_h * target_w / max(1, base_w)))
            scaled_w = max(1, round(target_w * banner_zoom))
            scaled_h = max(1, round(target_h * banner_zoom))
            logo = pygame.transform.smoothscale(tamamo_title_image, (scaled_w, scaled_h))
            logo.set_alpha(banner_alpha)
            surface.blit(logo, (SCREEN_WIDTH // 2 - scaled_w // 2, 130))

    def draw(self, surface):
        # 入場演出の光の柱はボスの背後に敷く
        if self.phase == "ENTRANCE":
            self.draw_entrance_column(surface)

        for p in self.particles: # p[3] は色
            pygame.draw.circle(surface, p[3], (int(p[0]), int(p[1])), p[2])

        self.draw_body(surface)

        # 基本レーザー描画: 警告線と短時間のビーム表示（縦方向2本）
        if self.phase == "LASER":
            for lx in self.laser_xs:
                if self.phase_timer < 42:
                    pygame.draw.line(surface, RED, (int(lx), 0), (int(lx), SCREEN_HEIGHT), 2)
                else:
                    laser_width = 30 if self.is_final_phase else 40
                    core_width = 6 if self.is_final_phase else 10
                    laser_rect = pygame.Rect(int(lx) - laser_width // 2, 0, laser_width, SCREEN_HEIGHT)
                    pygame.draw.rect(surface, (200, 0, 255), laser_rect)
                    pygame.draw.rect(surface, WHITE, (int(lx) - core_width // 2, 0, core_width, SCREEN_HEIGHT))

        if self.is_final_phase:
            # 前演出中は「WARNING」表示にして、本編のOVERDRIVE表示と切り替わるようにする
            if self.phase == "OVERDRIVE_INTRO":
                phase_label = "WARNING"
                label_color = (255, 210, 90) if (self.phase_timer // 6) % 2 == 0 else (255, 70, 70)
            elif self.phase == "OVERDRIVE":
                phase_label = "OVERDRIVE"
                label_color = (255, 70, 70)
            else:
                phase_label = "FINAL PHASE"
                label_color = (180, 80, 255)
            label_font = pygame.font.SysFont("msgothic", 24, bold=True)
            label = label_font.render(phase_label, True, label_color)
            surface.blit(label, (SCREEN_WIDTH // 2 - label.get_width() // 2, 70))

        if self.phase == "TRIPLE_COLUMN":
            column_width = max(1, int(self.column_width))
            column_left = int(self.column_left)
            if self.phase_timer < 90:
                blink_on = (self.phase_timer // 3) % 2 == 0
                warn_color = (255, 70, 70) if blink_on else (255, 230, 120)
                warn_surface = pygame.Surface((column_width, SCREEN_HEIGHT), pygame.SRCALPHA)
                warn_surface.fill((255, 70, 70, 55 if blink_on else 25))
                warn_surface.fill(warn_color + (220,), (column_width // 2 - 2, 0, 4, SCREEN_HEIGHT))
                surface.blit(warn_surface, (column_left, 0))
                pygame.draw.line(surface, warn_color, (column_left, 0), (column_left, SCREEN_HEIGHT), 2)
                pygame.draw.line(surface, warn_color, (column_left + column_width - 1, 0), (column_left + column_width - 1, SCREEN_HEIGHT), 2)
            else:
                active_t = self.phase_timer - 90
                alpha = max(0, 230 - active_t * 7)
                column_surface = pygame.Surface((column_width, SCREEN_HEIGHT), pygame.SRCALPHA)
                column_surface.fill((255, 40, 40, alpha))
                for y in range(-40, SCREEN_HEIGHT + 40, 60):
                    line_y = (y + active_t * 14) % (SCREEN_HEIGHT + 80) - 40
                    pygame.draw.line(
                        column_surface,
                        (255, 220, 100, min(255, alpha + 20)),
                        (0, line_y),
                        (column_width, line_y + 24),
                        3
                    )
                surface.blit(column_surface, (column_left, 0))
                center_x = column_left + column_width // 2
                pygame.draw.line(surface, WHITE, (center_x, 0), (center_x, SCREEN_HEIGHT), 6)
                pygame.draw.line(surface, (255, 80, 80), (column_left, 0), (column_left, SCREEN_HEIGHT), 4)
                pygame.draw.line(surface, (255, 80, 80), (column_left + column_width - 1, 0), (column_left + column_width - 1, SCREEN_HEIGHT), 4)

        if self.phase == "CROSS_LASER":
            cross_x = self.laser_xs[0]
            first_active = 42 <= self.phase_timer < 54
            second_warning = 54 <= self.phase_timer < 76
            second_active = 76 <= self.phase_timer < 88
            beam_width = 8 if (first_active or second_active) else 2
            beam_color = PURPLE if (first_active or second_active) else RED
            pygame.draw.line(surface, beam_color, (cross_x, 0), (cross_x, SCREEN_HEIGHT), beam_width)
            pygame.draw.line(surface, beam_color, (0, self.laser_y), (SCREEN_WIDTH, self.laser_y), beam_width)
            if second_warning:
                pygame.draw.circle(surface, (255, 220, 120), (int(cross_x), int(self.laser_y)), 18, 2)
        elif self.phase == "SHRINK_LASER":
            if self.phase_timer < 45:
                warning_width = 2 + (45 - self.phase_timer) // 5
                # 左右の境界線を強く光らせて、閉じ込められる方向が分かるようにする
                for offset in range(0, 30, 6):
                    left_x = int(self.safe_left) + offset
                    right_x = int(self.safe_right) - offset
                    pygame.draw.line(surface, (255, 80, 80), (left_x, 0), (left_x, SCREEN_HEIGHT), 2)
                    pygame.draw.line(surface, (255, 220, 120), (left_x, 0), (left_x, SCREEN_HEIGHT), 1)
                    pygame.draw.line(surface, (255, 80, 80), (right_x, 0), (right_x, SCREEN_HEIGHT), 2)
                    pygame.draw.line(surface, (255, 220, 120), (right_x, 0), (right_x, SCREEN_HEIGHT), 1)
                pygame.draw.rect(surface, (80, 0, 0), (0, 0, int(self.safe_left), SCREEN_HEIGHT))
                pygame.draw.rect(surface, (80, 0, 0), (int(self.safe_right), 0, SCREEN_WIDTH - int(self.safe_right), SCREEN_HEIGHT))
                pygame.draw.line(surface, RED, (self.safe_left, 0), (self.safe_left, SCREEN_HEIGHT), warning_width)
                pygame.draw.line(surface, RED, (self.safe_right, 0), (self.safe_right, SCREEN_HEIGHT), warning_width)
                # 安全ゾーンの中央に輝く帯を描画して、残りスペースが狭まっていることを視覚化
                center_zone = pygame.Rect(int(self.safe_left), 0, int(self.safe_right - self.safe_left), SCREEN_HEIGHT)
                pygame.draw.rect(surface, (40, 80, 40), center_zone, 1)
            else:
                active_width = 8
                pygame.draw.line(surface, (255, 90, 90), (self.safe_left, 0), (self.safe_left, SCREEN_HEIGHT), active_width)
                pygame.draw.line(surface, (255, 255, 255), (self.safe_left, 0), (self.safe_left, SCREEN_HEIGHT), 2)
                pygame.draw.line(surface, (255, 90, 90), (self.safe_right, 0), (self.safe_right, SCREEN_HEIGHT), active_width)
                pygame.draw.line(surface, (255, 255, 255), (self.safe_right, 0), (self.safe_right, SCREEN_HEIGHT), 2)
                # 端に点滅するハイライトを追加して直感的に見えるようにする
                for x in (self.safe_left, self.safe_right):
                    for y in range(40, SCREEN_HEIGHT, 80):
                        pygame.draw.circle(surface, (255, 220, 120), (int(x), y), 4)
        elif self.phase == "ALTERNATE_LASER":
            for index, lx in enumerate(self.laser_xs):
                active = False
                if 40 <= self.phase_timer < 52:
                    active = True
                elif 64 <= self.phase_timer < 76:
                    active = index % 2 == 0
                elif 88 <= self.phase_timer < 100:
                    active = index % 2 == 1
                elif 112 <= self.phase_timer < 124:
                    active = index % 2 == 0
                if active:
                    pygame.draw.line(surface, PURPLE, (int(lx), 0), (int(lx), SCREEN_HEIGHT), 10 if self.is_final_phase else 8)
                else:
                    pygame.draw.line(surface, RED, (int(lx), 0), (int(lx), SCREEN_HEIGHT), 2)

        if self.is_final_phase:
            pulse = 4 if (pygame.time.get_ticks() // 80) % 2 == 0 else 0
            pygame.draw.circle(surface, (255, 50, 50), (int(self.x), int(self.y - 70)), 86 + pulse, 3)
            pygame.draw.circle(surface, (255, 220, 120), (int(self.x), int(self.y - 70)), 96 + pulse, 1)

        if self.phase == "OVERDRIVE_INTRO":
            # 大技の前の演出: 画面を赤く染め、ボスを中心にエネルギーを溜める
            t = self.phase_timer
            progress = min(1.0, t / OVERDRIVE_INTRO_FRAMES)

            # 1) 画面全体を赤く暗くするオーバーレイ（溜めるほど濃くなる）
            tint = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            tint.fill((60, 0, 0, int(70 * progress)))
            surface.blit(tint, (0, 0))

            center = (int(self.x), int(self.y - 20))

            # 2) ボスの周りで縮まるチャージリング（溜めの進み具合を視覚化）
            for ring_index in range(3):
                ring_progress = (progress * 3 + ring_index / 3.0) % 1.0
                radius = int(40 + (1.0 - ring_progress) * 150)
                if radius >= 12:
                    ring_color = (255, 70, 70) if ring_index % 2 == 0 else (255, 210, 90)
                    pygame.draw.circle(surface, ring_color, center, radius, 2)

            # 3) 外側から中心へ吸い込まれる光の筋
            for i in range(8):
                angle = i * (math.pi / 4) + t * 0.12
                dist = 170 - int(((t * 6 + i * 40) % 170))
                start = (
                    int(center[0] + math.cos(angle) * dist),
                    int(center[1] + math.sin(angle) * dist),
                )
                end = (
                    int(center[0] + math.cos(angle) * max(0, dist - 34)),
                    int(center[1] + math.sin(angle) * max(0, dist - 34)),
                )
                pygame.draw.line(surface, (255, 235, 160), start, end, 2)

            # 4) 中央に大きな「OVERDRIVE」予告（終盤ほど早く点滅）
            if t >= 18:
                blink_rate = 10 if progress < 0.75 else 4
                if (t // blink_rate) % 2 == 0:
                    intro_font = get_overdrive_intro_font(64)
                    intro_label = intro_font.render("OVERDRIVE", True, (255, 70, 70))
                    outline = intro_font.render("OVERDRIVE", True, (255, 220, 120))
                    label_x = SCREEN_WIDTH // 2 - intro_label.get_width() // 2
                    label_y = SCREEN_HEIGHT // 2 - intro_label.get_height() // 2
                    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                        surface.blit(outline, (label_x + dx, label_y + dy))
                    surface.blit(intro_label, (label_x, label_y))

            # 5) 溜め切った瞬間の白フラッシュ → 本編へつなぐ
            remaining = OVERDRIVE_INTRO_FRAMES - t
            if 0 < remaining <= OVERDRIVE_INTRO_FLASH_FRAMES:
                flash = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                flash_alpha = int(
                    230 * (OVERDRIVE_INTRO_FLASH_FRAMES - remaining + 1)
                    / OVERDRIVE_INTRO_FLASH_FRAMES
                )
                flash.fill((255, 255, 255, flash_alpha))
                surface.blit(flash, (0, 0))

        if self.phase == "OVERDRIVE":
            target_x, target_y = self.overdrive_target
            reticle_color = (255, 70, 70) if self.phase_timer % 24 < 12 else (255, 230, 120)
            pygame.draw.circle(surface, reticle_color, (int(target_x), int(target_y)), 26, 2)
            pygame.draw.line(surface, reticle_color, (int(target_x) - 36, int(target_y)), (int(target_x) - 14, int(target_y)), 2)
            pygame.draw.line(surface, reticle_color, (int(target_x) + 14, int(target_y)), (int(target_x) + 36, int(target_y)), 2)
            pygame.draw.line(surface, reticle_color, (int(target_x), int(target_y) - 36), (int(target_x), int(target_y) - 14), 2)
            pygame.draw.line(surface, reticle_color, (int(target_x), int(target_y) + 14), (int(target_x), int(target_y) + 36), 2)
            for offset in (-0.32, -0.16, 0.0, 0.16, 0.32):
                angle = math.atan2(target_y - (self.y - 20), target_x - self.x) + offset
                end_x = self.x + math.cos(angle) * 150
                end_y = self.y - 20 + math.sin(angle) * 150
                pygame.draw.line(surface, (255, 100, 100), (int(self.x), int(self.y - 20)), (int(end_x), int(end_y)), 1)


        # 周囲近接攻撃の描画
        if self.phase == "MELEE":
            if self.phase_timer <= 40:
                # 予兆: 赤い点滅する円で攻撃範囲を表示
                if (pygame.time.get_ticks() // 100) % 2 == 0:
                    pygame.draw.circle(surface, RED, (int(self.x), int(self.y)), 120, 2)
            else:
                # 本番の衝撃波 (予兆終了後の30フレームで拡大)
                attack_timer = self.phase_timer - 40
                radius = attack_timer * (5 if self.is_final_phase else 4)
                pygame.draw.circle(surface, PURPLE, (int(self.x), int(self.y)), radius, 3)
                if attack_timer % 5 == 0:
                    pygame.draw.circle(surface, WHITE, (int(self.x), int(self.y)), radius + 10, 1)

        # 入場演出の着地エフェクトと名乗りバナー（本体より手前に重ねる）
        if (
            self.phase == "ENTRANCE"
            or self.landing_effect_timer > 0
            or self.entrance_banner_timer > 0
        ):
            self.draw_entrance_effects(surface)


# ボスを倒したときの共通演出（初級・中級・上級で共通使い）
BOSS_DEFEAT_DURATION = 150       # 演出全体の長さ（2.5秒）
BOSS_DEFEAT_FLASH_FRAMES = 14    # 冒頭：一瞬の画面フラッシュ
BOSS_DEFEAT_BODY_FLASH_END = 42  # ここまでは白く明滅する
BOSS_DEFEAT_SHAKE_FRAMES = 50    # ここまでは振動する
BOSS_DEFEAT_SINK_START = 74      # ここからは沈み込む
BOSS_DEFEAT_BODY_END = 126       # ここでボス本体が消える
BOSS_DEFEAT_LABEL_FRAME = 34     # 「撃破！」を出し始めるフレーム

boss_defeat_font = None


def get_boss_defeat_font():
    """撃破演出の文字。初回だけ生成して使い回す"""
    global boss_defeat_font
    if boss_defeat_font is None:
        boss_defeat_font = pygame.font.SysFont("msgothic", 96, bold=True)
    return boss_defeat_font


class BossDefeatEffect:
    """ボスを倒したときの演出

    初級・中級・上級ボスのどれでも共通で使えるように、
    敵リストから消えたボス（描画だけ残す）を保持し、
    白フラッシュ → 衝撃波と破片 → 「撃破！」 → 崩れ落ちる、を順に流す。
    """

    # 爆発のタイミング（何フレーム目, 破片の数, 速度）
    BURSTS = ((18, 26, 6.0), (44, 18, 5.0), (70, 24, 7.0))

    def __init__(self, boss):
        self.boss = boss
        self.timer = 0
        self.particles = []
        self.rings = []
        self.silhouette = None

    @property
    def finished(self):
        return self.timer >= BOSS_DEFEAT_DURATION

    def center(self):
        """演出の中心（ボスの当たり判定の中央）"""
        return self.boss.rect.center

    def burst(self, x, y, count, speed):
        """その場所から破片を撒く"""
        for _ in range(count):
            angle = random.uniform(0, math.pi * 2)
            velocity = random.uniform(speed * 0.4, speed)
            self.particles.append({
                "x": x,
                "y": y,
                "vx": math.cos(angle) * velocity,
                "vy": math.sin(angle) * velocity,
                "life": random.randint(25, 50),
                "max_life": 50,
                "color": random.choice([
                    (255, 255, 255),
                    (255, 230, 140),
                    (255, 140, 40),
                    (255, 70, 70),
                ]),
                "size": random.randint(3, 8),
            })

    def update(self):
        self.timer += 1
        cx, cy = self.center()
        for start, count, speed in self.BURSTS:
            if self.timer == start:
                self.burst(cx, cy, count, speed)
                self.rings.append(0)

        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vx"] *= 0.94
            p["vy"] *= 0.94
            p["vy"] += 0.12
            p["life"] -= 1
        self.particles = [p for p in self.particles if p["life"] > 0]

        for i in range(len(self.rings)):
            self.rings[i] += 1

    def white_silhouette(self, image):
        """ボス画像を白く塗りつぶした画像（被弾時のフラッシュ用）"""
        if self.silhouette is None or self.silhouette.get_size() != image.get_size():
            mask = pygame.mask.from_surface(image)
            self.silhouette = mask.to_surface(
                setcolor=(255, 255, 255, 255),
                unsetcolor=(0, 0, 0, 0),
            )
        return self.silhouette

    def draw_body(self, surface):
        """ボス本体：白く明滅 → 振動 → 縮みながら沈み込む"""
        t = self.timer
        if t >= BOSS_DEFEAT_BODY_END:
            return

        image, image_x, image_y = self.boss.body_surface()

        # 明滅（最初の BOSS_DEFEAT_FLASH_FRAMES は真っ白、その後は明滅）
        if t < BOSS_DEFEAT_FLASH_FRAMES or (
            t < BOSS_DEFEAT_BODY_FLASH_END and (t // 3) % 2 == 0
        ):
            image = self.white_silhouette(image)

        center_x = image_x + image.get_width() / 2

        # 後半は縮みながら沈み込む
        scale = 1.0
        sink = 0
        if t > BOSS_DEFEAT_SINK_START:
            scale = max(0.0, 1.0 - (t - BOSS_DEFEAT_SINK_START) / 55.0)
            sink = int((t - BOSS_DEFEAT_SINK_START) * 1.4)
        if scale < 1.0:
            image = pygame.transform.scale(
                image,
                (
                    max(1, int(image.get_width() * scale)),
                    max(1, int(image.get_height() * scale)),
                )
            )

        # 振動
        shake_x = shake_y = 0
        if t < BOSS_DEFEAT_SHAKE_FRAMES:
            amp = max(1, 6 - t // 8)
            shake_x = random.randint(-amp, amp)
            shake_y = random.randint(-amp, amp)

        image_x = int(center_x - image.get_width() / 2) + shake_x
        surface.blit(image, (image_x, image_y + sink + shake_y))

    def draw_rings(self, surface):
        """時間とともに広がって消える衝撃波"""
        cx, cy = self.center()
        for age in self.rings:
            fade = max(0.0, 1.0 - age / 46.0)
            # 1回の爆発につき3重の衝撃波にする（1フレームごとに半径を
            # 描き直すと渦のように見えるため、3本のリングで表現する）
            for ratio in (1.0, 0.78, 0.56):
                radius = int((12 + age * 7) * ratio)
                if radius > 460:
                    continue
                # pygame.draw はアルファを指定できないので、色と太さで「消えていく」感じにする
                color = (
                    int(255 * fade + 160 * (1 - fade)),
                    int(230 * fade + 20 * (1 - fade)),
                    int(140 * fade + 20 * (1 - fade)),
                )
                pygame.draw.circle(surface, color, (cx, cy), radius, max(1, int(7 * fade)))

    def draw_particles(self, surface):
        """破片"""
        for p in self.particles:
            alpha = max(0, int(255 * p["life"] / p["max_life"]))
            size = p["size"] * 2
            dot = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(dot, (*p["color"], alpha), (p["size"], p["size"]), p["size"])
            surface.blit(dot, (int(p["x"] - p["size"]), int(p["y"] - p["size"])))

    def draw_label(self, surface):
        """「撃破！」がぽんと出て、終わりは上へ逃げるように消える"""
        t = self.timer - BOSS_DEFEAT_LABEL_FRAME
        if t < 0 or t > 78:
            return
        label = get_boss_defeat_font().render("撃破！", True, (255, 90, 70))

        # 弹出してから、終わりは上へ縮小しながら消える
        pop = min(1.0, 0.45 + t / 10.0)
        if t > 60:
            pop = max(0.0, 1.0 - (t - 60) / 18.0)
        label = pygame.transform.scale(
            label,
            (
                max(1, int(label.get_width() * pop)),
                max(1, int(label.get_height() * pop)),
            )
        )

        lx = SCREEN_WIDTH // 2 - label.get_width() // 2
        ly = 170 - int(max(0, t - 60) * 1.6)
        # 黒い文字を少しずらして重ねれば、どの背景でも読み取れる
        outline = get_boss_defeat_font().render("撃破！", True, (24, 10, 16))
        outline = pygame.transform.scale(
            outline,
            (label.get_width(), label.get_height()),
        )
        for ox, oy in ((-4, 0), (4, 0), (0, -4), (0, 4), (-3, -3), (3, -3), (-3, 3), (3, 3)):
            surface.blit(outline, (lx + ox, ly + oy))
        surface.blit(label, (lx, ly))

    def draw_flash(self, surface):
        """冒頭の一瞬の画面フラッシュ"""
        if self.timer >= BOSS_DEFEAT_FLASH_FRAMES:
            return
        alpha = int(235 * (1 - self.timer / BOSS_DEFEAT_FLASH_FRAMES))
        flash = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        flash.fill((255, 255, 255, alpha))
        surface.blit(flash, (0, 0))

    def draw_hp_bar(self, surface):
        """演出中もHPバー(0)を出しておき、体力が尽きたことを示す"""
        bar_w, bar_h = 400, 24
        bx, by = (SCREEN_WIDTH - bar_w) // 2, 30
        pygame.draw.rect(surface, BLACK, (bx - 6, by - 6, bar_w + 12, bar_h + 12))
        pygame.draw.rect(surface, (60, 60, 60), (bx, by, bar_w, bar_h))

    def draw(self, surface):
        self.draw_body(surface)
        self.draw_rings(surface)
        self.draw_particles(surface)
        self.draw_label(surface)
        self.draw_hp_bar(surface)
        self.draw_flash(surface)


def game_clear_screen(screen, font):
    """ゲームクリア画面を表示する"""
    while True:
        screen.fill(WHITE)
        large_font = pygame.font.SysFont("msgothic", 80, bold=True)
        clear_label = large_font.render("GAME CLEAR!", True, GOLD)
        screen.blit(clear_label, (SCREEN_WIDTH // 2 - clear_label.get_width() // 2, 200))
        
        msg = font.render("おめでとう！ ボスを撃破し、全ての試練を突破しました！", True, BLACK)
        screen.blit(msg, (SCREEN_WIDTH // 2 - msg.get_width() // 2, 320))
        
        hint = font.render("Escキーで終了します", True, (100, 100, 100))
        screen.blit(hint, (SCREEN_WIDTH // 2 - hint.get_width() // 2, 450))

        pygame.display.flip()
        pygame.time.Clock().tick(60)
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()


def title_screen(screen, font):
    """タイトル画面を表示し、Enterキーでゲームを開始する"""
    title_font = pygame.font.SysFont("msgothic", 72, bold=True)
    sub_font = pygame.font.SysFont("msgothic", 28)
    small_font = pygame.font.SysFont("msgothic", 20)
    clock = pygame.time.Clock()

    while True:
        screen.fill((18, 18, 36))

        for y in range(0, SCREEN_HEIGHT, 24):
            pygame.draw.rect(screen, (30, 30, 60), (0, y, SCREEN_WIDTH, 12))

        title = title_font.render("BOSS RUSH", True, GOLD)
        subtitle = sub_font.render("最強のボスを倒せ！", True, WHITE)
        start_msg = small_font.render("ENTERキーでスタート", True, (220, 220, 220))
        controls = small_font.render("移動: ← → / Shift・右クリック: 回避 / Z: 射撃 / X: 近接攻撃", True, (200, 200, 255))

        screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 140))
        screen.blit(subtitle, (SCREEN_WIDTH // 2 - subtitle.get_width() // 2, 240))
        screen.blit(start_msg, (SCREEN_WIDTH // 2 - start_msg.get_width() // 2, 360))
        screen.blit(controls, (SCREEN_WIDTH // 2 - controls.get_width() // 2, 420))

        pygame.display.flip()
        clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    return


def game_over_screen(screen, font):
    """ゲームオーバー画面を表示し、コンテニューか終了を選ばせる"""
    large_font = pygame.font.SysFont("msgothic", 72, bold=True)
    small_font = pygame.font.SysFont("msgothic", 26)
    clock = pygame.time.Clock()

    set_hidden_boss_bgm(False)
    set_mid_boss_bgm(False)

    while True:
        screen.fill((20, 20, 30))
        title = large_font.render("GAME OVER", True, RED)
        msg = small_font.render("Enterキーでコンテニュー / Escキーで終了", True, WHITE)
        sub = small_font.render("最初からやり直します", True, (200, 200, 200))

        screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 180))
        screen.blit(msg, (SCREEN_WIDTH // 2 - msg.get_width() // 2, 300))
        screen.blit(sub, (SCREEN_WIDTH // 2 - sub.get_width() // 2, 340))

        pygame.display.flip()
        clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return True
                if event.key == pygame.K_ESCAPE:
                    return False


def setup_stage(stage_number):
    """ステージ番号に基づいて敵と足場を生成する"""
    enemies = []
    platforms = []

    # 常に地面の足場を追加する(画面下端まで伸ばす)
    # ステージ6は背景画像の歩道に足を合わせる。ステージ1(練習場)は神殿.pngの土手に合わせる。
    if stage_number == 6:
        ground_top = HIDDEN_BOSS_GROUND_TOP_Y
    elif stage_number == 1:
        ground_top = PRACTICE_GROUND_TOP_Y
    else:
        ground_top = GROUND_TOP_Y
    platforms.append(pygame.Rect(0, ground_top, SCREEN_WIDTH, SCREEN_HEIGHT - ground_top))

    if stage_number == 1:
        # 練習場: 神殿の画像に合わせて台は置かない(床だけ)。入口は床置き3つ。
        enemies = []
    elif stage_number == 2:
        # プレイヤーの初期位置(x=400)と重ならないように調整
        enemies = []
        platforms.extend([
            pygame.Rect(50, 480, 120, 20),
            pygame.Rect(250, 380, 120, 20),
            pygame.Rect(450, 280, 120, 20),
            pygame.Rect(650, 180, 120, 20)
        ])
    elif stage_number == 4:
        # ステージ4: 1つ目のボス戦
        enemies = [Boss(600, 450)]
    elif stage_number == 5:
        # ステージ5: 赤鬼戦（足場の台は無し。床だけ）
        # 登場演出つきで開始（画面左へ叩きつけ+赤鬼文字の名乗り）
        mid_boss = MidBoss(400, 450)
        mid_boss.start_entrance()
        enemies = [mid_boss]
    elif stage_number == 6:
        # ステージ6: 隠しボス戦 (体力が高い)
        # 入場演出から始める（画面上からゆっくり降り、着地後にBGMとともに戦闘開始）
        hidden_boss = HiddenBoss(400, 450)
        hidden_boss.start_entrance()
        enemies = [hidden_boss]
        # 隠しステージ用の特殊な足場 (中央にジャンプで届く台を追加)
        platforms.extend([
            pygame.Rect(100, 300, 150, 20), 
            pygame.Rect(550, 300, 150, 20),
            pygame.Rect(325, 420, 150, 20)
        ])
    else:
        # ボス以外の敵は配置しない
        pass
    
    return enemies, platforms

def hidden_boss_battle_active(enemies):
    """上級ボスとの戦闘が始まっているか（入場演出中は False）

    和風BGMは戦闘開始の合図として、入場演出が終わるまで流さない。
    """
    return any(
        isinstance(enemy, HiddenBoss) and enemy.battle_started
        for enemy in enemies
    )


def mid_boss_battle_active(enemies):
    """赤鬼(ステージ5)との戦闘中かどうか。

    赤鬼に入場演出があり、演出中は無敵・戦闘前なので、
    演出が終わった(battle_started)あと生存しているあいだ鬼BGMを流す。
    """
    return any(
        isinstance(enemy, MidBoss) and enemy.health > 0 and enemy.battle_started
        for enemy in enemies
    )


def main():
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("msgothic", 24)
    title_screen(screen, font)

    player = Player()
    current_stage = 1
    stage_names = {
        1: "練習場",
        2: "高台の戦い",
        3: "激戦区",
        4: "唐笠お化け",
        5: "赤鬼",
        6: "玉藻前"
    }
    enemies, platforms = setup_stage(current_stage)
    projectiles = []
    powerups = []
    effects = EffectManager()
    # ボスを倒したときの演出（演出が終わるまでステージクリアは進まない）
    defeat_effects = []

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        # ボス戦BGMをステージに応じて鳴らす
        # 玉藻前(6): 入場演出で着地し、戦闘が始まってから和風BGMを流す
        #             （演出中は無音にして、BGMの始まりを戦闘開始の合図にする）
        # 赤鬼(5): 入場演出で着地し、戦闘が始まってから鬼BGMを流す
        set_hidden_boss_bgm(
            current_stage == 6 and hidden_boss_battle_active(enemies)
        )
        set_mid_boss_bgm(
            current_stage == 5 and mid_boss_battle_active(enemies)
        )

        player.update(
            platforms,
            enemies,
            projectiles,
            powerups,
            effects
        )
        effects.update()

        for effect in defeat_effects:
            effect.update()
        defeat_effects = [e for e in defeat_effects if not e.finished]
        
        for powerup in powerups:
            powerup.update()

        for enemy in enemies:
            if isinstance(enemy, HiddenBoss):
                enemy.update(player, projectiles, platforms, enemies)
                # 隠しボスの近接判定はMELEEフェーズの既定の判定で行う
                if enemy.phase == "MELEE" and enemy.phase_timer > 40:
                    max_timer = 96 if enemy.is_final_phase else 78
                    if enemy.phase_timer <= max_timer and enemy.phase_timer % (8 if enemy.is_final_phase else 10) == 0:
                        dist = math.sqrt((player.x - enemy.x)**2 + (player.y - enemy.y)**2)
                        attack_timer = enemy.phase_timer - 40
                        hit_radius = attack_timer * (5 if enemy.is_final_phase else 4)
                        if dist < hit_radius:
                            player.take_damage()
            elif isinstance(enemy, MidBoss):
                enemy.update(player, projectiles, platforms)
            elif isinstance(enemy, Boss):
                enemy.update(player.x, projectiles, platforms, player.y)

        for proj in projectiles[:]:
            proj.update()
            # 画面外（上下左右）に出たら削除
            if proj.x < -50 or proj.x > SCREEN_WIDTH + 50 or proj.y < -50 or proj.y > SCREEN_HEIGHT + 50:
                projectiles.remove(proj)
                continue
            if proj.friendly:
                for enemy in enemies:
                    if proj.rect.colliderect(enemy.rect):
                        enemy.health -= 1
                        if enemy.health <= 0:
                            if isinstance(enemy, HiddenBoss):
                                player.score += 1200
                            elif isinstance(enemy, Boss):
                                player.score += 800
                        projectiles.remove(proj)
                        break

        for powerup in powerups[:]:
            if powerup.y < -50 or powerup.y > SCREEN_HEIGHT + 50:
                powerups.remove(powerup)
        
        # ボスを倒したときは敵リストから外し、専用の演出に任せる
        # （演出が終わるまでステージクリアへ進まないようにする）
        for enemy in enemies:
            if enemy.health <= 0 and isinstance(enemy, Boss):
                defeat_effects.append(BossDefeatEffect(enemy))
                player.health = player.max_health  # ボスを倒したら全回復

        # 体力がなくなった敵を削除
        enemies = [e for e in enemies if e.health > 0]

        # ステージ1のボス入口処理(練習場: 赤鬼=左、玉藻前=中央、唐笠お化け=右)
        if current_stage == 1:
            middle_boss_portal = PRACTICE_PORTALS[5]
            hidden_boss_portal = PRACTICE_PORTALS[6]
            normal_boss_portal = PRACTICE_PORTALS[4]
            keys = pygame.key.get_pressed()
            if player.rect.colliderect(normal_boss_portal) and (keys[pygame.K_UP] or keys[pygame.K_w]):
                current_stage = 4
                enemies, platforms = setup_stage(current_stage)
                projectiles.clear()
                player.x, player.y = SCREEN_WIDTH // 2, 450
                player.vel_y = 0
                player.is_jumping = False
                continue
            if player.rect.colliderect(middle_boss_portal) and (keys[pygame.K_UP] or keys[pygame.K_w]):
                current_stage = 5
                enemies, platforms = setup_stage(current_stage)
                projectiles.clear()
                player.x, player.y = SCREEN_WIDTH // 2, 450
                player.vel_y = 0
                player.is_jumping = False
                continue
            if player.rect.colliderect(hidden_boss_portal) and (keys[pygame.K_UP] or keys[pygame.K_w]):
                current_stage = 6
                enemies, platforms = setup_stage(current_stage)
                projectiles.clear()
                player.x, player.y = SCREEN_WIDTH // 2, 450
                player.vel_y = 0
                player.is_jumping = False
                continue # ステージ移行したので次のループへ

        # ステージクリア判定（ボスの撃破演出が終わってから次ステージへ進む）
        if not enemies and not defeat_effects and current_stage != 1:
            if current_stage == 6:
                set_hidden_boss_bgm(False)
                game_clear_screen(screen, font)
                
            current_stage += 1
            enemies, platforms = setup_stage(current_stage)
            projectiles.clear()
            defeat_effects.clear()
            # プレイヤーの位置と状態をリセット
            player.x = SCREEN_WIDTH // 2
            player.y = 450
            player.vel_y = 0
            player.is_jumping = False

        if current_stage == 6:
            screen.blit(hidden_boss_background, (0, 0))
        elif current_stage == 5:
            screen.blit(mid_boss_background, (0, 0))
        elif current_stage == 4:
            # 初級ボス(唐笠お化け)戦は唐笠背景.png
            screen.blit(normal_boss_background, (0, 0))
        elif current_stage == 1:
            # 練習場は神殿.png(無い場合は白背景)
            if practice_background is not None:
                screen.blit(practice_background, (0, 0))
            else:
                screen.fill(WHITE)
        else:
            screen.fill(WHITE)
        
        # 天井の描画（中ボス部屋だけ高く、他の部屋では非表示）
        if current_stage == 5:
            pygame.draw.rect(screen, (70, 70, 90), (0, 0, SCREEN_WIDTH, MID_BOSS_CEILING_Y))

        if current_stage == 6:
            for plat in platforms:
                tile = hidden_boss_platform_tiles.get(plat.size)
                if tile is None:
                    tile = build_hidden_boss_platform_tile(plat.size)
                    hidden_boss_platform_tiles[plat.size] = tile
                # 背景の暗い横線に紛れないよう、足場の周囲に暗い輪郭を敷いてから重ねる
                pygame.draw.rect(
                    screen,
                    HIDDEN_BOSS_RIM_COLOR,
                    plat.inflate(2, 2),
                    1,
                    border_radius=2,
                )
                screen.blit(tile, plat)
        else:
            # 地面の描画(練習場は神殿の絵を活かすため帯を描かない)
            if current_stage != 1 or practice_background is None:
                pygame.draw.rect(screen, GROUND_COLOR, (0, 535, SCREEN_WIDTH, 65))

            # 足場の描画
            for plat in platforms:
                pygame.draw.rect(screen, GROUND_COLOR, plat, border_radius=3)

        # ステージ1ならボス入口を描画(練習場: 赤鬼=左、玉藻前=中央、唐笠お化け=右)
        if current_stage == 1:
            middle_boss_portal = PRACTICE_PORTALS[5]
            hidden_boss_portal = PRACTICE_PORTALS[6]
            normal_boss_portal = PRACTICE_PORTALS[4]
            pygame.draw.rect(screen, BLACK, normal_boss_portal, border_radius=5)
            pygame.draw.rect(screen, GOLD, normal_boss_portal, 2, border_radius=5)
            pygame.draw.rect(screen, BLACK, middle_boss_portal, border_radius=5)
            pygame.draw.rect(screen, (255, 140, 0), middle_boss_portal, 2, border_radius=5)
            pygame.draw.rect(screen, BLACK, hidden_boss_portal, border_radius=5)
            pygame.draw.rect(screen, PURPLE, hidden_boss_portal, 2, border_radius=5)
            # 神殿の背景に合わせて白縁で読みやすくする
            portal_labels = (
                ("唐笠お化け", GOLD, normal_boss_portal),
                ("赤鬼", (255, 140, 0), middle_boss_portal),
                ("玉藻前", PURPLE, hidden_boss_portal),
            )
            for text, color, portal in portal_labels:
                label = font.render(text, True, color)
                edge = font.render(text, True, WHITE)
                label_x = portal.centerx - label.get_width() // 2
                label_y = portal.top - 30
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    screen.blit(edge, (label_x + dx, label_y + dy))
                screen.blit(label, (label_x, label_y))

        for enemy in enemies:
            enemy.draw(screen)

        # ボスの撃破演出（敵リストから消えたボスをここで描き足す）
        for effect in defeat_effects:
            effect.draw(screen)

        for proj in projectiles:
            proj.draw(screen)
        for powerup in powerups:
            powerup.draw(screen)

        effects.draw(screen)
        player.draw(screen)

        # --- UI表示 ---
        # プレイヤーの体力をハートで表示 (左上)
        for i in range(player.health):
            hx, hy = 30 + i * 35, 30
            pygame.draw.circle(screen, RED, (hx - 7, hy), 8)
            pygame.draw.circle(screen, RED, (hx + 7, hy), 8)
            pygame.draw.polygon(screen, RED, [(hx - 15, hy + 3), (hx + 15, hy + 3), (hx, hy + 18)])
        if player.health < player.max_health:
            gray_count = player.max_health - player.health
            for i in range(gray_count):
                hx, hy = 30 + (player.health + i) * 35, 30
                pygame.draw.circle(screen, (150, 150, 150), (hx - 7, hy), 8)
                pygame.draw.circle(screen, (150, 150, 150), (hx + 7, hy), 8)
                pygame.draw.polygon(screen, (150, 150, 150), [(hx - 15, hy + 3), (hx + 15, hy + 3), (hx, hy + 18)])

        # スコアの表示
        score_label = font.render(f"SCORE: {player.score}", True, BLACK)
        screen.blit(score_label, (SCREEN_WIDTH - score_label.get_width() - 20, 20))

        # 回避のクールダウン
        evade_color = CYAN if player.evade_cooldown == 0 else (150, 150, 150)
        pygame.draw.rect(screen, evade_color, (SCREEN_WIDTH - 170, 55, 140 * (1 - min(player.evade_cooldown, 90) / 90), 12))
        screen.blit(font.render("回避", True, BLACK), (SCREEN_WIDTH - 220, 50))

        # ステージ情報をタイトルに表示
        stage_name = stage_names.get(current_stage, f"ステージ {current_stage}")

        # ボスHPバーの表示 (上部中央)
        for enemy in enemies:
            # 赤鬼・玉藻前は入場演出のあいだ表示せず、戦闘開始の合図として着地後に出す
            if isinstance(enemy, (MidBoss, HiddenBoss)) and not enemy.battle_started:
                continue
            if isinstance(enemy, Boss):
                bar_w, bar_h = 400, 24
                bx, by = (SCREEN_WIDTH - bar_w) // 2, 30
                # ヘリ（枠）を太くして装飾
                pygame.draw.rect(screen, BLACK, (bx - 6, by - 6, bar_w + 12, bar_h + 12)) # 外枠
                pygame.draw.rect(screen, (60, 60, 60), (bx, by, bar_w, bar_h))      # 背景
                pygame.draw.rect(screen, RED, (bx, by, bar_w * (enemy.health / enemy.max_health), bar_h)) # 残量
                screen.blit(font.render(stage_name, True, WHITE), (bx, by - 20))

        pygame.display.set_caption(f"{stage_name} | Stage: {current_stage} | SCORE: {player.score}")

        # 画面上にステージ名を表示
        stage_label = font.render(stage_name, True, BLACK)
        screen.blit(stage_label, (SCREEN_WIDTH // 2 - stage_label.get_width() // 2, 10))

        pygame.display.flip()
        clock.tick(60)

        # ゲームオーバー判定
        if player.health <= 0:
            if not game_over_screen(screen, font):
                pygame.quit()
                sys.exit()

            # コンテニュー時は最初のステージからやり直す
            current_stage = 1
            player = Player()
            enemies, platforms = setup_stage(current_stage)
            projectiles.clear()
            powerups.clear()
            defeat_effects.clear()
            continue

if __name__ == "__main__":
    main()
