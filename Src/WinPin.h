#pragma once
#include <include/Ling.h>
#include "Ocr.h"
#include "ToolHost.h"

// 贴图窗口：把刚截下来的那块图钉在屏幕原处。
//
// 默认**没有工具条**，常态就是"一张图"：
//   · 鼠标移到识别到的文字上 —— 像在编辑器里那样按住拖选一段，Ctrl+C 复制
//   · 拖在空白处 —— 移动贴图位置
//   · 滚轮 —— 放大缩小
//   · Esc —— 关掉
//   · 右键 —— 把绘图工具条唤回来 / 再收起来（与截图覆盖层共用同一套 ToolHost 绘图代码）
//
// 文字识别在建窗口后自动跑一遍（见 startOcr），识别结果只画在屏幕上，不进导出图。
class WinPin : public ToolHost
{
public:
	~WinPin();
	// 从一块现成的 BGRA 像素建贴图窗口。data 要求 top-down、行紧凑（步长 = w*4）。
	// x / y 是窗口左上角的**屏幕坐标** —— 原位贴出时就是当初框的那块位置。
	// initScale < 1 时窗口按这个倍数建出来（底图仍是原始分辨率），
	// 贴一张比工作区还大的图时用它把整张图放进去
	static void initFromData(int x, int y, int w, int h, std::vector<BYTE>& data,
		float initScale = 1.f, bool ocr = false);
	// 把"最近一次截图"贴出来。App 每次收工都会把结果写进数据目录的临时文件
	//（见 Util::saveLastCapture），这里读它 —— 不从剪贴板读，免得复制过文字之后就贴不出图了。
	// 读不到就弹一句提示。返回是否真的贴出来了
	static bool initFromLastCapture(bool ocr);
	// "贴图"这个动作的统一入口（贴图热键与托盘菜单都走它）：
	//   · 截图窗口正开着 —— 说明用户是在截图过程中按的，立刻收尾：
	//     截图 → 存进剪贴板 → 贴到桌面上（见 WinCap::finishToPin）
	//   · 否则 —— 把最近一次截图贴出来
	static void doPin();
	// 当前屏幕上还有没有贴图窗口。用完即走模式靠它判断"活干完了没"：
	// 截图窗口关掉时贴图窗口可能才刚建起来，那时候不能退进程
	static bool hasWindow();
	// 退出流程里调：窗口对象是文件级静态变量，交给静态析构就在 CoUninitialize 之后了
	static void dispose();
	void layoutTools() override;
	// 把底图与所有未撤销的 shape 合成后写入剪切板，成功即关窗
	void copyToClipboard();
	// 弹另存为对话框，把合成结果存成 PNG，成功即关窗；用户取消或失败则保持窗口
	void saveToFile();
	// 起一次文字识别（异步）。notify 表示"这是用户主动要识别"：没装语言包、
	// 或没识别到文字时会明确告诉他。F3 贴图那条自动识别走 notify = false，
	// 免得贴一张没字的图就弹一个框
	void startOcr(bool notify);
	// 已经识别出文字了
	bool hasOcrText() const { return ocrPage && !ocrPage->words.empty(); }
	// 文字拾取模式：识别到文字了、而且没有选中任何画笔。
	// 选中画笔时鼠标归绘图，文字层让路（工具条是右键唤回来的，那时用户就是想画东西）
	bool textPickMode() const { return hasOcrText() && !hasTool(); }
private:
	WinPin(int x, int y, int w, int h, const std::vector<BYTE>* data = nullptr, float initScale = 1.f);
	void onCreated() override;
	void layout() override;
	void onMinMaxInfo(MINMAXINFO* mmi) override;
	void onDown(POINT pos, BOOL isRight);
	void onMove(POINT pos);
	void onUp(POINT pos, BOOL isRight);
	void onKey(UINT key);
	void onTimerCB(UINT id);
	void onClosed();
	BOOL setCursor() override;
	// 把工具条收起来 / 唤回来。默认是收起的（贴图窗口的常态就是一张图）
	void hideTools();
	void toggleTools();
	// 离屏合成出最终图像的像素（BGRA、top-down、行步长紧凑为 size.width*4）。
	// 只画底图和未撤销的 shape，不含蓝色边框、夹点与文字层高亮。
	// size 是出参，给的是底图的原始尺寸 —— 必须拿它去解释 pixels，不能用窗口的 w/h：
	// 缩放改的只有窗口大小，两者对不上就是按错误的宽高读缓冲区（越界崩溃、图也是花的）
	bool getImagePixels(std::vector<BYTE>& pixels, D2D1_SIZE_U& size);
	// 只读底图本身（不带任何 shape、不改编辑状态），交给 Ocr 去识别。
	// 之所以单独一个函数而不是复用 getImagePixels：OCR 要的是"原图"，
	// 就算图上已经画了标注也不该拿带标注的合成结果去识别
	bool getBaseImagePixels(std::vector<BYTE>& pixels, D2D1_SIZE_U& size);
	// 另存为对话框会抢走前台并把 WinPin 激活，取消保存后用它把窗口层级和前台窗口恢复原样
	void restoreWindowState(HWND foregroundBeforeDialog);
	// 把窗口尺寸掰成"底图像素 × scale"。系统在 DPI 变化时会按新旧缩放比擅自缩放窗口
	// （贴图窗口的尺寸其实是钉死在底图上的，见构造函数里的注释），缩放倍数变了也用它
	void applyWinSize();
	// 缩放到新倍数。anchor 是窗口客户区里要保持不动的那一点（一般就是光标位置），
	// 缩放后窗口跟着改大小，并反向挪一下窗口位置，让 anchor 底下的那块图还停在原处
	void applyScale(float newScale, POINT anchor);
	// 在右上角浮一条提示（缩放倍数、复制文字的反馈），停手 800ms 后由定时器收掉
	void showTip(const std::wstring& text);
	void paintTip(ID2D1DeviceContext* ctx);
	// 文字层：识别到的词铺一层很淡的蓝（"这里能选"），选中的那段加深
	void paintOcrLayer(ID2D1DeviceContext* ctx);
	// OCR 结果从后台线程回来（已经在 UI 线程上）
	void onOcrDone(std::shared_ptr<OcrPage> page);
	// 底图上 (x, y) 处那个词的下标。只在真正落在某个词上时才认 ——
	// 没落在任何词上返回 -1，那个位置要留给"拖窗口"。一张图一个词都没有时也返回 -1
	int wordIndexAt(float x, float y) const;
	// 选中的区间收成文本；没选中返回空串
	std::wstring selectedOcrText() const;
	// 选中区间的两个端点（底图 words 的下标，升序）。selFrom 是区间起点
	int selFrom() const;
	int selTo() const;
	bool hasSelection() const { return selAnchor >= 0 && selCur >= 0; }
	void clearSelection();
private:
	// OCR 跑在后台线程，回来时得确认"这个窗口还在"。这个对象随本窗口一起析构，
	// 回调里只拿它的 weak_ptr —— 锁不住就说明窗口没了，结果直接丢掉
	struct OcrGuard {};
	std::shared_ptr<OcrGuard> ocrGuard{ std::make_shared<OcrGuard>() };
	// 识别出来的文字层。为空表示没识别 / 没识别到 / 结果还没回来
	std::shared_ptr<OcrPage> ocrPage;
	// 这张图已经起过识别（不管成没成）。避免同一个窗口反复起 OCR
	bool ocrStarted{ false };
	// 文字选择：从按下那个"词"到当前光标所在"词"的连续区间（按阅读顺序），
	// 与文本编辑器里拖选一段文字是一回事。两个都是 ocrPage->words 的下标，-1 = 没有
	int selAnchor{ -1 }, selCur{ -1 };
	// 这一次按下是在拖窗口（而不是在选字 / 画图）
	bool movingWindow{ false };
	// 整个窗口内容都画在这块画布上，走 swap chain 后端：贴图窗口拖动时每帧重绘，
	// 单缓冲的合成表面会被采样到"擦干净→逐个重画"的中间态，表现为图和边框整帧闪掉。
	Ling::Canvas* canvas{ nullptr };
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> borderBrush;
	// 右上角的浮动提示。非空即显示，停手一会儿由定时器清掉
	Microsoft::WRL::ComPtr<IDWriteTextLayout> tipLayout;
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> brushTipBg, brushTipText;
	// 文字层的两层高亮
	// 选中文字时的高亮。识别到的词本身不铺底（图要保持原样），只有拖选中的那一段才画
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> brushOcrSel;
	bool isClosed{ false };
	// onDpiChanged 与 onSizeChanged 之间的接力标记，见构造函数里的注释
	bool dpiChanged{ false };
};
