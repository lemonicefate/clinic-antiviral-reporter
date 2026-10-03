//! Current-user launch preference, with no system-wide registry writes.

use windows_registry::CURRENT_USER;

const RUN: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
const NAME: &str = "tw.clinic.antiviral-reporter";
const PREFERENCES: &str = r"Software\tw.clinic.antiviral-reporter";

fn command() -> Result<String, Box<dyn std::error::Error>> {
    let executable = std::env::current_exe()?;
    let path = executable.to_str().ok_or("Executable path is not Unicode")?;
    Ok(format!("\"{path}\" --autostart"))
}

pub fn enabled() -> Result<bool, Box<dyn std::error::Error>> {
    // Creating the per-user Run key is harmless on a newly provisioned account;
    // no startup value is written unless the operator enables the preference.
    let key = CURRENT_USER.create(RUN)?;
    match key.get_string(NAME) {
        Ok(value) => Ok(value == command()?),
        Err(error) if error.code().0 as u32 == 0x80070002 => Ok(false),
        Err(error) => Err(error.into()),
    }
}

pub fn set_enabled(enabled: bool) -> Result<(), Box<dyn std::error::Error>> {
    let key = CURRENT_USER.create(RUN)?;
    // Save the user's choice first. If this is denied, leave the actual startup
    // command unchanged. A later Run failure is reported and read back by the UI.
    CURRENT_USER.create(PREFERENCES)?.set_u32("StartAtLogin", u32::from(enabled))?;
    if enabled {
        key.set_string(NAME, &command()?)?;
    } else {
        key.remove_value(NAME)?;
    }
    Ok(())
}
