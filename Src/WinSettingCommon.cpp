#include "pch.h"
#include "Lang.h"
#include "Setting.h"
#include "Util.h"
#include "WinSetting.h"
#include "WinSettingCommon.h"
#include "WinConfirm.h"    // 二次确认用自绘的框，不用系统 MessageBox
#include "Tray.h"       // 图标样式切换后让托盘立刻换图
#include <shellapi.h>   // IsUserAnAdmin / ShellExecuteW（管理员检测与重启）

WinSettingCommon::WinSettingCommon(Ling::WinBase* parent):Ling::Node(parent)
{
    // ⚠ 设置项的**显示顺序由这里的调用顺序决定**（每一项内部是 makeChild 加进去的），
    //    跟下面那些 init*Ctrls 函数的**定义顺序无关** —— 别靠挪函数定义来调顺序，没用。
    //    当前顺序：开机自启 → 管理员模式 → 游戏模式 → 语言 → 边框 → 保存目录 → 快速保存 → 历史保留
    initAutoStartCtrls();
    initAdminCtrls();
    initGameModeCtrls();
    initLangCtrls();
    initBorderCtrl();
    initSaveCtrls();
    initHistoryCtrl();
    initIconStyleCtrls();
    auto weakThis = getWeakThis();
    // 这个回调一直挂在窗口上，而本节点可能在窗口关闭之前就被菜单切换换掉了，
    // 所以先确认自己还活着再去碰成员
    win->onDestroy.add([this, weakThis]() {
        if (!weakThis.lock()) return;
        this->hideSelectBox();
    });
}

WinSettingCommon::~WinSettingCommon()
{
    win->onMouseDown.remove(onMouseDownToken);
}

// ⚠ 下面这些 init*Ctrls 的**定义顺序不代表显示顺序** —— 显示顺序由构造函数里
//    的调用顺序决定（每一项内部是 makeChild 加进父节点的）。要调顺序改构造函数，
//    挪这里的函数定义没用。
void WinSettingCommon::initAdminCtrls()
{
    auto box = makeChild<Ling::Node>();
    box->setHeight(39.f);
    box->setFlexDirection(Ling::FlexDirection::Row);
    box->setAlignItems(Ling::Align::Center);

    auto label = box->makeChild<Ling::Label>();
    label->setText(Lang::get(L"setting.admin"));
    label->setHeightPercent(100.f);
    label->setJustifyContent(Ling::Justify::Center);
    label->setFlexGrow(1.f);

    // 任务管理器这类管理员窗口，普通权限的进程往它身上注入鼠标/键盘会被 UIPI 拦掉，
    // 截图自然截不了。解决办法只有一个：程序本身以管理员跑 —— 所以做成一个开关：
    // 开 = 换成管理员实例重启，关 = 换回普通权限实例重启。
    // ⚠ 两个方向都要二次确认：点一下就是整个程序重启一遍，误触的代价太大
    const bool isAdmin = IsUserAnAdmin() != 0;

    auto btn = makeOnOffBtn(box);
    styleToggle(btn, isAdmin, Lang::get(L"setting.toggleOnAdmin"));
    btn->onClick.add([this](Ling::Button*) {
        // 二次确认走自绘的 WinConfirm（系统的 MessageBox 跟这个程序的观感不搭）。
        // 它是模态的：开着的时候设置窗口收不到输入，点"确定"才真去重启
        // 两个方向都带上 --open-setting：管理员模式切换就是一次重启（托盘图标会先消失
        // 再出现），用户是冲着"改权限"来的，重启完直接把设置页摆回来才接得上
        if (IsUserAnAdmin()) {
            // 退出管理员模式：降权重启（提权进程造不出普通权限的子进程，见 relaunchSelf）
            WinConfirm::showAt(win, Lang::get(L"setting.adminExitTitle"),
                Lang::get(L"setting.adminExitConfirm"), Lang::get(L"setting.ok"),
                []() { if (relaunchSelf(false)) Ling::App::get()->quit(0); });
        }
        else {
            // runas 触发提升（本机 UAC 是"静默提升"，不弹确认框）
            WinConfirm::showAt(win, Lang::get(L"setting.adminRestartTitle"),
                Lang::get(L"setting.adminRestartConfirm"), Lang::get(L"setting.ok"),
                []() { if (relaunchSelf(true)) Ling::App::get()->quit(0); });
        }
        // 没拉起来（用户在 UAC 上点了"否"、或者令牌复制失败）：留在原地，什么都不做
    });

    // 一句说明，与"快速保存"下面那条同一个写法：这个开关到底管什么用
    auto hint = makeChild<Ling::Label>();
    hint->setText(Lang::get(L"setting.adminTip"));
    hint->setHeight(20.f);
    hint->setFontSize(12.f);
    hint->setColor(0x888888FF);

    auto border = makeChild<Ling::Node>();
    border->setHeight(1.f);
    border->setBg(0xE0E0E0FF);
}

// 游戏模式：开着的时候，检测到全屏（含无边框全屏）游戏就自动暂停全局热键，
// 退出游戏自动恢复。检测本体在 App.cpp 的 GameWatcher 里 —— 这里只管开关与文案
void WinSettingCommon::initGameModeCtrls()
{
    auto box = makeChild<Ling::Node>();
    box->setHeight(39.f);
    box->setFlexDirection(Ling::FlexDirection::Row);
    box->setAlignItems(Ling::Align::Center);

    auto label = box->makeChild<Ling::Label>();
    label->setText(Lang::get(L"setting.gameMode"));
    label->setHeightPercent(100.f);
    label->setJustifyContent(Ling::Justify::Center);
    label->setFlexGrow(1.f);

    auto btn = makeOnOffBtn(box);
    styleToggle(btn, Setting::get()->getGameMode(), Lang::get(L"setting.toggleOn"));
    btn->onClick.add([this](Ling::Button* btn) {
        auto setting = Setting::get();
        // 和"开机自启"那边不同：这个开关只是写条配置，没有会失败的系统调用，
        // 所以不需要像自启那样"写失败就把按钮状态回滚"
        setting->setGameMode(!setting->getGameMode());
        styleToggle(btn, setting->getGameMode(), Lang::get(L"setting.toggleOn"));
    });

    // 一行说明，与"管理员模式"下面那条同一套写法：只写一句，不堆第二行
    auto hint = makeChild<Ling::Label>();
    hint->setText(Lang::get(L"setting.gameModeTip"));
    hint->setHeight(20.f);
    hint->setFontSize(12.f);
    hint->setColor(0x888888FF);

    auto border = makeChild<Ling::Node>();
    border->setHeight(1.f);
    border->setBg(0xE0E0E0FF);
}

void WinSettingCommon::initAutoStartCtrls()
{
    auto box = makeChild<Ling::Node>();
    box->setHeight(39.f);
    box->setFlexDirection(Ling::FlexDirection::Row);
    box->setAlignItems(Ling::Align::Center);

    auto label = box->makeChild<Ling::Label>();
    label->setText(Lang::get(L"setting.autoStart"));
    label->setHeightPercent(100.f);
    label->setJustifyContent(Ling::Justify::Center);
    label->setFlexGrow(1.f);

    // 文字按钮而不是图标开关：原先是一个只有图标的小按钮，状态全靠图标形状区分，
    // 用户根本看不出这是"开机自启"的开关（功能一直在，只是没人发现）
    auto btn = makeOnOffBtn(box);
    setAutoStartBtn(btn);

    btn->onClick.add([this](Ling::Button* btn) {
        auto setting = Setting::get();
        // 写注册表失败（组策略拦了、或者是精简过没有 Run 键的系统）就别改状态：
        // 按钮停在原样，用户一眼就知道没生效
        if (!setting->setAutoStart(!setting->getAutoStart())) return;
        setAutoStartBtn(btn);
    });

    auto border = makeChild<Ling::Node>();
    border->setHeight(1.f);
    border->setBg(0xE0E0E0FF);
}

void WinSettingCommon::initLangCtrls()
{
    auto box = makeChild<Ling::Node>();
    box->setHeight(39.f);
    box->setFlexDirection(Ling::FlexDirection::Row);
    box->setAlignItems(Ling::Align::Center);

    auto label = box->makeChild<Ling::Label>();
    label->setText(Lang::get(L"setting.language"));
    label->setHeightPercent(100.f);
    label->setJustifyContent(Ling::Justify::Center);
    label->setFlexGrow(1.f);

    auto langCode = Setting::get()->getLang();
    auto langs = Lang::get()->getSupportedLang();
    std::wstring langName{ L"简体中文" };
    for (auto& pair:langs)
    {
        if (pair.second == langCode) {
            langName = pair.first;
            break;
        }
    }
    selectBtn = box->makeChild<Ling::Button>();
    selectBtn->setText(langName);
    selectBtn->setHeight(28.f);
    selectBtn->setWidth(160.f);
    selectBtn->setBorder(1.f, 0xE0E0E0FF);
    selectBtn->setHoverBg(0XFFFFFFFF);
    selectBtn->onClick.add([this](Ling::Button* btn) {
        if (selectBox) return;
        this->showSelectBox(btn);
        });
    auto border = makeChild<Ling::Node>();
    border->setHeight(1.f);
    border->setBg(0xE0E0E0FF);
}

void WinSettingCommon::initBorderCtrl()
{
    auto box = makeChild<Ling::Node>();
    box->setHeight(39.f);
    box->setFlexDirection(Ling::FlexDirection::Row);
    box->setAlignItems(Ling::Align::Center);

    borderLabel = box->makeChild<Ling::Label>();
    borderLabel->setHeightPercent(100.f);
    borderLabel->setJustifyContent(Ling::Justify::Center);
    borderLabel->setFlexGrow(1.f);

    auto slider = box->makeChild<Ling::Slider>();
    slider->setWidth(160.f);
    slider->setHeight(28.f);
    slider->setRange(0.f, 10.f);
    slider->setStep(1.f);
    // setValue 排在 onValueChanged 之前：这一下不该反过来又去写一次配置
    slider->setValue(Setting::get()->getBorderWidth());
    slider->setThumbColor(0x888888FF);
    slider->setHoverThumbColor(0x888888FF);
    slider->setTrackColor(0x888888FF);
    slider->setFillColor(0x888888FF);
    slider->onValueChanged.add([this](Ling::Slider*, float val) {
        Setting::get()->setBorderWidth(val);
        updateBorderLabel();
    });
    updateBorderLabel();

    auto border = makeChild<Ling::Node>();
    border->setHeight(1.f);
    border->setBg(0xE0E0E0FF);
}

void WinSettingCommon::updateBorderLabel()
{
    // 0 直接把"隐藏"写进标签，省得用户猜 0 是什么意思
    auto val = Setting::get()->getBorderWidth();
    auto text = Lang::get(L"setting.borderWidth") + L"  ";
    text += val <= 0 ? Lang::get(L"setting.borderWidthOff") : std::to_wstring((int)val);
    borderLabel->setText(text);
}

void WinSettingCommon::initSaveCtrls()
{
    // ———— 默认保存位置：点按钮选文件夹，选了之后"快速保存"就存这儿 ————
    {
        auto box = makeChild<Ling::Node>();
        box->setHeight(39.f);
        box->setFlexDirection(Ling::FlexDirection::Row);
        box->setAlignItems(Ling::Align::Center);

        auto label = box->makeChild<Ling::Label>();
        label->setText(Lang::get(L"setting.saveDir"));
        label->setHeightPercent(100.f);
        label->setJustifyContent(Ling::Justify::Center);
        label->setFlexGrow(1.f);

        saveDirBtn = box->makeChild<Ling::Button>();
        saveDirBtn->setHeight(28.f);
        saveDirBtn->setWidth(220.f);
        // 路径天然很长，字号压小一点好多显示几个字符（按钮放不下会自己截断）
        saveDirBtn->setFontSize(11.f);
        saveDirBtn->setBorder(1.f, 0xE0E0E0FF);
        saveDirBtn->setHoverBg(0xFFFFFFFF);
        saveDirBtn->onClick.add([this](Ling::Button*) {
            // 取消（返回空串）就什么也不做，别把用户当前设置清掉
            auto dir = Util::pickFolder(win->hwnd, Setting::get()->getSaveDir());
            if (dir.empty()) return;
            Setting::get()->setSaveDir(dir);
            updateSaveDirLabel();
        });
        updateSaveDirLabel();

        auto border = makeChild<Ling::Node>();
        border->setHeight(1.f);
        border->setBg(0xE0E0E0FF);
    }
    // ———— 快速保存开关（与"开机自启动""管理员模式"同一套样式）————
    {
        auto box = makeChild<Ling::Node>();
        box->setHeight(39.f);
        box->setFlexDirection(Ling::FlexDirection::Row);
        box->setAlignItems(Ling::Align::Center);

        auto label = box->makeChild<Ling::Label>();
        label->setText(Lang::get(L"setting.quickSave"));
        label->setHeightPercent(100.f);
        label->setJustifyContent(Ling::Justify::Center);
        label->setFlexGrow(1.f);

        auto btn = makeOnOffBtn(box);
        setQuickSaveBtn(btn);
        btn->onClick.add([this](Ling::Button* btn) {
            auto setting = Setting::get();
            setting->setQuickSave(!setting->getQuickSave());
            setQuickSaveBtn(btn);
        });

        // 一句说明，免得用户不知道这个开关到底改了什么
        auto hint = makeChild<Ling::Label>();
        hint->setText(Lang::get(L"setting.quickSaveTip"));
        hint->setHeight(20.f);
        hint->setFontSize(12.f);
        hint->setColor(0x888888FF);

        auto border = makeChild<Ling::Node>();
        border->setHeight(1.f);
        border->setBg(0xE0E0E0FF);
    }
}

void WinSettingCommon::initHistoryCtrl()
{
    auto box = makeChild<Ling::Node>();
    box->setHeight(39.f);
    box->setFlexDirection(Ling::FlexDirection::Row);
    box->setAlignItems(Ling::Align::Center);

    historyLabel = box->makeChild<Ling::Label>();
    historyLabel->setHeightPercent(100.f);
    historyLabel->setJustifyContent(Ling::Justify::Center);
    historyLabel->setFlexGrow(1.f);

    auto slider = box->makeChild<Ling::Slider>();
    slider->setWidth(160.f);
    slider->setHeight(28.f);
    slider->setRange(0.f, 30.f);
    slider->setStep(1.f);
    // setValue 排在 onValueChanged 之前：这一下不该反过来又去写一次配置
    slider->setValue((float)Setting::get()->getHistoryDays());
    slider->setThumbColor(0x888888FF);
    slider->setHoverThumbColor(0x888888FF);
    slider->setTrackColor(0x888888FF);
    slider->setFillColor(0x888888FF);
    slider->onValueChanged.add([this](Ling::Slider*, float val) {
        Setting::get()->setHistoryDays((int)val);
        updateHistoryLabel();
    });
    updateHistoryLabel();

    auto border = makeChild<Ling::Node>();
    border->setHeight(1.f);
    border->setBg(0xE0E0E0FF);
}

// 托盘图标样式：彩色版（红蓝底 + 白 Z）/ 简洁版（透明底，只留白 Z）。
// 点一下在两档之间循环；切换立即生效（托盘当场换图）并写配置，重启保持。
// exe 文件本身的图标不受影响（嵌在 PE 资源里，运行期改不了）—— 这是 Windows 的边界
void WinSettingCommon::initIconStyleCtrls()
{
    auto box = makeChild<Ling::Node>();
    box->setHeight(39.f);
    box->setFlexDirection(Ling::FlexDirection::Row);
    box->setAlignItems(Ling::Align::Center);

    auto label = box->makeChild<Ling::Label>();
    label->setText(Lang::get(L"setting.icon"));
    label->setHeightPercent(100.f);
    label->setJustifyContent(Ling::Justify::Center);
    label->setFlexGrow(1.f);

    auto btn = makeOnOffBtn(box);
    auto applyStyle = [btn](const std::wstring& style) {
        // 这是"当前值"的展示，不是开/关 —— 不走 styleToggle（那套会把文案
        // 强行换成"已开启/未开启"），只换文案、颜色保持中性
        const bool simple = style == L"simple";
        btn->setText(simple ? Lang::get(L"setting.iconSimple")
                            : Lang::get(L"setting.iconColor"));
        btn->setColor(0x333333FF);
        btn->setHoverColor(0x333333FF);
        Tray::applyIconStyle(simple);
    };
    applyStyle(Setting::get()->getIconStyle());
    btn->onClick.add([applyStyle](Ling::Button*) {
        const auto next = Setting::get()->getIconStyle() == L"simple"
            ? std::wstring{ L"color" } : std::wstring{ L"simple" };
        Setting::get()->setIconStyle(next);
        applyStyle(next);
    });

    auto border = makeChild<Ling::Node>();
    border->setHeight(1.f);
    border->setBg(0xE0E0E0FF);
}

void WinSettingCommon::updateSaveDirLabel()
{
    if (!saveDirBtn) return;
    saveDirBtn->setText(Setting::get()->getSaveDir().wstring());
}

void WinSettingCommon::updateHistoryLabel()
{
    if (!historyLabel) return;
    auto days = Setting::get()->getHistoryDays();
    auto text = Lang::get(L"setting.historyDays") + L"  ";
    // 0 直接写"不保留"，省得用户猜 0 是什么意思（和边框粗细那里一个套路）
    text += days <= 0 ? Lang::get(L"setting.historyDaysOff")
                      : std::to_wstring(days) + Lang::get(L"setting.dayUnit");
    historyLabel->setText(text);
}

void WinSettingCommon::setQuickSaveBtn(Ling::Button* btn)
{
    styleToggle(btn, Setting::get()->getQuickSave(), Lang::get(L"setting.toggleOn"));
}

void WinSettingCommon::setAutoStartBtn(Ling::Button* btn)
{
    // 以管理员模式开的自启，开机后也是管理员（那个实例看到命令行里的 --elevate
    // 会自己再提权一次，见 App::relaunchElevatedIfNeeded）—— 按钮上把这点写出来，
    // 免得用户以为"自启了但还是截不了管理员窗口"
    auto on = Setting::get()->getAutoStart();
    styleToggle(btn, on, Lang::get(IsUserAnAdmin() != 0 ? L"setting.toggleOnAdmin"
                                                        : L"setting.toggleOn"));
}

// ———— 三个开关共用的一小套 ————

Ling::Button* WinSettingCommon::makeOnOffBtn(Ling::Node* row)
{
    auto btn = row->makeChild<Ling::Button>();
    btn->setHeightPercent(100.f);
    btn->setWidth(180.f);
    btn->setFontSize(13.f);
    btn->setHoverBg(0xF2F2F2ff);
    return btn;
}

void WinSettingCommon::styleToggle(Ling::Button* btn, bool on, const std::wstring& onText)
{
    if (on) {
        btn->setText(onText);
        btn->setColor(0x597ef7ff);
        btn->setHoverColor(0x597ef7ff);
    }
    else {
        btn->setText(Lang::get(L"setting.toggleOff"));
        btn->setColor(0x333333FF);
        btn->setHoverColor(0x333333FF);
    }
}

// 把自己重新拉起来。新实例带 --wait-pid=<本进程 pid>，等这边退干净再初始化 ——
// 否则会被 Ling 的单实例检查判成"第二个实例"直接退出，热键也抢不到。
// 再带一个 --open-setting：管理员模式切换整个程序要重启一遍（托盘图标先消失再出现），
// 用户是冲着"改权限"来的，重启完把设置页摆回来才接得上（App 那边收到就 WinSetting::init）。
//   elevate = true ：ShellExecuteW runas，走 UAC 提升
//   elevate = false：换成**普通权限**的实例。不能直接 CreateProcess —— 提权进程造出来的
//                    子进程一律继承提权令牌，等于没退出去。正规做法是借已登录的 shell
//                    （explorer，跑在用户会话、中等完整性）的令牌来起：
//                    GetShellWindow → 它的进程令牌 → DuplicateTokenEx → CreateProcessWithTokenW
bool WinSettingCommon::relaunchSelf(bool elevate)
{
    wchar_t exePath[MAX_PATH]{};
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    wchar_t argBuf[64]{};
    swprintf_s(argBuf, L"--wait-pid=%lu --open-setting", GetCurrentProcessId());
    if (elevate) {
        return (INT_PTR)ShellExecuteW(nullptr, L"runas", exePath, argBuf, nullptr, SW_SHOWNORMAL) > 32;
    }
    HWND shellWnd = GetShellWindow();
    if (!shellWnd) return false;
    DWORD shellPid = 0;
    GetWindowThreadProcessId(shellWnd, &shellPid);
    if (!shellPid) return false;
    HANDLE shellProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, shellPid);
    if (!shellProc) return false;
    HANDLE shellToken = nullptr, dupToken = nullptr;
    auto ok = OpenProcessToken(shellProc, TOKEN_DUPLICATE | TOKEN_QUERY, &shellToken) != 0
        && DuplicateTokenEx(shellToken, MAXIMUM_ALLOWED, nullptr, SecurityImpersonation,
            TokenPrimary, &dupToken) != 0;
    if (shellToken) CloseHandle(shellToken);
    CloseHandle(shellProc);
    if (!ok) {
        if (dupToken) CloseHandle(dupToken);
        return false;
    }
    std::wstring cmd = std::format(L"\"{}\" {}", exePath, argBuf);
    STARTUPINFOW si{ sizeof(si) };
    PROCESS_INFORMATION pi{};
    // CreateProcessWithTokenW 需要 SeImpersonatePrivilege —— 管理员进程默认就带
    auto created = CreateProcessWithTokenW(dupToken, LOGON_WITH_PROFILE, nullptr, cmd.data(),
        0, nullptr, nullptr, &si, &pi) != 0;
    CloseHandle(dupToken);
    if (created) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    return created != 0;
}

void WinSettingCommon::hideSelectBox()
{
    if (!selectBox) return;
    win->onMouseDown.remove(onMouseDownToken);
    win->body->removeChild(selectBox);
    selectBox = nullptr;
}

void WinSettingCommon::showSelectBox(Ling::Button* btn)
{
    auto weakThis = getWeakThis();
    onMouseDownToken = win->onMouseDown.add([this,weakThis](POINT pos, bool isRight) {
        if (!weakThis.lock()) return;
        if (!this->selectBox) return;
        if (this->selectBtn->isPosIn(pos)) return;
        if (this->selectBox->isPosIn(pos)) return;
        win->body->removeChild(selectBox);
        this->selectBox = nullptr;
        this->win->onMouseDown.remove(this->onMouseDownToken);
    });
    if (selectBox) {
        win->body->removeChild(selectBox);
    }
    auto langs = Lang::get()->getSupportedLang();
    auto itemH{ 30.f };
    auto totalH = std::min(320.f, itemH * (langs.size()+1));

    selectBox = win->body->makeChild<Ling::ScrollerBox>();
    selectBox->setSize(btn->w/win->dpi, totalH);
    selectBox->setPositionType(Ling::Position::Absolute);
    selectBox->setPosition(Ling::Edge::Left, btn->x/win->dpi);
    selectBox->setPosition(Ling::Edge::Top, btn->y/win->dpi);
    selectBox->setBg(0xFFFFFFFF);
    selectBox->setBorder(1.f, 0x597ef766);
    for (auto& pair:langs)
    {
        auto btn = selectBox->makeChild<Ling::Button>();
        btn->setText(pair.first);
        btn->setHeight(itemH);
        btn->setWidthPercent(100.f);
        btn->setHoverBg(0Xf2f2f2FF);
        btn->setHoverColor(0X000000FF);
        btn->onClick.add([this](Ling::Button* btn) {
            auto lang = Lang::get();
            auto langName = btn->getText();
            auto langs = lang->getSupportedLang();
            for (auto& pair : langs)
            {
                if (pair.first == langName) {
                    Setting::get()->setLang(pair.second);
                    win->close();
                    Ling::App::get()->dq.TryEnqueue([this]() {
                        WinSetting::init();
                    });
                    break;
                }
            }
        });
    }
    auto lastItem = selectBox->makeChild<Ling::Button>();
    lastItem->setText(Lang::get(L"setting.getMoreLang"));
    lastItem->setHeight(itemH);
    lastItem->setWidthPercent(100.f);
    lastItem->setHoverBg(0Xf2f2f2FF);
    lastItem->setHoverColor(0X000000FF);
    lastItem->onClick.add([this](Ling::Button* btn) {
        win->onMouseDown.remove(onMouseDownToken);
        std::wstring downloadUrl{ L"https://github.com/James-ctrl-Doyle/ZPin/tree/main/Lang" };
        ShellExecute(win->hwnd, L"open", downloadUrl.data(), nullptr, nullptr, SW_SHOWNORMAL);
        win->body->removeChild(selectBox);
        selectBox = nullptr;
    });
}
