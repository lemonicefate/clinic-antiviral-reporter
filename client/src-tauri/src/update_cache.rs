//! Append-only update attempts. Only a durable ready manifest makes a plan usable.

use crate::update_package::{version, Release, VerifiedPackage, MAX_PACKAGE_SIZE};
use serde::{Deserialize, Serialize};
use std::{fs::{self, File, OpenOptions}, io::{Read, Write}, path::{Path, PathBuf},
    os::windows::fs::{MetadataExt, OpenOptionsExt}, time::{SystemTime, UNIX_EPOCH}};

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UpdatePlan {
    pub id: String,
    pub previous: Release,
    pub next: Release,
    pub install_directory: PathBuf,
}

pub struct UpdateCache { root: PathBuf }

fn valid_id(id: &str) -> bool {
    id.len() == 53 && id.is_ascii() && id[..20].bytes().all(|c| c.is_ascii_digit()) && &id[20..21] == "-"
        && id[21..].bytes().all(|c| c.is_ascii_hexdigit())
}

pub fn reject_reparse(path: &Path) -> Result<(), String> {
    for item in path.ancestors() {
        match fs::symlink_metadata(item) {
            Ok(metadata) if metadata.file_attributes() & 0x400 != 0 => return Err("更新路徑不可使用連結或接合點。".into()),
            Ok(_) => {},
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {},
            Err(_) => return Err("無法檢查更新資料夾。".into()),
        }
    }
    Ok(())
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), String> {
    reject_reparse(path)?;
    let mut file = OpenOptions::new().write(true).create_new(true).open(path).map_err(|_| "無法保存更新檔案。")?;
    file.write_all(bytes).and_then(|_| file.sync_all()).map_err(|_| "更新檔案保存未完成。".into())
}

pub fn read_bounded(path: &Path, limit: u64) -> Result<Vec<u8>, String> {
    reject_reparse(path)?;
    let file = File::open(path).map_err(|_| "無法讀取更新檔案。")?;
    read_file(&file, limit)
}

fn read_file(file: &File, limit: u64) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes).map_err(|_| "更新檔案讀取失敗。")?;
    if bytes.len() as u64 > limit { return Err("更新檔案超出大小限制。".into()); }
    Ok(bytes)
}

pub struct VerifiedInstaller {
    path: PathBuf,
    // Keep the read-only handle open through process creation. Windows denies
    // writing, deleting or replacing these verified bytes while it is held.
    _file: File,
}
impl VerifiedInstaller { pub fn path(&self) -> &Path { &self.path } }

impl UpdateCache {
    pub fn new(root: PathBuf) -> Self { Self { root } }

    pub fn directory(&self, id: &str) -> Result<PathBuf, String> {
        if !valid_id(id) {
            return Err("更新識別碼不正確。".into());
        }
        let path = self.root.join(id);
        reject_reparse(&path)?;
        Ok(path)
    }

    pub fn prepare(&self, previous: &VerifiedPackage, next: &VerifiedPackage, helper: &Path,
                   install_directory: &Path) -> Result<UpdatePlan, String> {
        if version(&previous.release().version)? >= version(&next.release().version)? {
            return Err("新版本必須高於目前版本。".into());
        }
        reject_reparse(&self.root)?;
        reject_reparse(install_directory)?;
        if !install_directory.is_absolute() { return Err("安裝位置不正確。".into()); }
        let mut random = [0; 16];
        getrandom::fill(&mut random).map_err(|_| "無法建立更新識別碼。")?;
        let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let previous_time = self.latest()?.map(|plan| plan.id[..20].parse::<u128>()).transpose()
            .map_err(|_| "更新紀錄排序不正確。")?.unwrap_or(0);
        let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| "系統時間不正確。")?.as_nanos()
            .max(previous_time + 1);
        let id = format!("{timestamp:020}-{suffix}");
        let directory = self.directory(&id)?;
        fs::create_dir_all(&self.root).and_then(|_| fs::create_dir(&directory)).map_err(|_| "無法建立更新資料夾。")?;
        write_new(&directory.join("previous.exe"), previous.bytes())?;
        write_new(&directory.join("next.exe"), next.bytes())?;
        write_new(&directory.join("recovery.exe"), &read_bounded(helper, MAX_PACKAGE_SIZE)?)?;
        let plan = UpdatePlan { id, previous: previous.release().clone(), next: next.release().clone(),
            install_directory: install_directory.to_path_buf() };
        let manifest = serde_json::to_vec(&plan).map_err(|_| "無法保存更新資訊。")?;
        write_new(&directory.join("pending.json"), &manifest)?;
        fs::rename(directory.join("pending.json"), directory.join("ready.json")).map_err(|_| "更新準備未完成。")?;
        Ok(plan)
    }

    pub fn load(&self, id: &str) -> Result<UpdatePlan, String> {
        let plan: UpdatePlan = serde_json::from_slice(&read_bounded(&self.directory(id)?.join("ready.json"), 256 * 1024)?)
            .map_err(|_| "保存的更新資訊已損毀。")?;
        if plan.id != id || !plan.install_directory.is_absolute() || version(&plan.previous.version)? >= version(&plan.next.version)? {
            return Err("保存的更新資訊不正確。".into());
        }
        plan.previous.validate()?;
        plan.next.validate()?;
        Ok(plan)
    }

    pub fn latest(&self) -> Result<Option<UpdatePlan>, String> {
        reject_reparse(&self.root)?;
        if !self.root.exists() { return Ok(None); }
        let mut ids = Vec::new();
        for entry in fs::read_dir(&self.root).map_err(|_| "無法讀取更新資料夾。")? {
            let entry = entry.map_err(|_| "無法讀取更新資料夾。")?;
            let id = entry.file_name().to_string_lossy().to_string();
            if !valid_id(&id) { continue; }
            let Ok(directory) = self.directory(&id) else { continue; };
            if directory.join("ready.json").exists() { ids.push(id); }
        }
        ids.sort();
        // Keep every damaged/incomplete attempt for diagnosis. An unrelated file
        // or broken newer manifest must not hide an older usable recovery plan.
        Ok(ids.iter().rev().find_map(|id| self.load(id).ok()))
    }

    pub fn verified_installer(&self, plan: &UpdatePlan, rollback: bool, key: &str) -> Result<VerifiedInstaller, String> {
        let path = self.directory(&plan.id)?.join(if rollback { "previous.exe" } else { "next.exe" });
        reject_reparse(&path)?;
        let file = OpenOptions::new().read(true).share_mode(1).open(&path).map_err(|_| "無法鎖定安裝包供驗證。")?;
        VerifiedPackage::verify(if rollback { &plan.previous } else { &plan.next }, read_file(&file, MAX_PACKAGE_SIZE)?, key)?;
        Ok(VerifiedInstaller { path, _file: file })
    }
}
