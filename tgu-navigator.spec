# -*- mode: python ; coding: utf-8 -*-
"""Спецификация PyInstaller для сборки TGU-Navigator.exe (onefile).

Сборка выполняется на Windows в GitHub Actions (см. .github/workflows/build-exe.yml):
    pyinstaller tgu-navigator.spec --noconfirm

Frontend и seed-каталог упаковываются внутрь exe; база данных создаётся
рядом с exe в папке data/ при первом запуске (см. app/config.py, _bundle_root).
"""

from pathlib import Path

block_cipher = None

project_root = Path(SPECPATH)

a = Analysis(
    ["app/launcher.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        ("frontend", "frontend"),
        ("seed/opportunities.json", "seed"),
    ],
    hiddenimports=[
        # uvicorn[standard] подтягивает опциональные модули динамически
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "app.main",
        "app.api.health",
        "app.api.opportunities",
        "app.api.ask",
        "app.services.search",
        "app.services.answer",
        "app.services.llm.mock",
        "app.services.llm.openai_compatible",
        "app.seed",
        "app.migrations.add_origin_fields",
        "psycopg2",
        "rapidfuzz",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "langchain", "transformers"],
    win_no_prefer_redirects=False,
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
    name="TGU-Navigator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # консоль видна: пользователь видит прогресс и ошибки
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
