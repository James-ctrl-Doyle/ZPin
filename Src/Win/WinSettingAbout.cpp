#include "pch.h"
#include "../Lang.h"
#include "WinSetting.h"
#include "WinSettingAbout.h"
#include "../Util.h"

WinSettingAbout::WinSettingAbout(Ling::WinBase* parent):Ling::Node(parent)
{
    // 只留版本号与本项目地址。原来还有一项指向原作者微信，随 fork 一并去掉
    std::vector<std::wstring> keys = { L"version",L"project" };
    for (auto& key : keys)
    {
        auto box = makeChild<Ling::Node>();
        box->setHeight(39.f);
        box->setFlexDirection(Ling::FlexDirection::Row);
        box->setAlignItems(Ling::Align::Center);
        // ⚠ 这一行原来是"标签 flexGrow(1) + 按钮固定宽"。flexGrow 会把标签撑到吃光剩余
        // 空间，再把按钮挤到行的右外侧 —— 按钮的右边缘因此越过了内容区右内边距，
        // 里面的文字也跟着画到窗口边上（实测按钮 x+w 比内容区边界多出 26px）。
        // 改成 SpaceBetween：标签靠左、按钮靠右，两个都按内容宽度，谁都不会越界
        box->setJustifyContent(Ling::Justify::SpaceBetween);

        auto label = box->makeChild<Ling::Label>();
        label->setText(Lang::get(L"about." + key));
        label->setHeightPercent(100.f);
        label->setJustifyContent(Ling::Justify::Center);

        auto btn = box->makeChild<Ling::Button>();
        btn->setId(key);
        if (key == L"version") {
            auto ver = Ling::Util::getVerNum();
            auto verStr = std::format(L"{}.{}.{}", ver[0], ver[1], ver[2]);
            btn->setText(verStr);
            btn->setWidth(120.f);
        }
        else {
            // ⚠ 这一行原来是 setWidth(120)，而地址有 41 个字符 —— 文字直接画到按钮外面去，
            // 看着就是"这一项坏了 / 点不了"。原因不在宽度没给够，而是两件事叠加：
            //   1. Button::setWidth 只影响按钮自己的盒子，**不约束里面的 Text 子节点**
            //   2. Text 建 layout 用的是 FLT_MAX（无约束、永不折行），measureCB 又直接
            //      返回那个自然宽度 —— 于是父节点设多宽都拦不住，文字照着自己居中画出去
            // 所以除了给足宽度，还得用 setMaxTextWidth 把文字宽度也钉住，两边一致
            // 宽度按这串地址在 13pt 雅黑下的实际宽度（实测约 277px）留一点余量
            constexpr float linkW{ 290.f };
            btn->setText(L"github.com/James-ctrl-Doyle/ZPin");
            btn->setWidth(linkW);
            btn->setMaxTextWidth(linkW);
            btn->setColor(0x597ef7ff);
            btn->setHoverColor(0x597ef7ff);
            btn->onClick.add([this](Ling::Button* btn) {
                std::wstring url{ L"https://github.com/James-ctrl-Doyle/ZPin" };
                ShellExecute(win->hwnd, L"open", url.data(), nullptr, nullptr, SW_SHOWNORMAL);
                });
        }
        btn->setAlignItems(Ling::Align::FlexEnd);
        btn->setHeight(28.f);
        btn->setBg(0);
        btn->setHoverBg(0);
        btns.push_back(btn);

        auto border = makeChild<Ling::Node>();
        border->setHeight(1.f);
        border->setBg(0xE0E0E0FF);
    }
}

WinSettingAbout::~WinSettingAbout()
{

}
