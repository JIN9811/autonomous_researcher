# Copy these commands into a PowerShell session before starting the bridge.

$env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0"
$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<generated-token>"
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN_HEADER = "X-Bridge-Token"
$env:WINDOWS_PYAUTOGUI_DATA_ROOT = "$env:LOCALAPPDATA\ATR\PyAutoGUIBridge"
$env:WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT = "$env:WINDOWS_PYAUTOGUI_DATA_ROOT\artifacts"
$env:WINDOWS_PYAUTOGUI_LOCATOR_ROOT = "$env:WINDOWS_PYAUTOGUI_DATA_ROOT\locators"
$env:WINDOWS_PYAUTOGUI_PROGRAM_DIR = "$env:WINDOWS_PYAUTOGUI_DATA_ROOT\programs"
$env:WINDOWS_PYAUTOGUI_RECORDING_DIR = "$env:WINDOWS_PYAUTOGUI_DATA_ROOT\recordings"

# Optional managed-deployment override. Normally leave this unset: after an
# authenticated Linux request the bridge verifies that peer's ATR Skill API,
# then stores the controller URL in data\controller_connection.json. The GUI
# can also run bounded private-network discovery or verify a manual URL.
# $env:WINDOWS_PYAUTOGUI_ATR_API_URL = "http://<linux-atr-host>:7860"

# UTM visual-control/data-handoff settings. Tune these for the real UTM software export path.
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR = "$env:WINDOWS_PYAUTOGUI_DATA_ROOT\utm_exports"
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_GLOB = "*.csv"
$env:WINDOWS_PYAUTOGUI_UTM_FILE_STABLE_SEC = "2.0"
$env:WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS = "0"
$env:WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM = "0"
