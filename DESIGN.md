---
name: 公費抗病毒藥劑回報
description: Windows clinic device and session administration
colors:
  primary: "#175579"
  primary-hover: "#103f5b"
  surface: "white"
  canvas: "#f4f6f8"
  text: "#203242"
  text-muted: "#526678"
  border: "#cbd3db"
  input-border: "#8c9eae"
  placeholder: "#617384"
  focus: "#276d9c"
  secondary-hover: "#edf3f7"
  notice: "#eaf1f6"
  table-heading: "#e8eef3"
  error-text: "#82262b"
  error-surface: "#fff0f0"
  error-border: "#d6a0a4"
  selection: "#c6dfef"
  selection-text: "#16364b"
  scrollbar: "#7e91a1"
  scrollbar-track: "#eef2f5"
typography:
  headline:
    fontFamily: '"Segoe UI", "Microsoft JhengHei", sans-serif'
    fontSize: "30px"
    fontWeight: 650
    lineHeight: 1.4
  title:
    fontFamily: '"Segoe UI", "Microsoft JhengHei", sans-serif'
    fontSize: "21px"
    fontWeight: 700
    lineHeight: 1.6
  section:
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.6
  body:
    fontFamily: '"Segoe UI", "Microsoft JhengHei", sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.6
  help:
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  footer:
    fontSize: "13px"
    lineHeight: 1.6
  code:
    fontFamily: "Consolas, monospace"
    fontSize: "16px"
    lineHeight: 1.6
rounded:
  control: "6px"
  form: "12px"
spacing:
  field-gap: "6px"
  text-gap: "10px"
  actions: "12px"
  controls: "16px"
  form-gap: "20px"
  section-gap: "24px"
  form-padding: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
  button-secondary-hover:
    backgroundColor: "{colors.secondary-hover}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    width: "100%"
  connection-form:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.form}"
    padding: "28px"
  notice:
    backgroundColor: "{colors.notice}"
    rounded: "{rounded.control}"
    padding: "14px 18px"
  error:
    backgroundColor: "{colors.error-surface}"
    textColor: "{colors.error-text}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
---

# Design System: 公費抗病毒藥劑回報

## Overview

**Creative North Star: "Windows clinic administration"**

This descriptive name records the approved operating context, not a new brand. The implemented React interface inside the Windows Tauri client uses Traditional Chinese, familiar administrative forms and a device table. A light operating surface, blue actions and direct status language support deliberate work.

This record covers connection setup, session attribution, device authorization, pairing and revocation only. It does not establish completed patient, reporting or export screens. Visual authority is [PRODUCT.md](PRODUCT.md) and the approved SPEC v1.0 §8 defaults, subject to the authoritative v1.1 amendment. No separate branding or image composition was approved.

**Key Characteristics:**

- Light surfaces separated by borders and spacing.
- Traditional Chinese labels and visible operational state.
- Blue action controls with explicit keyboard focus.
- Disconnection guidance that names the approved paper fallback.

Extraction evidence: [style.css](client/src/style.css) supplies exact values; [App.tsx](client/src/App.tsx) supplies states and semantics. Rendered evidence: [connection](screenshots/connection-1080.png), [devices, wide](screenshots/devices-1080.png), [devices, narrow](screenshots/devices-720.png), [disconnected](screenshots/offline-720.png), [revoke focus](screenshots/revoke-focus-1080.png), and [pairing result](screenshots/pairing-result-1080.png). The latter two are scrolled views of synthetic long lists. These screenshots establish the observed surfaces, not whole-app completeness or a full accessibility certification.

## Colors

The palette uses muted blue for actions, cool neutrals for working surfaces and a distinct red error treatment.

### Primary

- **Action blue** (`primary`): primary buttons, secondary button text and input caret; `primary-hover` deepens filled actions on hover.
- **Focus blue** (`focus`): the keyboard outline on buttons, inputs and selects.

### Neutral

- **Working canvas** (`canvas`) surrounds white forms, table rows, header and footer (`surface`).
- **Main ink** (`text`) supports body copy; **supporting ink** (`text-muted`) supports field help and contextual explanations.
- **Dividers** (`border`) separate sections and rows; `input-border` gives fields stronger boundaries.
- `table-heading` marks column headings; `notice` supports the attribution notice; `secondary-hover` marks secondary control hover.
- `placeholder`, `selection`, `selection-text`, `scrollbar` and `scrollbar-track` record the existing interaction styling.

Error text, surface and border are semantic feedback colors, not a second branding accent. A revoked device is identified with text and a disabled action, without a colored chip.

The sidecar's synthesized tonal ramps are preview metadata only, not additional approved application colors. Source colors remain authoritative in this frontmatter.

**The Explicit State Rule.** Pair semantic color with readable state or recovery text; color alone does not explain an operation.

## Typography

The interface uses the Windows system stack recorded in the frontmatter. This is operational text, with no separate display face. Consolas is reserved for the read-only pairing code. There is no promotional typography treatment to propagate.

The hierarchy is page headline, section title, subsection heading, body, semibold field label, supporting help and footer. Titles and subsection headings retain browser heading boldness (700); labels and buttons explicitly use 600. The app header uses bold text (19px; 17px at the narrow breakpoint). At that breakpoint, the page headline becomes 27px. Paragraphs stop at 70ch; table numerals use tabular figures. The observed font sizes are discrete choices, not a mathematical scale.

## Layout

The app is a full-height flex column with a white header, flexible main area and normal-flow footer. Main content is centered with a maximum width of 1160px and desktop padding of 40px 32px. The connection surface has two columns (1fr 1.15fr), separated by 64px; the paper fallback remains beside the form on wide screens.

At a maximum width of 800px, main padding becomes 28px 20px, the connection surface becomes one column with a 28px gap, and form padding becomes 22px. Page actions and pairing controls stack vertically; header content remains in its row. The device table stays a table inside an overflow-x container. Do not infer a separate mobile navigation pattern from this breakpoint.

Desktop connection forms use the frontmatter form spacing. Header padding is 18px 32px (16px 20px at the breakpoint). Table cells use 14px 18px; compact row actions use 6px 12px with help-sized text. Pairing and revocation forms begin after a divider with a 28px top margin and 24px top padding. Pairing results and revocation fields stop at 600px; inline capability controls have a 220px minimum label width.

## Elevation & Depth

The observed interface has no shadows, gradients, floating cards or motion tokens. White surfaces, tinted notices, table headers and thin dividers establish grouping. The keyboard outline is an interaction cue, not elevation.

**The Flat Surface Rule.** Preserve the current border-and-tone grouping when extending these administrative surfaces.

## Shapes

Controls and feedback panels use the control radius; the connection form uses the larger form radius. Dividers, input borders and table row separators are one pixel. The table uses collapsed borders. There are no avatar, chip or icon shapes in the implemented surface.

## Components

### Buttons

Primary actions use filled action blue; secondary actions use white, blue text and the divider border. Hover treatments are recorded in the frontmatter. Focus uses a 3px solid focus-blue outline with a 3px offset. Disabled buttons retain their geometry with opacity 0.55 and a not-allowed cursor. No animated transition is defined.

### Inputs / Fields

Native inputs and selects span their container and sit beneath visible semibold labels with the field gap. Password fields are used for entered pairing codes and imported credentials. The result code is a read-only monospace input. Busy connection forms disable their fields and change the submit label to 「正在連線…」. Errors use alert semantics and the error panel; no separate invalid-field decoration is implemented.

### Cards / Containers

The connection form is the canonical bordered white container. Supporting paper-fallback guidance is an open text region separated by a top rule. The attribution notice uses a tinted panel, and the footer keeps the development/export limitation visible.

### Device table and recovery

Columns identify device name, capability, state and action. Authorized and revoked states remain explicit text; revoked-device actions are disabled. Loading and operation progress use a persistent `role="status"` region. List failures use an alert and offer 「重新載入」; a successful empty list has its own row. Loading, failure and empty are separate states.

### Pairing and revocation

Pairing selection is a native capability select followed by the primary action. The status region announces progress and success; the read-only result appears below with expiry and one-use guidance. The code itself is outside the live announcement.

Revocation expands an inline form naming the selected device and requiring a reason. Opening it moves focus to the reason input; cancelling returns focus to the invoking row action. Successful revocation reloads the table and focuses the management heading. This behavior is evidenced in source; the focus screenshot shows the reason field after scrolling a long table.

### Connection and disconnected state

The header gives the current connection state in words. A lost connection or failed device authorization removes the connected surface and presents an alert on connection setup. Paper fallback instructions remain visible. The non-administrator view explicitly says the case worklist is still in development. These states must not imply offline patient access or production export readiness.

## Do's and Don'ts

### Do:

- **Do** use Traditional Chinese operational labels and the CONTEXT glossary.
- **Do** retain visible labels, native form semantics and the explicit keyboard outline.
- **Do** distinguish loading, load failure, empty results and successful operations.
- **Do** preserve readable paper-fallback guidance when the central service is unavailable.
- **Do** use synthetic content for visual evidence and component previews.

### Don't:

- **Don't** describe operation identity as verified personal authentication.
- **Don't** imply offline viewing, editing or export in the disconnected surface.
- **Don't** present this device/session implementation as the completed reporting application.
- **Don't** invent clinic branding, decorative imagery or a separate display typography system from this record.

Not canonized: unimplemented case/reporting/export screens and unverified platforms or widths are not design patterns. System fonts are documented as the approved Windows operational stack, not a reusable decorative display treatment. No new aesthetic decisions or source repairs were made by this documentation pass.
