# label_app.py (stub with logging)
import label_app

try:
    label_app.run_app()
except Exception as e:
    with open("error_log.txt", "w") as f:
        f.write(str(e))
