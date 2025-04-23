@echo off

start cmd /k "cd /d A:\switchmap\backend\ENTUITY && node scraper.js"

start cmd /k "cd /d A:\switchmap\backend\CACHEMAPA && node cachemap.js"

start cmd /k "cd /d A:\switchmap\backend\CPU-C && py cpu.py"

start cmd /k "cd /d A:\SwitchMap\backend\SWICTHMAP\websocket && py app.py"
start cmd /k "cd /d A:\SwitchMap\backend\SWICTHMAP\websocket && py approve.py"
start cmd /k "cd /d A:\SwitchMap\backend\SWICTHMAP\websocket && py get_data_service.py"

start cmd /k "cd /d A:\switchmap\ && py auto_backup_git.py"

exit
