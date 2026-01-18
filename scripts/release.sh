#!/bin/bash
# 发版脚本：更新 changelog 并创建 tag
# 用法: ./scripts/release.sh v0.6.0

set -e

VERSION=$1

if [ -z "$VERSION" ]; then
    echo "用法: $0 <version>"
    echo "示例: $0 v0.6.0"
    exit 1
fi

# 检查是否安装 git-cliff
if ! command -v git-cliff &> /dev/null; then
    echo "正在安装 git-cliff..."
    pip install git-cliff -q
fi

echo "生成 CHANGELOG.md..."
git-cliff --tag "$VERSION" -o CHANGELOG.md

echo "提交 changelog 更新..."
git add CHANGELOG.md
git commit -m "chore(release): $VERSION"

echo "创建 tag: $VERSION"
git tag "$VERSION"

echo ""
echo "完成! 执行以下命令推送:"
echo "  git push && git push origin $VERSION"
