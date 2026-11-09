# ATOM Desktop Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sparse classroom dashboard with a responsive, professional dark-navy/cyan ATOM desktop experience while preserving live Firebase, FastAPI, and ESP32 control behavior.

**Architecture:** Keep the existing RTDB subscriptions and FastAPI command contract in the stateful dashboard container. Extract static presentation and navigation into UI components driven by explicit unavailable states; only values supplied by RTDB are shown as live. Route navigation inside the desktop shell and retain working mode and LED actions.

**Tech Stack:** Flutter Material 3, Firebase Core/Realtime Database, `http`, Windows desktop.

**Spec:** User request in this conversation.

## Global Constraints

- Do not change the backend, firmware, Firebase secrets, or existing web server.
- Preserve `ATOM/classroom1` Firebase RTDB paths, `http://127.0.0.1:8000/api/command`, and LED request payloads.
- Never invent occupancy or energy readings; show unavailable data as `N/A` or an explanatory empty state.
- Build and inspect the Windows desktop app after changes.

## Review Focus

- RTDB disconnected or empty: every telemetry surface stays explicit about unavailable data.
- A control request awaiting acknowledgement: the control remains visibly pending and reflects desired state.
- Narrow desktop window: navigation and information grid remain usable without overflow.
- Unsupported/malformed RTDB shapes: listeners preserve the dashboard rather than crashing.
- Navigation: every requested destination selects an implemented screen, with unavailable content clearly labeled.

---

### Task 1: Dashboard data model and regression tests

**Files:**
- Create: `lib/dashboard_models.dart`
- Create: `test/dashboard_models_test.dart`
- Modify: `test/widget_test.dart`

**Interfaces:**
- Produces: `TelemetryValue<T>`, `DashboardNavigation`, and pure RTDB parsing helpers used by the UI.

- [ ] **Step 1: Write failing parsing and unavailable-state tests**
- [ ] **Step 2: Run `flutter test test/dashboard_models_test.dart` and confirm the expected missing-symbol failures**
- [ ] **Step 3: Implement the smallest model and parser API in `lib/dashboard_models.dart`**
- [ ] **Step 4: Re-run the model test and then `flutter test`**

### Task 2: ATOM application shell and responsive overview

**Files:**
- Modify: `lib/main.dart`
- Modify: `lib/dashboard.dart`
- Create: `test/dashboard_shell_test.dart`

**Interfaces:**
- Consumes: models from Task 1.
- Produces: a responsive sidebar/topbar shell and Overview with summary, activity, control, and 3x3 zone-grid cards.

- [ ] **Step 1: Write failing widget tests for the named navigation destinations and unavailable zones**
- [ ] **Step 2: Run `flutter test test/dashboard_shell_test.dart` and confirm it fails against the old dashboard**
- [ ] **Step 3: Build the dark-navy/cyan desktop shell and compact overview, retaining existing listeners and command calls**
- [ ] **Step 4: Run the widget test and complete `flutter test`**

### Task 3: Functional section navigation and interactive controls

**Files:**
- Modify: `lib/dashboard.dart`
- Modify: `test/dashboard_shell_test.dart`

**Interfaces:**
- Consumes: Task 2 shell navigation and live state.
- Produces: Overview, Classroom Monitoring, Appliance Controls, Automation Rules, Energy Analytics, Activity Logs, and Settings views.

- [ ] **Step 1: Add failing tests that select every destination and verify the visible title and unavailable empty state**
- [ ] **Step 2: Run the focused widget test and confirm it fails**
- [ ] **Step 3: Add the requested views; bind live controls/logs/mode where supported and use clear unavailable copy elsewhere**
- [ ] **Step 4: Run `flutter test`, `flutter analyze`, and `flutter build windows --debug`**

### Task 4: Visual verification

**Files:**
- Modify: `lib/dashboard.dart` only if inspection finds an issue.

**Interfaces:**
- Consumes: completed Windows debug build.
- Produces: visually inspected desktop app, left running when possible.

- [ ] **Step 1: Launch the Windows debug app**
- [ ] **Step 2: Inspect Overview and each navigation destination at desktop width**
- [ ] **Step 3: If hardware is discoverable, toggle LED 1 once; otherwise leave hardware behavior unchanged and report it unverified**
