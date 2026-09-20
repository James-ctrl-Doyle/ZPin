"""把 Setting.cpp 里快捷键那套逻辑（表 / 迁移 / effective / 清空 / 冲突）复刻一遍，
跑几个场景验证语义正确。C++ 编不了（缺 Ling 框架），但语义可以先在这里证明。

关键映射：
  C++ JsonObject.GetNamedValue(k, nullptr)  →  Python: k in obj   （有键就是非 null）
  C++ JsonObject.GetNamedString(k, L"")     →  Python: obj.get(k, "")
"""
import json

# Setting.cpp 里的 shortcutTable
TABLE = [
    ('cap',    100, 'F1', 'Ctrl+Alt+A'),
    ('pin',    101, 'F3', ''),
    ('long',   102, '',   ''),
    ('video',  103, '',   ''),
    ('ocr',    104, '',   ''),
    ('qrcode', 105, '',   ''),
]
DEFAULT_CONFIG = json.loads('{"common":{"autoStart":false,"language":"zh-CN","shortcutSchema":1},'
                            '"shortcutKey":{"cap":"F1","pin":"F3"}}')


def migrate(cfg):
    """Setting::migrateShortcutKeys"""
    common = cfg.setdefault('common', {})
    if common.get('shortcutSchema', 0) >= 1:
        return cfg
    obj = cfg.setdefault('shortcutKey', {})
    for key, _mid, dflt, legacy in TABLE:
        if key not in obj:                      # GetNamedValue == nullptr
            if dflt:
                obj[key] = dflt
            continue
        if legacy and obj.get(key, '') == legacy:
            obj[key] = dflt
    common['shortcutSchema'] = 1
    return cfg


def effective(cfg, key):
    """Setting::effectiveShortcutKey"""
    obj = cfg.get('shortcutKey') or {}
    if key in obj:                              # 键在（哪怕是空串）就以配置为准
        return obj.get(key, '')
    for t, _mid, dflt, _lg in TABLE:
        if t == key:
            return dflt
    return ''


def set_key(cfg, key, keys):
    """Setting::setShortcutKey（keys 为空 = 清除）"""
    str_ = '+'.join('Win' if k in ('LWin', 'RWin') else k for k in keys)
    cfg.setdefault('shortcutKey', {})[key] = str_
    return str_


def registered(cfg):
    """initShortcutKeys 会注册哪些"""
    return {k: effective(cfg, k) for k, _m, _d, _l in TABLE if effective(cfg, k)}


def conflict(cfg, self_key, shortcut):
    for t, _m, _d, _l in TABLE:
        if t == self_key:
            continue
        if effective(cfg, t) == shortcut:
            return t
    return None


def show(title, cfg):
    print('%-34s %s' % (title, json.dumps(registered(cfg), ensure_ascii=False)))
    return cfg


print('--- 1) 全新安装（无配置文件 → 用 defaultConfig）---')
c = json.loads(json.dumps(DEFAULT_CONFIG))
show('  默认注册', c)
assert effective(c, 'cap') == 'F1' and effective(c, 'pin') == 'F3'
assert effective(c, 'long') == '' and effective(c, 'ocr') == ''

print('--- 2) 老配置：cap 还是老默认 Ctrl+Alt+A ---')
c = migrate({'common': {'autoStart': False, 'language': 'zh-CN'},
             'shortcutKey': {'cap': 'Ctrl+Alt+A'}})
show('  迁移后', c)
assert effective(c, 'cap') == 'F1', effective(c, 'cap')
assert effective(c, 'pin') == 'F3'
assert 'long' not in c['shortcutKey'], '默认是空的项不该被写进配置'

print('--- 3) 老配置：用户自己把 cap 改成过 Ctrl+Alt+S ---')
c = migrate({'common': {}, 'shortcutKey': {'cap': 'Ctrl+Alt+S'}})
show('  迁移后', c)
assert effective(c, 'cap') == 'Ctrl+Alt+S', '用户改过的值不能被覆盖'
assert effective(c, 'pin') == 'F3'

print('--- 4) 迁移只跑一次：用户之后改成 F5，重启不能再被顶回去 ---')
c = migrate({'common': {}, 'shortcutKey': {'cap': 'Ctrl+Alt+A'}})
set_key(c, 'cap', ['F5'])
migrate(c)                     # 重启
assert effective(c, 'cap') == 'F5', effective(c, 'cap')
show('  重启后', c)

print('--- 5) 清空某一项 ---')
c = json.loads(json.dumps(DEFAULT_CONFIG))
set_key(c, 'pin', [])          # 按 Delete
assert effective(c, 'pin') == '', effective(c, 'pin')
assert 'pin' in c['shortcutKey'] and c['shortcutKey']['pin'] == ''
show('  清空贴图后', c)
migrate(c)                     # 重启也不该把 F3 顶回来
assert effective(c, 'pin') == '', '清空后重启又被默认值顶回来了'
show('  重启后', c)

print('--- 6) 冲突检测 ---')
c = json.loads(json.dumps(DEFAULT_CONFIG))
set_key(c, 'long', ['F1'])     # 想给截长图也设 F1
owner = conflict(c, 'long', 'F1')
print('  给 long 设 F1 → 冲突方:', owner)
assert owner == 'cap'
assert conflict(c, 'long', 'F2') is None

print('--- 7) 六个热键全设上 ---')
c = json.loads(json.dumps(DEFAULT_CONFIG))
for k, combo in [('long', 'F2'), ('video', 'F4'), ('ocr', 'F6'), ('qrcode', 'F7')]:
    set_key(c, k, [combo.split('+', 1)[-1]] if '+' not in combo else combo.split('+'))
show('  全部注册', c)
assert len(registered(c)) == 6

print()
print('所有场景通过')
