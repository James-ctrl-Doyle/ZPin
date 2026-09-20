#pragma once
#include <include/Ling.h>
#include <filesystem>
#include <winrt/Windows.Data.Json.h>
using namespace winrt::Windows::Data::Json;

class Setting
{
public:
	// 一个可配置的全局热键。
	// type 既是 config.json 里 shortcutKey 下的键名，也是语言文件里的键名（shortcut.<type>）
	// msgId 是 RegisterHotKey 的 id，Ling 靠它区分 WM_HOTKEY
	// def 是配置里从没写过这一项时的默认组合，空串表示默认不给热键（功能照旧可用，只是没热键）
	// legacy 是这个热键在老版本里的默认值，迁移时用它判断"用户改过没有"，空串表示没有老默认
	// windowOnly = true 的项**不是全局热键**，它只在截图窗口开着的时候生效
	// （比如"上一条/下一条截图"）。这类项：
	//   · msgId 写 0，不参与 RegisterHotKey，也不参与"暂停/恢复热键"
	//   · 捕获时用另一套校验（见 WinSettingShortcut）：允许单个不带修饰键的键
	//   · 存储仍然在 shortcutKey 段下，和全局热键共用 get/setShortcutKey
	struct ShortcutDef
	{
		const wchar_t* type;
		int msgId;
		const wchar_t* def;
		const wchar_t* legacy;
		bool windowOnly{ false };
	};
	// 全部可配置的全局热键。设置页的列表和热键注册都从这一张表走，
	// 以后加一个热键只改这里，两边不会各自漏掉一项
	static const std::vector<ShortcutDef>& shortcutDefs();
	// 由 type 反查 msgId，表里没有就返回 0
	static int shortcutMsgId(const std::wstring& type);
	// 键名（"," "F1" "Enter" 之类）→ 虚拟键码，认不出返回 0。
	// ⚠ 单个字符**不能**直接交给 `Ling::Util::strToKey`：它把 "." 认成小键盘的 VK_DECIMAL
	//（"小键盘符号"那一段排在"主键盘符号键"前面，先匹配先返回，后面那几行是死代码），
	// 于是句号键永远匹配不上。单字符统一用 VkKeyScanW 反查 —— 它给的是主键盘上那个键，
	// 正是捕获时 MapVirtualKeyW(VK_TO_CHAR) 的逆运算。
	// 设置页的校验和截图窗口里的按键匹配都走这一个函数，免得两处认的键不一样
	static UINT keyNameToVk(const std::wstring& name);

	~Setting();
	static void init();
	// 必须在 CoUninitialize 之前调用：configObj 是 WinRT 对象，晚一步释放就是野内存
	static void dispose();
	static Setting* get();
	std::filesystem::path getDataPath();
	const JsonObject getConfigObj();
	// keys 为空表示清除这一项的热键。不论设置还是清除，都会把结果同步到系统热键上
	void setShortcutKey(const std::wstring& type, const std::vector<std::wstring>& keys);
	// 只读配置里存的那一份，没配过、或配成了空串都返回空
	std::wstring getShortcutKey(const std::wstring& type);
	// 这一项实际生效的组合：配置里"显式写过"就以配置为准（写空串 = 用户主动不要这个热键），
	// 配置里压根没有这一项才用表里的默认值。设置页显示的和 initShortcutKeys 注册的都是它
	std::wstring effectiveShortcutKey(const std::wstring& type);
	// 把上面那个组合串翻成虚拟键码，给"截图窗口内的按键"用（比如历史翻页）。
	// 没配、配成了空串、或者翻不出键码（Macro 之类）都返回 0 —— 调用方拿 0 去比
	// 任何真实按键都不会相等，等于这一项没绑键
	UINT effectiveShortcutVk(const std::wstring& type);
	void setAutoStart(bool autoStart);
	bool getAutoStart();
	std::wstring getLang();
	void setLang(const std::wstring& lang);
	// 截图选区的边框粗细（逻辑像素，0 = 不画边框）。乘上 dpi 才是物理像素
	float getBorderWidth();
	void setBorderWidth(float w);
	// ———— 保存位置 ————
	// 默认保存目录。没设过、或设的那个目录已经不存在了，就用系统的"下载"文件夹
	std::filesystem::path getSaveDir();
	void setSaveDir(const std::filesystem::path& dir);
	// 快速保存：勾上之后点保存不再弹另存为，直接写进 getSaveDir()，文件名还是时间戳
	bool getQuickSave();
	void setQuickSave(bool on);
	// 截图历史保留天数（0 = 不保留历史）。超期的历史文件在启动/每次写历史时清掉
	int getHistoryDays();
	void setHistoryDays(int days);
	// 数据目录下的 temp 子目录：截图缓存、录屏临时文件、截图历史都在这下面
	std::filesystem::path getTempPath();
	// 按 shortcutDefs 逐项注册热键，并挂一个统一的分发回调
	void initShortcutKeys();
	// 用户正在设置页里捕获新组合时，把已注册的热键全撤掉；捕获结束再挂回去。
	// 不撤的话：点"截图"那一行、按下 F1（想把它重设成 F1，这是最常见的操作），
	// 全局热键会抢先把截图窗口弹出来盖住设置页 —— 而它正是这一项自己在生效。
	// 两个都不写配置，纯粹是暂时的让位；resume 先撤再加，重复调用也安全
	void suspendShortcuts();
	void resumeShortcuts();
	// 贴图窗口子工具栏（ToolSub）的状态。每个工具在 config.json 的 toolPin 下各占一组，
	// 组名就是 ToolMain 上的按钮 id（rect / ellipse / ... / eraser），键名由调用方给
	// （fill、width、colorIndex 之类，各工具语义不同）。
	// 取不到就返回 def —— 老版本的配置文件里没有这些键，用户手工改坏了也算取不到，都不该抛异常。
	// set 一律立即落盘：用户调一次工具状态就得记住一次。
	bool getToolFlag(const std::wstring& tool, const std::wstring& key, bool def);
	void setToolFlag(const std::wstring& tool, const std::wstring& key, bool val);
	float getToolNum(const std::wstring& tool, const std::wstring& key, float def);
	void setToolNum(const std::wstring& tool, const std::wstring& key, float val);
	// 上次检查更新是哪一天（std::chrono::days 的计数，即 1970-01-01 以来的天数），
	// 从来没查过返回 0。一天最多查一次服务端，靠它记账 —— 每次空闲都去请求纯属浪费人家的流量
	long long getUpdateCheckDay();
	void setUpdateCheckDay(long long day);
private:
	Setting();
	// toolPin.<tool> 那个 JsonObject。缺哪一层就现建一层挂上去 ——
	// SetNamedValue 得有个落脚的对象，而这两层在旧配置文件里都不存在
	JsonObject getToolObj(const std::wstring& tool);
	std::filesystem::path initDataPath();
	// 决定配置文件用哪一份：exe 同目录有 config.json 就用它（绿色版，配置跟着程序走），
	// 否则用 %appdata%\ScreenCapture\config.json。二者只认一个，读哪儿就写哪儿。
	std::filesystem::path initConfigPath();
	// 把老配置里的快捷键补齐 / 换到新默认值。只做一次，靠 common.shortcutSchema 记账
	void migrateShortcutKeys();
	void save();
private:
	const std::filesystem::path dataPath;
	// 必须声明在 dataPath 之后：initConfigPath 找不到 exe 同目录的配置时要回落到 dataPath 上，
	// 成员按声明顺序初始化
	const std::filesystem::path configPath;
	JsonObject configObj;
};

