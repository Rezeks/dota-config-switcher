# Dota Config Switcher

Windows-приложение: переносит настройки Dota 2 (управление, хоткеи, конфиги) с одного Steam-аккаунта на другой,
показывает ники и аватарки, умеет сохранять конфиг в ZIP и загружать его обратно.

## Скачать
[**⬇ Скачать Dota Config Switcher.exe**](https://github.com/Rezeks/dota-config-switcher/releases/latest/download/Dota.Config.Switcher.exe)
· [все релизы](https://github.com/Rezeks/dota-config-switcher/releases/latest)

Скачайте exe и запустите — установка и Python не нужны. Windows SmartScreen может предупредить о неизвестном издателе: «Подробнее» → «Выполнить в любом случае».

## Запуск
- Из исходников: `pip install -r requirements.txt` и `python dota_cfg_switcher.py`.
- Сборка exe: `build.bat` (результат в `dist`).

Настройки лежат в `Steam\userdata\<ID>\570\remote`. Перед записью делается резервная копия в папку `backups`.
Лучше закрывать Steam и Dota на время переноса (Steam Cloud может перезаписать настройки).
