#!/usr/bin/env bash
# 下载本地 Embedding 模型。**这份脚本进 git,模型文件不进。**
#
# ## 为什么模型不进版本库
#
# 90.5 MB 二进制。进了 git 之后**每次克隆都要拉它**,而且 git 存不下
# 二进制的增量 —— 换一次模型版本,仓库就永久胖一份。
# 它是**可重下的**,所以进 git 的应该是「怎么重下」而不是「那一份」。
#
# ## 许可证:一个必须写下来的模糊点
#
# 原模型 `BAAI/bge-small-zh-v1.5` 是 **MIT**(BAAI / 智源研究院明确声明)。
# 这里下的是 `Xenova/bge-small-zh-v1.5` —— 同一个模型的 ONNX 格式转换版,
# README 里写了 `base_model: BAAI/bge-small-zh-v1.5`,但**它自己没声明许可证**。
#
# MIT 允许修改和再分发,所以格式转换的派生作品条款上仍受 MIT 覆盖。
# 但**转换者没写** —— 所以准确的说法是「它派生自 MIT,而 MIT 允许这种派生」,
# 不是「这一份是 MIT」。两句话在实际风险上几乎没差别,在准确性上差别很大。
#
# ⚠️ 要一条完全干净的许可证链:从 BAAI 原仓库下 PyTorch 权重自己转 ONNX
# (转换时要临时装 PyTorch ~2GB,**转完可以卸掉**,运行时仍只要 onnxruntime)。
# 这个项目是学习/作品集,不上线,所以选了省事那条 —— **但这个事实要留在这儿**。
#
# ## 为什么用 curl 而不是 huggingface_hub
#
# 这台机器有 TLS 拦截,**Python 的 urllib 会证书校验失败**。
# 项目里所有 HTTP 请求都走 curl。
# ⚠️ **变量名一律 ASCII。** bash 不接受中文变量名 ——
# 而这个坑在这个项目里踩过两次:一次在 CI 的 admin job 里(退出码变成 255
# 而不是 1,**全绿时完全看不出来**),一次就是这个脚本的第一版(语法错误,当场炸)。
# 同一个错误在两个位置的代价差很远,所以别赌它会当场炸。
set -uo pipefail
cd "$(dirname "$0")/.."

REPO="Xenova/bge-small-zh-v1.5"
DIR=".models/bge-small-zh-v1.5"
# ⚠️ 用**原精度** `model.onnx`(90.5 MB),不用 int8 量化版(22.8 MB)。
# 用户 2026-09-27:「如果都免费的话,就用好的,不要用压缩的了」。
FILES=(
  "onnx/model.onnx"
  "tokenizer.json"
  "tokenizer_config.json"
  "config.json"
  "vocab.txt"
  "special_tokens_map.json"
)

mkdir -p "$DIR/onnx"
for f in "${FILES[@]}"; do
  OUT="$DIR/$f"
  if [ -s "$OUT" ]; then
    echo "  ✅ 已有 $f ($(du -h "$OUT" | cut -f1))"
    continue
  fi
  echo "  ▸ 下 $f …"
  if ! curl -fSL --retry 3 --retry-delay 2 -o "$OUT" \
       "https://huggingface.co/$REPO/resolve/main/$f"; then
    # **下失败就删掉那个半截文件。** 一个 0 字节或截断的 .onnx
    # 会让 onnxruntime 报一个和「没下载」完全不同的错,
    # 而那个错会把人引到模型格式上去查。
    rm -f "$OUT"
    echo "  ❌ $f 下载失败 —— 半截文件已删掉(截断的 .onnx 报的错会把人引错方向)"
    exit 1
  fi
done

echo ""
echo "校验:每个文件都得有内容,而且 .onnx 得是真的 ONNX(前 4 字节)"
BAD=0
for f in "${FILES[@]}"; do
  OUT="$DIR/$f"
  if [ ! -s "$OUT" ]; then echo "  ❌ $f 是空的"; BAD=1; continue; fi
  printf "  ✅ %-28s %s\n" "$f" "$(du -h "$OUT" | cut -f1)"
done
# ONNX 文件是 protobuf,开头不是文本。**验一下不是 HTML 错误页** ——
# HuggingFace 在限流或改了路径时会返回 200 + 一页 HTML,
# 而那份 HTML 存成 .onnx 之后,报的错是「protobuf 解析失败」。
if head -c 200 "$DIR/onnx/model.onnx" | grep -qi "<html\|<!doctype"; then
  echo "  ❌ model.onnx 是一页 HTML,不是模型 —— 大概被限流或路径变了"
  BAD=1
fi
[ "$BAD" = 0 ] && echo "" && echo "✅ 模型就位:$DIR"
exit $BAD
