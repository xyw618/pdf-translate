#!/bin/bash
# 从本源码树构建 deb。用法: ./build-deb.sh [版本号]
set -e
VER="${1:-1.0.1}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD="$(mktemp -d)/pdf-translate"
mkdir -p "$BUILD/opt/pdf-translate"
cp -r "$ROOT/pkg/." "$BUILD/"
cp "$ROOT/server.py" "$BUILD/opt/pdf-translate/"
cp -r "$ROOT/static" "$BUILD/opt/pdf-translate/static"
# 部署用户占位符替换(仓库内不含用户名)
grep -rl "__APP_USER__" "$BUILD" | xargs -r sed -i "s/__APP_USER__/$USER/g"
chmod 755 "$BUILD/DEBIAN/"* "$BUILD/usr/bin/translate-pdf"
chmod 755 "$BUILD/opt/pdf-translate/setup-venv.sh"
find "$BUILD/opt" -type f ! -name "setup-venv.sh" -exec chmod 644 {} \;
dpkg-deb --build --root-owner-group "$BUILD" "$ROOT/pdf-translate_${VER}_all.deb"
echo "构建完成: $ROOT/pdf-translate_${VER}_all.deb"
