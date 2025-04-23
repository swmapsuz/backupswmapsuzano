@echo off

start cmd /k "cd /d A:\ENTUITY && node scraper.js"

start cmd /k "cd /d A:\CACHEMAPA\ && node cachemap.js"

start cmd /k "cd /d A:\CPU-C && py cpu.py"

start cmd /k "cd /d A:\SwitchMap 1.0\backend\websocket && py app.py"
start cmd /k "cd /d A:\SwitchMap 1.0\backend\websocket && py approve.py"
start cmd /k "cd /d A:\SwitchMap 1.0\backend\websocket && py get_data_service.py"

start cmd /k "cd /d A:\ && py auto_backup_git.py"

exit
