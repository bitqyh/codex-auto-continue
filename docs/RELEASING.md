# 发布与签名（RELEASING）

tag 推送后由 `.github/workflows/release.yml` 自动构建并发布：

| 产物 | 签名 | 构建方式 |
| --- | --- | --- |
| `CodexContinue-Setup-<ver>.exe` | SignPath Foundation（配置 secret 后） | Inno Setup，内嵌 Python |
| `CodexContinue-<ver>-win-x64.zip` | 未签名 | 便携包（嵌入 Python + 托盘） |
| `CodexContinue-<ver>-macOS.dmg` | ad-hoc（未公证） | universal app（arm64 + x86_64） |
| `SHA256SUMS` | — | 发布 job 生成 |

## 1. 发布前检查

```bash
python3 scripts/check_version.py --tag v0.5.0   # tag 必须与 pyproject/__init__ 一致
PYTHONPATH=src python3 -m unittest discover -s tests
```

合并到 `main`、CI 三平台全绿后再打 tag：

```bash
git tag -a v0.5.0 -m "v0.5.0"
git push origin v0.5.0
```

## 2. 本地构建

```bash
# macOS：universal app + ad-hoc 签名 + dmg
./scripts/build_macos_release.sh
# 产物：dist/CodexContinue-<ver>-macOS.dmg

# Windows（在 Windows 上）
pwsh ./scripts/build_windows_bundle.ps1 -Version 0.5.0
choco install innosetup -y
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "/DAppVersion=0.5.0" "installer\codex-auto-continue.iss"
# 产物：dist/CodexContinue-0.5.0-win-x64.zip 与 dist/CodexContinue-Setup-0.5.0.exe
```

macOS 构建会把 `src/` 和 `bin/codex-continue` 嵌入 `Contents/Resources/cli`，`CLIPath` 使用包内相对路径，因此 app 移动到 `/Applications` 后仍可用。

## 3. SignPath Foundation 接入（Windows 签名）

1. 用 GitHub 账号在 https://signpath.org/apply 申请；项目需 MIT、公开、已发布、有文档（当前满足）。
2. 审核通过后，在 SignPath 中：
   - 创建 Project，关联 `bitqyh/codex-auto-continue`；
   - 在 Organization 中添加 Trusted Build System **GitHub.com** 并链接 Project；
   - 安装 SignPath GitHub App（公开仓库也建议安装，便于审计）；
   - 创建 signing policy（如 `release-signing`）；
   - 创建 artifact configuration，用于签名安装器。`actions/upload-artifact` 默认把文件包成 zip，因此根元素用 `zip-file`（示例，字段以 SignPath 控制台为准）：
     ```xml
     <artifact-configuration xmlns="http://signpath.io/artifact-configuration">
       <zip-file>
         <file path="CodexContinue-Setup-*.exe" />
       </zip-file>
     </artifact-configuration>
     ```
3. 在仓库 **Settings → Secrets and variables → Actions** 添加：

   | Secret | 值 |
   | --- | --- |
   | `SIGNPATH_API_TOKEN` | SignPath 用户 API token（submitter 权限） |
   | `SIGNPATH_ORGANIZATION_ID` | Organization ID |
   | `SIGNPATH_PROJECT_SLUG` | Project slug |
   | `SIGNPATH_SIGNING_POLICY_SLUG` | 例如 `release-signing` |
   | `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` | 安装器配置的 slug |

4. 之后打 tag：workflow 会先上传未签名的 `Setup.exe`，调用 `signpath/github-action-submit-signing-request@v3` 签名，再用 `signtool verify /pa` 校验，最后把签名后的 exe 放进 Release。
5. `SIGNPATH_API_TOKEN` 未配置时，安装器会被重命名为 `CodexContinue-Setup-<ver>-unsigned.exe` 并照常发布（不会冒充已签名）。

注意：
- SignPath 的证书签发给 **SignPath Foundation**，安装器“发布者”显示为 SignPath Foundation，而不是个人。
- 签名保证发布者与完整性；Windows SmartScreen 对新证书仍有信誉累积期，可能短暂提示。
- 只签名安装器（`.exe`）；便携 zip 内的 `.cmd/.vbs/.ps1` 不适用 Authenticode。

## 4. 本地校验

```powershell
# Windows
signtool verify /pa /v dist\CodexContinue-Setup-0.5.0.exe
Get-FileHash dist\CodexContinue-0.5.0-win-x64.zip -Algorithm SHA256
```

```bash
# macOS
codesign --verify --deep --strict dist/CodexContinue-0.5.0-macOS.dmg  # dmg 本身未签，检查 app 时先挂载
hdiutil verify dist/CodexContinue-0.5.0-macOS.dmg
shasum -a 256 dist/CodexContinue-0.5.0-macOS.dmg
```

macOS 为 ad-hoc 签名、**未公证**：下载后首次启动需右键 → 打开，或：

```bash
xattr -dr com.apple.quarantine /Applications/CodexContinue.app
```

## 5. 失败处理与轮换

- SignPath 审核/签名失败：workflow 失败，不发布冒充签名的产物；可先手动发布 `-unsigned.exe`。
- 证书或 token 过期：更新 Secrets；SignPath 每年续签由基金会处理。
- macOS 构建失败（交叉编译）：确认 Xcode CLT 支持 `-target x86_64-apple-macos13.0`；必要时改为在两个 runner 分别构建再合并。
- 版本号只改 `pyproject.toml` 与 `src/codex_auto_continue/__init__.py`；`build.sh`、安装器版本都从它们派生。
