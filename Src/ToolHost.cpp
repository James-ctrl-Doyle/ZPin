#include "pch.h"
#include "ToolHost.h"
#include "ToolMain.h"
#include "ToolSub.h"
#include "ShapeBase.h"
#include "ShapeText.h"

ToolHost::ToolHost()
{
	// History 的构造只是把 this 存起来，所以在基类构造期建是安全的
	history = std::make_unique<History>(this);
	// 全屏宿主一被激活就会盖住自己的工具条（见 raiseToolbars 的注释），每次拿到焦点顶一遍
	onFocus.add([this]() { raiseToolbars(); });
}

ToolHost::~ToolHost()
{
}

bool ToolHost::hasTool() const
{
	return toolMain && !toolMain->curId.empty();
}

D2D1_SIZE_U ToolHost::getImgSize() const
{
	if (!screenImg) return D2D1::SizeU(0, 0);
	// 要的是像素数，所以问 GetPixelSize 而不是 GetSize（后者返回的是按位图自身 dpi 折算的 DIP）
	return screenImg->GetPixelSize();
}

POINT ToolHost::toImgPos(const POINT& pos) const
{
	if (scale == 1.f) return pos;
	return POINT{ static_cast<LONG>(std::lround(pos.x / scale)),
		static_cast<LONG>(std::lround(pos.y / scale)) };
}

void ToolHost::paintShapes(ID2D1DeviceContext* ctx)
{
	if (!history) return;
	for (auto& shape : history->shapes)
	{
		if (!shape->isUndo) {
			shape->paint(ctx);
		}
	}
	// 拖着图形的时候不画夹点：夹点跟着图形走会互相打架
	if (!isMouseDown && shapeHover) {
		shapeHover->paintDragger(ctx);
	}
}

bool ToolHost::setToolCursor()
{
	if (!hasTool()) return false;
	if (shapeHover) {
		shapeHover->setCursor();
		return true;
	}
	SetCursor(LoadCursor(nullptr, toolMain->curId == L"text" ? IDC_IBEAM : IDC_CROSS));
	return true;
}

bool ToolHost::hoverShapeAt(POINT pos)
{
	if (!hasTool() || !history) return false;
	auto imgPos = toImgPos(pos);
	// 从后往前找：后画的压在先画的上面，重叠时该命中的是更"表面"的那个
	for (auto it = history->shapes.rbegin(); it != history->shapes.rend(); ++it)
	{
		auto cur = it->get();
		if (cur->isUndo) continue;
		cur->mouseMove((float)imgPos.x, (float)imgPos.y);
		if (cur->hoverDraggerIndex >= 0) {
			if (shapeHover != cur) {
				shapeHover = cur;
				// 停手 800ms 后由定时器把夹点收掉，和 WinPin 原来的做法一致
				setTimer(800, 100);
				refresh();
			}
			return true;
		}
	}
	if (shapeHover) shapeHover = nullptr;
	return false;
}

bool ToolHost::beginShape(POINT pos)
{
	if (!hasTool() || !history) return false;
	pressPos = pos;
	hasDragged = false;
	auto imgPos = toImgPos(pos);
	if (shapeHover) {
		newShape = nullptr; // 改的是已有元素，不参与"空元素"判定
		shapeHover->mouseDown((float)imgPos.x, (float)imgPos.y);
		return true;
	}
	shapeHover = history->createShape(toolMain->curId, imgPos.x, imgPos.y);
	newShape = shapeHover;
	return true;
}

void ToolHost::dragShape(POINT pos)
{
	if (!shapeHover) return;
	// 光标一步没挪也会来 WM_MOUSEMOVE，所以跟按下点比一下再算拖动
	if (pos.x != pressPos.x || pos.y != pressPos.y) hasDragged = true;
	auto imgPos = toImgPos(pos);
	shapeHover->mouseDrag((float)imgPos.x, (float)imgPos.y);
	refresh();
}

bool ToolHost::endShape(POINT pos)
{
	if (!shapeHover) return false;
	auto justCreated = newShape;
	newShape = nullptr;
	// 新建的这一笔按下马上弹起，什么也没画出来：直接丢掉，
	// 也省了 mouseUp 里的收尾开销（马赛克那边要把 GPU 像素读回内存，不该为一个要删的元素白做）
	if (shapeHover == justCreated && !hasDragged && !shapeHover->isValidWithoutDrag()) {
		history->removeShape(shapeHover); //它会顺手清掉 shapeHover 并刷新
		return false;
	}
	bool created = (shapeHover == justCreated);
	auto imgPos = toImgPos(pos);
	shapeHover->mouseUp((float)imgPos.x, (float)imgPos.y);
	refresh();
	setTimer(800, 100);
	return created;
}

Ling::TextBox* ToolHost::getTextBox()
{
	if (textBox) return textBox;
	// 建在 canvas 之后：Composition 的子 visual 按插入顺序叠放，文本框要盖在截图上面。
	// 绝对定位，位置由 ShapeText 按自己的矩形指定，不参与 body 的 flex 排布
	textBox = body->makeChild<Ling::TextBox>();
	textBox->setPositionType(Ling::Position::Absolute);
	// 不折行、尺寸跟着文字长，与 2.4.25 的文本窗口一致
	textBox->setAutoSize(true);
	// 背景、边框都不画：编辑中看到的就是最终效果，那圈虚线框由 ShapeText 自己画
	textBox->hide();
	return textBox;
}

void ToolHost::setEditingText(ShapeText* shape)
{
	editingText = shape;
	// 清空 = 编辑结束。宿主的 ESC 用这个时间戳识别"刚退出编辑"（见头文件注释）
	if (!shape) textEditEndedAt = GetTickCount64();
}

void ToolHost::raiseTopmost(HWND hwnd)
{
	if (!hwnd || !IsWindow(hwnd)) return;
	SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
		SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
}

void ToolHost::raiseToolbars()
{
	// 写死成 WinBase* 数组：两个派生类指针直接放 initializer_list 推不出公共类型
	Ling::WinBase* tools[] = { toolMain.get(), toolSub.get() };
	for (auto t : tools) {
		if (t) raiseTopmost(t->hwnd);
	}
}

void ToolHost::takeForeground()
{
	if (!hwnd) return;
	DWORD fgPid{ 0 };
	const DWORD fgThread = GetWindowThreadProcessId(GetForegroundWindow(), &fgPid);
	const DWORD curThread = GetCurrentThreadId();
	// 前台窗口可能属于本线程（那就直接抢）；挂在别人的输入队列上要记得摘，否则键鼠状态互相污染
	const bool attached = fgThread != 0 && fgThread != curThread;
	if (attached) AttachThreadInput(curThread, fgThread, TRUE);
	SetForegroundWindow(hwnd);
	SetFocus(hwnd);
	if (attached) AttachThreadInput(curThread, fgThread, FALSE);
}

void ToolHost::onToolStyleChanged()
{
	if (editingText) editingText->applyStyle();
}
