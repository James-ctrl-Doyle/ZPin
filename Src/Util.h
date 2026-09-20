#pragma once
#include <include/Ling.h>
#include <filesystem>
#include <fstream>
#include <array>

// 图像输出相关的工具函数。data 一律要求 BGRA、top-down、行紧凑（步长 = w*4），
// 这也是 WinPin::getImagePixels 交出来的格式。
class Util
{
public:
	// 同时写入 CF_DIBV5（Office / 微信 / WPS 这类原生程序认）和 "PNG" 注册格式
	//（浏览器 / Electron 程序认），两份都带 alpha
	// ———— 截图历史 ————
	// 每次截图在数据目录 temp\shots 下留一份"整屏画面 + 当时的截图框"，
	// 以时间戳命名，截图模式里按 ← 可以翻出来重看/重裁。默认只留 3 天
	struct ShotInfo
	{
		std::wstring path;
		std::wstring name;   // 文件名（时间戳），排序与判过期都用它
	};
	static std::filesystem::path shotDir();
	// 生成一个还没被占用的历史文件路径（时间戳命名）。写盘要一两百毫秒，
	// 所以"落盘"和"起个名字"分成两步：名字当场取，落盘丢后台线程
	static std::wstring makeShotPath();
	// 真正把整屏图（PNG）和框写进文件。pixels 按值收（后台线程自己拿着），
	// 先写 .tmp 再改名，避免中途被杀留下半个文件让下次读到坏数据
	static bool writeShot(const std::wstring& path, const int screenX, const int screenY,
		const int screenW, const int screenH, std::vector<BYTE> pixels, const RECT& mask);
	// 同步写一条历史（makeShotPath + writeShot）。返回写出的路径，失败返回空串
	static std::wstring saveShot(const int screenX, const int screenY, const int screenW,
		const int screenH, BYTE* screenData, const RECT& mask);
	// 只改头里的截图框（不重新编码 PNG）。翻看历史时"改完框再翻走"用它记回去
	static bool patchShotRect(const std::wstring& path, const RECT& mask);
	// 读回一条历史：整屏像素（BGRA、top-down、行紧凑）+ 尺寸 + 屏幕原点 + 截图框
	static bool loadShot(const std::wstring& path, std::vector<BYTE>& pixels, int& w, int& h,
		int& screenX, int& screenY, RECT& mask);
	// 列出全部历史，最新的排前面
	static std::vector<ShotInfo> listShots();
	// 清掉超过 days 天的历史；days <= 0 表示不保留历史，全清
	static void pruneShots(int days);
	static void saveToClipboard(const int w, const int h, BYTE* data);
	static bool saveToFile(const std::wstring& path, const int w, const int h, BYTE* data);
	// 弹系统另存为对话框，返回空串表示用户取消。
	// dir 非空时强制以它作为初始目录（"默认保存位置"设置）；不传就看系统记住的上次目录
	static std::wstring getSaveFilePath(HWND hwnd, const std::wstring& ext = L"png",
		const std::filesystem::path& dir = std::filesystem::path{});
	// 保存位置 / 快速保存的统一出口，截图、长图、录屏三条保存路径都走它：
	// 勾了"快速保存"就直接返回默认目录下的时间戳文件名（不弹框），
	// 否则弹另存为。返回空串 = 用户取消了，或没地方可写
	static std::wstring resolveSavePath(const std::wstring& ext, HWND owner = nullptr);
	// 弹"选择文件夹"对话框（设置里的"默认保存位置"用），返回空串 = 用户取消
	static std::wstring pickFolder(HWND owner, const std::filesystem::path& initial);
	// 以当前时间生成默认文件名，精确到毫秒，避免连续保存时重名
	static std::wstring createFileName(const std::wstring& ext);
	// GDI 抓屏。返回 BGRA、top-down、行紧凑（步长 = w*4），与本类其他函数的入参格式一致
	static std::vector<BYTE> captureScreen(const int x, const int y, const int w, const int h);
	// 把文件路径以 CF_HDROP 写进剪切板，粘贴到资源管理器/聊天窗口就是一个文件
	static void addFileToClipboard(const std::wstring& filePath);
	// 从剪贴板取一张图，转成 BGRA、top-down、行紧凑（步长 = w*4）—— 与 saveToClipboard
	// 的入参格式一致，可以直接喂给 WinPin::initFromData 贴到屏幕上。
	// 优先取注册格式 "PNG"（本程序、浏览器、Electron 放进去的那一份，带完整 alpha），
	// 没有再退到 CF_DIBV5 / CF_DIB（其它 Windows 程序放的那一份）。
	// 剪贴板里没有图片时返回 false，w / h 保持 0
	static bool getClipboardImage(std::vector<BYTE>& pixels, int& w, int& h);
	// ———— "最近一次截图"的临时文件 ————
	// 贴图（F3）不从剪贴板取图，而是取这个文件 —— 这样复制过文字、剪贴板被占之后照样能贴图。
	// 只留一份、每次截图收工时覆盖它，所以不需要任何清理逻辑。
	// 存的是裸 BGRA + 自描述头而不是 PNG：这条路径每次截图都要跑一遍，PNG 编码要多花几十毫秒，
	// 而这张图只在本机一写一读。头里还存了当初那块选区在屏幕上的位置，贴图据此回到原位。
	// 数据来自 getCutPixels，格式与 saveToClipboard 一致（BGRA、top-down、行紧凑）
	static bool saveLastCapture(const int w, const int h, const int x, const int y, BYTE* data);
	// 读回最近一次截图。没有（还没截过图）或文件坏掉时返回 false，出参保持不动
	static bool loadLastCapture(std::vector<BYTE>& pixels, int& w, int& h, int& x, int& y);
	// 用 quirc 识别图里的二维码，返回识别到的内容，没识别到返回空串。
	// 图里有多个码时用换行拼在一起
	static std::wstring decodeQrCode(const int w, const int h, BYTE* data);
};
