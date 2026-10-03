#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod desktop;
mod startup;
mod updates;

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use keyring::Entry;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{sync::Mutex, time::Duration};

const KEYRING_SERVICE: &str = "tw.clinic.antiviral-reporter";
static CREDENTIAL_LOCK: Mutex<()> = Mutex::new(());

fn entry(name: &str) -> Result<Entry, String> {
    Entry::new(KEYRING_SERVICE, name).map_err(|_| "無法存取 Windows 裝置憑證。".into())
}

fn normalize_endpoint(value: &str) -> Result<String, String> {
    let url = reqwest::Url::parse(value).map_err(|_| "請輸入有效的中央服務 HTTPS 位址。")?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
    {
        return Err("中央位址必須使用 HTTPS，且不可包含帳密或額外路徑。".into());
    }
    Ok(url.as_str().trim_end_matches('/').to_string())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConnectionSettings {
    endpoint: String,
    credential_configured: bool,
}

#[derive(Default, Deserialize, Serialize)]
struct DeviceIdentity {
    active: Option<String>,
    pending: Option<PendingIdentity>,
    last_enrollment: Option<String>,
}

#[derive(Deserialize, Serialize)]
struct PendingIdentity {
    request_id: String,
    credential: String,
}

fn read_identity(endpoint: &str) -> Result<DeviceIdentity, String> {
    match entry(endpoint)?.get_password() {
        Ok(value) => serde_json::from_str(&value).map_err(|_| "裝置憑證格式無法讀取。".into()),
        Err(keyring::Error::NoEntry) => Ok(DeviceIdentity::default()),
        Err(_) => Err("無法讀取装置憑證。".into()),
    }
}

fn save_identity(endpoint: &str, identity: &DeviceIdentity) -> Result<(), String> {
    let value = serde_json::to_string(identity).map_err(|_| "無法保存裝置憑證。")?;
    entry(endpoint)?
        .set_password(&value)
        .map_err(|_| "無法保存裝置憑證。".into())
}

impl DeviceIdentity {
    fn prepare(&mut self, request_id: &str) -> Result<(), String> {
        if self.last_enrollment.as_deref() == Some(request_id)
            || self
                .pending
                .as_ref()
                .is_some_and(|pending| pending.request_id == request_id)
        {
            return Ok(());
        }
        let mut bytes = [0u8; 32];
        getrandom::fill(&mut bytes).map_err(|_| "無法產生裝置憑證。")?;
        self.pending = Some(PendingIdentity {
            request_id: request_id.to_owned(),
            credential: URL_SAFE_NO_PAD.encode(bytes),
        });
        Ok(())
    }

    fn enrollment_key(&self, request_id: &str) -> Result<String, String> {
        if self.last_enrollment.as_deref() == Some(request_id) {
            return self
                .active
                .clone()
                .ok_or_else(|| "裝置憑證尚未啟用。".into());
        }
        self.pending
            .as_ref()
            .filter(|pending| pending.request_id == request_id)
            .map(|pending| pending.credential.clone())
            .ok_or_else(|| "配對設定已變更，請重新核對。".into())
    }

    fn activate(&mut self, request_id: &str) -> Result<(), String> {
        let key = self.enrollment_key(request_id)?;
        self.active = Some(key);
        self.pending = None;
        self.last_enrollment = Some(request_id.to_owned());
        Ok(())
    }
}

#[tauri::command]
fn connection_settings() -> Result<ConnectionSettings, String> {
    let _guard = CREDENTIAL_LOCK.lock().map_err(|_| "裝置憑證忙碌中。")?;
    let endpoint = match entry("central-endpoint")?.get_password() {
        Ok(value) => normalize_endpoint(&value)?,
        Err(keyring::Error::NoEntry) => String::new(),
        Err(_) => return Err("無法讀取中央連線設定。".into()),
    };
    let credential_configured = !endpoint.is_empty() && read_identity(&endpoint)?.active.is_some();
    Ok(ConnectionSettings {
        endpoint,
        credential_configured,
    })
}

#[tauri::command]
fn configure_connection(endpoint: String, credential: Option<String>) -> Result<(), String> {
    let _guard = CREDENTIAL_LOCK.lock().map_err(|_| "裝置憑證忙碌中。")?;
    let endpoint = normalize_endpoint(&endpoint)?;
    if let Some(secret) = credential.filter(|value| !value.is_empty()) {
        if secret.len() != 43
            || !secret
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
        {
            return Err("裝置金鑰格式不正確，請向管理者確認。".into());
        }
        save_identity(
            &endpoint,
            &DeviceIdentity {
                active: Some(secret),
                ..Default::default()
            },
        )?;
    }
    entry("central-endpoint")?
        .set_password(&endpoint)
        .map_err(|_| "無法保存中央位址。")?;
    Ok(())
}

fn identity(enrollment_request: Option<&str>) -> Result<(String, String), String> {
    let _guard = CREDENTIAL_LOCK.lock().map_err(|_| "裝置憑證忙碌中。")?;
    let endpoint = normalize_endpoint(
        &entry("central-endpoint")?
            .get_password()
            .map_err(|_| "請先設定中央位址。")?,
    )?;
    let identity = read_identity(&endpoint)?;
    let credential = match enrollment_request {
        Some(request_id) => identity.enrollment_key(request_id)?,
        None => identity.active.ok_or("此裝置尚未配對。")?,
    };
    Ok((endpoint, credential))
}

#[tauri::command]
fn prepare_identity(request_id: String) -> Result<(), String> {
    let _guard = CREDENTIAL_LOCK.lock().map_err(|_| "裝置憑證忙碌中。")?;
    let endpoint = normalize_endpoint(
        &entry("central-endpoint")?
            .get_password()
            .map_err(|_| "請先設定中央位址。")?,
    )?;
    let mut identity = read_identity(&endpoint)?;
    identity.prepare(&request_id)?;
    save_identity(&endpoint, &identity)
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CentralRequest {
    method: String,
    path: String,
    session_id: Option<String>,
    body: Option<Value>,
}

#[derive(Serialize)]
struct CentralResponse {
    status: u16,
    body: String,
}

fn permitted_route(path: &str) -> bool {
    // Query values may contain encoded chart numbers or physician labels. Only
    // the path portion selects a route; encoded path traversal remains forbidden.
    let route = path.split('?').next().unwrap_or("");
    route.starts_with("/api/v1/")
        && !route.contains("..")
        && !route.contains(['\\', '#', '%'])
        && !path.contains(['#', '\\', '\r', '\n'])
}

#[tauri::command]
async fn central_request(mut request: CentralRequest) -> Result<CentralResponse, String> {
    let enrollment = if request.path == "/api/v1/devices/enroll" {
        Some(
            request
                .body
                .as_ref()
                .and_then(|body| body.get("requestId"))
                .and_then(Value::as_str)
                .ok_or("配對請求缺少識別碼。")?
                .to_owned(),
        )
    } else {
        None
    };
    let (endpoint, credential) = identity(enrollment.as_deref())?;
    // The webview chooses an API route, never a server or arbitrary outbound URL.
    if !permitted_route(&request.path)
        || !["GET", "POST"].contains(&request.method.as_str())
    {
        return Err("不支援的中央服務操作。".into());
    }
    let client = reqwest::Client::builder()
        .no_proxy()
        .https_only(true)
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|_| "無法建立安全連線。")?;
    let method =
        reqwest::Method::from_bytes(request.method.as_bytes()).map_err(|_| "不支援的操作。")?;
    let mut builder = client.request(method, format!("{endpoint}{}", request.path));
    if request.path == "/api/v1/devices/enroll" {
        if let Some(body) = request.body.as_mut().and_then(Value::as_object_mut) {
            body.insert("credential".into(), Value::String(credential));
        }
    } else {
        builder = builder.bearer_auth(credential);
    }
    if let Some(session) = request.session_id {
        builder = builder.header("X-Session-Id", session);
    }
    if let Some(body) = request.body {
        builder = builder.json(&body);
    }
    let response = builder
        .send()
        .await
        .map_err(|_| "中央服務無法連線，請確認網路與憑證並改用紙本流程。")?;
    let status = response.status().as_u16();
    let body = response
        .text()
        .await
        .map_err(|_| "中央服務回應中斷，請改用紙本流程。")?;
    if status == 200 {
        if let Some(request_id) = enrollment {
            let result: Value = serde_json::from_str(&body).map_err(|_| "配對回應格式不正確。")?;
            if result.get("deviceId").and_then(Value::as_str).is_none() {
                return Err("配對回應格式不正確。".into());
            }
            let _guard = CREDENTIAL_LOCK.lock().map_err(|_| "裝置憑證忙碌中。")?;
            let mut identity = read_identity(&endpoint)?;
            identity.activate(&request_id)?;
            save_identity(&endpoint, &identity)?;
        }
    }
    Ok(CentralResponse { status, body })
}

fn main() {
    if updates::run_recovery_if_requested() { return; }
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            desktop::show_for_launch(app, args.into_iter());
        }))
        .setup(desktop::setup)
        .on_window_event(desktop::window_event)
        .invoke_handler(tauri::generate_handler![
            connection_settings,
            configure_connection,
            prepare_identity,
            central_request,
            updates::update_state,
            updates::check_updates,
            updates::prepare_update,
            updates::install_update,
            updates::open_update_recovery
        ])
        .run(tauri::generate_context!())
        .expect("Unable to start clinic desktop client");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encoded_filters_do_not_change_the_api_route() {
        assert!(permitted_route("/api/v1/cases?physician=%E5%90%88%E6%88%90&chart=A%2FB"));
        for route in ["https://other/api/v1/cases", "/api/v1/%2e%2e/secrets", "/api/v1/../other",
                      "/api/v1/cases#other", "/api/v1/cases\\other"] {
            assert!(!permitted_route(route));
        }
    }

    #[test]
    fn fresh_pairing_rotates_identity_but_retries_keep_the_same_key() {
        let mut identity = DeviceIdentity {
            active: Some("synthetic-old-key".into()),
            ..Default::default()
        };
        identity.prepare("first-request").unwrap();
        let first = identity.enrollment_key("first-request").unwrap();
        identity.prepare("first-request").unwrap();
        assert_eq!(identity.enrollment_key("first-request").unwrap(), first);
        assert_eq!(identity.active.as_deref(), Some("synthetic-old-key"));
        identity.activate("first-request").unwrap();
        identity.prepare("first-request").unwrap();
        assert_eq!(identity.enrollment_key("first-request").unwrap(), first);
        identity.prepare("new-pairing-request").unwrap();
        assert_ne!(
            identity.enrollment_key("new-pairing-request").unwrap(),
            first
        );
        assert_eq!(identity.active.as_deref(), Some(first.as_str()));
    }

    #[test]
    fn endpoints_cannot_embed_credentials_or_redirect_transport() {
        for value in [
            "http://clinic",
            "https://user:secret@clinic",
            "https://clinic/api",
            "https://clinic?server=other",
            "https://clinic/#fragment",
        ] {
            assert!(normalize_endpoint(value).is_err());
        }
        assert_eq!(
            normalize_endpoint("https://CLINIC:8443/").unwrap(),
            "https://clinic:8443"
        );
    }

    #[test]
    fn synthetic_device_key_roundtrips_in_windows_credential_store() {
        let mut random = [0u8; 32];
        getrandom::fill(&mut random).unwrap();
        let name = format!("synthetic-test-{}", URL_SAFE_NO_PAD.encode(random));
        let entry = Entry::new("tw.clinic.antiviral-reporter.tests", &name).unwrap();
        let secret = URL_SAFE_NO_PAD.encode(random);
        entry.set_password(&secret).unwrap();
        let actual = entry.get_password();
        entry.delete_credential().unwrap();
        assert_eq!(actual.unwrap(), secret);
        assert!(matches!(entry.get_password(), Err(keyring::Error::NoEntry)));
    }
}
