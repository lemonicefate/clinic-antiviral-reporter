# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The interface is a React webview inside a Windows Tauri 2 desktop client, not a
public website. SPEC v1.1 fixes the stack and Windows deployment model.

## Users

Clinic physicians confirm a selected patient and enter the medication reason.
Reporting staff reconcile dispensing, lots, exclusions, exports, and manual SMIS
results. Administrators authorize devices and maintain central operations.

## Product Purpose

Turn read-only HIS source orders into versioned report cases without retyping
facts already available in HIS. SMIS login, upload, and confirmation remain manual.

## Operating Context

One outpatient clinic, Windows computers, central service on the clinic network.
Follow the already approved SPEC v1.0 section 8 desktop workflow defaults without
additional product interviews. The user's approved ticket breakdown and instruction
to continue govern this implementation.

## Capabilities and Constraints

Use Traditional Chinese and the CONTEXT glossary. Device capability authorizes;
operator identity only attributes work. Patient content is memory-only in clients.
Central outages clear patient views and require the approved paper fallback.
HIS and backup paths and SMB credentials never enter client settings or API schemas.
No production export until every M0 gate is evidenced. Unknown official rules stay OPEN.

## Evidence on Hand

SPEC v1.0, authoritative v1.1, CONTEXT, ADRs, approved ticket breakdown, and the
preserved official workbook. No clinic branding or product screenshots supplied.

## Product Principles

- Make patient selection and the current operation explicit.
- Preserve source facts, human decisions, and export history independently.
- Show conflicts, disconnection, and incomplete work honestly.
- Keep the physician workflow short and avoid disruptive notifications.
