# 语言文件统一：UTF-16LE + BOM + CRLF
#
# ⚠ 两个坑（都踩过）：
#   1. 用 io.open(p, 'w', encoding='utf-16') 写的时候，文本层的换行转换会把
#      已经排好的 '\n' 再翻一次，结果落盘成 '\r\r\n'。必须用 open(p,'wb') 显式
#      写字节：BOM = '\ufeff'.encode('utf-16-le')，正文 = out.encode('utf-16-le')。
#   2. json.dumps(indent=4) 生成的分隔符就是 '\n'，别想当然以为它带了 '\r'。
import io, json, os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for name in ("简体中文.zh-CN.json", "English.en-US.json"):
    p = os.path.join(root, "Lang", name)
    with io.open(p, encoding="utf-16") as f:
        d = json.load(f)
    out = json.dumps(d, indent=4, ensure_ascii=False)
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    with open(p, "wb") as f:
        f.write("\ufeff".encode("utf-16-le") + out.encode("utf-16-le"))
    with open(p, "rb") as f:
        head = f.read(8)
    print(name, "ok, head =", head.hex(" "))
