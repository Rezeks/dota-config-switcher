@echo off
cd /d "%~dp0"
pip install -r requirements.txt
python -m PyInstaller --noconfirm --onefile --windowed --name "Dota Config Switcher" --collect-all customtkinter dota_cfg_switcher.py
echo Готово: dist\Dota Config Switcher.exe
pause
