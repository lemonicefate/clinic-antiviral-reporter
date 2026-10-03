//! Native update boundary: credentials, verified files and executable paths never enter the webview.

use clinic_antiviral_reporter::{update_cache::{reject_reparse, UpdateCache, UpdatePlan},
    update_package::{version, Release, VerifiedPackage, MAX_PACKAGE_SIZE}};
use serde::{Deserialize, Serialize};
use std::{path::{Path, PathBuf}, process::Command, os::windows::process::CommandExt,
    sync::atomic::{AtomicBool, Ordering}, time::Duration};
use tauri::{AppHandle, Manager};

const PUBLIC_KEY: Option<&str> = option_env!("CLINIC_REPORTER_UPDATE_PUBLIC_KEY");
static BUSY: AtomicBool = AtomicBool::new(false);
struct Busy;
impl Busy {
    fn acquire() -> Result<Self, String> {
        BUSY.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map(|_| Self).map_err(|_| "另一個更新操作正在進行，請稍候。".into())
    }
}
impl Drop for Busy { fn drop(&mut self) { BUSY.store(false, Ordering::SeqCst); } }

fn key() -> Result<&'static str, String> {
    PUBLIC_KEY.filter(|value| !value.trim().is_empty()).ok_or_else(|| "本安裝版本尚未啟用安全更新，請聯絡管理者。".into())
}

fn cache(app: &AppHandle) -> Result<UpdateCache, String> {
    Ok(UpdateCache::new(app.path().app_local_data_dir().map_err(|_| "無法取得更新資料夾。")?.join("updates")))
}

fn registered_install_directory() -> Result<PathBuf, String> {
    let key = windows_registry::CURRENT_USER.open(r"Software\Microsoft\Windows\CurrentVersion\Uninstall\公費抗病毒藥劑回報")
        .map_err(|_| "請先以目前 Windows 帳號安裝回報工具，再使用更新功能。")?;
    let value = key.get_string("InstallLocation").map_err(|_| "無法確認目前安裝位置。")?;
    let path = PathBuf::from(value.trim_matches('"'));
    reject_reparse(&path)?;
    if !path.is_absolute() || path.to_string_lossy().contains(['"', '\r', '\n']) {
        return Err("目前安裝位置不正確。".into());
    }
    Ok(path)
}

fn same_directory(left: &Path, right: &Path) -> Result<(), String> {
    reject_reparse(left)?;
    reject_reparse(right)?;
    if left.canonicalize().map_err(|_| "安裝資料夾不存在。")? != right.canonicalize().map_err(|_| "安裝資料夾不存在。")? {
        return Err("安裝位置已變更，請重新準備更新。".into());
    }
    Ok(())
}

fn installed_directory() -> Result<PathBuf, String> {
    let directory = registered_install_directory()?;
    let executable = std::env::current_exe().map_err(|_| "無法確認目前程式位置。")?;
    same_directory(&directory, executable.parent().ok_or("無法確認目前程式位置。")?)?;
    Ok(directory)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateState {
    enabled: bool,
    current_version: String,
    available: Option<Release>,
    plan_token: Option<String>,
    prepared_version: Option<String>,
    rollback_version: Option<String>,
    recovery_available: bool,
}

#[tauri::command]
pub fn update_state(app: AppHandle) -> Result<UpdateState, String> {
    let current = app.package_info().version.to_string();
    let plan = cache(&app)?.latest()?;
    Ok(UpdateState {
        enabled: key().is_ok(), current_version: current.clone(), available: None,
        plan_token: plan.as_ref().map(|plan| plan.id.clone()),
        prepared_version: plan.as_ref().filter(|plan| plan.previous.version == current).map(|plan| plan.next.version.clone()),
        rollback_version: plan.as_ref().filter(|plan| plan.next.version == current).map(|plan| plan.previous.version.clone()),
        recovery_available: plan.is_some(),
    })
}

async fn get_bytes(endpoint: &str, credential: &str, route: &str, limit: u64) -> Result<Vec<u8>, String> {
    let client = reqwest::Client::builder().https_only(true).no_proxy()
        .redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(120))
        .connect_timeout(Duration::from_secs(5)).build().map_err(|_| "無法建立安全更新連線。")?;
    let mut response = client.get(format!("{endpoint}{route}")).bearer_auth(credential).send().await
        .map_err(|_| "更新連線失敗；目前版本不會變更。")?;
    if response.status() != reqwest::StatusCode::OK {
        return Err("更新資料無法取得，請確認裝置授權與中央版本設定。".into());
    }
    if response.content_length().is_some_and(|size| size > limit) { return Err("更新資料超出大小限制。".into()); }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "更新下載中斷；請重試。")? {
        if bytes.len() as u64 + chunk.len() as u64 > limit { return Err("更新資料超出大小限制。".into()); }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

#[derive(Deserialize)]
struct Announcement { release: Option<Release> }

async fn announcement(endpoint: &str, credential: &str) -> Result<Option<Release>, String> {
    let value: Announcement = serde_json::from_slice(&get_bytes(endpoint, credential, "/api/v1/client-releases/current", 65536).await?)
        .map_err(|_| "更新公告格式不正確。")?;
    if let Some(release) = &value.release { release.validate()?; }
    Ok(value.release)
}

#[tauri::command]
pub async fn check_updates(app: AppHandle) -> Result<UpdateState, String> {
    let _busy = Busy::acquire()?;
    let mut state = update_state(app)?;
    if !state.enabled { return Ok(state); }
    let (endpoint, credential) = crate::identity(None)?;
    if let Some(release) = announcement(&endpoint, &credential).await? {
        if version(&release.version)? > version(&state.current_version)? { state.available = Some(release); }
    }
    Ok(state)
}

#[tauri::command]
pub async fn prepare_update(app: AppHandle, expected_version: String) -> Result<UpdateState, String> {
    let _busy = Busy::acquire()?;
    let public_key = key()?;
    let directory = installed_directory()?;
    let current = app.package_info().version.to_string();
    let (endpoint, credential) = crate::identity(None)?;
    let next = announcement(&endpoint, &credential).await?.ok_or("中央尚未發布更新。")?;
    if next.version != expected_version || version(&next.version)? <= version(&current)? {
        return Err("公告版本已變更，請重新檢查更新。".into());
    }
    let previous: Release = serde_json::from_slice(&get_bytes(&endpoint, &credential,
        &format!("/api/v1/client-releases/{current}"), 65536).await?).map_err(|_| "無法取得目前版本的回復資訊。")?;
    if previous.version != current { return Err("回復版本與目前版本不符。".into()); }
    previous.validate()?;
    let old = VerifiedPackage::verify(&previous, get_bytes(&endpoint, &credential,
        &format!("/api/v1/client-releases/{current}/installer"), MAX_PACKAGE_SIZE).await?, public_key)?;
    let new = VerifiedPackage::verify(&next, get_bytes(&endpoint, &credential,
        &format!("/api/v1/client-releases/{}/installer", next.version), MAX_PACKAGE_SIZE).await?, public_key)?;
    cache(&app)?.prepare(&old, &new, &std::env::current_exe().map_err(|_| "無法保留回復工具。")?, &directory)?;
    update_state(app)
}

fn launch(cache: &UpdateCache, plan: &UpdatePlan, rollback: bool) -> Result<(), String> {
    same_directory(&registered_install_directory()?, &plan.install_directory)?;
    // Keep the old installer verified and locked even when installing the new one.
    let previous = cache.verified_installer(plan, true, key()?)?;
    let next = if rollback { None } else { Some(cache.verified_installer(plan, false, key()?)?) };
    let installer = next.as_ref().unwrap_or(&previous);
    Command::new(installer.path()).args(["/P", "/UPDATE"])
        .raw_arg(format!("/D={}", plan.install_directory.to_str().ok_or("安裝位置不正確。")?))
        .creation_flags(0x08000000).spawn().map_err(|_| "安裝程式無法啟動；目前程式保持開啟。")?;
    Ok(())
}

#[tauri::command]
pub async fn install_update(app: AppHandle, token: String, confirmed: bool, rollback: bool) -> Result<(), String> {
    let _busy = Busy::acquire()?;
    if !confirmed { return Err("請先確認已儲存工作並結束本次使用。".into()); }
    let directory = installed_directory()?;
    let cache = cache(&app)?;
    let plan = cache.load(&token)?;
    same_directory(&directory, &plan.install_directory)?;
    let current = app.package_info().version.to_string();
    if !rollback && plan.previous.version != current { return Err("目前版本已變更，請重新準備更新。".into()); }
    if rollback && plan.next.version != current { return Err("回復資訊與目前版本不符，請使用保留的回復工具。".into()); }
    launch(&cache, &plan, rollback)?;
    app.exit(0);
    Ok(())
}

#[tauri::command]
pub fn open_update_recovery(app: AppHandle) -> Result<(), String> {
    let cache = cache(&app)?;
    let plan = cache.latest()?.ok_or("尚未準備回復工具。")?;
    Command::new("explorer.exe").arg(cache.directory(&plan.id)?).spawn().map_err(|_| "無法開啟回復工具資料夾。")?;
    Ok(())
}

fn message(text: &str, confirm: bool) -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, IDYES, MB_YESNO, MB_DEFBUTTON2, MB_ICONWARNING, MB_OK};
    let wide: Vec<_> = text.encode_utf16().chain(Some(0)).collect();
    let title: Vec<_> = "回報工具版本回復".encode_utf16().chain(Some(0)).collect();
    unsafe { MessageBoxW(std::ptr::null_mut(), wide.as_ptr(), title.as_ptr(),
        if confirm { MB_YESNO | MB_DEFBUTTON2 | MB_ICONWARNING } else { MB_OK | MB_ICONWARNING }) == IDYES }
}

pub fn run_recovery_if_requested() -> bool {
    let Ok(executable) = std::env::current_exe() else { return false; };
    if !executable.file_name().is_some_and(|name| name.to_string_lossy().eq_ignore_ascii_case("recovery.exe")) { return false; }
    let recover = || -> Result<(), String> {
        let directory = executable.parent().ok_or("回復工具位置不正確。")?;
        let root = directory.parent().ok_or("回復工具位置不正確。")?;
        let id = directory.file_name().and_then(|name| name.to_str()).ok_or("回復工具位置不正確。")?;
        let cache = UpdateCache::new(root.to_path_buf());
        let plan = cache.load(id)?;
        cache.verified_installer(&plan, true, key()?)?;
        if message(&format!("將回復至 {}。請先儲存並結束所有回報工具視窗。\n中央案件與資料庫不會回復舊版。\n確定開始安裝？", plan.previous.version), true) {
            launch(&cache, &plan, true)?;
        }
        Ok(())
    };
    if let Err(error) = recover() { message(&error, false); }
    true
}
