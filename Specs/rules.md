# 🤖 Rules for Coding Agent: NI Thermocouple Logger Project

**Target File:** `production_logger.py`  
**Input Specifications:** `requirements.yaml`, `ux_design.yaml`, `system_workflow.yaml`, `architecture.yaml`

---

## 🛑 Strict Compliance Directives


2.  **YAML Adherence:**
    * **Architecture:** You must strictly implement the variables defined in `architecture.yaml` under `configuration_entities`. Do not rename variables (e.g., use `DEVICE_NAME`, not `device`).
    * **Logic Flow:** The `daq_engine` function must follow the exact 7-step sequence defined in `system_workflow.yaml` -> `workflow_daq_engine`.
    * **UI/UX:** The HTML/CSS must reflect the structure in `ux_design.yaml`. Use the exact color codes provided (e.g., `#007bff` for buttons, `#dc3545` for alerts).
    Do not modify any existing input .yaml files

3.  **Code Constraints:**


---

## 🧠 Implementation Rules


### 3. User Interface
