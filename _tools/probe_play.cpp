// 录屏产出的 MP4 到底能不能播 —— 用 Media Foundation 亲手解几帧出来。
// 除了"解码是否成功"，还把帧原样写成裸 BGRA，交给 Python 转 PNG 看一眼内容。
//
// 编译：_tools/build_probe_play.sh
// 用法：probe_play.exe <mp4路径> <输出前缀> [要取的时间点秒数...]
//       例：probe_play.exe C:\...\temp.mp4 C:\...\logs\frame 0.5 2.5 4.5
#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mferror.h>
#include <wrl/client.h>
#include <cstdio>
#include <vector>
#include <string>

using namespace Microsoft::WRL;

static void dumpDecoderMfts()
{
    // 系统里到底有没有 HEVC 解码器：有编码器不代表播放器能解
    MFT_REGISTER_TYPE_INFO inHevc{ MFMediaType_Video, MFVideoFormat_HEVC };
    MFT_REGISTER_TYPE_INFO inH264{ MFMediaType_Video, MFVideoFormat_H264 };
    struct { const char* name; MFT_REGISTER_TYPE_INFO* info; } kinds[] = {
        { "HEVC", &inHevc }, { "H264", &inH264 },
    };
    for (auto& k : kinds) {
        IMFActivate** acts = nullptr;
        UINT32 n = 0;
        HRESULT hr = MFTEnumEx(MFT_CATEGORY_VIDEO_DECODER,
                               MFT_ENUM_FLAG_ALL, k.info, nullptr, &acts, &n);
        printf("  解码器 %-5s : hr=0x%08X 个数=%u", k.name, (unsigned)hr, n);
        for (UINT32 i = 0; i < n; ++i) {
            LPWSTR nm = nullptr;
            if (SUCCEEDED(acts[i]->GetAllocatedString(MFT_FRIENDLY_NAME_Attribute, &nm, nullptr))) {
                printf(" [%ls]", nm);
                CoTaskMemFree(nm);
            }
            acts[i]->Release();
        }
        printf("\n");
        if (acts) CoTaskMemFree(acts);
    }
}

int wmain(int argc, wchar_t** argv)
{
    if (argc < 3) {
        printf("用法: probe_play.exe <mp4> <输出前缀> [秒...]\n");
        return 2;
    }
    if (FAILED(MFStartup(MF_VERSION))) { printf("MFStartup 失败\n"); return 2; }
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) { printf("CoInitializeEx 失败\n"); return 2; }

    printf("系统上的视频解码器：\n");
    dumpDecoderMfts();

    // 让 SourceReader 允许插入视频处理（色彩转换）MFT，否则只能拿到解码器的原生格式
    ComPtr<IMFAttributes> rattrs;
    MFCreateAttributes(&rattrs, 1);
    // 只开这一个：再加 ADVANCED 那个属性，MFCreateSourceReaderFromURL 会直接 E_INVALIDARG
    rattrs->SetUINT32(MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, TRUE);

    ComPtr<IMFSourceReader> reader;
    HRESULT hr = MFCreateSourceReaderFromURL(argv[1], rattrs.Get(), &reader);
    printf("\n打开文件 %ls : hr=0x%08X\n", argv[1], (unsigned)hr);
    if (FAILED(hr)) return 1;

    ComPtr<IMFMediaType> out;
    MFCreateMediaType(&out);
    out->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
    // 要 RGB32：中间必须过一个解码器 + 色彩转换，解码器缺了这一步就会失败
    out->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_RGB32);
    hr = reader->SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, out.Get());
    printf("要求输出 RGB32 : hr=0x%08X%s\n", (unsigned)hr, FAILED(hr) ? "   <<< 解码不了" : "");

    ComPtr<IMFMediaType> cur;
    if (SUCCEEDED(reader->GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, &cur))) {
        UINT32 w = 0, h = 0;
        MFGetAttributeSize(cur.Get(), MF_MT_FRAME_SIZE, &w, &h);
        GUID sub{};
        cur->GetGUID(MF_MT_SUBTYPE, &sub);
        printf("当前输出类型: %ux%u subtype=%08X%c%c%c%c\n", w, h, (unsigned)sub.Data1,
               (char)(sub.Data2 >> 8), (char)(sub.Data2), (char)(sub.Data3 >> 8), (char)sub.Data3);
    }

    struct Want { double t; std::wstring path; };
    std::vector<Want> wants;
    for (int i = 3; i < argc; ++i) {
        double t = _wtof(argv[i]);
        wchar_t buf[512];
        swprintf_s(buf, L"%s_%.2f.raw", argv[2], t);
        wants.push_back({ t, buf });
    }
    if (wants.empty()) { MFShutdown(); return 0; }

    // 顺序读，边读边比对想要的时间点（SourceReader 从当前读到的帧数推时间最省事）
    size_t next = 0;
    int frames = 0;
    for (;;) {
        DWORD flags = 0;
        LONGLONG ts = 0;
        ComPtr<IMFSample> sample;
        hr = reader->ReadSample(MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, nullptr, &flags, &ts, &sample);
        if (FAILED(hr)) { printf("ReadSample 失败 hr=0x%08X（第 %d 帧）\n", (unsigned)hr, frames); break; }
        if (flags & MF_SOURCE_READERF_ENDOFSTREAM) { printf("读到文件尾，共 %d 帧\n", frames); break; }
        if (!sample) continue;
        ++frames;
        double sec = ts / 10000000.0;
        while (next < wants.size() && sec >= wants[next].t) {
            ComPtr<IMFMediaBuffer> mb;
            if (SUCCEEDED(sample->ConvertToContiguousBuffer(&mb))) {
                BYTE* p = nullptr;
                DWORD len = 0;
                if (SUCCEEDED(mb->Lock(&p, nullptr, &len))) {
                    FILE* f = nullptr;
                    _wfopen_s(&f, wants[next].path.c_str(), L"wb");
                    if (f) { fwrite(p, 1, len, f); fclose(f); }
                    printf("  第 %d 帧 t=%.2fs 取到 %u 字节 -> %ls\n", frames, sec, len, wants[next].path.c_str());
                    mb->Unlock();
                }
            }
            ++next;
        }
        if (next >= wants.size() && frames > 200) break;
    }

    reader.Reset();
    CoUninitialize();
    MFShutdown();
    return 0;
}
