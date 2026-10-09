# GUI 应用的存储位置与 NTFS junction 说明

> 本次缓存迁移的配套文档，对应 R:\Caches 统一缓存目录方案。

## 一、NTFS junction 是什么

junction（目录联接）是 NTFS 的**目录级重定向**：在 C 盘某个路径放一个「门牌」，
该目录的内容实际存放在另一个盘的目录里。对应用程序完全透明 —— 应用仍然以为
数据在 C 盘原路径，读写、枚举、权限表现都和真目录一样。

创建方式（cmd；在自己用户目录内不需要管理员）：

```cmd
mklink /J "C:\原路径" "R:\Caches\apps\目标目录"
```

PowerShell 等价：

```powershell
New-Item -ItemType Junction -Path "C:\原路径" -Target "R:\Caches\apps\目标目录"
```

标准三步（**必须先完全退出该应用**）：

1. 把 `C:\原路径` 的全部内容复制到 `R:\Caches\apps\目标目录`
2. 逐项核对复制完整（文件数 + 字节数）后，删除或改名 `C:\原路径`
3. `mklink /J "C:\原路径" "R:\Caches\apps\目标目录"`

### 风险（动手前务必知道）

- 第 2 步是**删除动作，不可逆**，必须先备份。
- 有些应用启动时会检测到「目录不是普通目录」，直接重建真目录覆盖 junction，
  造成新旧数据分裂，比不搬更麻烦。
- 卸载 / 自动更新该应用时，安装器可能**顺着 junction 删掉另一个盘上的真实数据**。
- 备份软件（含系统还原、OneDrive 同步）可能跟随 junction 重复备份，体积翻倍。
- 带完整性校验的程序会直接报错或拒绝启动。

结论：junction 是**最后手段**。能用官方设置就用官方设置。

## 二、各应用官方是否支持改存储位置

| 应用 | 当前数据/缓存目录 | 官方设置方式 | 能否改到其他盘 |
|---|---|---|---|
| **Chrome** | `%LOCALAPPDATA%\Google\Chrome\User Data` | 启动参数 `--user-data-dir=<路径>` | 能（用户数据）；`--disk-cache-dir` 无官方文档背书 |
| **JetBrains 系**（Android Studio / IntelliJ） | `%LOCALAPPDATA%\Google\AndroidStudio*` | `idea.properties` 中 `idea.system.path` / `idea.config.path` / `idea.log.path` / `idea.plugins.path` | 能（官方支持） |
| **通义灵码 / Qoder CN** | `%USERPROFILE%\.lingma` | VS Code `settings.json` 的 `Lingma.LocalMachineStoragePath`；「高级设置」可改解压路径 | 能（官方支持） |
| **LM Studio** | `%USERPROFILE%\.lmstudio` | 官方文档只描述 `~/.lmstudio/models` 结构，未记载更改模型目录的设置项 | 官方未说明 |
| **SynthCut by Relo** | `%USERPROFILE%\.aive`（17.3G） | 未检索到官方帮助文档 | 未找到官方说明 |
| **微信 Windows 4.x** | `%APPDATA%\Tencent`（7.5G） | 未从官方渠道找到「更改文件保存位置」说明 | 未找到官方说明 |
| **剪映专业版** | `%LOCALAPPDATA%\JianyingPro`（4.3G） | 官方帮助页返回 404 | 未找到官方说明 |
| **WorkBuddy** | `%USERPROFILE%\.workbuddy`（6.7G） | 未见官方文档 | 未找到官方说明 |

### 局限

- 「未找到官方说明」是基于公开检索的结论，不等于「官方一定不支持」；这几家帮助中心
  索引质量差，可能漏检。**最终以你打开应用设置界面看到的为准。**
- 微信、剪映的设置菜单没有实际打开逐项确认，建议在「设置」里搜「存储」「文件位置」
  「草稿」等关键词自行确认。
- WorkBuddy 配置里已有 `"defaultWorkspacePath": "R:\\WorkBuddy_work"`，说明它的
  **工作区**可重定向，但 `.workbuddy` 数据目录本身未见官方设置项。

## 三、建议顺序

1. **优先官方设置**：Chrome、JetBrains、通义灵码三家官方明确支持，先改这三个。
2. **微信**：在「设置 → 文件管理」确认能否改保存位置 —— 7.5G 里的主要占用。
3. **剪映**：在「设置」里找草稿位置与缓存清理。
4. **SynthCut（17.3G，最大一块）**：先看软件内有无缓存/代理目录设置；它的
   `data\proxies` 属于**可重建的代理媒体**，在软件内执行「清理代理缓存」比迁移目录更安全。
5. **junction 只留作最后手段**，且只对确实没有官方设置的应用使用。
6. 动手前先备份：环境变量已备份在 `C:\Users\28177\env-backup\`（HKLM/HKCU 两个 .reg）。
