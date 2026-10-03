//! Native window lifecycle. No case data or central paths enter this module.

use tauri::{
    menu::{CheckMenuItem, Menu, MenuItem, Submenu},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    App, AppHandle, Manager, WindowEvent,
};
use crate::startup;
use std::sync::atomic::{AtomicBool, Ordering};

static READY: AtomicBool = AtomicBool::new(false);
static SHOW_REQUESTED: AtomicBool = AtomicBool::new(false);

pub fn show(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

pub fn show_for_launch(app: &AppHandle, arguments: impl Iterator<Item = String>) {
    if !arguments.into_iter().any(|argument| argument == "--autostart") {
        // Single-instance messages can arrive during WebView initialization,
        // before Tauri has registered the main window. Retain that activation.
        SHOW_REQUESTED.store(true, Ordering::SeqCst);
        if READY.load(Ordering::SeqCst) {
            SHOW_REQUESTED.store(false, Ordering::SeqCst);
            show(app);
        }
    }
}

pub fn setup(app: &mut App) -> Result<(), Box<dyn std::error::Error>> {
    let open = MenuItem::with_id(app, "desktop-open", "開啟回報工具", true, None::<&str>)?;
    let startup_state = startup::enabled();
    let autostart = CheckMenuItem::with_id(
        app, "desktop-autostart", if startup_state.is_err() {
            "無法讀取自啟設定；請檢查 Windows 權限後重試"
        } else { "Windows 登入時啟動並縮至系統列" }, true,
        startup_state.unwrap_or(false), None::<&str>,
    )?;
    let quit = MenuItem::with_id(app, "desktop-quit", "結束回報工具", true, None::<&str>)?;
    let tray_menu = Menu::with_items(app, &[&open, &autostart, &quit])?;
    let application = Submenu::with_items(app, "程式", true, &[&open, &autostart, &quit])?;
    app.set_menu(Menu::with_items(app, &[&application])?)?;
    app.on_menu_event(move |app, event| match event.id().as_ref() {
        "desktop-open" => show(app),
        "desktop-quit" => app.exit(0),
        "desktop-autostart" => {
            // Re-read the OS state; the menu's auto-toggled check is not evidence
            // that Windows accepted the change.
            let result = startup::enabled().and_then(|enabled| startup::set_enabled(!enabled));
            let current = startup::enabled();
            let failed = result.is_err() || current.is_err();
            let _ = autostart.set_checked(current.unwrap_or(false));
            let _ = autostart.set_text(if failed {
                "自啟設定失敗；請檢查 Windows 權限後重試"
            } else { "Windows 登入時啟動並縮至系統列" });
        }
        _ => {}
    });
    let icon = app.default_window_icon().ok_or("Application icon missing")?.clone();
    TrayIconBuilder::with_id("clinic-desktop")
        .icon(icon)
        .tooltip("公費抗病毒藥劑回報")
        .menu(&tray_menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if matches!(event, TrayIconEvent::Click {
                button: MouseButton::Left, button_state: MouseButtonState::Up, ..
            }) {
                show(tray.app_handle());
            }
        })
        .build(app)?;
    READY.store(true, Ordering::SeqCst);
    show_for_launch(app.handle(), std::env::args());
    if SHOW_REQUESTED.swap(false, Ordering::SeqCst) {
        show(app.handle());
    }
    Ok(())
}

pub fn window_event(window: &tauri::Window, event: &WindowEvent) {
    if let WindowEvent::CloseRequested { api, .. } = event {
        // Keep the window available if hiding fails, so explicit quit remains
        // reachable. The tray is created before the initial window is shown.
        api.prevent_close();
        let _ = window.hide();
    }
}
