; Only current-user preferences. Preserve a deliberate disable across upgrades.
!macro NSIS_HOOK_POSTINSTALL
  Push $R9
  ClearErrors
  ReadRegDWORD $R9 HKCU "Software\tw.clinic.antiviral-reporter" "StartAtLogin"
  ${If} ${Errors}
    StrCpy $R9 1
  ${EndIf}
  ${If} $R9 == 1
    ClearErrors
    WriteRegDWORD HKCU "Software\tw.clinic.antiviral-reporter" "StartAtLogin" 1
    ${If} ${Errors}
      MessageBox MB_OK|MB_ICONEXCLAMATION "無法保存登入自啟偏好，未變更自啟項目；請檢查目前帳號權限。" /SD IDOK
      SetErrorLevel 1
    ${Else}
      WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tw.clinic.antiviral-reporter" '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" --autostart'
      ${If} ${Errors}
        MessageBox MB_OK|MB_ICONEXCLAMATION "無法設定登入自啟；請啟動程式後從「程式」選單重試。" /SD IDOK
        SetErrorLevel 1
      ${EndIf}
    ${EndIf}
  ${ElseIf} $R9 == 0
    ReadRegStr $R9 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tw.clinic.antiviral-reporter"
    ${If} $R9 == '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" --autostart'
      ClearErrors
      DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tw.clinic.antiviral-reporter"
      ${If} ${Errors}
        MessageBox MB_OK|MB_ICONEXCLAMATION "無法套用已保存的關閉自啟偏好；請檢查目前帳號權限。" /SD IDOK
        SetErrorLevel 1
      ${EndIf}
    ${EndIf}
  ${EndIf}
  Pop $R9
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Push $R9
  ReadRegStr $R9 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tw.clinic.antiviral-reporter"
  ${If} $R9 == '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" --autostart'
    ClearErrors
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tw.clinic.antiviral-reporter"
    ${If} ${Errors}
      MessageBox MB_OK|MB_ICONEXCLAMATION "程式已移除，但登入自啟項目無法清除；請檢查目前帳號權限。" /SD IDOK
      SetErrorLevel 1
    ${EndIf}
  ${EndIf}
  ; Keep StartAtLogin as an allowed preference for reinstall/rollback.
  Pop $R9
!macroend
