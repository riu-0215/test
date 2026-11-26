# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


a = Analysis(
    ['bosgame.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\Student\\Desktop\\test - コピー\\.sprite_frames_preview.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\m (1).png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\m (2)-animated.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\tora_door_small.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\tora_door_top_clean.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\tora_door_top_clean2.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\tora_door_top_preview.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\たま封印.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\たま扉.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\たま開く.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\クリア.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ショット.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ジャンプ.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\タ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\タイトル.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\タイトル画面.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\タマミツネ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\タマモ文字.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\パリィ.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\パリィ音.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ビーム.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ビーム動き.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ビーム砲2.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ビーム砲チャージ.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ホーム.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\主人公立ち絵.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\傘突き上げ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\叩きつけ音.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\和風.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠地面.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠扉.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠攻撃.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠攻撃.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠新ジャンプ.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠背景.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\唐笠開く.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\回避.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\富裕.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\後ろ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\撃破.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\攻撃(仮).gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\攻撃.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\斬撃音.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\新ダッシュ.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\新攻撃.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\新歩き.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\神殿.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\背景.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\被弾音.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\赤鬼文字.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\足場.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\足音.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\踏み込み.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼BGM.mp3', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼クナイ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼ジャンプ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼ジャンプ予備.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼叩きつけ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼封印.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼扉.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼新突進.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼構え.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼突進.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼立ち絵.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼背景.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\鬼開く.gif', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ｗ.png', '.'), ('C:\\Users\\Student\\Desktop\\test - コピー\\ｗｗ.gif', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MyGame',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
