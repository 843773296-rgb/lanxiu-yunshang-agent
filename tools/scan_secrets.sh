#!/bin/bash
# push 前扫密钥。**规则文件自己要排除掉** ——
# 这个坑踩了两次:第一次规则写在 CLAUDE.md 里,文档匹配了自己;
# 挪到 .secretscan 之后,规则文件里的 `gho_` 又匹配了自己。
#
# 教训不是「再挪一次」,是**把它做成一条命令,让人不必记得任何例外**。
# 要人记住的规则迟早会被忘记 —— 和「Hook 比提示词可靠」是同一条道理。
#
# 而且误报的代价不是「多看一眼」:一个天天误报的检查等于没有检查,
# 人会学会忽略它,然后真漏密钥的那一次也一样被忽略。
cd "$(dirname "$0")/.."
HIT=$(git ls-files | grep -v '^\.secretscan$' | xargs grep -lE "$(cat .secretscan)" 2>/dev/null)
if [ -n "$HIT" ]; then
  printf "\033[31m❌ 疑似密钥:\033[0m\n%s\n" "$HIT"; exit 1
fi
printf "\033[32m✅ 密钥扫描干净\033[0m\n"
