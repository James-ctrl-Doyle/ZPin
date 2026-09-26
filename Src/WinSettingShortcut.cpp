#include "pch.h"
#include "Lang.h"
#include "Setting.h"
#include "WinSetting.h"
#include "WinSettingShortcut.h"

namespace {
    bool isShortcutModifierKey(const std::wstring& key)
    {
        return key == L"Ctrl" || key == L"Alt" || key == L"Shift" || key == L"Win" || key == L"LWin" || key == L"RWin";
    }

    // 不配修饰键、单独按下也能当快捷键的那一类：它们本来就不承担输入职能，占用了不影响
    // 用户正常打字。字母、数字、符号、方向键、Esc / Tab / Space / Enter 这些必须配修饰键，
    // 否则用户一敲键盘就开始截图
    bool canBeUsedAlone(const std::wstring& key)
    {
        if (key.size() >= 2 && key[0] == L'F') { //F1 ~ F12
            auto num = key.substr(1);
            auto isDigit = [](wchar_t c) { return c >= L'0' && c <= L'9'; };
            if (std::all_of(num.begin(), num.end(), isDigit)) return true;
        }
        return key == L"PrintScreen" || key == L"ScrollLock" || key == L"Pause";
    }

    // 抢不得的那一小批。前一组是所有软件里手指记忆最强的编辑键，抢了用户会难受；
    // 后一组被系统独占，让用户设上了也注册不成功（Ctrl+Alt+Delete 连消息都到不了应用）。
    // 除这些之外一律放开，冲不冲突交给用户自己判断
    bool isReservedShortcut(const std::wstring& shortcut)
    {
        static const std::vector<std::wstring> reserved{
            L"Ctrl+C", L"Ctrl+V", L"Ctrl+X", L"Ctrl+Z", L"Ctrl+Y", L"Ctrl+A", L"Ctrl+S",
            L"Ctrl+Alt+Delete", L"Ctrl+Shift+Esc", L"Ctrl+Esc",
            L"Alt+Tab", L"Alt+Esc", L"Alt+F4",
            L"Win+L", L"Win+D", L"Win+E", L"Win+R", L"Win+Tab",
        };
        return std::find(reserved.begin(), reserved.end(), shortcut) != reserved.end();
    }

    // keys 进来之前已经用 normalizeShortcutKeys 排过序，拼起来就是 "Ctrl+Alt+A" 这种规范写法。
    // LWin / RWin 都按 Win 记，好跟上面的黑名单对上
    std::wstring joinShortcutKeys(const std::vector<std::wstring>& keys)
    {
        std::wstring result;
        for (const auto& key : keys) {
            if (!result.empty()) result += L"+";
            result += (key == L"LWin" || key == L"RWin") ? L"Win" : key;
        }
        return result;
    }

    bool isValidShortcutKeys(const std::vector<std::wstring>& keys)
    {
        bool hasModifier{ false };
        std::wstring normalKey;
        for (const auto& key : keys) {
            if (isShortcutModifierKey(key)) {
                hasModifier = true;
                continue;
            }
            //两个普通键凑不成快捷键，RegisterHotKey 也只认一个
            if (!normalKey.empty()) return false;
            normalKey = key;
        }
        if (normalKey.empty()) return false;                            //光按修饰键不算快捷键
        if (!hasModifier && !canBeUsedAlone(normalKey)) return false;
        // 注册热键时要把这个键名再翻回虚拟键码，翻不出来的（比如 CapsLock）
        // 让用户设上了也是个按了没反应的死键，这里先拦住。
        // 用 Setting::keyNameToVk 而不是 Ling::Util::strToKey：单字符要按主键盘算，
        // 否则 "." 会被认成小键盘的小数点，跟捕获时记下的键名对不上
        if (Setting::keyNameToVk(normalKey) == 0) return false;
        return !isReservedShortcut(joinShortcutKeys(keys));
    }

    // 这一项是不是"只在截图窗口里生效"的按键（历史翻页那两项就是）
    bool isWindowKeyType(const std::wstring& type)
    {
        for (const auto& def : Setting::shortcutDefs()) {
            if (type == def.type) return def.windowOnly;
        }
        return false;
    }

    // 窗口内按键的校验：它不进系统热键表，所以不受"必须带修饰键"那条约束
    //（, 和 . 本来就不该配 Ctrl），但反过来也不能带任何修饰键 —— 否则就跟
    // Ctrl+S / Ctrl+Z 这些现成的组合打架了。
    // Esc / Enter / Tab 也排除：前一个在捕获时表示"放弃"、后两个应用自己要用
    bool isValidWindowKey(const std::wstring& key)
    {
        if (isShortcutModifierKey(key)) return false;
        if (key == L"Esc" || key == L"Enter" || key == L"Tab") return false;
        return Setting::keyNameToVk(key) != 0;
    }

    // 修饰键固定排序：Ctrl > Alt > Shift > Win > LWin > RWin > 普通键
    int modifierRank(const std::wstring& key)
    {
        if (key == L"Ctrl")  return 0;
        if (key == L"Alt")   return 1;
        if (key == L"Shift") return 2;
        if (key == L"Win")   return 3;
        if (key == L"LWin")  return 4;
        if (key == L"RWin")  return 5;
        return 100; // 普通键都排到修饰键之后
    }

    void normalizeShortcutKeys(std::vector<std::wstring>& keys)
    {
        std::stable_sort(keys.begin(), keys.end(),
            [](const std::wstring& a, const std::wstring& b) {
                return modifierRank(a) < modifierRank(b);
            });
    }
}



WinSettingShortcut::WinSettingShortcut(Ling::WinBase* parent):Ling::Node(parent)
{
    // 说明行：不写这一句，用户看到一排按钮不会知道要先点它、再直接按键
    auto tip = makeChild<Ling::Label>();
    tip->setText(Lang::get(L"shortcut.tip"));
    tip->setHeight(28.f);
    auto tipBorder = makeChild<Ling::Node>();
    tipBorder->setHeight(1.f);
    tipBorder->setBg(0xE0E0E0FF);

    // 列表来自 Setting 里那张唯一的表 —— 以后加热键只改那一处，
    // 设置页和热键注册不会各自漏掉一项
    bool windowTipAdded{ false };
    for (const auto& def : Setting::shortcutDefs())
    {
        // 从"全局热键"切到"只在截图里生效的按键"时插一段说明：不然用户按了 , 发现
        // 在桌面上没反应，只会以为坏了
        if (def.windowOnly && !windowTipAdded) {
            windowTipAdded = true;
            auto gap = makeChild<Ling::Node>();
            gap->setHeight(14.f);
            auto section = makeChild<Ling::Label>();
            section->setText(Lang::get(L"shortcut.windowTip"));
            section->setHeight(28.f);
            auto sectionBorder = makeChild<Ling::Node>();
            sectionBorder->setHeight(1.f);
            sectionBorder->setBg(0xE0E0E0FF);
        }

        std::wstring key{ def.type };
        auto box = makeChild<Ling::Node>();
        box->setHeight(39.f);
        box->setFlexDirection(Ling::FlexDirection::Row);
        box->setAlignItems(Ling::Align::Center);

        auto label = box->makeChild<Ling::Label>();
        label->setText(Lang::get(L"shortcut."+key));
        label->setHeightPercent(100.f);
        label->setJustifyContent(Ling::Justify::Center);
        label->setFlexGrow(1.f);

        auto btn = box->makeChild<Ling::Button>();
        btn->setId(key);
        btn->setText(btnText(key));
        btn->setHeight(28.f);
        btn->setWidth(120.f);
        btn->setBg(0xFFFFFFFF);
        btn->setHoverBg(0xFFFFFFFF);
        btn->setBorder(1.f, 0xE0E0E0FF);
        btn->onClick.add([this](Ling::Button* btn) {this->onBtnClick(btn);});
        btns.push_back(btn);

        auto border = makeChild<Ling::Node>();
        border->setHeight(1.f);
        border->setBg(0xE0E0E0FF);
    }

    // 底部的提示行。冲突、设置失败一类需要用户知道的事都写在这里，
    // 平时是空的，不占视觉
    status = makeChild<Ling::Label>();
    status->setHeight(28.f);
    status->setColor(0xCF1322FF);

    auto weakThis = getWeakThis();
    onKeyDownToken = win->onKeyDown.add([this,weakThis](UINT key) {
        if (!weakThis.lock()) return;
        if (this->curKey.empty()) return;
        this->onKeyDown(key);
    });
    onKeyUpToken = win->onKeyUp.add([this,weakThis](UINT key) {
        if (!weakThis.lock()) return;
        if (this->curKey.empty()) return;
        this->onKeyUp(key);
    });
    onMouseDownToken = win->onMouseDown.add([this,weakThis](POINT pos, bool isRight) {
        if (!weakThis.lock()) return;
        if (this->curKey.empty()) return;
        for (auto btn: this->btns)
        {
            if(btn->isPosIn(pos)) return;
        }
        this->endCapture();
    });
}

WinSettingShortcut::~WinSettingShortcut()
{
    win->onMouseDown.remove(onMouseDownToken);
    win->onKeyDown.remove(onKeyDownToken);
    win->onKeyUp.remove(onKeyUpToken);
    // 正在捕获时用户切了别的菜单 / 关了设置窗口，不会走到 endCapture ——
    // 热键会一直被压在注销状态，必须在这里补一次。resumeShortcuts 可重入，平时多跑一遍也无害
    Setting::get()->resumeShortcuts();
}

void WinSettingShortcut::onBtnClick(Ling::Button* btn)
{
    // 再次点击当前正在捕获的按钮 → 取消
    if (curKey == btn->id) {
        endCapture();
        return;
    }
    // 已经在捕获别的按钮 → 先复位旧的
    if (!curKey.empty()) {
        endCapture();
    }
    beginCapture(btn);
}

void WinSettingShortcut::beginCapture(Ling::Button* btn)
{
    curKey = btn->id;
    tempKeys.clear();
    clearRequested = false;
    setStatus(L"");   // 上一次留下的提示（比如冲突）不该继续挂在屏幕上
    // 让已注册的全局热键先退场：否则用户点"截图"那一行、按下 F1（想重设成 F1，
    // 这是最常做的一件事），F1 会先把截图窗口弹出来盖住设置页
    Setting::get()->suspendShortcuts();
    btn->setText(Lang::get(L"shortcut.pressKey"));
}

void WinSettingShortcut::endCapture()
{
    if (curKey.empty()) return;
    for (auto& btn : btns)
    {
        if (btn->id == curKey) {
            // 用 btnText 而不是直接读配置：清空之后要显示成"未设置"，
            // 不能把空串当成按钮文字
            btn->setText(btnText(curKey));
            break;
        }
    }
    curKey.clear();
    tempKeys.clear();
    clearRequested = false;
    // 捕获结束，把热键挂回去。放在这里而不是只放在按键那条路上：鼠标点到别处、
    // 切菜单、关窗口都会走到 endCapture（或析构函数里的那一次）
    Setting::get()->resumeShortcuts();
}

// 按钮上显示的文字：这一项实际生效的组合（配过就用配的，没配过用默认值），
// 两者都没有说明这一项没有热键
std::wstring WinSettingShortcut::btnText(const std::wstring& type)
{
    auto key = Setting::get()->effectiveShortcutKey(type);
    return key.empty() ? Lang::get(L"shortcut.unset") : key;
}

std::wstring WinSettingShortcut::conflictingType(const std::wstring& self, const std::wstring& shortcut)
{
    // 一个组合只能挂一个功能：RegisterHotKey 对同一个组合的第二个 id 会直接失败，
    // 用户看到的是"明明设上了、按下去却没反应"，很难自己想到是撞车了。
    // 所以在这里当场拦住，并说清楚被哪一项占了
    for (const auto& def : Setting::shortcutDefs()) {
        std::wstring other{ def.type };
        if (other == self) continue;
        if (Setting::get()->effectiveShortcutKey(other) == shortcut) return other;
    }
    return L"";
}

void WinSettingShortcut::setStatus(const std::wstring& text)
{
    if (status) status->setText(text);
}

void WinSettingShortcut::onKeyDown(UINT key)
{
    // Delete / Backspace = 清掉这一项的热键。必须在 keyToStr 之前拦下来 ——
    // 不拦的话它会被当成"用户想把 Delete 设成快捷键"，而 Delete 单按本身不是合法组合
    //（见 isValidShortcutKeys 里的 canBeUsedAlone），用户按完只会觉得没反应
    if (key == VK_DELETE || key == VK_BACK) {
        clearRequested = true;
        return;
    }
    auto keyStr = keyToStr(key);
    if (keyStr.empty()) return;

    // 当按下的是普通键（非修饰键）时，主动补齐当前按住的修饰键
    // 因为 Alt 等键走 WM_SYSKEYDOWN，Ling 框架可能不会转发到 onKeyDown
    if (!isShortcutModifierKey(keyStr)) {
        auto ensure = [&](int vk, const std::wstring& name) {
            if ((GetAsyncKeyState(vk) & 0x8000) &&
                std::find(tempKeys.begin(), tempKeys.end(), name) == tempKeys.end()) {
                tempKeys.push_back(name);
            }
        };
        ensure(VK_CONTROL, L"Ctrl");
        ensure(VK_MENU,    L"Alt");
        ensure(VK_SHIFT,   L"Shift");
        ensure(VK_LWIN,    L"LWin");
        ensure(VK_RWIN,    L"RWin");
    }

    bool isContains = std::find(tempKeys.begin(), tempKeys.end(), keyStr) != tempKeys.end();
    if (isContains) return;
    tempKeys.push_back(keyStr);
}

void WinSettingShortcut::onKeyUp(UINT key)
{
    if (curKey.empty()) return;

    // 清除：等有按键松手了再执行，免得还按住的修饰键混进判断
    if (clearRequested) {
        clearRequested = false;
        tempKeys.clear();
        Setting::get()->setShortcutKey(curKey, {});
        setStatus(L"");
        endCapture();
        return;
    }

    normalizeShortcutKeys(tempKeys);

    // 只按了一个 Esc = 放弃这一项。用户按 Esc 就是想撤，不该提示"组合无效"
    if (tempKeys.size() == 1 && tempKeys[0] == L"Esc") {
        endCapture();
        return;
    }

    // 只在截图窗口里生效的那两项（历史翻页）走另一套规则：允许单个不带修饰键的键
    if (isWindowKeyType(curKey)) {
        if (tempKeys.size() == 1 && isValidWindowKey(tempKeys[0])) {
            auto str = joinShortcutKeys(tempKeys);
            auto owner = conflictingType(curKey, str);
            if (!owner.empty()) {
                setStatus(Lang::get(L"shortcut.conflict") + Lang::get(L"shortcut." + owner));
                endCapture();
                return;
            }
            Setting::get()->setShortcutKey(curKey, tempKeys);
            setStatus(L"");
        }
        else {
            // 按了修饰键 + 键、或一次按了两个键：说清楚这类键只能是单个按键
            setStatus(Lang::get(L"shortcut.invalidWindow"));
        }
        endCapture();
        return;
    }

    if (isValidShortcutKeys(tempKeys)) {
        auto str = joinShortcutKeys(tempKeys);
        auto owner = conflictingType(curKey, str);
        if (!owner.empty()) {
            setStatus(Lang::get(L"shortcut.conflict") + Lang::get(L"shortcut." + owner));
            endCapture();
            return;
        }
        Setting::get()->setShortcutKey(curKey, tempKeys);
        setStatus(L"");
    }
    else {
        // 组合不合法（只按了修饰键、两个普通键、或者碰了保留组合）时说一句。
        // 不然用户松手看到按钮弹回原样，分不清是没设上还是程序坏了
        setStatus(Lang::get(L"shortcut.invalid"));
    }
    endCapture();
}

std::wstring WinSettingShortcut::keyToStr(UINT vkCode)
{
    switch (vkCode) {
        // --- 修饰键 ---
    case VK_CONTROL: return L"Ctrl";
    case VK_MENU:    return L"Alt";
    case VK_SHIFT:   return L"Shift";
    case VK_LWIN:    return L"LWin";
    case VK_RWIN:    return L"RWin";
    case VK_CAPITAL: return L"CapsLock";
        // --- 功能键 (F1 - F12) ---
    case VK_F1: return L"F1";
    case VK_F2: return L"F2";
    case VK_F3: return L"F3";
    case VK_F4: return L"F4";
    case VK_F5: return L"F5";
    case VK_F6: return L"F6";
    case VK_F7: return L"F7";
    case VK_F8: return L"F8";
    case VK_F9: return L"F9";
    case VK_F10: return L"F10";
    case VK_F11: return L"F11";
    case VK_F12: return L"F12";
        // --- 方向键 ---
    case VK_UP: return L"Up";
    case VK_DOWN: return L"Down";
    case VK_LEFT: return L"Left";
    case VK_RIGHT: return L"Right";
        // --- 控制与编辑键 ---
    case VK_RETURN:  return L"Enter";
    case VK_ESCAPE:  return L"Esc";
    case VK_TAB:     return L"Tab";
    case VK_SPACE:   return L"Space";
    case VK_BACK:    return L"Backspace";
    case VK_DELETE:  return L"Delete";
    case VK_INSERT:  return L"Insert";
    case VK_HOME:    return L"Home";
    case VK_END:     return L"End";
    case VK_PRIOR:   return L"PageUp";
    case VK_NEXT:    return L"PageDown";
    case VK_SNAPSHOT:return L"PrintScreen";
    case VK_SCROLL:  return L"ScrollLock";
    case VK_PAUSE:   return L"Pause";
        // --- 小键盘 ---
    case VK_NUMLOCK: return L"NumLock";
    case VK_MULTIPLY: return L"*";
    case VK_ADD:      return L"+";
    case VK_SUBTRACT: return L"-";
    case VK_DIVIDE:   return L"/";
    case VK_DECIMAL:  return L".";
    default:
        // --- 字母键 (A-Z 对应 ASCII 码 65-90) ---
        if (vkCode >= 'A' && vkCode <= 'Z') {
            return std::wstring(1, static_cast<wchar_t>(vkCode));
        }
        // --- 主键盘数字键 (0-9 对应 ASCII 码 48-57) ---
        if (vkCode >= '0' && vkCode <= '9') {
            return std::wstring(1, static_cast<wchar_t>(vkCode));
        }
        // --- 小键盘数字键 (0-9) ---
        if (vkCode >= VK_NUMPAD0 && vkCode <= VK_NUMPAD9) {
            return L"Num" + std::to_wstring(vkCode - VK_NUMPAD0);
        }
        if (vkCode == VK_OEM_3 || vkCode == VK_OEM_1 || vkCode == VK_OEM_4 ||
            vkCode == VK_OEM_6 || vkCode == VK_OEM_7 || vkCode == VK_OEM_5 ||
            vkCode == VK_OEM_2 || vkCode == VK_OEM_COMMA || vkCode == VK_OEM_PERIOD ||
            vkCode == VK_OEM_MINUS || vkCode == VK_OEM_PLUS)
        {
            wchar_t ch = 0;
            // MAPVK_VK_TO_CHAR (2) 会将虚拟键码转换为不带 Shift 状态的基础字符
            UINT scanCode = MapVirtualKeyW(vkCode, MAPVK_VK_TO_VSC);
            int result = MapVirtualKeyW(vkCode, MAPVK_VK_TO_CHAR);

            // 结果的低 16 位是字符，如果最高位(0x80000000)被置位，说明是死键(Dead Key)
            if (result != 0 && !(result & 0x80000000)) {
                ch = static_cast<wchar_t>(result & 0xFFFF);
                return std::wstring(1, ch);
            }
        }
        return L"";
    }
}
