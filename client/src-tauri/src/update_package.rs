//! The only constructor of executable update bytes validates the pinned signature.

use base64::{engine::general_purpose::STANDARD, Engine};
use minisign_verify::{PublicKey, Signature};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const MAX_PACKAGE_SIZE: u64 = 128 * 1024 * 1024;

#[derive(Clone, Deserialize, Serialize)]
pub struct Release {
    pub version: String,
    pub sha256: String,
    pub size: u64,
    pub signature: String,
    pub notes: String,
}

pub fn version(value: &str) -> Result<[u16; 3], String> {
    let parts: Vec<_> = value.split('.').collect();
    if parts.len() != 3 {
        return Err("更新版本格式不正確。".into());
    }
    let mut result = [0; 3];
    for (index, part) in parts.iter().enumerate() {
        if part.is_empty() || (part.len() > 1 && part.starts_with('0')) || !part.bytes().all(|c| c.is_ascii_digit()) {
            return Err("更新版本格式不正確。".into());
        }
        result[index] = part.parse().map_err(|_| "更新版本超出支援範圍。")?;
    }
    Ok(result)
}

impl Release {
    pub fn validate(&self) -> Result<(), String> {
        version(&self.version)?;
        if self.size == 0 || self.size > MAX_PACKAGE_SIZE || self.sha256.len() != 64
            || !self.sha256.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            || self.signature.len() > 16384 || self.notes.chars().count() > 4000 {
            return Err("更新套件資訊不正確。".into());
        }
        Ok(())
    }
}

pub struct VerifiedPackage {
    release: Release,
    bytes: Vec<u8>,
}

impl VerifiedPackage {
    pub fn verify(release: &Release, bytes: Vec<u8>, public_key: &str) -> Result<Self, String> {
        release.validate()?;
        if bytes.len() as u64 != release.size || format!("{:x}", Sha256::digest(&bytes)) != release.sha256 {
            return Err("安裝包不完整或已損毀；目前版本不會變更。".into());
        }
        let decode = |value: &str| -> Result<String, String> {
            String::from_utf8(STANDARD.decode(value.trim()).map_err(|_| "更新簽章格式不正確。")?)
                .map_err(|_| "更新簽章格式不正確。".into())
        };
        let key = PublicKey::decode(&decode(public_key)?).map_err(|_| "本版本未設定有效的更新公鑰。")?;
        let signature = Signature::decode(&decode(&release.signature)?).map_err(|_| "更新簽章格式不正確。")?;
        key.verify(&bytes, &signature, true).map_err(|_| "更新簽章驗證失敗；目前版本不會變更。")?;
        // The trusted comment is authenticated by the global signature above.
        // Reject missing or duplicate version fields, including older signatures
        // without a version binding. This is not a restriction on minisign's algorithm.
        let signed_versions: Vec<_> = signature.trusted_comment().split('\t')
            .filter_map(|field| field.strip_prefix("version:")).collect();
        if signed_versions != [release.version.as_str()] {
            return Err("簽章版本與公告版本不符，或未綁定版本。".into());
        }
        Ok(Self { release: release.clone(), bytes })
    }

    pub fn release(&self) -> &Release { &self.release }
    pub fn bytes(&self) -> &[u8] { &self.bytes }
}
