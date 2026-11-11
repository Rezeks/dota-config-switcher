# Dota Config Switcher

Windows-приложение: переносит настройки Dota 2 (управление, хоткеи, конфиги) с одного Steam-аккаунта на другой,
показывает ники и аватарки, умеет сохранять конфиг в ZIP и загружать его обратно.

## Запуск
- Готовый exe — на странице **Releases**.
- Из исходников: `pip install -r requirements.txt` и `python dota_cfg_switcher.py`.
- Сборка exe: `build.bat` (результат в `dist`).

Настройки лежат в `Steam\userdata\<ID>\570\remote`. Перед записью делается резервная копия в папку `backups`.
Лучше закрывать Steam и Dota на время переноса (Steam Cloud может перезаписать настройки).
