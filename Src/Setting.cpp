#include "pch.h"
#include <algorithm>   // std::transform（把组合串转小写再交给 strToKey）
#include <include/Ling.h>
#include "Setting.h"
#include "Util.h"
#include "Lang.h"
#include "Win/WinCap.h"
#include "Win/WinPin.h"
#include "App.h"

namespace {
    std::unique_ptr<Setting> setting;
    // 每个可配置的全局热键占一个 RegisterHotKey 的 id。
    // 默认只给"截图"和"贴图"配热键：一个刚装上的程序不该一口气抢走用户六个按键，
    // 剩下的四项默认留空（不注册）—— 功能照旧能从工具条进，想用键盘的人去设置页自己设
    const std::vector<Setting::ShortcutDef> shortcutTable{
        { L"cap",    100, L"F1", L"Ctrl+Alt+A" }, // 截图。老版本的默认是 Ctrl+Alt+A
        { L"pin",    101, L"F3", L"" },           // 贴图：把剪贴板里的图贴到屏幕上
        { L"long",   102, L"",   L"" },           // 截长图
        { L"video",  103, L"",   L"" },           // 录屏
        { L"qrcode", 105, L"",   L"" },           // 二维码识别

        // —— 下面两项只在截图窗口里生效，不是全局热键（msgId=0，windowOnly=true）——
        // 翻看截图历史。默认 , 和 . —— 屏幕上不会有人想用它们当热键（尤其不能做成全局的：
        // 那会把整台机器的逗号句号都抢走），但在截图窗口里是手边最顺的一对
        { L"prevShot", 0, L",", L"", true },      // 上一条截图
        { L"nextShot", 0, L".", L"", true },      // 下一条截图（回到更新的）
    };
    // 文字识别（原 msgId 104）已移除：工具条上不再有那个按钮，设置页也不再列它。
    // WinCap::startOcr 本身还在（贴图窗口 F3 之后仍会自动识别），只是没有独立入口了

    // 快捷键配置的版本号，记在 common.shortcutSchema 下。这次同时做了两件事：把截图的默认
    // 从 Ctrl+Alt+A 换成 F1、又把"贴图"加了进来。光靠"配置里没有这一项就补默认值"补不回
    // 截图那一项（它在老配置里本来就有），所以用一个版本号记账，让迁移只跑一次
    constexpr double shortcutSchemaVer{ 1 };
    // 配置文件的默认内容。空文件、坏 JSON、缺键都拿它兜底，所以这里列出的每一项
    // 都是代码里会直接按名字取的（见 getLang / getAutoStart / initShortcutKeys）
    constexpr std::wstring_view defaultConfig{ LR"""({"common":{"autoStart":false,"language":"zh-CN","shortcutSchema":1},"shortcutKey":{"cap":"F1","pin":"F3"}})""" };
}


Setting::Setting() :dataPath{ initDataPath() }, configPath{ initConfigPath() }
{
    if (std::filesystem::exists(configPath)) {
        auto content = Ling::Util::readFileText(configPath);
        if (content.empty() || content.find_first_not_of(L" \t\r\n") == std::wstring::npos) {
            configObj = JsonObject::Parse(defaultConfig);
            save();
            return;
        }
        JsonObject obj{ nullptr };
        if (JsonObject::TryParse(content, obj)) {
            configObj = obj;
            // 老配置里没有"贴图"，截图的默认值也是老的那一个 —— 在这里补/换一次。
            // 空文件那条路不用管：上面那份 defaultConfig 本来就是新的
            migrateShortcutKeys();
            return;
        }
        MessageBox(nullptr, L"config.json parse error，use default config", L"ScreenCapture", MB_OK | MB_ICONWARNING);
    }
    configObj = JsonObject::Parse(defaultConfig); 
}



Setting::~Setting()
{

}

void Setting::init()
{
    auto ptr = new Setting();
    setting.reset(ptr);
}

void Setting::dispose()
{
    setting.reset();
}

Setting* Setting::get()
{
    return setting.get();
}

std::filesystem::path Setting::getDataPath()
{
    return dataPath; //复制一份路径对象，不允许就地修改
}

const JsonObject Setting::getConfigObj()
{
    return configObj;
}

const std::vector<Setting::ShortcutDef>& Setting::shortcutDefs()
{
    return shortcutTable;
}

int Setting::shortcutMsgId(const std::wstring& type)
{
    for (const auto& def : shortcutTable) {
        if (type == def.type) return def.msgId;
    }
    return 0;
}

void Setting::setShortcutKey(const std::wstring& type, const std::vector<std::wstring>& keys)
{
    // keys 进来之前已经按 Ctrl > Alt > Shift > Win > 普通键 排过序（见 WinSettingShortcut），
    // 拼起来就是 "Ctrl+Alt+A" 这种规范写法。LWin / RWin 统一记成 Win，好跟黑名单对上。
    // keys 为空 = 清除这一项：拼出来就是空串
    std::wstring str;
    for (const auto& key : keys)
    {
        if (!str.empty()) str += L"+";
        str += (key == L"LWin" || key == L"RWin") ? L"Win" : key;
    }
    // 用带默认值的重载：老配置里可能整块 shortcutKey 都不在
    auto shortcutKey = configObj.GetNamedObject(L"shortcutKey", nullptr);
    if (!shortcutKey) {
        shortcutKey = JsonObject();
        configObj.SetNamedValue(L"shortcutKey", shortcutKey);
    }
    // 空串也是"显式写过"。effectiveShortcutKey 靠 GetNamedValue 把"用户清成了空"和
    // "从没配过"分开，否则清掉之后又被表里的默认值顶回来，用户会觉得清不掉
    shortcutKey.SetNamedValue(type, JsonValue::CreateStringValue(str));

    // 先注销旧的再注册新的。注册同一个 id 的新组合本来就会把旧的顶掉，这一步是为了
    // "清除"那条路 —— 空串不能拿去注册。注册成不成功这里不看：只有热键真被按下才知道，
    // 组合被别的程序占着的时候 regHotKey 会失败，让用户自己去设置页试
      auto msgId = shortcutMsgId(type);
      if (msgId) {
          auto app = Ling::App::get();
          app->unRegHotKey(msgId);
          // "关闭所有快捷键"开着的时候不注册回去：托盘里关了热键打游戏，
          // 不能因为用户顺手在设置页改了下键就又抢回系统全局键。
          // 关闭禁用时 setDisableHotkeys 会按表把所有热键统一注册回来
          if (!str.empty() && !getDisableHotkeys()) app->regHotKey(str, msgId);
      }
      save();
}

std::wstring Setting::getShortcutKey(const std::wstring& type)
{
    // 一路用带默认值的重载：启动时 ensureDefaults 已经补齐过，这里只是别让运行期
    // 意外（配置被外部改动、问了个没配过的 type）变成一次崩溃
    auto obj = configObj.GetNamedObject(L"shortcutKey", nullptr);
    if (!obj) return L"";
    return std::wstring{ obj.GetNamedString(type, L"") };
}

std::wstring Setting::effectiveShortcutKey(const std::wstring& type)
{
    auto obj = configObj.GetNamedObject(L"shortcutKey", nullptr);
    // GetNamedValue 能把"这一项不存在"和"这一项是空串"分开：前者拿到 nullptr，
    // 后者拿到一个空字符串值。用户清掉某个热键之后重开设置页，那一行还得显示"未设置"
    // 而不是被默认值顶回来，靠的就是这个区别（GetNamedString 两种情况都返回空）
    if (obj && obj.GetNamedValue(type, nullptr)) {
        return getShortcutKey(type);
    }
    // 配置里压根没有这一项：老配置，或者程序从没写过它。用表里的默认值
    for (const auto& def : shortcutTable) {
        if (type == def.type) return std::wstring{ def.def };
    }
    return L"";
}

UINT Setting::keyNameToVk(const std::wstring& name)
{
    if (name.empty()) return 0;
    // 单字符（, . A 1 之类）：按主键盘上那个键算。见头文件里为什么不能用 strToKey
    if (name.size() == 1) {
        SHORT vk = VkKeyScanW(name[0]);
        // -1 = 这个字符在当前键盘布局里打不出来；高位是 Shift/Ctrl/Alt 状态，只要低 8 位
        if (vk != -1) return static_cast<UINT>(vk & 0xFF);
        return 0;
    }
    // 多字符是 "F1" / "Enter" / "PageUp" 这类名字，strToKey 认的是小写形式
    std::wstring lower = name;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::towlower);
    return Ling::Util::strToKey(lower);
}

UINT Setting::effectiveShortcutVk(const std::wstring& type)
{
    // 空串 = 用户把这一项清掉了（或者表里的默认值就是空），这种不绑键。
    // 注意不能拿 keyNameToVk 的返回值当"有没有配"的判据：两者返回 0 的含义分得开
    auto str = effectiveShortcutKey(type);
    if (str.empty()) return 0;
    return keyNameToVk(str);
}

// 老配置升级：补上新增的"贴图"，并把截图的默认值从 Ctrl+Alt+A 换成 F1。
// 只跑一次 —— common.shortcutSchema 记着版本号，有它就说明已经处理过了，
// 之后用户在设置页里的任何选择都不会再被这里碰到
void Setting::migrateShortcutKeys()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        configObj.SetNamedValue(L"common", common);
    }
    if (common.GetNamedNumber(L"shortcutSchema", 0) >= shortcutSchemaVer) return;

    auto obj = configObj.GetNamedObject(L"shortcutKey", nullptr);
    if (!obj) {
        obj = JsonObject();
        configObj.SetNamedValue(L"shortcutKey", obj);
    }
    for (const auto& def : shortcutTable) {
        // 窗口内的按键不写进配置：effectiveShortcutKey 本来就会回落到表里的默认值，
        // 写进去只是让配置文件变脏，还会让"以后想改这个默认值"改不动
        if (def.windowOnly) continue;
        // GetNamedValue 拿到 nullptr 才说明配置里没有这一项（空串是有值的，See effectiveShortcutKey）
        if (!obj.GetNamedValue(def.type, nullptr)) {
            // 老配置里根本没有这一项（比如新增的贴图）：补上默认值。
            // 默认是空串的就不写 —— 配置文件干净些，以后想改这项的默认值也改得动
            if (*def.def) {
                obj.SetNamedValue(def.type, JsonValue::CreateStringValue(def.def));
            }
            continue;
        }
        // 这一项在、值又正好是老版本的默认值：说明用户从没改过它，换掉。
        // 用户自己改成过别的组合的，保持不动
        if (*def.legacy && std::wstring{ obj.GetNamedString(def.type, L"") } == def.legacy) {
            obj.SetNamedValue(def.type, JsonValue::CreateStringValue(def.def));
        }
    }
    common.SetNamedValue(L"shortcutSchema", JsonValue::CreateNumberValue(shortcutSchemaVer));
    save();
}

void Setting::setAutoStart(bool autoStart)
{
    std::wstring runKey = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
    if (autoStart) {
        wchar_t buffer[MAX_PATH];
        GetModuleFileName(nullptr, buffer, MAX_PATH);
        auto curPath = std::filesystem::path(buffer);
        std::wstring commandLine = std::format(L"\"{}\" --auto-start", curPath.wstring());
        HKEY hKey;
        if (RegOpenKeyEx(HKEY_CURRENT_USER, runKey.data(), 0, KEY_WRITE, &hKey) == ERROR_SUCCESS) {
            RegSetValueEx(hKey, L"ScreenCapture", 0, REG_SZ, (const BYTE*)commandLine.data(), (commandLine.size() + 1) * sizeof(wchar_t));
            RegCloseKey(hKey);
        }
    }
    else {
        HKEY hKey;
        if (RegOpenKeyEx(HKEY_CURRENT_USER, runKey.data(), 0, KEY_WRITE, &hKey) == ERROR_SUCCESS) {
            RegDeleteValue(hKey, L"ScreenCapture");
            RegCloseKey(hKey);
        }
    }
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        configObj.SetNamedValue(L"common", common);
    }
    common.SetNamedValue(L"autoStart", JsonValue::CreateBooleanValue(autoStart));
    save();
}

bool Setting::getAutoStart()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    return common && common.GetNamedBoolean(L"autoStart", false);
}

bool Setting::getDisableHotkeys()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    return common && common.GetNamedBoolean(L"disableHotkeys", false);
}

void Setting::setDisableHotkeys(bool disable)
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        configObj.SetNamedValue(L"common", common);
    }
    common.SetNamedValue(L"disableHotkeys", JsonValue::CreateBooleanValue(disable));
    save();
    // 立即生效：禁用 = 注销所有全局热键；恢复 = 按表重新注册一遍。
    // 窗口内按键（翻截图历史的 , / .）不在这里管 —— 它们本来就不是全局热键，
    // 只在截图窗口里生效，打游戏时窗口不开着就碰不到
    auto app = Ling::App::get();
    for (const auto& def : shortcutTable) {
        if (def.windowOnly) continue;
        auto str = effectiveShortcutKey(def.type);
        if (str.empty()) continue;
        if (disable) {
            app->unRegHotKey(def.msgId);
        }
        else {
            // 注册不上（组合被别的程序占着）与 initShortcutKeys 同一态度：不拦着，
            // 用户去设置页换个组合就是了
            app->regHotKey(str, def.msgId);
        }
    }
}

std::filesystem::path Setting::getTempPath()
{
    // 数据目录下的 temp：截图缓存 last.bin、录屏临时文件、截图历史都放这儿
    auto path = dataPath; //复制一份，append 会就地改
    return path.append(L"temp");
}

std::filesystem::path Setting::getSaveDir()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (common) {
        auto dir = std::wstring{ common.GetNamedString(L"saveDir", L"") };
        // 设过的目录可能后来被删了/挪走了，那种情况也回落到默认，别让保存直接失败
        if (!dir.empty() && std::filesystem::exists(dir)) return dir;
    }
    PWSTR tmp{ nullptr };
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_Downloads, 0, nullptr, &tmp)) && tmp) {
        auto path = std::filesystem::path{ tmp };
        CoTaskMemFree(tmp);
        return path;
    }
    return dataPath; //兜底：连"下载"都问不到就用数据目录
}

void Setting::setSaveDir(const std::filesystem::path& dir)
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        configObj.SetNamedValue(L"common", common);
    }
    // 传空 = 恢复"用系统的下载文件夹"
    common.SetNamedValue(L"saveDir", JsonValue::CreateStringValue(dir.wstring()));
    save();
}

bool Setting::getQuickSave()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) return false;
    return common.GetNamedBoolean(L"quickSave", false);
}

void Setting::setQuickSave(bool on)
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        configObj.SetNamedValue(L"common", common);
    }
    common.SetNamedValue(L"quickSave", JsonValue::CreateBooleanValue(on));
    save();
}

int Setting::getHistoryDays()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) return 3;
    auto days = static_cast<int>(common.GetNamedNumber(L"historyDays", 3.0));
    return std::clamp(days, 0, 365);
}

void Setting::setHistoryDays(int days)
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        configObj.SetNamedValue(L"common", common);
    }
    common.SetNamedValue(L"historyDays", JsonValue::CreateNumberValue(std::clamp(days, 0, 365)));
    save();
}

std::filesystem::path Setting::initDataPath()
{
    // 数据目录就是 exe 同目录（绿色版：配置和临时文件都跟着程序走）。
    // 只在旁边建一个 temp 子目录（last.bin / 录屏临时文件 / 截图历史都在里面），
    // exe 目录本身除了 config.json 不再多任何东西。
    // 不再创建 %appdata%\ScreenCapture —— 用户要的就是"别在别处留东西"。
    // 装在 Program Files 下时这里可能没写权限，那 create 会失败，但也不回退到 appdata
    wchar_t buffer[MAX_PATH]{};
    GetModuleFileName(nullptr, buffer, MAX_PATH);
    auto dir = std::filesystem::path{ buffer }.parent_path();
    auto tempDir = dir / L"temp";
    if (!std::filesystem::exists(tempDir)) {
        std::error_code ec;
        std::filesystem::create_directories(tempDir, ec);
    }
    return dir;
}

std::filesystem::path Setting::initConfigPath()
{
    // 配置就在 exe 同目录。
    // 老版本把它放在 %appdata%\ScreenCapture\config.json 下：升级上来时**搬一次**过来，
    // 否则用户的热键、画笔粗细、边框粗细会整套回到默认值。
    // 用 copy 而不是 move —— 老文件留在原地不动，删不删由用户自己决定
    wchar_t buffer[MAX_PATH]{};
    GetModuleFileName(nullptr, buffer, MAX_PATH);
    auto path = std::filesystem::path{ buffer }.parent_path().append(L"config.json");
    if (std::filesystem::exists(path)) return path;
    PWSTR oldTmp{ nullptr };
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_RoamingAppData, 0, nullptr, &oldTmp)) && oldTmp) {
        auto legacy = std::filesystem::path{ oldTmp }
            .append(L"ScreenCapture").append(L"config.json");
        CoTaskMemFree(oldTmp);
        std::error_code ec;
        if (std::filesystem::exists(legacy, ec)) {
            std::filesystem::copy_file(legacy, path, std::filesystem::copy_options::skip_existing, ec);
        }
    }
    return path;
}

void Setting::save()
{
    std::wstring str{ configObj.Stringify() };
    Ling::Util::saveFile(configPath.wstring(), str);
}

std::wstring Setting::getLang()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) return L"zh-CN";
    return std::wstring{ common.GetNamedString(L"language", L"zh-CN") };
}

void Setting::setLang(const std::wstring& langCode)
{
    auto common = setting->configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        setting->configObj.SetNamedValue(L"common", common);
    }
    common.SetNamedValue(L"language", JsonValue::CreateStringValue(langCode));
    setting->save();
	Lang::get()->initLang(langCode);
}

float Setting::getBorderWidth()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    // 默认 2：与以前写死的 2 * dpi 一致，老配置升上来观感不变
    if (!common) return 2.f;
    return static_cast<float>(common.GetNamedNumber(L"borderWidth", 2.0));
}

void Setting::setBorderWidth(float w)
{
    auto common = setting->configObj.GetNamedObject(L"common", nullptr);
    if (!common) {
        common = JsonObject();
        setting->configObj.SetNamedValue(L"common", common);
    }
    common.SetNamedValue(L"borderWidth", JsonValue::CreateNumberValue(w));
    setting->save();
}

JsonObject Setting::getToolObj(const std::wstring& tool){
    // 用带默认值的重载：这两层在旧配置文件里都不存在，直接 GetNamedObject 会抛异常，
    // 值被手工改成非对象时它也一样返回默认值，不会炸
    auto root = configObj.GetNamedObject(L"toolPin", nullptr);
    if (!root) {
        root = JsonObject();
        configObj.SetNamedValue(L"toolPin", root);
    }
    auto obj = root.GetNamedObject(tool, nullptr);
    if (!obj) {
        obj = JsonObject();
        root.SetNamedValue(tool, obj);
    }
    return obj;
}

bool Setting::getToolFlag(const std::wstring& tool, const std::wstring& key, bool def)
{
    return getToolObj(tool).GetNamedBoolean(key, def);
}

void Setting::setToolFlag(const std::wstring& tool, const std::wstring& key, bool val)
{
    getToolObj(tool).SetNamedValue(key, JsonValue::CreateBooleanValue(val));
    save();
}

float Setting::getToolNum(const std::wstring& tool, const std::wstring& key, float def)
{
    return static_cast<float>(getToolObj(tool).GetNamedNumber(key, def));
}

void Setting::setToolNum(const std::wstring& tool, const std::wstring& key, float val)
{
    getToolObj(tool).SetNamedValue(key, JsonValue::CreateNumberValue(val));
    save();
}

long long Setting::getUpdateCheckDay()
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) return 0;
    return static_cast<long long>(common.GetNamedNumber(L"updateCheckDay", 0));
}

void Setting::setUpdateCheckDay(long long day)
{
    auto common = configObj.GetNamedObject(L"common", nullptr);
    if (!common) return;
    // 这项不写进 defaultConfig：它是程序自己的记账，不是给用户改的配置
    common.SetNamedValue(L"updateCheckDay", JsonValue::CreateNumberValue(static_cast<double>(day)));
    save();
}

void Setting::suspendShortcuts()
{
    // 只注销、不写配置：这是给捕获让位，不是用户改了设置
    auto app = Ling::App::get();
    for (const auto& def : shortcutTable) {
        if (def.windowOnly) continue; // 不是全局热键，没什么可注销的
        app->unRegHotKey(def.msgId);
    }
}

void Setting::resumeShortcuts()
{
    auto app = Ling::App::get();
    for (const auto& def : shortcutTable) {
        if (def.windowOnly) continue; // 同上：窗口内的按键不参与注册
        // 先撤再加：RegisterHotKey 对同一个 id 重复注册会失败，先撤掉这里才是可重入的，
        // 也才能把捕获期间被 setShortcutKey 换掉的组合重新挂成最新那个
        app->unRegHotKey(def.msgId);
        auto str = effectiveShortcutKey(def.type);
        if (!str.empty()) app->regHotKey(str, def.msgId);
    }
}

void Setting::initShortcutKeys()
{
    auto lingApp = Ling::App::get();
    // "关闭所有快捷键"开着（上次退出前勾了游戏模式）就一个都不注册。
    // onHotKey 回调照样挂：热键没注册就不会有 WM_HOTKEY 进来，挂回调无副作用
    const bool disabled = getDisableHotkeys();
    // 逐项注册。空串 = 这一项没有热键（默认就没给，或者用户自己清掉了），跳过就行 ——
    // 功能本身还在，只是不能从键盘直接唤起来
    for (const auto& def : shortcutTable) {
        if (def.windowOnly) continue; // 截图窗口内的按键，不走系统热键
        auto str = effectiveShortcutKey(def.type);
        if (str.empty()) continue;
        if (disabled) continue;
        // 注册不上（组合被别的程序占着）也不管：顶多是这个热键不好用，
        // 不该让程序起不来，用户在设置页里换一个就是了
        lingApp->regHotKey(str, def.msgId);
    }

    // 一个回调管全部：Ling 把 WM_HOTKEY 的 id 原样递过来，按 id 分派。
    // 除截图外的五项都走"先把截图窗口开起来、框完直接进对应功能"这条既有路子
    lingApp->onHotKey.add([this](UINT msg) {
        if (msg == shortcutMsgId(L"cap")) {
            WinCap::init();
        }
        else if (msg == shortcutMsgId(L"pin")) {
            // 贴图：截图窗口正开着就把它立刻收尾（截图 → 剪贴板 → 贴图），
            // 否则把最近一次截图贴出来。图来自临时文件而不是剪贴板，
            // 所以复制过文字之后照样能贴
            WinPin::doPin();
        }
        else if (msg == shortcutMsgId(L"long")) {
            WinCap::init(L"long");
        }
        else if (msg == shortcutMsgId(L"video")) {
            WinCap::init(L"video");
        }
        else if (msg == shortcutMsgId(L"qrcode")) {
            WinCap::init(L"qr"); // WinCap::enterByArg 认的是 "qr"
        }
    });
    lingApp->onSecondInstance.add([this]() {
        WinCap::init();
    });
}
