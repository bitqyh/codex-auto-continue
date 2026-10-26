# 发布（RELEASING，不签名）

tag 推送后由 `.github/workflows/release.yml` 自动构建并发布：

| 产物 | 签名 | 构建方式 |
| --- | --- | --- |
| `CodexContinue-Setup-<ver>-unsigned.exe` | **未签名** | Inno Setup，内嵌 Python |
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
# 产物：dist/CodexContinue-0.5.0-win-x64.zip 与 dist/CodexContinue-Setup-0.5.1-unsigned.exe
```

macOS 构建会把 `src/` 和 `bin/codex-continue` 嵌入 `Contents/Resources/cli`，`CLIPath` 使用包内相对路径，因此 app 移动到 `/Applications` 后仍可用。

## 3. 签名状态（当前不签名）

- Windows 安装器**不签名**：workflow 构建出 `Setup.exe` 后，由 `scripts/finalize_windows_assets.ps1` 改名为 `CodexContinue-Setup-<ver>-unsigned.exe`，不做 Authenticode 签名。
- macOS dmg 内 app 为 ad-hoc 签名、**未公证**；首次启动需右键打开。
- SignPath Foundation 申请未通过；仓库不再包含 `SIGNPATH_*` Secrets 或签名步骤。如果以后重新考虑签名，需要重新评估（Azure Artifact Signing、商业 OV/EV 证书或自签名）并更新本文件。
- `SHA256SUMS` 只校验文件完整性，不是发布者签名；Windows SmartScreen 可能提示“未知发布者”。

## 4. 本地校验

```powershell
# Windows（安装器未签名，signtool 会报告 No signature found；用哈希校验）
Get-FileHash dist\CodexContinue-Setup-0.5.1-unsigned.exe -Algorithm SHA256
Get-FileHash dist\CodexContinue-0.5.1-win-x64.zip -Algorithm SHA256
```

```bash
# macOS
codesign --verify --deep --strict dist/CodexContinue-0.5.1-macOS.dmg  # dmg 本身未签，检查 app 时先挂载
hdiutil verify dist/CodexContinue-0.5.1-macOS.dmg
shasum -a 256 dist/CodexContinue-0.5.1-macOS.dmg
```

macOS 为 ad-hoc 签名、**未公证**：下载后首次启动需右键 → 打开，或：

```bash
xattr -dr com.apple.quarantine /Applications/CodexContinue.app
```

## 5. 失败处理与轮换

- 签名步骤已从 workflow 移除；发布产物固定为未签名安装器。
- 如果以后恢复签名：需要新增 Secrets、签名步骤与验签，并重新评估发布者信任链。
- macOS 构建失败（交叉编译）：确认 Xcode CLT 支持 `-target x86_64-apple-macos13.0`；必要时改为在两个 runner 分别构建再合并。
- 版本号只改 `pyproject.toml` 与 `src/codex_auto_continue/__init__.py`；`build.sh`、安装器版本都从它们派生。
