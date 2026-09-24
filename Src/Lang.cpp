#include "pch.h"
#include <filesystem>
#include "Lang.h"
#include "Util.h"
#include "Setting.h"

std::unique_ptr<Lang> lang;

namespace {
	// 语言文件从 exe 同目录的 Lang 子目录加载（绿色部署 / 调试方便）；
	// 那个目录不存在就用数据目录（现在也是 exe 同目录）下的 Lang，同样不存在就当没有额外语言。
	// 注意：内置的 zh-CN / en-US 是内嵌在 exe 里的，这里的目录只用来追加 / 覆盖
	// directory_iterator 碰到不存在的目录会抛 filesystem_error，
	// 所以用带 error_code 的重载，目录不在就当没有额外语言。
	std::vector<std::filesystem::path> getLangFiles()
	{
		std::vector<std::filesystem::path> result;
		wchar_t buffer[MAX_PATH]{};
		GetModuleFileName(nullptr, buffer, MAX_PATH);
		auto langPath = std::filesystem::path{ buffer }.parent_path().append(L"Lang");
		if (!std::filesystem::is_directory(langPath)) {
			langPath = Setting::get()->getDataPath().append(L"Lang");
		}
		std::error_code ec;
		std::filesystem::directory_iterator it{ langPath, ec }, end{};
		for (; !ec && it != end; it.increment(ec)) {
			result.push_back(it->path());
		}
		return result;
	}
}

Lang::Lang()
{
}

Lang::~Lang()
{
}

void Lang::init()
{
	auto ptr = new Lang();
	lang.reset(ptr);
	lang->initLang(Setting::get()->getLang());
}

void Lang::dispose()
{
	lang.reset();
}

Lang* Lang::get()
{
	return lang.get();
}

std::wstring Lang::get(const std::wstring& keyPath)
{
	// 一路用带默认值的重载：第三方语言文件缺键是常态（程序加了新文案，人家的文件还是老的），
	// 而带默认值的 GetNamedObject/GetNamedString 不抛异常。缺了先找内置的 en-US，
	// 连那儿也没有就把键名本身显示出来 —— 界面上难看，但比崩掉好，也一眼能看出缺哪个键
	auto arr = Ling::Util::splitStr(keyPath, L'.');
	if (arr.size() < 2) return keyPath;
	auto& self = *lang;
	auto obj = self.langObj.GetNamedObject(arr[0], nullptr);
	if (obj) {
		auto text = obj.GetNamedString(arr[1], L"");
		if (!text.empty()) return std::wstring{ text };
	}
	if (!self.fallbackObj) return keyPath;
	auto def = self.fallbackObj.GetNamedObject(arr[0], nullptr);
	if (!def) return keyPath;
	auto text = def.GetNamedString(arr[1], L"");
	if (text.empty()) return keyPath;
	return std::wstring{ text };
}

void Lang::initLang(const std::wstring& langCode)
{
	auto [pData, size] = Ling::Util::getRes(langCode);
	std::wstring builtinJson;
	if (pData && size > 0)
		builtinJson = Ling::Util::readTextFromBytes(pData, size);
	JsonObject builtinObj{ nullptr };
	if (!builtinJson.empty())
		builtinObj = JsonObject::Parse(builtinJson);

	if (langCode == L"zh-CN" || langCode == L"en-US") {
		langObj = builtinObj;
		return;
	}
	// 第三方语言文件：用户自己放进来的，可能是老版本的（缺新加的键）、也可能手工改坏了。
	// 所以一是用 TryParse（Parse 解析失败直接抛，一路抛出去就是进程没了），
	// 二是把内置的 en-US 留在 fallbackObj 里给 Lang::get 兜底
	fallbackObj = builtinObj;
	bool loaded{ false };
	for (const auto& entry : getLangFiles()) {
		std::wstring filename = entry.filename().wstring();
		if (filename.find(langCode) == std::wstring::npos) continue;
		auto pathStr = entry.wstring();
		std::wstring content = Ling::Util::readFileText(entry);
		JsonObject obj{ nullptr };
		if (JsonObject::TryParse(content, obj)) {
			langObj = obj;
			loaded = true;
		}
		else {
			auto msg = L"lang pare error：" + pathStr + L"\n use English";
			MessageBox(nullptr, msg.data(), L"ZPin", MB_OK | MB_ICONWARNING);
		}
		break;
	}
	//文件没找到、或者内容不是合法 JSON：整份都用内置的 en-US
	if (!loaded) langObj = fallbackObj;
}

std::vector<std::pair<std::wstring, std::wstring>> Lang::getSupportedLang()
{
	// 内置这两门（内嵌在 exe 里，不依赖 Lang 目录），其余的从 Lang 目录里扫出来
	std::vector<std::pair<std::wstring, std::wstring>> result = { {L"简体中文",L"zh-CN"},{L"English",L"en-US"} };
	for (const auto& entry : getLangFiles()) {
		std::wstring filename = entry.filename().wstring();
		auto arr = Ling::Util::splitStr(filename, L'.');
		if (arr.size() == 3 && arr[2] == L"json") {
			// 代码已经在内置列表里了就跳过 —— 否则用户把仓库里的 Lang 目录整个拷到 exe 旁边，
			// 语言菜单里会出现两条"简体中文"、两条"English"
			bool dup{ false };
			for (const auto& item : result) {
				if (item.second == arr[1]) { dup = true; break; }
			}
			if (dup) continue;
			result.push_back({ arr[0] ,arr[1] });
		}
	}
	return result;
}
