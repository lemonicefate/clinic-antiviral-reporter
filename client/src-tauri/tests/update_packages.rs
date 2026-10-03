use base64::{engine::general_purpose::STANDARD, Engine};
use clinic_antiviral_reporter::update_package::{Release, VerifiedPackage};
use sha2::{Digest, Sha256};
use std::{fs, path::Path, process::Command};
use clinic_antiviral_reporter::update_cache::UpdateCache;

fn signer(arguments: &[&str]) {
    let cli = Path::new(env!("CARGO_MANIFEST_DIR")).join("../node_modules/@tauri-apps/cli/tauri.js");
    let result = Command::new("node").arg(cli).arg("signer").args(arguments).output().unwrap();
    // Never print signer output: key generation can contain private key material.
    assert!(result.status.success(), "Synthetic signing command failed");
}

#[test]
fn signed_package_rejects_corruption_wrong_key_and_relabelled_version() {
    let root = tempfile::tempdir().unwrap();
    let key = root.path().join("synthetic.key");
    signer(&["generate", "--ci", "--password", "synthetic-only", "--write-keys", key.to_str().unwrap()]);
    let package = root.path().join("synthetic.exe");
    let bytes = b"MZ synthetic installer; never execute";
    fs::write(&package, bytes).unwrap();
    signer(&["sign", "--private-key-path", key.to_str().unwrap(), "--password", "synthetic-only",
        "--app-version", "0.1.1", package.to_str().unwrap()]);
    let public_key = fs::read_to_string(key.with_extension("key.pub")).unwrap();
    let signature = fs::read_to_string(package.with_extension("exe.sig")).unwrap();
    let release = Release { version: "0.1.1".into(), sha256: format!("{:x}", Sha256::digest(bytes)),
        size: bytes.len() as u64, signature, notes: String::new() };
    let mut extended = serde_json::to_value(&release).unwrap();
    extended["futureOptionalMetadata"] = serde_json::json!("synthetic added API field");
    let compatible: Release = serde_json::from_value(extended).unwrap();
    assert!(VerifiedPackage::verify(&compatible, bytes.to_vec(), public_key.trim()).is_ok());
    assert!(VerifiedPackage::verify(&release, bytes.to_vec(), public_key.trim()).is_ok());
    assert!(VerifiedPackage::verify(&release, b"MZ altered".to_vec(), public_key.trim()).is_err());
    let relabelled = Release { version: "0.1.2".into(), ..release.clone() };
    assert!(VerifiedPackage::verify(&relabelled, bytes.to_vec(), public_key.trim()).is_err());
    let other_key = root.path().join("other.key");
    signer(&["generate", "--ci", "--password", "synthetic-only", "--write-keys", other_key.to_str().unwrap()]);
    let other_public = fs::read_to_string(other_key.with_extension("key.pub")).unwrap();
    assert!(VerifiedPackage::verify(&release, bytes.to_vec(), other_public.trim()).is_err());
    let mut forged_comment = release.clone();
    let signature_text = String::from_utf8(STANDARD.decode(release.signature.trim()).unwrap()).unwrap();
    forged_comment.signature = STANDARD.encode(signature_text.replace("version:0.1.1", "version:0.1.2"));
    forged_comment.version = "0.1.2".into();
    assert!(VerifiedPackage::verify(&forged_comment, bytes.to_vec(), public_key.trim()).is_err());
    let previous_package = root.path().join("previous.exe");
    fs::write(&previous_package, bytes).unwrap();
    signer(&["sign", "--private-key-path", key.to_str().unwrap(), "--password", "synthetic-only",
        "--app-version", "0.1.0", previous_package.to_str().unwrap()]);
    let previous = Release { version: "0.1.0".into(), signature: fs::read_to_string(previous_package.with_extension("exe.sig")).unwrap(),
        ..release.clone() };
    let cache = UpdateCache::new(root.path().join("cache"));
    for invalid in ["../escape".to_string(), "中".repeat(17) + "aa"] {
        assert!(cache.directory(&invalid).is_err());
    }
    let old = VerifiedPackage::verify(&previous, bytes.to_vec(), public_key.trim()).unwrap();
    let new = VerifiedPackage::verify(&release, bytes.to_vec(), public_key.trim()).unwrap();
    let plan = cache.prepare(&old, &new, &package, root.path()).unwrap();
    let reopened = UpdateCache::new(root.path().join("cache"));
    let ready = reopened.latest().unwrap().unwrap();
    assert_eq!(ready.id, plan.id);
    assert_eq!(ready.previous.version, "0.1.0");
    assert_eq!(ready.next.version, "0.1.1");
    assert!(reopened.verified_installer(&ready, false, public_key.trim()).is_ok());
    assert!(reopened.verified_installer(&ready, true, public_key.trim()).is_ok());
    fs::write(root.path().join("cache/desktop.ini"), b"synthetic unrelated shell metadata").unwrap();
    assert_eq!(reopened.latest().unwrap().unwrap().id, plan.id);
    // A newer interrupted directory must not replace the retained ready plan.
    fs::create_dir(root.path().join("cache/99999999999999999999-00000000000000000000000000000000")).unwrap();
    fs::write(root.path().join("cache/99999999999999999999-00000000000000000000000000000000/ready.json"), b"synthetic damaged manifest").unwrap();
    assert_eq!(reopened.latest().unwrap().unwrap().id, plan.id);
    fs::write(root.path().join("cache").join(&plan.id).join("next.exe"), b"damaged").unwrap();
    assert!(reopened.verified_installer(&ready, false, public_key.trim()).is_err());
    assert!(reopened.verified_installer(&ready, true, public_key.trim()).is_ok());
    signer(&["sign", "--private-key-path", key.to_str().unwrap(), "--password", "synthetic-only", package.to_str().unwrap()]);
    let unbound = Release { signature: fs::read_to_string(package.with_extension("exe.sig")).unwrap(), ..release };
    assert!(VerifiedPackage::verify(&unbound, bytes.to_vec(), public_key.trim()).is_err());
}
