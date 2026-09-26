#pragma once
#include <include/Ling.h>
#include "History.h"

class ToolMain;
class ToolSub;
class ShapeBase;
class ShapeText;

// 能承载"绘图 / 标注"这套东西的窗口的共同部分。
//
// 两个窗口都从这里派生：
//   WinCap —— 截图覆盖层。框好选区之后就能在选区里直接画，画完再钉住 / 保存 / 复制。
//   WinPin —— 贴图窗口。默认没有工具条、只有一张图；右键把工具条唤回来时还是同一套绘图代码。
//
// 这里的成员名是**刻意**与原来 WinPin 上的保持一致的（toolMain / toolSub / history /
// shapeHover / screenImg / scale / getTextBox / setEditingText / onToolStyleChanged /
// layoutTools）—— 这样 Shape* / History / ToolMain / ToolSub 里的 win->xxx 一行都不用改，
// 只是 owner 的类型从 WinPin 变成了 ToolHost。改名前请先确认那几个目录里没有引用。
class ToolHost : public Ling::WinBase
{
public:
	// history 在这里建，两个宿主就都不用各自操心了。
	// 之前是 WinPin 在构造体里建、WinCap 忘了建 —— 结果截图窗口上点了画笔却画不出东西
	// （beginShape 里 !history 直接返回 false），Ctrl+Z 更是直接踩空指针
	ToolHost();
	~ToolHost();
	// ———— 绘图子系统共用的状态 ————
	// 未选中任何画笔时 curId 为空。两个窗口都靠它区分"拖窗口 / 调选区"和"画图"
	std::unique_ptr<ToolMain> toolMain;
	std::unique_ptr<ToolSub> toolSub;
	// 光标下可拖拽的图形（不是本次新建的那个）。History 删元素时会把它清掉
	ShapeBase* shapeHover{ nullptr };
	// 本次按下新建出来的图形。抬手时只对它做"有没有画出东西"的判定
	ShapeBase* newShape{ nullptr };
	// 本次按下之后光标有没有真的移动过。判"按下马上弹起"只认这个，
	// 不去看各 shape 的几何 —— 那些成员的初值状态不一，不可靠
	bool hasDragged{ false };
	// 左键是不是按着（拉窗口、调选区、画图都算）。图形据此决定要不要画夹点
	bool isMouseDown{ false };
	// 按下点在窗口客户区的坐标（拖窗口按它算位移，画图按它判"动没动"）
	POINT pressPos{ 0, 0 };
	// 未撤销的绘图元素。两个窗口各自持有一份，互不影响
	std::unique_ptr<History> history;
	// 绘图所基于的底图。ShapeMosaic 要读它算马赛克块，ShapeEraser 拿它当"擦回原样"的画刷。
	// WinPin 是截图（或外部像素）；WinCap 是整张桌面
	Microsoft::WRL::ComPtr<ID2D1Bitmap1> screenImg;
	// 显示倍数。1 = 原始像素。底图与所有 shape 的坐标一律按底图像素存，
	// 缩放只体现在画的时候上一个变换、以及收到鼠标坐标时先除回去。
	// WinCap 固定 1（覆盖层就是 1:1 铺满桌面），WinPin 会被 Ctrl+滚轮改
	float scale{ 1.f };

	// 当前有没有选中画笔。定义在 .cpp 里 —— 这里要用到 ToolMain 的完整定义，
	// 而头文件里只前置声明了它（ToolMain.h 又要回头包含本文件，不能在头里直接包含）
	bool hasTool() const;

	// ———— 共用几何 ————
	// 底图的像素尺寸
	D2D1_SIZE_U getImgSize() const;
	// 窗口客户区坐标 → 底图坐标。shape 存的、认的都是底图像素
	POINT toImgPos(const POINT& pos) const;

	// ———— 共用绘制 ————
	// 把所有未撤销的 shape 画到 ctx 上（不含底图、不含窗口装饰、不设变换）。
	// 调用方负责准备好坐标系（底图像素）与裁剪
	void paintShapes(ID2D1DeviceContext* ctx);

	// ———— 共用鼠标交互（入参一律是窗口客户区坐标）————
	// 判断光标下有没有可拖拽的图形，顺带更新 shapeHover。
	// 返回是否命中（命中时不改 isMouseDown，调用方自己决定怎么处理）
	bool hoverShapeAt(POINT pos);
	// 按下：命中已有元素就拖它，否则按当前画笔新建。返回是否被绘图接手
	bool beginShape(POINT pos);
	void dragShape(POINT pos);
	// 抬手。返回"这一下是否新建出了一个留得住的元素"，
	// 供调用方填 prevPressCreatedShape（双击前半段放下的东西不该被复制进剪贴板）
	bool endShape(POINT pos);

	// ———— 共用的文本输入框 ————
	// 两个窗口共用一套逻辑：所有 ShapeText 共用一个 TextBox，第一次用到时才建。
	// 共用而不是一个 shape 一个：TextBox 构造时会往窗口的十来个事件上挂回调，
	// N 个实例意味着每次鼠标移动都要跑 N 遍，而同一时刻只可能有一个 ShapeText 在编辑。
	Ling::TextBox* getTextBox();
	// ShapeText 进入 / 退出编辑时登记自己。传 nullptr 表示没有在编辑的文本
	void setEditingText(ShapeText* shape);
	// 选了画笔时光标归绘图：悬停在已有元素上由元素自己决定（夹点朝哪个方向拖），
	// 否则是十字（文字工具给 I 形，提示这里要打字）。
	// 返回**是否已经接手** —— 没接手时宿主才按自己的规则来：
	// 截图覆盖层接着判"调整选区"的那套箭头，贴图窗口接着判"取字 / 普通箭头"。
	// 两个宿主的光标分支曾经是各写一遍，这里收成一份，免得改了一边忘了另一边
	bool setToolCursor();
	// 把窗口抬成前台并获得键盘焦点。截图覆盖层、贴图窗口都是热键唤出的 ——
	// ShowWindow 不会激活它们，窗口不是前台时 SetFocus 会被系统立刻收回
	// （WM_KILLFOCUS）：文字编辑刚建起来就被掐掉，键盘快捷键也时灵时不灵。
	// 普通 SetForegroundWindow 受前台锁限制（本进程不是前台时多半被拒），
	// 经典解法是先把自己挂到当前前台线程的输入队列里拿许可，抢完再摘掉
	void takeForeground();
	// 把工具条重新顶到 topmost 带的最上面。宿主窗口被激活时系统会把它提到这一带的
	// 最上面，而全屏的宿主一抬就把同样是 topmost 的工具条全盖住了 —— 看起来就是
	// "工具条凭空消失"。每次宿主拿到焦点（WM_SETFOCUS）都要顶一遍。
	//
	// 虚函数：WinCap 除了 toolMain/toolSub，还挂着"截长图 / 录屏"那两根**独立的**
	// 工具条（它们各有自己的窗口，不是 ToolHost 的成员），同样会被全屏宿主盖住，
	// 必须在派生类里一并顶回去 —— 这正是"点录屏之后按钮全没了、退不出来"的成因
	virtual void raiseToolbars();
	// 把一个 topmost 窗口顶到 topmost 带的最上面（不动大小位置、不抢激活）。
	// 非 ToolHost 的工具条（ToolLong / ToolVideo）也用它，所以是静态的
	static void raiseTopmost(HWND hwnd);

	// ToolSub 上的颜色 / 字号 / 粗体 / 斜体变了，转给正在编辑的文本立即生效
	void onToolStyleChanged();
	// 正在编辑的文本。非空表示"编辑中"：此时落在文本框里的鼠标事件、
	// 以及所有键盘事件都归 TextBox，宿主自己那套要让路
	ShapeText* editingText{ nullptr };
	// 最近一次文字编辑结束的时刻（GetTickCount64，毫秒）。TextBox 与宿主订阅的是
	// **同一个** onKeyDown 事件，按 ESC 时两边都会被调到 —— 若 TextBox 先执行，
	// 它的失焦收尾会把 editingText 清掉，轮到宿主时就分不清"刚退编辑"和"本来没在编辑"了。
	// 宿主的 ESC 靠这个时间戳保证：编辑刚结束的一小段窗口期内不关整个窗口
	ULONGLONG textEditEndedAt{ 0 };

	// 把工具条摆到选区/贴图周围。两个窗口各有各的规则
	virtual void layoutTools() {}
	// 共用的绘图工具条上有"复制到剪切板""保存为文件"两个按钮，它们对两个宿主都是
	// "把这张合成好的图拿出去"，所以提到这里当接口 —— 两个窗口各自实现
	virtual void copyToClipboard() = 0;
	virtual void saveToFile() = 0;
	// 工具条上"只有截图那一根才有"的功能按钮（截长图 / 录屏 / 文字识别 / 二维码）。
	// 贴图窗口上不会出现这几个（图已经贴出来了，再截长图没有意义），所以默认什么都不做，
	// 由 WinCap 覆写去派发
	virtual void onCapAction(const std::wstring& id) { (void)id; }

protected:
	// 文本输入框见 getTextBox()。位置由 ShapeText 按自己的矩形指定
	Ling::TextBox* textBox{ nullptr };
};
