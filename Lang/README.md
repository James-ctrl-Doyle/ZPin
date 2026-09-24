1. 在 `ZPin.exe` 同目录下创建一个 `Lang` 子目录。
2. 把语言文件拷贝进去，文件名格式为 `<语言名>.<语言代码>.json`（例如 `English.en-US.json`）。
3. 重启应用，在「设置 → 语言」里即可看到新语言。

> 程序不读取 `%appdata%`，配置、临时文件、语言文件都在 exe 同目录下。
> 内置了简体中文与英文两套翻译（内嵌在 exe 里），放到 `Lang` 目录的文件用于覆盖或追加语言。

------

1. Create a `Lang` subdirectory next to `ZPin.exe`.
2. Copy the language file into it. The file name must be `<Language name>.<locale code>.json` (for example `English.en-US.json`).
3. Restart the application; the new language appears under Settings -> Language.

> The application does not read from `%appdata%`: configuration, temporary files and language files all live next to the exe.
> Simplified Chinese and English are built into the executable; files placed under `Lang` add or override languages.
