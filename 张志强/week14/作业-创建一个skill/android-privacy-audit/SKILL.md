---
name: android-privacy-audit
description: >-
  对 Android 项目执行隐私合规全量排查。当用户要求检查、扫描或审计 Android 应用的
  隐私合规、隐私政策、权限问题、SDK 合规、信息收集或相关监管合规问题时使用。
  覆盖隐私政策同意流程、信息收集与使用、权限声明与实际使用对照、第三方 SDK 合规、
  以及自启动、关联唤醒、静默安装等违规行为。适用于任意 Android 项目，不依赖特定
  模块结构、语言（Java/Kotlin）或第三方库。
---

# Android Privacy Compliance Audit

对任意 Android 项目执行隐私合规全量排查，输出结构化报告和优先级整改建议。

适用于任何 Android 项目，不预设模块名、包名、权限框架或网络框架。

## 审计前置：项目结构探测

正式排查前，先探测项目结构以确定后续 Grep 路径范围。

1. **定位主模块**：读取根目录 `settings.gradle` 或 `settings.gradle.kts`，找到 `include` 的模块列表。主模块通常是名为 `app` 的模块，但也可能是其他名称。
2. **定位所有 Manifest**：Glob `**/src/main/AndroidManifest.xml`，排除 `build/` 目录。记录每个 Manifest 所属模块。
3. **定位所有 build.gradle**：Glob `**/build.gradle` 和 `**/build.gradle.kts`，排除 `build/` 目录。
4. **定位所有 libs 目录**：Glob `**/libs/*.aar` 和 `**/libs/*.jar`，排除 `build/` 目录。
5. **确定主 Application 类**：读取主模块 Manifest 的 `<application android:name="...">`，得到 Application 类全限定名。
6. **确定入口 Activity**：在主模块 Manifest 中找带 `android.intent.action.MAIN` + `android.intent.category.LAUNCHER` 的 Activity。

## 审计流程

按以下顺序逐项排查，每项必须使用 Grep/Read/Glob 工具获取代码证据，不得凭空推断。

### Phase 1: 隐私政策同意流程

1. **定位入口 Activity**：从前置探测结果中获取入口 Activity 类名，Read 该文件。
2. **定位隐私弹窗**：Grep 以下关键词（中英文混合，覆盖常见命名）：
   ```
   隐私政策|隐私协议|用户协议|privacy|Privacy|PrivacyPolicy|PrivacyDialog|
   XieYi|isAgree|isShowXieYi|FirstLaunch|同意并继续|agreePrivacy|
   isFirstRun|isFirstTime|hasAgreed|privacyAgreed|showPrivacy|协议弹窗
   ```
   找到弹窗 Dialog/Activity/Fragment。
3. **读取弹窗代码**：检查以下要点：
   - 首次启动是否通过弹窗提示阅读隐私政策
   - 是否存在默认勾选/登录即同意等非明示方式（Grep `setChecked\(true\)|isChecked.*=.*true` 在弹窗相关代码中）
   - 弹窗是否可取消（`setCancelable`）
   - "不同意"按钮是否有合理的退出机制（非仅 finish 当前页导致后续流程崩溃）
   - 弹窗协议摘要是否与实际收集行为匹配（对比弹窗文案 vs Manifest 权限 vs SDK 清单）
4. **定位隐私政策链接**：Grep 以下关键词在常量类/配置类中找到隐私政策 URL：
   ```
   PrivacyContract|UserContract|privacy.*url|privacy.*Url|privacyPolicy|
   H5_PRIVACY|H5_USER_CONTRACT|隐私.*url|隐私.*地址|privacyPolicyUrl|agreementUrl
   ```
   - 确认是否可通过 App 内 WebView 访问（非外跳浏览器）
   - 确认隐私政策中开发者/应用名称是否与 Manifest `android:label` 一致

### Phase 2: 信息收集与使用

1. **检查 Application.onCreate**：Read 主 Application 类，检查 SDK 初始化时机。
   - 是否在用户同意隐私政策前就初始化了 SDK
   - Grep `initSdk|initSDK|\.init\(|\.initialize\(` 确认所有 init 调用点
   - 是否在同意前发起了网络请求
2. **检查设备信息采集**：Grep 以下关键词，覆盖所有常见设备标识采集方式：
   ```
   getDeviceId|getIMEI|IMEI|getMeid|getOaid|OAID|ANDROID_ID|android_id|
   getMacAddress|getMac|MacAddress|TelephonyManager|READ_PHONE_STATE|
   getSerial|getSubscriberId|getSimSerialNumber|getLine1Number|
   WifiInfo|wifiManager\.getConnectionInfo|getBSSID|getSSID
   ```
   - 逐一确认采集场景和合法性
   - 确认是否使用本地生成 UUID 替代系统设备标识（合规）
3. **检查设备信息上报**：Grep `uploadDeviceInfo|DeviceInfo|deviceInfo|reportDevice|设备信息` 找到上报逻辑。
   - 确认上报字段是否在隐私政策中声明
   - 确认是否违反最小必要原则
4. **检查 HTTP 拦截器**：
   - Grep `Interceptor|interceptor|addInterceptor` 找到所有 OkHttp/Retrofit 拦截器
   - Read 拦截器代码，确认是否在请求头/参数中注入设备标识、token 等敏感信息
   - 确认拦截器是否在 Debug/Release 下有不同的日志行为
5. **检查同意前采集门控**：确认 Application 中是否有门控变量控制 SDK 初始化。
   - Grep `isShowXieYi|isAgree|isAgreePrivacy|hasAgreed|privacyAgreed|isFirstRun|needAgree`
   - 确认门控变量是否在 `onCreate` 中正确使用（同意前不初始化 SDK）

### Phase 3: 权限申请排查

1. **读取所有 AndroidManifest.xml**：从前置探测结果中读取所有模块的 Manifest。
2. **汇总所有声明的权限**：逐一列出权限名，去重后与实际使用场景对照。注意 Manifest 合并：子模块声明的权限会合并到主 Manifest。
3. **检查高风险权限**：重点关注以下权限是否有使用场景：
   - `READ_PHONE_STATE` / `READ_CALL_LOG` / `READ_CONTACTS` / `WRITE_CONTACTS` — 是否已 `tools:node="remove"`
   - `READ_LOGS` — 声明但无实际调用即为违规
   - `WRITE_SETTINGS` / `MOUNT_UNMOUNT_FILESYSTEMS` — 系统级权限，无场景即违规
   - `SYSTEM_ALERT_WINDOW` — 悬浮窗，需有明确功能场景
   - `CALL_PHONE` — 需有拨打电话功能
   - `RECORD_AUDIO` / `MODIFY_AUDIO_SETTINGS` — 需有录音/语音功能
   - `MANAGE_EXTERNAL_STORAGE` — 所有文件访问，需证明最小必要
   - `REQUEST_INSTALL_PACKAGES` — 需确认关联 SDK 和使用场景
   - `GET_TASKS` — 已废弃，应移除
   - `BROADCAST_STICKY` — 无 `sendStickyBroadcast` 调用即违规
   - `ACCESS_BACKGROUND_LOCATION` — 需证明后台定位场景
   - `ACTIVITY_RECOGNITION` — 需有运动/步数功能
   - `QUERY_ALL_PACKAGES` — 应 `tools:node="remove"`（除非有明确业务需求）
   - `READ_EXTERNAL_STORAGE` / `WRITE_EXTERNAL_STORAGE` — Android 10+ 应考虑 Scoped Storage 替代
   - `USE_FINGERPRINT` / `USE_BIOMETRIC` — 需有生物识别功能
   - `READ_SMS` / `RECEIVE_SMS` / `SEND_SMS` — 高敏感权限，需有明确业务场景
4. **检查重复声明**：同一权限在 Manifest 中出现多次，标注为冗余。
5. **权限动态申请排查**：Grep 以下关键词，覆盖常见权限框架：
   ```
   requestPermissions|checkSelfPermission|onRequestPermissionsResult|
   XXPermissions|XPermissionUtils|EasyPermissions|Dexter|PermissionX|
   ActivityCompat\.requestPermissions|shouldShowRequestPermissionRationale
   ```
   确认动态申请时机是否在用户同意隐私政策后。

### Phase 4: 第三方 SDK 排查

1. **汇总 SDK 清单**：从前置探测结果中收集所有第三方 SDK，来源包括：
   - 所有模块 `build.gradle` / `build.gradle.kts` 中的 `implementation`/`api`/`compile` 依赖
   - 所有 `libs/` 目录下的 `.aar`/`.jar` 文件
   - 源码模块（非 `build/` 目录下的独立 Gradle 模块）
2. **检查 SDK 初始化代码**：Grep `initSdk|initSDK|\.init\(|\.initialize\(` 在 Application 和入口 Activity 中。
   - 确认每个 SDK 是否在用户同意后才初始化
   - 确认 SDK 初始化时是否传入了设备标识（如 `setDeviceId`、`setOAID`）
3. **检查广告 SDK 个性化策略**：Grep 以下关键词：
   ```
   AgreePersonal|PersonalStrategy|personalize|个性化|个性化推荐|
   setPersonalized|personalizedAd|GDPR|consent
   ```
   - `setAgreePersonalStrategy(true)` 或类似方法硬编码为 true 即为违规，应动态设置
4. **检查地图/定位 SDK 隐私设置**：Grep `setAgreePrivacy|agreePrivacy|updatePrivacyShow|updatePrivacyAgree`。
   - 硬编码为 true 需确认是否在同意后调用
5. **检查 SDK 密钥硬编码**：Grep `meta-data.*APPKEY|meta-data.*APPSECRET|meta-data.*SECRET|meta-data.*KEY.*android:value` 在 Manifest 中。
   - APPKey/Secret 硬编码在 Manifest 中属安全风险
6. **标注每个 SDK**：名称、版本、来源（Maven/AAR/JAR/Module）、用途、是否需在隐私政策中声明、风险等级。
   - 对于用途不明的 SDK（特别是 AAR/JAR），标注"需人工确认用途"。

### Phase 5: 其他违规行为

1. **自启动/关联唤醒**：Grep `BOOT_COMPLETED|RECEIVE_BOOT_COMPLETED|android.intent.action.BOOT|autoStart|AutoStart|AUTO_LAUNCH`。
   - 检查 Manifest 中是否有接收 BOOT_COMPLETED 的 Receiver
   - 无结果即合规
2. **静默安装**：Grep `REQUEST_INSTALL_PACKAGES|PackageInstaller|pm install|silent.*install|installPackage`。
   - 确认 `REQUEST_INSTALL_PACKAGES` 权限关联的 SDK 是否有静默安装行为
   - 检查是否有 `FileProvider` + `Intent.ACTION_INSTALL` 的安装流程
3. **应用列表读取**：Grep `getInstalledPackages|getInstalledApplications|queryIntentActivities|getPackagesForUid`。
   - `getLaunchIntentForPackage` 判断单个 App 是否安装，合规度较好
   - `getInstalledPackages` 读取完整列表需确认是否有明确业务需要
4. **前后台判断**：Grep `getRunningTasks|getRunningAppProcesses|getRunningServices`。
   - `getRunningAppProcesses()` 不需要 `GET_TASKS` 权限，但声明了该权限即为冗余
5. **粘性广播**：Grep `BROADCAST_STICKY|sendStickyBroadcast|sendStickyOrderedBroadcast`。
   - 声明但无调用即为冗余
6. **数据外传风险**：Grep `uploadString|uploadData|reportData|syncData` 确认是否有未经声明的数据上传行为。

## 输出格式

使用以下模板输出报告，所有发现必须附带代码证据（文件路径+行号或代码片段）：

```markdown
# [应用名] 隐私合规排查报告

## 一、隐私政策问题
### 1.x [具体问题]
**合规项/违规风险：** [描述]
[代码引用]
[风险表格：风险项 | 说明 | 严重度]

## 二、信息收集与使用问题
### 2.x [具体问题]
[同上格式]

## 三、权限申请问题
### 3.1 高风险/敏感权限清单
[权限表格：权限 | 声明位置 | 实际使用场景 | 风险评估]
### 3.x 其他权限问题

## 四、第三方 SDK 问题
### 4.1 SDK 完整清单
[SDK表格：SDK | 来源 | 用途 | 是否在隐私政策中声明 | 风险]
### 4.x 具体风险

## 五、其他违规行为
### 5.x [具体问题]

## 六、补充发现
### 6.x [具体问题]

## 七、整改建议优先级

### P0 — 必须立即修复
[编号] [问题描述] [整改建议]

### P1 — 尽快修复
[编号] [问题描述] [整改建议]

### P2 — 建议修复
[编号] [问题描述] [整改建议]
```

## 严重度判定标准

| 严重度 | 判定条件 |
|--------|----------|
| 高 | 违反《个人信息保护法》或《App 违法违规收集使用个人信息行为认定方法》的明确禁止条款，可能导致应用下架 |
| 中 | 存在合规隐患但不直接违反禁止条款，审核可能被标记要求整改 |
| 低 | 代码规范或最佳实践层面的问题，不影响合规判定但建议修复 |

## 整改优先级标准

- **P0（必须立即修复）**：违法违规行为，审核必中被拒，需在上线前修复
- **P1（尽快修复）**：审核可能被标记，或存在被举报风险，上线后尽快修复
- **P2（建议修复）**：代码规范/安全加固层面，不影响合规判定但提升质量

## 注意事项

- 所有结论必须基于代码证据，不得凭推断下结论
- 无法确认的场景标注"需人工核实"而非直接判定
- 第三方 SDK 的实际采集行为需结合 SDK 官方文档确认，代码层面只能检查初始化方式和传入参数
- 隐私政策文本内容需人工访问 URL 确认，代码层面只能检查链接是否可达
- 对于 `tools:node="remove"` 的权限，视为已移除（合规），但需确认代码中无残留调用
- 多模块项目中，子模块 Manifest 声明的权限会合并到最终 Manifest，需全部检查
- Kotlin 项目中同样适用本流程，Grep 搜索范围应包含 `.kt` 文件
- 如果项目使用 Retrofit，还需检查 Retrofit Interceptor（通过 `addInterceptor` 添加的 OkHttpClient）