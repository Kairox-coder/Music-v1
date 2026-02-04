from flask import Flask
import threading, os

app = Flask(__name__)

@app.route("/")
def home():
    return "ok"

def keep_alive():
    port = int(os.getenv("PORT", 10000))
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port)
    ).start()
