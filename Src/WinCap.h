#pragma once
#include <include/Ling.h>
#include "ToolHost.h"

class CutMask;
class CapLong;
class CapVideo;
// 截图主窗口。铺满整个虚拟桌面，拖框结束后并不马上让位，而是留下来当宿主：
// 选区可以继续调整，选区外侧摆着一根工具条 —— 绘图按钮（框完就能在选区里直接画）+
// 撤销重做 + 截长图 / 录屏 / 文字识别 / 二维码 + 关闭 / 保存 / 复制。
// 长图和录屏都挂在它身上。
//
// 它同时是 ToolHost：绘图子系统（Shape* / History / ToolMain / ToolSub）在截图阶段与
// 贴图窗口上跑的是同一份代码，见 ToolHost 的注释。
class WinCap: public ToolHost
{
public:
	~WinCap();
	// enter 为空 = 普通截图，框完出工具条。非空表示框完直接进对应功能，
	// 取值 "pin" / "long" / "video" / "ocr" / "qr"，等价于命令行 --enter=xxx，
	// 但优先级更高 —— 热键是用户当下按的，命令行是进程启动时的约定。
	// 截图窗口已经开着时不再建第二个，只把新的目标功能记下来（还没开始拖框才有效）
	static void init(const std::wstring& enter = L"");
	static WinCap* get();
	// 退出流程里调：窗口对象是文件级静态变量，交给静态析构就在 CoUninitialize 之后了
	static void dispose();
	// 退出流程里调：正在录制时先把编码线程停掉，否则线程与设备会卡住
	static void stopIfRecording();
	// 截图过程中按贴图热键（F3）：立刻收尾 —— 把选区（含标注）存进剪贴板并贴到桌面上。
	// 与"框完点钉住"的差别只是顺手复制了一份，方便马上粘到别处。
	// 还没框出选区时返回 false，让调用方去决定要不要提示
	bool finishToPin();
	// 工具条的摆放：主条（ToolMain）+ 画笔选项（ToolSub）右对齐摞在选区外侧。
	// 只在调整选区这个阶段说话 —— 长图 / 录屏阶段各自的工具条由它们自己摆
	void layoutTools() override;
	// 工具条统一定位规则：右边与选区右边对齐，下方空间够就摆在选区右下方，
	// 不够就摆右上方，上下都不够就盖在选区右下角内部（留一点边距）。
	// 单根条的摆放，ToolVideo / CapVideo 也用它
	void layoutTool(Ling::WinBase* tool);
	// 整窗让出鼠标：录制中用户要能直接操作被录的应用
	void setMouseTransparent(bool transparent);
	// CapLong 开始滚动之前把选区抠成一个洞，滚轮消息才落得到底下的目标窗口上
	void hollowWin();
	void restoreWin();
	// 下面都是给工具条用的门面 ————————————————
	void startPin();
	void startLong();
	void startVideo();
	void startOcr();
	void startQrcode();
	void saveToFile();
	void copyToClipboard();
	// 工具条上那几个"只有截图才有"的功能按钮（截长图 / 录屏 / 文字识别 / 二维码）落到这里
	void onCapAction(const std::wstring& id) override;
	// ToolVideo，转给 capVideo
	void startMp4(bool useSpeaker, bool useMic);
	std::wstring stopRecord();
	// ToolLong，转给 capLong
	// ToolLong 的摆放规则在 CapLong 手里，它 DPI 变了要重走一遍，从这里转进去
	void layoutLongTool();
	void longPin();
	// 用户在另存为对话框里取消时返回 false，此时图还在，不该收工
	bool longSaveToFile();
	void longCopyToClipboard();
public:
	// CapLong / CapVideo 用的就是这一份选区，它们自己不再框选
	std::unique_ptr<CutMask> cutMask;
private:
	WinCap();
	void onCreated() override;
	void layout() override;
	BOOL setCursor() override;
	LRESULT onHitTest(const POINT pos) override;
	// 取景框（放大镜）的位置。preferLeft / preferTop 表示优先摆到光标左侧 / 上方 ——
	// 拖框过程中用它把取景框推到拖动方向的反侧，免得压住正在调的选区
	void setPixPos(POINT pos, bool preferLeft = false, bool preferTop = false);
	void getPixImg(POINT pos);
	void paintPix(ID2D1DeviceContext* ctx);
	void onKey(UINT key);
	// Enter 用：把当前阶段手上的图存进剪切板，效果与 Ctrl+C 一致。
	// 三个阶段各有各的图（选区像素 / 拼好的长图 / 录到的视频），
	// 还在拖框取色（Select）时手上什么都没有，什么也不做
	void copyCurrentStage();
	void onDown(POINT pos, bool isRight);
	void onMove(POINT pos);
	void onUp(POINT pos, bool isRight);
	void onClosed();
	// 建工具条。进"调整选区"阶段时建出来 —— 框完就能直接在选区里画。
	// 传 capTools=true，所以这一根上除了绘图按钮还有截长图 / 录屏 / 文字识别 / 二维码
	void makeTools();
	// 命令行给了 --enter=xxx（long / video / ocr / qr / pin）时，框完选区不出工具条，
	// 直接走对应的那条路 —— 等于替用户点了工具条上的那个按钮。
	// 返回是否已经接手；值不认识（拼错了）就返回 false，照常出工具条
	bool enterByArg();
	// DPI 变了之后重走一遍工具条的摆放规则（哪个阶段就重排哪个工具条）
	void relayoutTool();
	// 宿主（全屏覆盖层）被激活时系统会把它提到 topmost 带的最上面，把同样是 topmost
	// 的工具条全盖住。基类只管 toolMain/toolSub，这里把"截长图 / 录屏"那两根独立工具条
	// 也一并顶回去 —— 不顶的话点了录屏就"按钮全没了"，还退不出来
	void raiseToolbars() override;
	// 进长图 / 录屏阶段的公共动作：收掉底图与工具条，并提到最上层
	void enterLiveStage();
	// 点是不是落在选区里。选了画笔时靠它区分"在选区里画东西"和"在外面调整选区"
	bool isPosInMask(POINT pos) const;
	// 选区（含标注）的像素。复制 / 存盘 / 钉住 / 文字识别都从这里出去。
	// remember 为真时顺手把它写进数据目录的临时文件（贴图 F3 取的就是那份）
	bool getCutPixels(std::vector<BYTE>& pixels, int& cw, int& ch, bool remember = true);

	// ———— 截图历史（数据目录 temp\shots 下，按时间戳命名）————
	// 把当前这张（整屏画面 + 截图框）记进历史。已经在历史里的那一条只更新框，不重复记一条
	void saveShotToHistory();
	// 能不能往前 / 往后翻历史（截图态、且历史里还有更早/更新的）
	bool canGoPrevShot();
	bool canGoNextShot();
	// 翻到上一条 / 下一条：换底图、换框、回到"调选区"阶段，可以重新裁、接着画
	void goPrevShot();
	void goNextShot();
	// 把一条历史读进来当底图：换图、换框、回到调选区阶段。失败返回 false
	bool applyShot(const std::wstring& path);
	// 回到"这次截图本身"（F1 那一刻的整屏图 + 翻出去之前的选区状态）。
	// 与 applyShot 的区别：那个读的是历史文件，这个用的是手里还留着的 screenRaw，
	// 而且能把"还没框"（Select）这个状态也还原回来
	bool restoreLiveShot();
	// 能不能翻历史：截图态的两个阶段都算 —— Select = 刚按 F1、还没框（用户一进来就该能翻），
	// Adjust = 框好了在调。长图/录屏阶段没有"截图框"这回事，不翻。
	// ⚠ 手上正按着鼠标（拖框 / 画图形）时不翻：半途换底图会把这一笔弄乱
	bool historyNavStage() const {
		return (stage == CapStage::Select || stage == CapStage::Adjust)
			&& !isPress && !isMouseDown;
	}
	std::tuple<int, int, int, int> getCMYK(const BYTE& r, const BYTE& g, const BYTE& b);
private:
	enum class CapStage { Select, Adjust, Long, Video };
	CapStage stage{ CapStage::Select };
	// 这次截图框完之后要直奔哪个功能（见 init）。空 = 走常规流程出工具条。
	// 来源是命令行 --enter=xxx 或设置页里配的功能热键，后者优先生效
	std::wstring enterArg;
	std::unique_ptr<CapLong> capLong;
	std::unique_ptr<CapVideo> capVideo;
	// screenImg 是基类 ToolHost 上的成员，这里**不要再声明一个同名的** ——
	// 那样会遮蔽掉基类的：本窗口自己的代码用得到，可 Shape* 拿到的是 ToolHost*，
	// 取到的是基类那个永远为空的（马赛克 / 橡皮擦就静默失效了）。pixImg 是本窗口特有的
	Microsoft::WRL::ComPtr<ID2D1Bitmap1> pixImg;
	D2D1_RECT_F pixSrcRect{};
	// 铺满窗口的画布，走 swap chain 双缓冲：底图、蒙版、放大镜每帧都重画，
	// 单缓冲会让合成器采到"擦干净还没画完"的中间态
	Ling::Canvas* canvas{ nullptr };
	POINT pixPos;
	// 放大镜最近的避让偏好（拖框/调角时按拖动方向定）。调整阶段的悬停沿用同一侧 ——
	// 松手后若改用默认（右下），放大镜会立刻翻进刚框好的选区里挡住内容
	bool pixPreferL{ false }, pixPreferT{ false };
	// 这次拖框的起点（Select 阶段按下的那一点）。拖框中放大镜往背离选区的方向摆，
	// 靠它判断光标在起点的哪一侧
	POINT dragStartPos{ 0, 0 };
	bool isPress{ false }, isClosed{ false }, isMouseTransparent{ false };
	// onDpiChanged 与 onSizeChanged 之间的接力标记，见构造函数里的注释
	bool dpiChanged{ false };
	// 自己认双击用的上一次按下时间与位置。Ling 的窗口类没带 CS_DBLCLKS，
	// 收不到 WM_LBUTTONDBLCLK，只能按系统的双击间隔和双击判定框自己算
	ULONGLONG lastDownTime{ 0 };
	POINT lastDownPos{ 0, 0 };
	// 进长图 / 录屏后不再画底图：底图是拖框那一刻的静态截图，
	// 留着的话录屏和滚动截图拿到的都是这张死图
	bool hideScreenImg{ false };
	// ———— 截图历史 ————
	// F1 那一刻的整屏原始像素（干净、没被遮罩和标注污染），写历史文件时用它
	std::vector<BYTE> screenRaw;
	// 历史文件名，时间倒序（最新在前）。首次用到时才去扫目录
	std::vector<std::wstring> shotFiles;
	bool shotFilesLoaded{ false };
	// -1 = 当前这次截图（还没记进历史）；>= 0 = 正在看 shotFiles[shotIndex]
	int shotIndex{ -1 };
	// 当前画布对应哪条历史（空 = 还没记过）。有值时"再存一次"只更新它的框，不再新增条目
	std::wstring curShotPath;
	// 翻历史翻出去之前，"这次截图"本身是什么状态 —— 全靠它让 . 能翻回来。
	// ⚠ 不能用 saveShotToHistory 代替：那个要求有选区（hasRect），Select 阶段存不了。
	// ⚠ 这两个成员必须写在 CapStage 声明**之后**：带初始化器的成员声明是立即解析的，
	// 放到前面会报 C3646（"未知重写说明符"）；而内联函数体是延迟解析的，所以
	// historyNavStage() 那种写法放在前面没事
	CapStage liveStage{ CapStage::Select };
	D2D1_RECT_F liveMaskRect{};
	// 翻历史的两个键的虚拟键码（设置-快捷键里可改，默认 , 和 .）。
	// 在 init 里取一次就够：窗口是每次截图新建的，用户在设置里改完值再来截图必然生效。
	// 0 = 这一项没绑键（拿 0 去比任何真实按键都不会相等）
	UINT historyPrevVk{ 0 };
	UINT historyNextVk{ 0 };
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> brushBg;
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> brushText;
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> crossBrush;
	// 原地提示（二维码识别结果之类）：一行半透明底 + 白字，画在选区正中，2 秒后自己消失。
	// 与 WinPin 的 showTip 是同一个路子，只是位置在选区中央、窗口默认不退出
	Microsoft::WRL::ComPtr<IDWriteTextLayout> tipLayout;
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> brushTipBg;
	Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> brushTipText;
	void showTip(const std::wstring& text);
	void paintTip(ID2D1DeviceContext* ctx);
};

