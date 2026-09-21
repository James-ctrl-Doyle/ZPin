#pragma once
#include <wrl.h>
#include <dwrite_3.h>
#include <winrt/Windows.UI.Composition.h>
#include "../include/Node.h"

namespace Ling {
    class WinBase;

    // 内部实现类：一段文本的最小渲染单元。
    //   - surface 尺寸恒等于 DWrite 的 metric（避免父容器 flexGrow 撑爆显存）；
    //   - 通过 yoga 的 measureFunc 把 metric 报告给父节点，父节点用原生 flex
    //     完成对齐（不再在 paint() 里手写偏移）。
    // 只在 src 内部使用，不对外暴露。
    class Text : public Node
    {
    public:
        Text(WinBase* win);
        ~Text();
        void setText(const std::wstring& text);
        std::wstring getText();
        void setFontSize(float val);
        void setFontFamily(const std::wstring& val);
        void setColor(Color color);
        // 约束文字的最大宽度（逻辑像素，内部 ×dpi）。
        //
        // 为什么需要它：Text 是按钮/标签的子节点，而建 layout 用的是 FLT_MAX —— 即
        // **无约束**，永不折行，measureCB 也直接返回这个自然宽度。于是父节点无论设多宽
        // 都拦不住文字，它会按自然宽度居中画出去、溢出到父容器之外（设置-关于-项目
        // 那一项就是这么坏的：41 字符的地址从 120px 宽的按钮里画出来，压到窗口边上）。
        // 设了 maxWidth 之后：measure 返回被夹住的宽度，绘制也在同一宽度上 CreateTextLayout，
        // 超出部分由 DWrite 自己按 word wrapping 处理。
        // ⚠ 传 0 或负数 = 不约束（回到原行为）
        void setMaxWidth(float val);
    private:
        // 尺寸/布局完全由内容决定，屏蔽掉外部改尺寸、改子节点的 API，避免误用。
        using Node::makeChild;
        using Node::setFlexGrow;
        using Node::setFlexShrink;
        using Node::setWidth;
        using Node::setHeight;
        using Node::setSize;
        using Node::setWidthPercent;
        using Node::setHeightPercent;
        using Node::setSizePercent;
        using Node::setPadding;
        using Node::setPaddingLeft;
        using Node::setPaddingTop;
        using Node::setPaddingRight;
        using Node::setPaddingBottom;
        using Node::setFlexWrap;
        using Node::setAlignItems;
        using Node::setJustifyContent;
        using Node::setFlexDirection;
        using Node::setBg;

        static YGSize measureCB(YGNodeConstRef node, float width, YGMeasureMode widthMode, float height, YGMeasureMode heightMode);
        void layout() override;
        void onDpiChanged() override;
        void paint();
        // 建 textLayout。字体族名决定用哪个 TextFormat（图标字体和系统字体不在同一个
        // 字体集合里），所以换族名不能只 SetFontFamilyName，得整个重建
        void makeLayout();

    private:
        winrt::Windows::UI::Composition::CompositionDrawingSurface surface{ nullptr };
        Microsoft::WRL::ComPtr<IDWriteTextLayout> textLayout;
        Color color{ 0x333333FF };
        std::wstring text;
        std::wstring fontFamily;
        float fontSize{ 12.f };
        // 0 = 不约束。见 setMaxWidth 的说明
        float maxWidth{ 0.f };
    };
}
