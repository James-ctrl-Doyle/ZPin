#include "pch.h"
#include "../Lang.h"
#include "../Setting.h"
#include "../Util.h"
#include "WinSetting.h"
#include "WinSettingCommon.h"

WinSettingCommon::WinSettingCommon(Ling::WinBase* parent):Ling::Node(parent)
{    
    initAutoStartCtrls();
    initLangCtrls();
    initBorderCtrl();
    initSaveCtrls();
    initHistoryCtrl();
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

    auto btn = box->makeChild<Ling::Button>();
    btn->setText(L"\ue687");
    btn->setFontFamily(L"icon");
    btn->setHeightPercent(100.f);
    btn->setFontSize(18.f);
    btn->setWidth(60.f);
    setAutoStartBtn(btn);

    btn->onClick.add([this](Ling::Button* btn) {
        auto setting = Setting::get();
        auto isAutoStart = setting->getAutoStart();
        setting->setAutoStart(!isAutoStart);
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
    // ———— 快速保存开关（照"开机自启动"那个开关的写法）————
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

        auto btn = box->makeChild<Ling::Button>();
        btn->setText(L"\ue687");
        btn->setFontFamily(L"icon");
        btn->setHeightPercent(100.f);
        btn->setFontSize(18.f);
        btn->setWidth(60.f);
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
    auto on = Setting::get()->getQuickSave();
    if (on) {
        btn->setText(L"\ue688");
        btn->setColor(0x597ef7ff);
        btn->setHoverColor(0x597ef7ff);
    }
    else {
        btn->setText(L"\ue687");
        btn->setColor(0x666666FF);
        btn->setHoverColor(0x666666FF);
    }
}

void WinSettingCommon::setAutoStartBtn(Ling::Button* btn)
{
    auto setting = Setting::get();
    auto isAutoStart = setting->getAutoStart();
    if (isAutoStart) {
        btn->setText(L"\ue688");
        btn->setColor(0x597ef7ff);
        btn->setHoverColor(0x597ef7ff);
    }
    else {
        btn->setText(L"\ue687");
        btn->setColor(0x666666FF);
        btn->setHoverColor(0x666666FF);
    }
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
        std::wstring downloadUrl{ L"https://github.com/James-ctrl-Doyle/ScreenCapture/tree/main/Lang" };
        ShellExecute(win->hwnd, L"open", downloadUrl.data(), nullptr, nullptr, SW_SHOWNORMAL);
        win->body->removeChild(selectBox);
        selectBox = nullptr;
    });
}
