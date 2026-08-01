param(
    [string]$PythonCommand = "py -3.13",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128",
    [switch]$CpuOnly
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$pythonParts = $PythonCommand -split " "
$pythonExe = $pythonParts[0]
$pythonArgs = @($pythonParts | Select-Object -Skip 1)
& $pythonExe @pythonArgs -m venv .venv_sam
$samPython = Join-Path $RepoRoot ".venv_sam\Scripts\python.exe"
& $samPython -m pip install --upgrade pip setuptools wheel
if ($CpuOnly) {
    & $samPython -m pip install torch torchvision
} else {
    & $samPython -m pip install torch torchvision --index-url $TorchIndexUrl
}
& $samPython -m pip install numpy Pillow huggingface_hub git+https://github.com/facebookresearch/sam2.git
& $samPython -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
Write-Output "Set AGA_SAM_PYTHON=$samPython if the web service is not launched from this repo."