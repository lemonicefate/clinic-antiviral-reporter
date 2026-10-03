fn main() {
    println!("cargo:rerun-if-env-changed=CLINIC_REPORTER_UPDATE_PUBLIC_KEY");
    tauri_build::build()
}
