# Copy these commands into a PowerShell session before starting the bridge.

$env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0"
$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<8-char-token>"
$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN_HEADER = "X-Bridge-Token"
$env:WINDOWS_PYAUTOGUI_ARTIFACT_DIR = "artifacts/equipment"
$env:WINDOWS_PYAUTOGUI_REFERENCE_DIR = "reference_images"

# UTM visual-control/data-handoff settings. Tune these for the real UTM software export path.
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR = "C:\ATR\utm_exports"
$env:WINDOWS_PYAUTOGUI_UTM_EXPORT_GLOB = "*.csv"
$env:WINDOWS_PYAUTOGUI_UTM_FILE_STABLE_SEC = "2.0"
$env:WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS = "0"
$env:WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM = "0"
$env:WINDOWS_PYAUTOGUI_LOCATOR_ROOT = "C:\ATR\equipment_locators"
